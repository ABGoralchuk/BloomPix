"""Reproducible JSON settings, Markdown report, heatmap ZIP, and complete publication archive.

Strictly pure Python (ZERO ``streamlit`` imports).
"""

from __future__ import annotations

import inspect
import io
import json
import zipfile
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any, Callable, Optional

import numpy as np
import pandas as pd

from core.kinetics import (
    aggregate_kinetics_table,
    compute_morphology_pca,
    compute_treatment_statistics,
    fit_treatment_kinetics,
)
from core.models import (
    AnalysisConfig,
    ArtifactMask,
    DatasetSummary,
    KineticFitResult,
)
from core.report_plots import (
    KINETIC_METRIC_CATALOG,
    render_all_weeks_heatmap_grid_png,
    render_all_weeks_psd_png,
    render_kinetic_progression_png,
    render_morphology_pca_png,
    render_single_week_heatmap_png,
    render_treatment_week_heatmap_png,
)
from core.texture import compute_treatment_week_maps
from core.version import APP_NAME, get_build_label

PSEUDO_AFM_GAUSSIAN_SIGMA_UM = 1.0


def build_settings_json(
    summary: DatasetSummary,
    config: AnalysisConfig,
    scale_cal_info: dict[str, Any],
    artifact_masks: dict[str, ArtifactMask],
) -> str:
    """Serialize complete analysis settings, dataset audit, and active artifact masks to JSON."""
    serialized_masks = {
        k: asdict(v)
        for k, v in sorted(artifact_masks.items(), key=lambda item: item[0])
        if v.exclude_rects_um or v.auto_mask_pores
    }
    payload = {
        "application": APP_NAME,
        "build": get_build_label(),
        "exported_utc": datetime.now(timezone.utc).isoformat(),
        "dataset": {
            "root_dir": summary.root_dir,
            "n_records": len(summary.records),
            "treatments": summary.treatments,
            "weeks": summary.weeks,
            "scales": summary.scales,
            "dominant_hv_kv": summary.dominant_hv_kv,
            "has_shared_control": summary.has_shared_control,
            "excluded_image_ids": [r.image_id for r in summary.records if r.excluded],
            "hv_mismatch_image_ids": [r.image_id for r in summary.records if r.hv_mismatch],
        },
        "analysis_config": asdict(config),
        "methodology_parameters": {
            "pseudo_afm_gaussian_sigma_um": PSEUDO_AFM_GAUSSIAN_SIGMA_UM,
        },
        "scale_calibration_info": scale_cal_info,
        "artifact_masks": serialized_masks,
    }
    return json.dumps(payload, indent=2, sort_keys=False)


def _fmt_opt(val: Optional[float], fmt: str = ".2f") -> str:
    if val is None or pd.isna(val):
        return "—"
    return format(val, fmt)


