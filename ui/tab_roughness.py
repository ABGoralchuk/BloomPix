"""Tab 2: Batch surface-roughness computation, all-weeks Pseudo-AFM grids, and 2D FFT PSD."""

from __future__ import annotations

import math
import time

import matplotlib
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import streamlit as st

from core.export_engine import build_individual_heatmaps_zip
from core.io_loader import load_sem_image
from core.preprocessing import make_display_image
from core.texture import (
    analyze_dataset_scale,
    compute_image_roughness,
    compute_treatment_week_maps,
)
from ui import plot_utils, state

_HEATMAP_CHOICES = [
    "Pseudo-AFM Local TRNR",
    "Sato Crystal Blade Response",
]


def _heatmap_spec(heatmap_type: str) -> tuple[str, str, str]:
    if heatmap_type == "Sato Crystal Blade Response":
        return "ridges_map", "magma", "Sato Ridge Response"
    return "loc_trnr_map", "inferno", "Local TRNR"


def render() -> None:
    st.header("2. Roughness & Pseudo-AFM")
    st.caption(
        "Brightness/contrast-invariant surface roughness, smooth isotropic Gaussian Pseudo-AFM "
        "heatmaps (σ = 1.0 µm), Sato crystal blade responses, and 2D FFT Radial PSD in µm⁻¹."
    )

    summary = state.get_dataset_summary()
    if summary is None:
        st.info("Scan a dataset in **1. Data & Metadata** first.")
        return

    active_scale = state.get_active_scale()
    cfg = state.get_analysis_config()
    masks = state.get_artifact_masks()

    if st.button(f"🚀 Run Surface Roughness Analysis ({active_scale})", type="primary"):
        prog = st.progress(0.0, text=f"Initializing {active_scale} batch analysis...")
        t0 = time.perf_counter()

        def _on_progress(done: int, total: int) -> None:
            frac = min(max(done / max(total, 1), 0.0), 1.0)
            prog.progress(frac, text=f"Analyzed {done}/{total} images ({active_scale})...")

        df_res, _, cal_info = analyze_dataset_scale(
            summary.records,
            scale_label=active_scale,
            config=cfg,
            artifact_masks=masks,
            progress_callback=_on_progress,
        )
        dt = time.perf_counter() - t0
        cal_info["runtime_sec"] = round(dt, 2)
        state.set_scale_results(active_scale, df_res, cal_info)
        prog.empty()
        st.success(
            f"Completed {cal_info['n_images']} images at `{active_scale}` in {dt:.2f} s "
            f"(control threshold = {cal_info['bloom_cov_threshold']:.3f})."
        )

    metrics_df = state.get_metrics_df(active_scale)
    cal_info = state.get_scale_cal_info(active_scale)
    scale_records = [
        r for r in summary.records if r.scale_label == active_scale and not r.excluded
    ]
    if not scale_records:
        st.warning(f"No active images available for scale `{active_scale}`.")
        return

    bloom_thresh = float(cal_info.get("bloom_cov_threshold", 6.0))
    treatments_non_ctrl = sorted(
        {r.treatment for r in scale_records if not r.is_shared_control}
    ) or sorted({r.treatment for r in scale_records})

    st.subheader("Pseudo-AFM & 2D FFT Spectral Inspector")
    mode = st.radio(
        "Inspection Mode",
        options=["Single Treatment (All Weeks)", "Compare Two Treatments"],
        horizontal=True,
        key="roughness_mode",
    )

    if mode == "Single Treatment (All Weeks)":
        c1, c2, c3 = st.columns(3)
        with c1:
            sel_trt = st.selectbox("Select Treatment", treatments_non_ctrl, key="aw_trt")
        reps_avail = sorted(
            {
                r.replicate
                for r in scale_records
                if r.treatment == sel_trt
            }
        ) or [1]
        with c2:
            sel_rep = st.selectbox(
                "Select Replicate",
                reps_avail,
                format_func=lambda rep: f"Rep {rep}",
                key="aw_rep",
            )
        with c3:
            heatmap_type = st.selectbox(
                "Select Heatmap Type",
                _HEATMAP_CHOICES,
                key="aw_hmap",
            )

        if st.button("🖼️ Generate All-Weeks Heatmaps & PSD", type="primary", key="btn_all_weeks"):
            with st.spinner(f"Computing all weeks for {sel_trt} (Rep {sel_rep})..."):
                entries = compute_treatment_week_maps(
                    scale_records,
                    treatment=sel_trt,
                    scale_label=active_scale,
                    replicate=int(sel_rep),
                    config=cfg,
                    bloom_cov_threshold=cal_info.get("bloom_cov_threshold"),
                    artifact_masks=masks,
                )
                state.set_week_maps(active_scale, sel_trt, int(sel_rep), entries)

        entries = state.get_week_maps(active_scale, sel_trt, int(sel_rep))
        if not entries:
            st.info(
                "Click **Generate All-Weeks Heatmaps & PSD** to render the complete week-by-week "
                "progression grid and 2D FFT Radial PSD curves."
            )
        else:
            map_key, cmap_name, cbar_label = _heatmap_spec(heatmap_type)
            shared_vmax = max(
                max(float(np.percentile(e[map_key], 98.0)) for e in entries),
                1e-6,
            )

            n_panels = len(entries)
            ncols = min(5, max(1, n_panels))
            nrows = math.ceil(n_panels / ncols)

            fig_grid, axes = plt.subplots(
                nrows,
                ncols,
                figsize=(3.5 * ncols, 3.0 * nrows),
                squeeze=False,
            )
            axes_flat = axes.ravel()
            last_im = None
            for idx, entry in enumerate(entries):
                ax = axes_flat[idx]
                extent, unit = plot_utils.make_spatial_extent(entry["calibration"])
                last_im = ax.imshow(
                    entry[map_key],
                    cmap=cmap_name,
                    vmin=0.0,
                    vmax=shared_vmax,
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

            for idx in range(n_panels, len(axes_flat)):
                axes_flat[idx].axis("off")

            fig_grid.suptitle(
                f"{sel_trt} (Rep {sel_rep}) — {heatmap_type} ({active_scale})",
                fontsize=12,
                y=0.995,
            )
            fig_grid.tight_layout(rect=[0.0, 0.0, 0.93, 0.96])
            if last_im is not None:
                cax = fig_grid.add_axes([0.94, 0.12, 0.015, 0.78])
                fig_grid.colorbar(last_im, cax=cax, label=cbar_label)

            plot_utils.render_and_register_fig(
                fig_grid,
                filename_base=f"all_weeks_{active_scale}_{sel_trt}_R{sel_rep}_{map_key}",
                caption="Shared color scale across all weeks (p98 global ceiling). Asterisk (*) marks HV_Mismatch (10 kV).",
                download_label="Download Combined All-Weeks Grid (300 DPI PNG)",
            )

            indiv_zip = build_individual_heatmaps_zip(
                week_entries=entries,
                map_type=map_key,
                treatment=sel_trt,
                scale_label=active_scale,
                shared_vmax=shared_vmax,
            )
            st.download_button(
                label="Download Individual High-Res Week Maps (ZIP)",
                data=indiv_zip,
                file_name=f"bloompix_{sel_trt}_{active_scale}_R{sel_rep}_{map_key}_weeks.zip",
                mime="application/zip",
                key=f"dl_indiv_zip_{active_scale}_{sel_trt}_{sel_rep}_{map_key}",
            )

            # All-Weeks 2D FFT Radial PSD Overlay
            st.subheader(f"All-Weeks 2D FFT Radial PSD — {sel_trt} (`{active_scale}`)")
            fig_psd, ax_psd = plt.subplots(figsize=(9.0, 4.8))
            cmap_wk = matplotlib.colormaps["viridis"]
            weeks_list = [int(e["week"]) for e in entries]
            wk_min, wk_max = min(weeks_list), max(max(weeks_list), 1)

            psd_table: dict[str, np.ndarray] = {
                "Frequency_um_inv": entries[0]["freq_um_inv"]
            }
            for entry in entries:
                wk = int(entry["week"])
                freqs = entry["freq_um_inv"]
                psd = entry["radial_psd"]
                col_key = "Week_0_Control" if wk == 0 else f"Week_{wk}"
                psd_table[col_key] = psd

                pos = (freqs > 0) & (psd > 0)
                t_norm = (wk - wk_min) / max(wk_max - wk_min, 1)
                lbl = "W0 (Ctrl)" if wk == 0 else (f"W{wk}*" if entry.get("hv_mismatch") else f"W{wk}")
                ax_psd.loglog(
                    freqs[pos],
                    psd[pos],
                    color=cmap_wk(t_norm),
                    lw=1.5,
                    alpha=0.9,
                    label=lbl if wk in (0, 2, 4, 8, 12, 16) or wk == wk_max else None,
                )

            sm = plt.cm.ScalarMappable(
                cmap=cmap_wk,
                norm=plt.Normalize(vmin=wk_min, vmax=wk_max),
            )
            sm.set_array([])
            fig_psd.colorbar(sm, ax=ax_psd, label="Storage Time (Weeks)")
            ax_psd.set_title(f"{sel_trt} (Rep {sel_rep}) — 2D FFT Radial PSD Progression ({active_scale})")
            ax_psd.set_xlabel("Spatial Frequency (µm⁻¹)")
            ax_psd.set_ylabel("Normalized PSD (a.u.)")
            ax_psd.grid(True, which="both", alpha=0.3)
            ax_psd.legend(loc="lower left", ncol=2, fontsize=8.5, frameon=True)
            fig_psd.tight_layout()
            plot_utils.render_and_register_fig(
                fig_psd,
                filename_base=f"psd_all_weeks_{active_scale}_{sel_trt}_R{sel_rep}",
            )

            psd_df = pd.DataFrame(psd_table)
            psd_csv = psd_df.to_csv(index=False).encode("utf-8")
            state.register_exported_table("psd_radial_data.csv", psd_csv)
            st.download_button(
                label="Download 2D FFT Radial PSD Data (CSV)",
                data=psd_csv,
                file_name=f"bloompix_{sel_trt}_{active_scale}_R{sel_rep}_radial_psd.csv",
                mime="text/csv",
                key=f"dl_psd_csv_{active_scale}_{sel_trt}_{sel_rep}",
            )

    else:
        non_ctrl_weeks = sorted({r.week for r in scale_records if r.week > 0}) or sorted(
            {r.week for r in scale_records}
        )
        c1, c2, c3, c4, c5 = st.columns(5)
        with c1:
            trt_a = st.selectbox("Treatment A", treatments_non_ctrl, index=0, key="cmp_trt_a")
        with c2:
            trt_b = st.selectbox(
                "Treatment B",
                treatments_non_ctrl,
                index=min(1, len(treatments_non_ctrl) - 1),
                key="cmp_trt_b",
            )
        with c3:
            cmp_wk = st.selectbox(
                "Week",
                non_ctrl_weeks,
                index=len(non_ctrl_weeks) - 1,
                key="cmp_wk",
            )
        with c4:
            cmp_rep = st.selectbox(
                "Replicate",
                [1, 2],
                format_func=lambda r: f"Rep {r}",
                key="cmp_rep",
            )
        with c5:
            cmp_hmap = st.selectbox("Heatmap Type", _HEATMAP_CHOICES, key="cmp_hmap")

        rec_a = next(
            (r for r in scale_records if r.treatment == trt_a and r.week == cmp_wk and r.replicate == cmp_rep),
            next((r for r in scale_records if r.treatment == trt_a and r.week == cmp_wk), None),
        )
        rec_b = next(
            (r for r in scale_records if r.treatment == trt_b and r.week == cmp_wk and r.replicate == cmp_rep),
            next((r for r in scale_records if r.treatment == trt_b and r.week == cmp_wk), None),
        )

        if rec_a is None or rec_b is None:
            st.warning("Selected treatments do not both have micrographs at this week.")
        else:
            raw_a, cal_a = load_sem_image(rec_a.filepath, rec_a.calibration)
            raw_b, cal_b = load_sem_image(rec_b.filepath, rec_b.calibration)
            m_a, maps_a = compute_image_roughness(
                raw_a, cal_a, record=rec_a, config=cfg, artifact_mask=masks.get(rec_a.image_id),
                bloom_cov_threshold=bloom_thresh, return_maps=True,
            )
            m_b, maps_b = compute_image_roughness(
                raw_b, cal_b, record=rec_b, config=cfg, artifact_mask=masks.get(rec_b.image_id),
                bloom_cov_threshold=bloom_thresh, return_maps=True,
            )
            assert maps_a is not None and maps_b is not None

            map_key, cmap_name, cbar_label = _heatmap_spec(cmp_hmap)
            shared_vmax = max(
                float(np.percentile(maps_a[map_key], 98.0)),
                float(np.percentile(maps_b[map_key], 98.0)),
                1e-6,
            )
            ext_a, unit_a = plot_utils.make_spatial_extent(cal_a)
            ext_b, unit_b = plot_utils.make_spatial_extent(cal_b)

            fig, axes = plt.subplots(2, 2, figsize=(12, 8.6))
            axes[0, 0].imshow(make_display_image(raw_a), cmap="gray", extent=ext_a, aspect="equal")
            axes[0, 0].set_title(f"{trt_a} — Week {cmp_wk} (SEM)")
            axes[0, 0].set_xlabel(f"X ({unit_a})")
            axes[0, 0].set_ylabel(f"Y ({unit_a})")

            axes[0, 1].imshow(make_display_image(raw_b), cmap="gray", extent=ext_b, aspect="equal")
            axes[0, 1].set_title(f"{trt_b} — Week {cmp_wk} (SEM)")
            axes[0, 1].set_xlabel(f"X ({unit_b})")
            axes[0, 1].set_ylabel(f"Y ({unit_b})")

            im_a = axes[1, 0].imshow(
                maps_a[map_key], cmap=cmap_name, vmin=0.0, vmax=shared_vmax, extent=ext_a, aspect="equal"
            )
            sub_a = f"Med={m_a.loc_trnr_median:.2f}, Cov={m_a.bloom_coverage_pct:.1f}%" if map_key == "loc_trnr_map" else f"Mean={m_a.blade_index:.3f}"
            axes[1, 0].set_title(f"{trt_a} — {cmp_hmap} ({sub_a})")
            axes[1, 0].set_xlabel(f"X ({unit_a})")
            axes[1, 0].set_ylabel(f"Y ({unit_a})")
            fig.colorbar(im_a, ax=axes[1, 0], fraction=0.046, pad=0.04, label=cbar_label)

            im_b = axes[1, 1].imshow(
                maps_b[map_key], cmap=cmap_name, vmin=0.0, vmax=shared_vmax, extent=ext_b, aspect="equal"
            )
            sub_b = f"Med={m_b.loc_trnr_median:.2f}, Cov={m_b.bloom_coverage_pct:.1f}%" if map_key == "loc_trnr_map" else f"Mean={m_b.blade_index:.3f}"
            axes[1, 1].set_title(f"{trt_b} — {cmp_hmap} ({sub_b})")
            axes[1, 1].set_xlabel(f"X ({unit_b})")
            axes[1, 1].set_ylabel(f"Y ({unit_b})")
            fig.colorbar(im_b, ax=axes[1, 1], fraction=0.046, pad=0.04, label=cbar_label)

            fig.tight_layout()
            plot_utils.render_and_register_fig(
                fig,
                filename_base=f"compare_{map_key}_{active_scale}_{trt_a}_vs_{trt_b}_W{cmp_wk}",
                caption=f"Shared {cmap_name} color scale across both treatments.",
            )

            fig_psd, ax_psd = plt.subplots(figsize=(7.6, 4.4))
            fa, pa = maps_a["freq_um_inv"], maps_a["radial_psd"]
            fb, pb = maps_b["freq_um_inv"], maps_b["radial_psd"]
            ax_psd.loglog(fa[(fa > 0) & (pa > 0)], pa[(fa > 0) & (pa > 0)], lw=1.8, label=f"{trt_a} (β={m_a.psd_beta:.2f})")
            ax_psd.loglog(fb[(fb > 0) & (pb > 0)], pb[(fb > 0) & (pb > 0)], lw=1.8, label=f"{trt_b} (β={m_b.psd_beta:.2f})")
            ax_psd.set_title(f"2D FFT Radial PSD Comparison — Week {cmp_wk} ({active_scale})")
            ax_psd.set_xlabel("Spatial Frequency (µm⁻¹)")
            ax_psd.set_ylabel("Normalized PSD (a.u.)")
            ax_psd.grid(True, which="both", alpha=0.3)
            ax_psd.legend()
            plot_utils.render_and_register_fig(
                fig_psd,
                filename_base=f"compare_psd_{active_scale}_{trt_a}_vs_{trt_b}_W{cmp_wk}",
            )

            cmp_psd_df = pd.DataFrame(
                {
                    "Frequency_um_inv": fa,
                    f"PSD_{trt_a}": pa,
                    f"PSD_{trt_b}": np.interp(fa, fb, pb) if len(fa) != len(fb) else pb,
                }
            )
            cmp_psd_csv = cmp_psd_df.to_csv(index=False).encode("utf-8")
            state.register_exported_table("psd_radial_data.csv", cmp_psd_csv)
            st.download_button(
                label="Download 2D FFT Radial PSD Data (CSV)",
                data=cmp_psd_csv,
                file_name=f"bloompix_{active_scale}_{trt_a}_vs_{trt_b}_W{cmp_wk}_psd.csv",
                mime="text/csv",
                key=f"dl_cmp_psd_{active_scale}_{trt_a}_{trt_b}_{cmp_wk}",
            )

    if metrics_df is not None and not metrics_df.empty:
        st.divider()
        st.subheader(f"Image-Level Metrics Table (`{active_scale}`)")
        st.dataframe(metrics_df, width="stretch", hide_index=True)
        st.download_button(
            label=f"Download {active_scale}_image_metrics.csv",
            data=metrics_df.to_csv(index=False).encode("utf-8"),
            file_name=f"bloompix_{active_scale}_image_metrics.csv",
            mime="text/csv",
        )
    else:
        st.info(
            f"Batch metrics table for `{active_scale}` is not computed yet. "
            "Click **Run Surface Roughness Analysis** above to populate all images."
        )
