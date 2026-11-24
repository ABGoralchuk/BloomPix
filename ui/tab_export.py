"""Tab 5: Reproducible settings, report preview, and complete 300-DPI archive builder."""

from __future__ import annotations

from datetime import datetime

import pandas as pd
import streamlit as st

from core.export_engine import (
    build_analysis_report_md,
    build_complete_publication_archive,
    build_export_zip,
    build_settings_json,
)
from core.kinetics import (
    aggregate_kinetics_table,
    compute_treatment_statistics,
    fit_treatment_kinetics,
)
from ui import state


def render() -> None:
    st.header("5. Export & Report")
    st.caption(
        "Build and download a complete, study-agnostic publication package containing 300-DPI "
        "figures and CSV tables for all treatments and all 8 kinetic metrics."
    )

    summary = state.get_dataset_summary()
    active_scale = state.get_active_scale()
    metrics_df = state.get_metrics_df(active_scale)
    cfg = state.get_analysis_config()
    cal_info = state.get_scale_cal_info(active_scale)
    masks = state.get_artifact_masks()
    figures = state.get_exported_figures()
    extra_tables = state.get_exported_tables()
    dsc_corr_df, _ = state.get_dsc_results()

    if summary is None or metrics_df is None or metrics_df.empty:
        st.info(
            "Run dataset scan (**1. Data & Metadata**) and surface roughness analysis for "
            f"`{active_scale}` (**2. Roughness & Pseudo-AFM**) to enable full archive export."
        )
        return

    kin_cache = state.get_kinetics_cache(active_scale)
    if kin_cache is not None:
        agg_df = kin_cache["agg_df"]
        fits = kin_cache["fit_results"]
        stats = kin_cache["stats"]
    else:
        agg_df = aggregate_kinetics_table(metrics_df, include_shared_control=True)
        fits, _ = fit_treatment_kinetics(
            agg_df,
            scale_label=active_scale,
            metric_col="cbi_score",
            exclude_hv_mismatch=cfg.exclude_hv_mismatch_from_fits,
        )
        stats = compute_treatment_statistics(
            metrics_df,
            metric_col="cbi_score",
            exclude_hv_mismatch=cfg.exclude_hv_mismatch_from_fits,
            min_week=state.get_stats_min_week(),
        )

    settings_json = build_settings_json(summary, cfg, cal_info, masks)
    report_md = build_analysis_report_md(
        summary, cfg, fits, stats, artifact_masks=masks
    )

    # Section 1: Analysis Report & Reproducible Settings Preview
    st.subheader("1. Analysis Report & Reproducible Settings Preview")
    prev_rep, prev_set = st.tabs(
        ["Report Preview (analysis_report.md)", "Reproducibility Config (settings.json)"]
    )
    with prev_rep:
        st.markdown(report_md)
    with prev_set:
        st.code(settings_json, language="json")

    st.divider()

    # Section 2: Complete Publication Archive (ZIP)
    st.subheader(f"2. Complete Publication Archive (ZIP — `{active_scale}`)")
    reps_avail = sorted(
        {
            int(r.replicate)
            for r in summary.records
            if r.scale_label == active_scale and not r.excluded
        }
    ) or [1]
    scope_options = ["Rep 1 (Recommended — Fast)"]
    if 2 in reps_avail:
        scope_options.append("Rep 2")
    if len(reps_avail) > 1:
        scope_options.append("All Replicates")

    max_wk = int(metrics_df["week"].max()) if not metrics_df.empty else 16
    default_mw = min(max(state.get_stats_min_week(), 1), max(1, max_wk))

    c_scope, c_mw = st.columns([2, 1])
    with c_scope:
        rep_scope = st.selectbox(
            "Heatmap & PSD Replicate Scope",
            options=scope_options,
            index=0,
            key=f"exp_rep_scope_{active_scale}",
        )
    with c_mw:
        stats_mw = int(
            st.number_input(
                "Statistical Comparison Min Week (all 8 metrics)",
                min_value=1,
                max_value=max(1, max_wk),
                value=default_mw,
                step=1,
                key=f"exp_stats_mw_{active_scale}",
            )
        )
    if stats_mw != state.get_stats_min_week():
        state.set_stats_min_week(stats_mw)
        state.clear_publication_archive(active_scale)

    include_indiv = st.checkbox(
        "Include individual per-week 300-DPI heatmaps for every treatment (larger ZIP)",
        value=False,
        key=f"exp_indiv_{active_scale}",
        help="All-Weeks Combined Grids for BOTH Pseudo-AFM Local TRNR and Sato Crystal Blade Response are ALWAYS included for every treatment.",
    )

    if rep_scope == "All Replicates":
        reps_tuple = tuple(reps_avail)
    elif rep_scope == "Rep 2":
        reps_tuple = (2,)
    else:
        reps_tuple = (1,)

    if st.button(
        f"📦 Build Complete Publication Archive ({active_scale})",
        type="primary",
        key=f"btn_build_archive_{active_scale}",
    ):
        prog = st.progress(0.0, text="Initializing Complete Publication Archive build...")

        def _on_archive_progress(done: int, total: int, msg: str) -> None:
            frac = min(max(done / max(total, 1), 0.0), 1.0)
            prog.progress(frac, text=msg)

        zip_bytes, manifest = build_complete_publication_archive(
            summary=summary,
            metrics_df=metrics_df,
            config=cfg,
            scale_label=active_scale,
            scale_cal_info=cal_info,
            stats_min_week=stats_mw,
            replicates_to_export=reps_tuple,
            include_individual_week_maps=include_indiv,
            session_figures=figures,
            dsc_corr_df=dsc_corr_df,
            artifact_masks=masks,
            progress_callback=_on_archive_progress,
        )
        stamp = datetime.now().strftime("%Y%m%d_%H%M")
        fname = f"BloomPix_Publication_Archive_{active_scale}_{stamp}.zip"
        state.set_publication_archive(active_scale, zip_bytes, manifest, fname)
        prog.empty()

    cached_arch = state.get_publication_archive(active_scale)
    if cached_arch is not None:
        man = cached_arch["manifest"]
        st.success(
            f"**{man['n_pngs']} PNG figures (300 DPI) | {man['n_csvs']} CSV tables | "
            f"{man['zip_size_mb']:.2f} MB** — Ready for download across "
            f"{man['n_treatments']} treatments."
        )
        st.download_button(
            label="⬇️ Download Complete Publication Archive (ZIP)",
            data=cached_arch["zip_bytes"],
            file_name=cached_arch["filename"],
            mime="application/zip",
            type="primary",
            key=f"dl_complete_arch_{active_scale}",
        )
        with st.expander(f"Archive File Manifest ({man['n_files']} files)", expanded=False):
            st.dataframe(
                pd.DataFrame({"Path inside ZIP": man["entries"]}),
                width="stretch",
                hide_index=True,
            )

    st.divider()

    # Section 3: Lightweight Quick Session Export
    with st.expander("Quick Session Export (Already-Rendered Figures & Core Tables Only)", expanded=False):
        k1, k2, k3 = st.columns(3)
        k1.metric("Analyzed Images", len(metrics_df))
        k2.metric("Session 300-DPI Figures", len(figures))
        k3.metric("Session Extra CSV Tables", len(extra_tables))

        quick_zip = build_export_zip(
            metrics_df=metrics_df,
            agg_df=agg_df,
            fit_results=fits,
            settings_json=settings_json,
            report_md=report_md,
            figures=figures,
            dsc_corr_df=dsc_corr_df,
            extra_tables=extra_tables,
        )
        st.download_button(
            label="Download Quick Session Bundle (ZIP)",
            data=quick_zip,
            file_name=f"bloompix_{active_scale}_session_bundle.zip",
            mime="application/zip",
            key=f"dl_quick_zip_{active_scale}",
        )
