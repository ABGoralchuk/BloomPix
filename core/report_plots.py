"""Pure-Python 300-DPI figure renderers for BloomPix publication archives.

Strictly decoupled from Streamlit (ZERO ``streamlit`` imports).
"""

from __future__ import annotations

import io
import math
from typing import Any

import matplotlib
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure

from core.models import Calibration, KineticFitResult

KINETIC_METRIC_CATALOG: list[tuple[str, str]] = [
    ("cbi_score", "Composite Bloom Index (CBI)"),
    ("bloom_coverage_pct", "Bloom Coverage (%)"),
    ("trnr_relief", "TRNR Relief"),
    ("loc_trnr_median", "Local Roughness Median"),
    ("blade_index", "Blade Index"),
    ("anisotropy_coh", "Anisotropy Coherency"),
    ("corr_len_um", "Correlation Length (µm)"),
    ("geom_bloom_index", "Geometric Bloom Index"),
]


def _fig_to_png_bytes(fig: Figure, dpi: int = 300) -> bytes:
    FigureCanvasAgg(fig)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=dpi, bbox_inches="tight")
    return buf.getvalue()


def _spatial_extent(calibration: Calibration) -> tuple[list[float], str]:
    if calibration.um_per_px > 0.0:
        return [
            0.0,
            float(calibration.res_x * calibration.um_per_px),
            float(calibration.res_y * calibration.um_per_px),
            0.0,
        ], "µm"
    return [0.0, float(calibration.res_x), float(calibration.res_y), 0.0], "px (uncalibrated)"


def _heatmap_spec(map_type: str) -> tuple[str, str, str, str]:
    is_sato = "sato" in map_type.lower() or map_type == "ridges_map"
    if is_sato:
        return "ridges_map", "magma", "Sato Ridge Response", "Sato Crystal Blade Response"
    return "loc_trnr_map", "inferno", "Local TRNR", "Pseudo-AFM Local TRNR"


def _treatment_colors(treatments: list[str]) -> dict[str, tuple[float, float, float, float]]:
    cmap = matplotlib.colormaps["tab10"]
    return {trt: cmap(idx % 10) for idx, trt in enumerate(sorted(treatments))}


def render_single_week_heatmap_png(
    entry: dict[str, Any],
    map_type: str,
    treatment: str,
    scale_label: str,
    shared_vmax: float,
    dpi: int = 300,
) -> bytes:
    """Render a standalone 300-DPI heatmap for a single week with physical ``µm`` axes."""
    map_key, cmap_name, cbar_label, map_title = _heatmap_spec(map_type)
    wk = int(entry["week"])
    cal: Calibration = entry["calibration"]
    arr = entry[map_key]
    extent, unit = _spatial_extent(cal)

    wk_label = "Week 0 (Control)" if wk == 0 else f"Week {wk}"
    if entry.get("hv_mismatch") and entry.get("hv_kv") is not None:
        wk_label += f"* ({entry['hv_kv']:.0f} kV)"

    fig = Figure(figsize=(7.2, 5.2))
    try:
        ax = fig.add_subplot(111)
        im = ax.imshow(
            arr,
            cmap=cmap_name,
            vmin=0.0,
            vmax=max(float(shared_vmax), 1e-6),
            extent=extent,
            aspect="equal",
        )
        ax.set_title(f"{treatment} — {wk_label} | {map_title} ({scale_label})")
        ax.set_xlabel(f"X ({unit})")
        ax.set_ylabel(f"Y ({unit})")
        fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04, label=cbar_label)
        fig.tight_layout()
        return _fig_to_png_bytes(fig, dpi=dpi)
    finally:
        fig.clear()
        plt.close(fig)


