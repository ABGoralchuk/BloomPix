"""Tab 3: Kinetic evolution, treatment ranking, heatmaps, PCA, and hypothesis tests."""

from __future__ import annotations

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns
import streamlit as st

from core.kinetics import (
    aggregate_kinetics_table,
    compute_morphology_pca,
    compute_treatment_statistics,
    fit_treatment_kinetics,
)
from ui import plot_utils, state

_METRIC_OPTIONS: dict[str, str] = {
    "Composite Bloom Index (CBI)": "cbi_score",
    "Bloom Coverage (%)": "bloom_coverage_pct",
    "TRNR Relief": "trnr_relief",
    "Local Roughness Median": "loc_trnr_median",
    "Blade Index": "blade_index",
    "Anisotropy Coherency": "anisotropy_coh",
    "Correlation Length (µm)": "corr_len_um",
    "Geometric Bloom Index": "geom_bloom_index",
}


def _fmt_opt(val: float | None, fmt: str = ".2f") -> str:
    if val is None or pd.isna(val):
        return "—"
    return format(val, fmt)


def render() -> None:
    st.header("3. Kinetics & Comparison")
    st.caption(
        "Storage-time logistic modeling, treatment suppression ranking, multi-metric PCA, "
        "and ANOVA / Kruskal–Wallis comparisons."
    )

    active_scale = state.get_active_scale()
    metrics_df = state.get_metrics_df(active_scale)
    if metrics_df is None or metrics_df.empty:
        st.info(
            f"Run surface roughness analysis for `{active_scale}` in "
            "**2. Roughness & Pseudo-AFM** first."
        )
        return

    cfg = state.get_analysis_config()

    metric_label = st.selectbox(
        "Kinetic Metric",
        options=list(_METRIC_OPTIONS.keys()),
        index=0,
        key="kin_metric_sel",
    )
    metric_col = _METRIC_OPTIONS[metric_label]

    agg_df = aggregate_kinetics_table(metrics_df, include_shared_control=True)
    fits, curves = fit_treatment_kinetics(
        agg_df,
        scale_label=active_scale,
        metric_col=metric_col,
        exclude_hv_mismatch=cfg.exclude_hv_mismatch_from_fits,
    )
    pca_res = compute_morphology_pca(
        metrics_df,
        exclude_hv_mismatch=cfg.exclude_hv_mismatch_from_fits,
    )

    # 1. Kinetic Evolution Plot
    st.subheader(f"Kinetic Progression — {metric_label} (`{active_scale}`)")
    treatments = sorted(agg_df["treatment"].unique())
    colors = plot_utils.treatment_colors(treatments)
    mean_col = f"{metric_col}_mean"
    sd_col = f"{metric_col}_sd"
    sem_col = f"{metric_col}_sem"

    fig_kin, ax_kin = plt.subplots(figsize=(9.5, 5.2))
    for trt in treatments:
        sub = agg_df[agg_df["treatment"] == trt].sort_values("week")
        col = colors[trt]
        normal = sub[~sub["any_hv_mismatch"]] if "any_hv_mismatch" in sub.columns else sub
        ax_kin.errorbar(
            normal["week"],
            normal[mean_col],
            yerr=normal[sd_col],
            fmt="o",
            color=col,
            capsize=3,
            markersize=5.5,
            label=f"{trt}",
        )
        if cfg.include_hv_mismatch_in_plots and "any_hv_mismatch" in sub.columns:
            hv_sub = sub[sub["any_hv_mismatch"]]
            if not hv_sub.empty:
                ax_kin.scatter(
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
            res = next((r for r in fits if r.treatment == trt), None)
            ls = "-" if (res is not None and res.fit_status == "Fitted") else "--"
            alpha = 0.9 if (res is not None and res.fit_status == "Fitted") else 0.55
            ax_kin.plot(tx, ty, linestyle=ls, color=col, alpha=alpha, lw=1.9)

    if cfg.include_hv_mismatch_in_plots and agg_df.get("any_hv_mismatch", pd.Series(False)).any():
        ax_kin.scatter([], [], marker="D", facecolors="none", edgecolors="black", label="HV_Mismatch (10 kV)")

    ax_kin.set_title(f"{metric_label} vs. Storage Time ({active_scale})")
    ax_kin.set_xlabel("Storage Time (Weeks)")
    ax_kin.set_ylabel(metric_label)
    ax_kin.grid(True, alpha=0.25)
    ax_kin.legend(ncol=2, frameon=True)
    plot_utils.render_and_register_fig(
        fig_kin,
        filename_base=f"kinetics_{active_scale}_{metric_col}",
        caption="Solid curves: fitted 4-parameter logistic (R² ≥ 0.50). Dashed curves: drift/suppressed reference. Hollow diamonds: HV_Mismatch weeks.",
    )

    # Focused CSV export for the currently displayed kinetic metric
    kin_export_rows: list[dict[str, object]] = []
    for trt in treatments:
        sub = agg_df[agg_df["treatment"] == trt].sort_values("week")
        tx, ty = curves.get(trt, (np.array([]), np.array([])))
        for _, row in sub.iterrows():
            wk = float(row["week"])
            fitted_val = float(np.interp(wk, tx, ty)) if tx.size > 0 else float("nan")
            kin_export_rows.append(
                {
                    "Treatment": trt,
                    "Week": int(row["week"]),
                    "Replicates_n": int(row["n"]),
                    "HV_Mismatch": bool(row.get("any_hv_mismatch", False)),
                    f"{metric_col}_mean": row[mean_col],
                    f"{metric_col}_sd": row[sd_col],
                    f"{metric_col}_sem": row[sem_col],
                    "Fitted_Curve_Value": fitted_val,
                }
            )
    kin_disp_df = pd.DataFrame(kin_export_rows)
    kin_disp_csv = kin_disp_df.to_csv(index=False).encode("utf-8")
    state.register_exported_table("kinetic_displayed_metric.csv", kin_disp_csv)
    st.download_button(
        label="Download Displayed Kinetic Data (CSV)",
        data=kin_disp_csv,
        file_name=f"bloompix_{active_scale}_{metric_col}_kinetics.csv",
        mime="text/csv",
        key=f"dl_kin_disp_{active_scale}_{metric_col}",
    )

    # 2. Ranking Table
    st.subheader("Treatment Ranking & Kinetic Parameters (Rank 1 = Best Bloom Suppression)")
    rank_df = pd.DataFrame(
        [
            {
                "Rank": r.rank,
                "Treatment": r.treatment,
                "Fit Status": r.fit_status,
                "t_lag (wk)": _fmt_opt(r.t_lag_weeks, ".2f"),
                "t_half (wk)": _fmt_opt(r.t_half_weeks, ".2f"),
                "k_rate": f"{r.k_rate:.3f}",
                "R²": _fmt_opt(r.r_squared, ".3f"),
                "AUC / wk": f"{r.auc_norm_per_week:.2f}",
                "Late-Stage Mean ± SD": f"{r.late_stage_mean:.2f} ± {r.late_stage_sd:.2f}",
                "Excluded HV Weeks": ", ".join(map(str, r.excluded_hv_weeks)) or "None",
            }
            for r in fits
        ]
    )
    st.dataframe(rank_df, width="stretch", hide_index=True)

    # 3. Treatment x Week Heatmap
    st.subheader(f"Treatment × Week Heatmap — {metric_label} (`{active_scale}`)")
    piv = agg_df.pivot(index="treatment", columns="week", values=mean_col)
    fig_hm, ax_hm = plt.subplots(figsize=(11, max(3.2, 0.7 * len(piv) + 1.5)))
    sns.heatmap(
        piv,
        annot=True,
        fmt=".1f",
        cmap="YlOrRd",
        linewidths=0.4,
        ax=ax_hm,
        cbar_kws={"label": metric_label},
    )
    ax_hm.set_title(f"{metric_label} Progression Matrix ({active_scale})")
    ax_hm.set_xlabel("Storage Time (Weeks)")
    ax_hm.set_ylabel("Treatment")
    plot_utils.render_and_register_fig(
        fig_hm,
        filename_base=f"heatmap_{active_scale}_{metric_col}",
    )

    hm_csv = piv.to_csv().encode("utf-8")
    state.register_exported_table("heatmap_matrix.csv", hm_csv)
    st.download_button(
        label="Download Heatmap Matrix (CSV)",
        data=hm_csv,
        file_name=f"bloompix_{active_scale}_{metric_col}_heatmap_matrix.csv",
        mime="text/csv",
        key=f"dl_hm_csv_{active_scale}_{metric_col}",
    )

    # 4. 2D Morphology PCA Ordination
    st.subheader("2D Morphology PCA Ordination")
    scores_df = pca_res["scores_df"]
    if scores_df.empty:
        st.warning("Insufficient samples for 2D PCA.")
    else:
        col_pca_fig, col_pca_tbl = st.columns([3, 2])
        with col_pca_fig:
            ev1, ev2 = pca_res["explained_variance_ratio"]
            fig_pca, ax_pca = plt.subplots(figsize=(7.2, 5.2))
            for trt in sorted(scores_df["treatment"].unique()):
                sub_p = scores_df[scores_df["treatment"] == trt]
                col = colors.get(trt, (0.3, 0.3, 0.3, 1.0))
                sizes = 28.0 + sub_p["week"].to_numpy(dtype=float) * 7.5
                ax_pca.scatter(
                    sub_p["PC1"],
                    sub_p["PC2"],
                    s=sizes,
                    color=col,
                    alpha=0.8,
                    edgecolors="white",
                    linewidths=0.5,
                    label=trt,
                )
            ax_pca.axhline(0.0, color="gray", lw=0.7, ls="--")
            ax_pca.axvline(0.0, color="gray", lw=0.7, ls="--")
            ax_pca.set_title(f"PCA of 9 Invariant Metrics ({active_scale})")
            ax_pca.set_xlabel(f"PC1 ({ev1 * 100:.1f}% variance)")
            ax_pca.set_ylabel(f"PC2 ({ev2 * 100:.1f}% variance)")
            ax_pca.legend(frameon=True)
            plot_utils.render_and_register_fig(
                fig_pca,
                filename_base=f"pca_{active_scale}",
                caption="Marker size scales with storage week.",
            )
        with col_pca_tbl:
            st.markdown("**Feature Loadings (9 Invariant Metrics)**")
            st.dataframe(
                pca_res["loadings_df"].round(3),
                width="stretch",
                hide_index=True,
            )

    # 5. Between-Treatment Statistical Comparison (isolated Min Week control)
    st.divider()
    st.subheader("Between-Treatment Statistical Comparison")
    st.caption(
        "Applies ONLY to ANOVA, Kruskal–Wallis, and pairwise hypothesis tests below "
        "(does not alter Kinetic Progression or PCA above)."
    )
    max_wk = int(metrics_df["week"].max()) if not metrics_df.empty else 16
    default_mw = min(max(state.get_stats_min_week(), 1), max(1, max_wk))
    col_mw, _ = st.columns([1, 4])
    with col_mw:
        min_week = int(
            st.number_input(
                "Statistical Comparison Min Week",
                min_value=1,
                max_value=max(1, max_wk),
                value=default_mw,
                step=1,
                key="kin_min_week",
            )
        )
    if min_week != state.get_stats_min_week():
        state.set_stats_min_week(min_week)
        state.clear_publication_archive(active_scale)

    stats = compute_treatment_statistics(
        metrics_df,
        metric_col=metric_col,
        exclude_hv_mismatch=cfg.exclude_hv_mismatch_from_fits,
        min_week=min_week,
    )

    state.set_kinetics_cache(
        active_scale,
        {
            "metric_col": metric_col,
            "agg_df": agg_df,
            "fit_results": fits,
            "curves": curves,
            "stats": stats,
            "pca": pca_res,
        },
    )

    s1, s2, s3 = st.columns(3)
    s1.metric("Post-Induction Observations", stats["n_observations"])
    s2.metric("One-Way ANOVA F", _fmt_opt(stats["anova_f"], ".2f"), f"p = {_fmt_opt(stats['anova_p'], '.2e')}")
    s3.metric("Kruskal–Wallis H", _fmt_opt(stats["kruskal_h"], ".2f"), f"p = {_fmt_opt(stats['kruskal_p'], '.2e')}")

    c_grp, c_pw = st.columns([2, 3])
    with c_grp:
        st.markdown(f"**Group Summary (Weeks ≥ {min_week})**")
        st.dataframe(stats["group_summary_df"].round(3), width="stretch", hide_index=True)
    with c_pw:
        st.markdown("**Pairwise Comparisons**")
        pw_df = stats["pairwise_df"].copy()
        if not pw_df.empty:
            for col in ("mean_a", "mean_b", "mean_diff", "t_welch"):
                pw_df[col] = pw_df[col].round(3)
            for col in ("p_welch", "p_mannwhitney"):
                pw_df[col] = pw_df[col].map(lambda v: f"{v:.3e}" if pd.notna(v) else "—")
        st.dataframe(pw_df, width="stretch", hide_index=True)