def build_analysis_report_md(
    summary: DatasetSummary,
    config: AnalysisConfig,
    fit_results: list[KineticFitResult],
    stats_dict: dict[str, Any],
    artifact_masks: Optional[dict[str, ArtifactMask]] = None,
) -> str:
    """Build a structured Markdown summary report of dataset QC, kinetics, and statistics."""
    lines: list[str] = [
        f"# {APP_NAME} Quantitative SEM Fat-Bloom Report",
        "",
        f"- **Build:** `{get_build_label()}`",
        f"- **Generated (UTC):** `{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}`",
        f"- **Active Scale:** `{config.active_scale}`",
        f"- **Treatments:** `{', '.join(summary.treatments) or 'None'}`",
        f"- **Weeks:** `{summary.weeks}`",
        f"- **Dominant HV (kV):** `{summary.dominant_hv_kv}`",
        f"- **Exclude HV_Mismatch from Fits:** `{config.exclude_hv_mismatch_from_fits}`",
        f"- **Pseudo-AFM Local Roughness Smoothing:** `Isotropic Gaussian (σ = {PSEUDO_AFM_GAUSSIAN_SIGMA_UM:.1f} µm)`",
    ]

    if artifact_masks:
        active_masks = [
            k
            for k, v in artifact_masks.items()
            if v.exclude_rects_um or v.auto_mask_pores
        ]
        if active_masks:
            lines.append(f"- **Active Artifact Masks:** `{len(active_masks)}` image(s)")

    lines.extend(
        [
            "",
            "## Kinetic Treatment Ranking",
            "",
            "| Rank | Treatment | Fit Status | t_lag (wk) | t_half (wk) | k_rate | R² | AUC_norm | Late-Stage Mean ± SD |",
            "| ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )

    for res in fit_results:
        late_str = f"{res.late_stage_mean:.2f} ± {res.late_stage_sd:.2f}"
        lines.append(
            f"| {res.rank} | {res.treatment} | {res.fit_status} | "
            f"{_fmt_opt(res.t_lag_weeks)} | {_fmt_opt(res.t_half_weeks)} | "
            f"{res.k_rate:.3f} | {_fmt_opt(res.r_squared, '.3f')} | "
            f"{res.auc_norm_per_week:.2f} | {late_str} |"
        )

    lines.extend(
        [
            "",
            "## Between-Treatment Statistical Comparison",
            "",
            f"- **Metric:** `{stats_dict.get('metric_col', 'cbi_score')}` (weeks ≥ {stats_dict.get('min_week', 8)}, n = {stats_dict.get('n_observations', 0)})",
            f"- **One-Way ANOVA:** `F = {_fmt_opt(stats_dict.get('anova_f'), '.3f')}`, `p = {_fmt_opt(stats_dict.get('anova_p'), '.4e')}`",
            f"- **Kruskal-Wallis:** `H = {_fmt_opt(stats_dict.get('kruskal_h'), '.3f')}`, `p = {_fmt_opt(stats_dict.get('kruskal_p'), '.4e')}`",
            "",
        ]
    )

    pairwise_df = stats_dict.get("pairwise_df")
    if isinstance(pairwise_df, pd.DataFrame) and not pairwise_df.empty:
        lines.extend(
            [
                "| Comparison | Mean Diff | Welch t | p (Welch) | p (Mann-Whitney) |",
                "| --- | ---: | ---: | ---: | ---: |",
            ]
        )
        for _, row in pairwise_df.iterrows():
            lines.append(
                f"| {row['treatment_a']} vs {row['treatment_b']} | "
                f"{row['mean_diff']:.2f} | {_fmt_opt(row['t_welch'], '.3f')} | "
                f"{_fmt_opt(row['p_welch'], '.4e')} | {_fmt_opt(row['p_mannwhitney'], '.4e')} |"
            )

    return "\n".join(lines) + "\n"


def build_individual_heatmaps_zip(
    week_entries: list[dict[str, Any]],
    map_type: str,
    treatment: str,
    scale_label: str,
    shared_vmax: float,
    dpi: int = 300,
) -> bytes:
    """Render each week's Pseudo-AFM or Sato heatmap at 300 DPI into a single ZIP archive."""
    is_sato = "sato" in map_type.lower() or map_type == "ridges_map"
    map_key = "ridges_map" if is_sato else "loc_trnr_map"

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for entry in week_entries:
            wk = int(entry["week"])
            png_bytes = render_single_week_heatmap_png(
                entry=entry,
                map_type=map_key,
                treatment=treatment,
                scale_label=scale_label,
                shared_vmax=shared_vmax,
                dpi=dpi,
            )
            fname = f"{treatment}_{scale_label}_week_{wk:02d}_{map_key}.png"
            zf.writestr(fname, png_bytes)

    return buf.getvalue()


def build_export_zip(
    metrics_df: pd.DataFrame,
    agg_df: pd.DataFrame,
    fit_results: list[KineticFitResult],
    settings_json: str,
    report_md: str,
    figures: dict[str, bytes],
    dsc_corr_df: Optional[pd.DataFrame] = None,
    extra_tables: Optional[dict[str, bytes]] = None,
) -> bytes:
    """Package session CSV tables, JSON settings, Markdown report, and 300-DPI figures into ZIP."""
    buf = io.BytesIO()
    ranking_df = pd.DataFrame([asdict(r) for r in fit_results])

    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("settings.json", settings_json.encode("utf-8"))
        zf.writestr("analysis_report.md", report_md.encode("utf-8"))
        zf.writestr("tables/image_metrics.csv", metrics_df.to_csv(index=False).encode("utf-8"))
        zf.writestr("tables/kinetics_aggregated.csv", agg_df.to_csv(index=False).encode("utf-8"))
        zf.writestr("tables/kinetic_ranking.csv", ranking_df.to_csv(index=False).encode("utf-8"))

        if dsc_corr_df is not None and not dsc_corr_df.empty:
            zf.writestr(
                "tables/dsc_correlations.csv",
                dsc_corr_df.to_csv(index=False).encode("utf-8"),
            )

        if extra_tables:
            for tname, tbytes in extra_tables.items():
                clean_t = tname.lstrip("/")
                if not clean_t.startswith("tables/"):
                    clean_t = f"tables/{clean_t}"
                zf.writestr(clean_t, tbytes)

        for fname, fig_bytes in figures.items():
            clean_name = fname.lstrip("/")
            if not clean_name.startswith("figures/"):
                clean_name = f"figures/{clean_name}"
            zf.writestr(clean_name, fig_bytes)

    return buf.getvalue()


def _report_progress(
    cb: Optional[Callable[..., None]],
    done: int,
    total: int,
    msg: str,
) -> None:
    if cb is None:
        return
    try:
        n_params = len(inspect.signature(cb).parameters)
    except (TypeError, ValueError):
        n_params = 2
    if n_params >= 3:
        cb(done, total, msg)
    else:
        cb(done, total)


def _build_focused_kinetic_df(
    agg_df: pd.DataFrame,
    curves: dict[str, tuple[np.ndarray, np.ndarray]],
    metric_col: str,
) -> pd.DataFrame:
    mean_col = f"{metric_col}_mean"
    sd_col = f"{metric_col}_sd"
    sem_col = f"{metric_col}_sem"
    rows: list[dict[str, Any]] = []
    for trt in sorted(agg_df["treatment"].unique()):
        sub = agg_df[agg_df["treatment"] == trt].sort_values("week")
        tx, ty = curves.get(trt, (np.array([]), np.array([])))
        for _, row in sub.iterrows():
            wk = float(row["week"])
            fitted_val = float(np.interp(wk, tx, ty)) if tx.size > 0 else float("nan")
            rows.append(
                {
                    "Treatment": trt,
                    "Week": int(row["week"]),
                    "Replicates_n": int(row["n"]),
                    "HV_Mismatch": bool(row.get("any_hv_mismatch", False)),
                    mean_col: row[mean_col],
                    sd_col: row[sd_col],
                    sem_col: row[sem_col],
                    "Fitted_Curve_Value": fitted_val,
                }
            )
    return pd.DataFrame(rows)


def build_complete_publication_archive(
    summary: DatasetSummary,
    metrics_df: pd.DataFrame,
    config: AnalysisConfig,
    scale_label: str,
    scale_cal_info: dict[str, Any],
    stats_min_week: int = 8,
    replicates_to_export: tuple[int, ...] = (1,),
    include_individual_week_maps: bool = False,
    session_figures: Optional[dict[str, bytes]] = None,
    dsc_corr_df: Optional[pd.DataFrame] = None,
    artifact_masks: Optional[dict[str, ArtifactMask]] = None,
    progress_callback: Optional[Callable[..., None]] = None,
) -> tuple[bytes, dict[str, Any]]:
    """Build a self-contained, study-agnostic 300-DPI ZIP publication archive."""
    if metrics_df.empty:
        raise ValueError(f"Cannot build publication archive: no metrics computed for {scale_label}.")

    masks = artifact_masks or {}
    active_treatments = sorted(
        {
            str(t)
            for t in metrics_df["treatment"].dropna().unique()
            if str(t).strip().lower() != "control"
        }
    )
    if not active_treatments:
        active_treatments = list(summary.treatments)

    reps = tuple(dict.fromkeys(int(r) for r in replicates_to_export)) or (1,)
    total_steps = max(
        len(active_treatments) * len(reps) + len(KINETIC_METRIC_CATALOG) + 2,
        1,
    )
    step = 0

    agg_all = aggregate_kinetics_table(metrics_df, include_shared_control=True)
    pca_res = compute_morphology_pca(
        metrics_df,
        exclude_hv_mismatch=config.exclude_hv_mismatch_from_fits,
    )

    fits_cbi, _ = fit_treatment_kinetics(
        agg_all,
        scale_label=scale_label,
        metric_col="cbi_score",
        exclude_hv_mismatch=config.exclude_hv_mismatch_from_fits,
    )
    stats_cbi = compute_treatment_statistics(
        metrics_df,
        metric_col="cbi_score",
        exclude_hv_mismatch=config.exclude_hv_mismatch_from_fits,
        min_week=stats_min_week,
    )
    settings_json = build_settings_json(summary, config, scale_cal_info, masks)
    report_md = build_analysis_report_md(
        summary, config, fits_cbi, stats_cbi, artifact_masks=masks
    )

    scale_records = [
        r for r in summary.records if r.scale_label == scale_label and not r.excluded
    ]
    bloom_thresh = scale_cal_info.get("bloom_cov_threshold")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("settings.json", settings_json.encode("utf-8"))
        zf.writestr("analysis_report.md", report_md.encode("utf-8"))
        zf.writestr(
            "tables/image_metrics_all.csv",
            metrics_df.to_csv(index=False).encode("utf-8"),
        )
        zf.writestr(
            "tables/kinetics_aggregated_all.csv",
            agg_all.to_csv(index=False).encode("utf-8"),
        )

        # 1. Per-Treatment Tables, Heatmaps & 2D FFT Radial PSD
        for trt in active_treatments:
            trt_img_df = metrics_df[
                (metrics_df["treatment"] == trt)
                | (
                    (metrics_df["treatment"].astype(str).str.lower() == "control")
                    & (metrics_df["week"] == 0)
                )
            ]
            zf.writestr(
                f"tables/by_treatment/{trt}_image_metrics.csv",
                trt_img_df.to_csv(index=False).encode("utf-8"),
            )
            trt_agg_df = agg_all[agg_all["treatment"] == trt]
            zf.writestr(
                f"tables/by_treatment/{trt}_kinetics_summary.csv",
                trt_agg_df.to_csv(index=False).encode("utf-8"),
            )

            for rep in reps:
                step += 1
                _report_progress(
                    progress_callback,
                    step,
                    total_steps,
                    f"Rendering {trt} (Rep {rep}) Pseudo-AFM, Sato & PSD...",
                )
                week_entries = compute_treatment_week_maps(
                    scale_records,
                    treatment=trt,
                    scale_label=scale_label,
                    replicate=rep,
                    config=config,
                    bloom_cov_threshold=bloom_thresh,
                    artifact_masks=masks,
                )
                if not week_entries:
                    continue

                pafm_vmax = max(
                    max(float(np.percentile(e["loc_trnr_map"], 98.0)) for e in week_entries),
                    1e-6,
                )
                pafm_grid_png = render_all_weeks_heatmap_grid_png(
                    week_entries=week_entries,
                    map_type="loc_trnr_map",
                    treatment=trt,
                    replicate=rep,
                    scale_label=scale_label,
                    shared_vmax=pafm_vmax,
                )
                zf.writestr(
                    f"figures/heatmaps_pseudo_afm/{trt}_rep{rep}_pseudo_afm_all_weeks.png",
                    pafm_grid_png,
                )

                sato_vmax = max(
                    max(float(np.percentile(e["ridges_map"], 98.0)) for e in week_entries),
                    1e-6,
                )
                sato_grid_png = render_all_weeks_heatmap_grid_png(
                    week_entries=week_entries,
                    map_type="ridges_map",
                    treatment=trt,
                    replicate=rep,
                    scale_label=scale_label,
                    shared_vmax=sato_vmax,
                )
                zf.writestr(
                    f"figures/heatmaps_sato_blades/{trt}_rep{rep}_sato_blades_all_weeks.png",
                    sato_grid_png,
                )

                if include_individual_week_maps:
                    for entry in week_entries:
                        wk = int(entry["week"])
                        pafm_single = render_single_week_heatmap_png(
                            entry=entry,
                            map_type="loc_trnr_map",
                            treatment=trt,
                            scale_label=scale_label,
                            shared_vmax=pafm_vmax,
                        )
                        zf.writestr(
                            f"figures/heatmaps_pseudo_afm/individual/{trt}_rep{rep}/"
                            f"{trt}_{scale_label}_week_{wk:02d}_loc_trnr_map.png",
                            pafm_single,
                        )
                        sato_single = render_single_week_heatmap_png(
                            entry=entry,
                            map_type="ridges_map",
                            treatment=trt,
                            scale_label=scale_label,
                            shared_vmax=sato_vmax,
                        )
                        zf.writestr(
                            f"figures/heatmaps_sato_blades/individual/{trt}_rep{rep}/"
                            f"{trt}_{scale_label}_week_{wk:02d}_ridges_map.png",
                            sato_single,
                        )

                psd_png, psd_df = render_all_weeks_psd_png(
                    week_entries=week_entries,
                    treatment=trt,
                    replicate=rep,
                    scale_label=scale_label,
                )
                zf.writestr(
                    f"figures/fft_radial_psd/{trt}_rep{rep}_fft_radial_psd_all_weeks.png",
                    psd_png,
                )
                zf.writestr(
                    f"tables/by_treatment/{trt}_rep{rep}_fft_radial_psd.csv",
                    psd_df.to_csv(index=False).encode("utf-8"),
                )

        # 2. All 8 Kinetic Metrics (Plots + Focused CSVs + Ranking + Hypothesis Tests)
        for m_idx, (metric_col, metric_label) in enumerate(KINETIC_METRIC_CATALOG, start=1):
            step += 1
            _report_progress(
                progress_callback,
                step,
                total_steps,
                f"Rendering Kinetic Metric {m_idx}/{len(KINETIC_METRIC_CATALOG)}: {metric_label}...",
            )
            if f"{metric_col}_mean" not in agg_all.columns:
                continue

            fits, curves = fit_treatment_kinetics(
                agg_all,
                scale_label=scale_label,
                metric_col=metric_col,
                exclude_hv_mismatch=config.exclude_hv_mismatch_from_fits,
            )
            stats = compute_treatment_statistics(
                metrics_df,
                metric_col=metric_col,
                exclude_hv_mismatch=config.exclude_hv_mismatch_from_fits,
                min_week=stats_min_week,
            )

            kin_png = render_kinetic_progression_png(
                agg_df=agg_all,
                fits=fits,
                curves=curves,
                metric_col=metric_col,
                metric_label=metric_label,
                scale_label=scale_label,
                include_hv_mismatch=config.include_hv_mismatch_in_plots,
            )
            zf.writestr(
                f"figures/kinetics_all_8_metrics/{metric_col}_kinetic_progression.png",
                kin_png,
            )

            hm_png, piv_df = render_treatment_week_heatmap_png(
                agg_df=agg_all,
                metric_col=metric_col,
                metric_label=metric_label,
                scale_label=scale_label,
            )
            zf.writestr(
                f"figures/kinetics_all_8_metrics/{metric_col}_treatment_x_week_heatmap.png",
                hm_png,
            )

            focused_df = _build_focused_kinetic_df(agg_all, curves, metric_col)
            zf.writestr(
                f"tables/by_metric/{metric_col}_kinetic_data.csv",
                focused_df.to_csv(index=False).encode("utf-8"),
            )
            zf.writestr(
                f"tables/by_metric/{metric_col}_heatmap_matrix.csv",
                piv_df.to_csv().encode("utf-8"),
            )
            zf.writestr(
                f"tables/by_metric/{metric_col}_kinetic_ranking.csv",
                pd.DataFrame([asdict(r) for r in fits]).to_csv(index=False).encode("utf-8"),
            )
            stats_summary_df = pd.DataFrame(
                [
                    {
                        "metric_col": stats["metric_col"],
                        "min_week": stats["min_week"],
                        "n_observations": stats["n_observations"],
                        "anova_f": stats["anova_f"],
                        "anova_p": stats["anova_p"],
                        "kruskal_h": stats["kruskal_h"],
                        "kruskal_p": stats["kruskal_p"],
                    }
                ]
            )
            zf.writestr(
                f"tables/by_metric/{metric_col}_stats_summary.csv",
                stats_summary_df.to_csv(index=False).encode("utf-8"),
            )
            zf.writestr(
                f"tables/by_metric/{metric_col}_stats_pairwise.csv",
                stats["pairwise_df"].to_csv(index=False).encode("utf-8"),
            )

        # 3. Morphology PCA & Optional DSC / Session Figures
        step += 1
        _report_progress(
            progress_callback,
            step,
            total_steps,
            "Rendering 2D Morphology PCA & packaging archive...",
        )
        if not pca_res["scores_df"].empty:
            pca_png = render_morphology_pca_png(pca_res, scale_label=scale_label)
            zf.writestr(
                "figures/morphology_pca/morphology_pca_ordination.png",
                pca_png,
            )
            zf.writestr(
                "tables/pca_scores.csv",
                pca_res["scores_df"].to_csv(index=False).encode("utf-8"),
            )
            zf.writestr(
                "tables/pca_loadings.csv",
                pca_res["loadings_df"].to_csv(index=False).encode("utf-8"),
            )

        if dsc_corr_df is not None and not dsc_corr_df.empty:
            zf.writestr(
                "dsc/dsc_correlations.csv",
                dsc_corr_df.to_csv(index=False).encode("utf-8"),
            )

        if session_figures:
            for fname, fig_bytes in session_figures.items():
                clean_name = fname.lstrip("/").split("/")[-1]
                zf.writestr(f"figures/session_figures/{clean_name}", fig_bytes)

        entries = sorted(zf.namelist())

    step += 1
    _report_progress(progress_callback, total_steps, total_steps, "Archive complete.")

    zip_bytes = buf.getvalue()
    manifest_stats: dict[str, Any] = {
        "scale_label": scale_label,
        "n_treatments": len(active_treatments),
        "n_replicates": len(reps),
        "n_pngs": sum(1 for e in entries if e.lower().endswith(".png")),
        "n_csvs": sum(1 for e in entries if e.lower().endswith(".csv")),
        "n_files": len(entries),
        "zip_size_bytes": len(zip_bytes),
        "zip_size_mb": len(zip_bytes) / (1024.0 * 1024.0),
        "entries": entries,
    }
    return zip_bytes, manifest_stats
