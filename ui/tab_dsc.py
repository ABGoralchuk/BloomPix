"""Tab 5: Differential Scanning Calorimetry (DSC) upload and SEM-DSC correlations."""

from __future__ import annotations

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns
import streamlit as st

from core.dsc import correlate_sem_with_dsc, load_dsc_table
from core.kinetics import aggregate_kinetics_table
from ui import plot_utils, state


def render() -> None:
    st.header("4. DSC Correlation")
    st.caption(
        "Correlate SEM fat-bloom roughness/morphology metrics with Differential Scanning Calorimetry (DSC) "
        "thermal parameters across treatments and storage weeks."
    )

    summary = state.get_dataset_summary()
    active_scale = state.get_active_scale()
    metrics_df = state.get_metrics_df(active_scale)

    if summary is not None:
        tmpl_rows: list[dict[str, object]] = []
        if summary.has_shared_control:
            tmpl_rows.append(
                {
                    "treatment": "control",
                    "week": 0,
                    "T_onset_C": "",
                    "T_peak_C": "",
                    "Delta_H_J_g": "",
                    "Beta_VI_pct": "",
                }
            )
        for trt in summary.treatments:
            for wk in summary.weeks:
                if wk == 0 and summary.has_shared_control:
                    continue
                tmpl_rows.append(
                    {
                        "treatment": trt,
                        "week": wk,
                        "T_onset_C": "",
                        "T_peak_C": "",
                        "Delta_H_J_g": "",
                        "Beta_VI_pct": "",
                    }
                )
        tmpl_df = pd.DataFrame(tmpl_rows)
        st.download_button(
            label="📥 Download Pre-Populated DSC Template CSV",
            data=tmpl_df.to_csv(index=False).encode("utf-8"),
            file_name="bloompix_dsc_template.csv",
            mime="text/csv",
        )

    uploaded = st.file_uploader(
        "Upload DSC Table (.csv, .xlsx, .xls)",
        type=["csv", "xlsx", "xls"],
        key="dsc_uploader",
    )

    if uploaded is not None:
        try:
            dsc_df = load_dsc_table(uploaded)
            state.set_dsc_df(dsc_df)
            st.success(f"Loaded {len(dsc_df)} DSC rows.")
        except Exception as exc:
            st.error(f"Could not parse DSC file: {exc}")
            return

    dsc_df = state.get_dsc_df()
    if dsc_df is None:
        st.info("Upload a DSC CSV/Excel file above to compute SEM–DSC correlations.")
        return

    if metrics_df is None or metrics_df.empty:
        st.warning(
            f"Run surface roughness analysis for `{active_scale}` in **2. Roughness & Pseudo-AFM** "
            "before correlating with DSC."
        )
        return

    agg_df = aggregate_kinetics_table(metrics_df, include_shared_control=True)
    corr_df, merged_df = correlate_sem_with_dsc(agg_df, dsc_df)
    state.set_dsc_results(corr_df, merged_df)

    if corr_df.empty or merged_df.empty:
        st.warning("No overlapping `(treatment, week)` pairs with ≥ 3 valid points were found.")
        return

    st.subheader("Pearson & Spearman Correlation Summary")
    st.dataframe(corr_df.round(4), width="stretch", hide_index=True)

    col_hm, col_sc = st.columns(2)
    with col_hm:
        piv_r = corr_df.pivot(index="sem_metric", columns="dsc_parameter", values="pearson_r")
        fig_hm, ax_hm = plt.subplots(figsize=(6.5, max(4.0, 0.45 * len(piv_r) + 1.5)))
        sns.heatmap(
            piv_r,
            annot=True,
            fmt=".2f",
            cmap="RdBu_r",
            center=0.0,
            vmin=-1.0,
            vmax=1.0,
            ax=ax_hm,
            cbar_kws={"label": "Pearson r"},
        )
        ax_hm.set_title(f"SEM × DSC Correlation Matrix ({active_scale})")
        ax_hm.set_xlabel("DSC Parameter")
        ax_hm.set_ylabel("SEM Metric")
        plot_utils.render_and_register_fig(
            fig_hm,
            filename_base=f"dsc_heatmap_{active_scale}",
        )

    with col_sc:
        sem_choices = sorted(corr_df["sem_metric"].unique())
        dsc_choices = sorted(corr_df["dsc_parameter"].unique())
        sel_sem = st.selectbox("SEM Metric", sem_choices, key="dsc_sem_sel")
        sel_dsc = st.selectbox("DSC Parameter", dsc_choices, key="dsc_par_sel")

        x_col = f"{sel_sem}_mean" if f"{sel_sem}_mean" in merged_df.columns else sel_sem
        pair_df = merged_df[["treatment", "week", x_col, sel_dsc]].dropna()
        match = corr_df[
            (corr_df["sem_metric"] == sel_sem) & (corr_df["dsc_parameter"] == sel_dsc)
        ]

        fig_sc, ax_sc = plt.subplots(figsize=(6.5, 4.8))
        colors = plot_utils.treatment_colors(sorted(pair_df["treatment"].unique()))
        for trt, grp in pair_df.groupby("treatment"):
            ax_sc.scatter(
                grp[x_col],
                grp[sel_dsc],
                color=colors[str(trt)],
                s=65,
                alpha=0.85,
                label=str(trt),
            )
        if len(pair_df) >= 2:
            xv = pair_df[x_col].to_numpy(dtype=float)
            yv = pair_df[sel_dsc].to_numpy(dtype=float)
            if np.std(xv) > 1e-12:
                m_slope, b_int = np.polyfit(xv, yv, 1)
                x_line = np.linspace(xv.min(), xv.max(), 100)
                ax_sc.plot(x_line, m_slope * x_line + b_int, "k--", lw=1.4)

        ann = ""
        if not match.empty:
            r_val = float(match["pearson_r"].iloc[0])
            p_val = float(match["p_pearson"].iloc[0])
            ann = f" (r = {r_val:.3f}, p = {p_val:.2e})"
        ax_sc.set_title(f"{sel_sem} vs. {sel_dsc}{ann}")
        ax_sc.set_xlabel(sel_sem)
        ax_sc.set_ylabel(sel_dsc)
        ax_sc.grid(True, alpha=0.25)
        ax_sc.legend(frameon=True)
        plot_utils.render_and_register_fig(
            fig_sc,
            filename_base=f"dsc_scatter_{active_scale}_{sel_sem}_vs_{sel_dsc}",
        )