def render_all_weeks_heatmap_grid_png(
    week_entries: list[dict[str, Any]],
    map_type: str,
    treatment: str,
    replicate: int,
    scale_label: str,
    shared_vmax: float,
    dpi: int = 300,
) -> bytes:
    """Render all weeks of one treatment into a multi-panel grid with one shared colorbar."""
    map_key, cmap_name, cbar_label, map_title = _heatmap_spec(map_type)
    n_panels = len(week_entries)
    ncols = min(5, max(1, n_panels))
    nrows = max(1, math.ceil(n_panels / ncols))

    fig = Figure(figsize=(3.5 * ncols, 3.0 * nrows))
    try:
        axes_flat = []
        last_im = None
        for idx in range(nrows * ncols):
            ax = fig.add_subplot(nrows, ncols, idx + 1)
            axes_flat.append(ax)
            if idx >= n_panels:
                ax.axis("off")
                continue

            entry = week_entries[idx]
            extent, unit = _spatial_extent(entry["calibration"])
            last_im = ax.imshow(
                entry[map_key],
                cmap=cmap_name,
                vmin=0.0,
                vmax=max(float(shared_vmax), 1e-6),
                extent=extent,
                aspect="equal",
            )
            wk = int(entry["week"])
            title = "Week 0 (Control)" if wk == 0 else f"Week {wk}"
            if entry.get("hv_mismatch"):
                title += "* (10 kV)"
            ax.set_title(title, fontsize=9.5)
            if idx // ncols == nrows - 1:
                ax.set_xlabel(f"X ({unit})", fontsize=8)
            else:
                ax.set_xticks([])
            if idx % ncols == 0:
                ax.set_ylabel(f"Y ({unit})", fontsize=8)
            else:
                ax.set_yticks([])

        fig.suptitle(
            f"{treatment} (Rep {replicate}) — {map_title} ({scale_label})",
            fontsize=12,
            y=0.985,
        )
        fig.subplots_adjust(
            left=0.06, right=0.91, bottom=0.08, top=0.90, wspace=0.14, hspace=0.28
        )
        if last_im is not None:
            cax = fig.add_axes([0.93, 0.12, 0.015, 0.76])
            fig.colorbar(last_im, cax=cax, label=cbar_label)

        return _fig_to_png_bytes(fig, dpi=dpi)
    finally:
        fig.clear()
        plt.close(fig)


def render_all_weeks_psd_png(
    week_entries: list[dict[str, Any]],
    treatment: str,
    replicate: int,
    scale_label: str,
    dpi: int = 300,
) -> tuple[bytes, pd.DataFrame]:
    """Render overlaid all-weeks 2D FFT Radial PSD (``µm⁻¹``) and return PNG + wide DataFrame."""
    cmap_wk = matplotlib.colormaps["viridis"]
    weeks_list = [int(e["week"]) for e in week_entries]
    wk_min, wk_max = min(weeks_list), max(max(weeks_list), 1)

    psd_table: dict[str, np.ndarray] = {
        "Frequency_um_inv": week_entries[0]["freq_um_inv"]
    }

    fig = Figure(figsize=(9.0, 4.8))
    try:
        ax = fig.add_subplot(111)
        for entry in week_entries:
            wk = int(entry["week"])
            freqs = entry["freq_um_inv"]
            psd = entry["radial_psd"]
            col_key = "Week_0_Control" if wk == 0 else f"Week_{wk}"
            psd_table[col_key] = psd

            pos = (freqs > 0) & (psd > 0)
            t_norm = (wk - wk_min) / max(wk_max - wk_min, 1)
            lbl = (
                "W0 (Ctrl)"
                if wk == 0
                else (f"W{wk}*" if entry.get("hv_mismatch") else f"W{wk}")
            )
            ax.loglog(
                freqs[pos],
                psd[pos],
                color=cmap_wk(t_norm),
                lw=1.5,
                alpha=0.9,
                label=lbl if wk in (0, 2, 4, 8, 12, 16) or wk == wk_max else None,
            )

        sm = matplotlib.cm.ScalarMappable(
            cmap=cmap_wk,
            norm=matplotlib.colors.Normalize(vmin=wk_min, vmax=wk_max),
        )
        sm.set_array([])
        fig.colorbar(sm, ax=ax, label="Storage Time (Weeks)")
        ax.set_title(
            f"{treatment} (Rep {replicate}) — 2D FFT Radial PSD Progression ({scale_label})"
        )
        ax.set_xlabel("Spatial Frequency (µm⁻¹)")
        ax.set_ylabel("Normalized PSD (a.u.)")
        ax.grid(True, which="both", alpha=0.3)
        ax.legend(loc="lower left", ncol=2, fontsize=8.5, frameon=True)
        fig.tight_layout()
        return _fig_to_png_bytes(fig, dpi=dpi), pd.DataFrame(psd_table)
    finally:
        fig.clear()
        plt.close(fig)


def render_kinetic_progression_png(
    agg_df: pd.DataFrame,
    fits: list[KineticFitResult],
    curves: dict[str, tuple[np.ndarray, np.ndarray]],
    metric_col: str,
    metric_label: str,
    scale_label: str,
    include_hv_mismatch: bool = True,
    dpi: int = 300,
) -> bytes:
    """Render 300-DPI kinetic evolution plot (Mean ± SD + fitted curves + HV markers)."""
    treatments = sorted(agg_df["treatment"].unique())
    colors = _treatment_colors(treatments)
    mean_col = f"{metric_col}_mean"
    sd_col = f"{metric_col}_sd"

    fig = Figure(figsize=(9.5, 5.2))
    try:
        ax = fig.add_subplot(111)
        for trt in treatments:
            sub = agg_df[agg_df["treatment"] == trt].sort_values("week")
            col = colors[trt]
            normal = (
                sub[~sub["any_hv_mismatch"]]
                if "any_hv_mismatch" in sub.columns
                else sub
            )
            ax.errorbar(
                normal["week"],
                normal[mean_col],
                yerr=normal[sd_col],
                fmt="o",
                color=col,
                capsize=3,
                markersize=5.5,
                label=str(trt),
            )
            if include_hv_mismatch and "any_hv_mismatch" in sub.columns:
                hv_sub = sub[sub["any_hv_mismatch"]]
                if not hv_sub.empty:
                    ax.scatter(
                        hv_sub["week"],
                        hv_sub[mean_col],
                        marker="D",
                        facecolors="none",
                        edgecolors=col,
                        s=70,
                        linewidths=1.6,
                        zorder=5,
                    )
            if trt in curves:
                tx, ty = curves[trt]
                if tx.size > 0:
                    res = next((r for r in fits if r.treatment == trt), None)
                    ls = "-" if (res is not None and res.fit_status == "Fitted") else "--"
                    alpha = 0.9 if (res is not None and res.fit_status == "Fitted") else 0.55
                    ax.plot(tx, ty, linestyle=ls, color=col, alpha=alpha, lw=1.9)

        if include_hv_mismatch and agg_df.get("any_hv_mismatch", pd.Series(False)).any():
            ax.scatter(
                [],
                [],
                marker="D",
                facecolors="none",
                edgecolors="black",
                label="HV_Mismatch (10 kV)",
            )

        ax.set_title(f"{metric_label} vs. Storage Time ({scale_label})")
        ax.set_xlabel("Storage Time (Weeks)")
        ax.set_ylabel(metric_label)
        ax.grid(True, alpha=0.25)
        ax.legend(ncol=2, frameon=True)
        fig.tight_layout()
        return _fig_to_png_bytes(fig, dpi=dpi)
    finally:
        fig.clear()
        plt.close(fig)


def render_treatment_week_heatmap_png(
    agg_df: pd.DataFrame,
    metric_col: str,
    metric_label: str,
    scale_label: str,
    dpi: int = 300,
) -> tuple[bytes, pd.DataFrame]:
    """Render 300-DPI ``Treatment × Week`` heatmap and return PNG + pivot DataFrame."""
    mean_col = f"{metric_col}_mean"
    piv = agg_df.pivot(index="treatment", columns="week", values=mean_col)

    fig = Figure(figsize=(11.0, max(3.2, 0.7 * len(piv) + 1.5)))
    try:
        ax = fig.add_subplot(111)
        sns.heatmap(
            piv,
            annot=True,
            fmt=".1f",
            cmap="YlOrRd",
            linewidths=0.4,
            ax=ax,
            cbar_kws={"label": metric_label},
        )
        ax.set_title(f"{metric_label} Progression Matrix ({scale_label})")
        ax.set_xlabel("Storage Time (Weeks)")
        ax.set_ylabel("Treatment")
        fig.tight_layout()
        return _fig_to_png_bytes(fig, dpi=dpi), piv
    finally:
        fig.clear()
        plt.close(fig)


def render_morphology_pca_png(
    pca_res: dict[str, Any],
    scale_label: str,
    dpi: int = 300,
) -> bytes:
    """Render 300-DPI 2D PCA morphology ordination plot."""
    scores_df = pca_res["scores_df"]
    ev1, ev2 = pca_res["explained_variance_ratio"]
    treatments = sorted(scores_df["treatment"].unique())
    colors = _treatment_colors(treatments)

    fig = Figure(figsize=(7.4, 5.4))
    try:
        ax = fig.add_subplot(111)
        for trt in treatments:
            sub_p = scores_df[scores_df["treatment"] == trt]
            col = colors.get(trt, (0.3, 0.3, 0.3, 1.0))
            sizes = 28.0 + sub_p["week"].to_numpy(dtype=float) * 7.5
            ax.scatter(
                sub_p["PC1"],
                sub_p["PC2"],
                s=sizes,
                color=col,
                alpha=0.8,
                edgecolors="white",
                linewidths=0.5,
                label=str(trt),
            )
        ax.axhline(0.0, color="gray", lw=0.7, ls="--")
        ax.axvline(0.0, color="gray", lw=0.7, ls="--")
        ax.set_title(f"PCA of 9 Invariant Metrics ({scale_label})")
        ax.set_xlabel(f"PC1 ({ev1 * 100:.1f}% variance)")
        ax.set_ylabel(f"PC2 ({ev2 * 100:.1f}% variance)")
        ax.legend(frameon=True)
        fig.tight_layout()
        return _fig_to_png_bytes(fig, dpi=dpi)
    finally:
        fig.clear()
        plt.close(fig)
