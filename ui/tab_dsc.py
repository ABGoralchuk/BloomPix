"""Tab 4: Raw TA Instruments DSC thermogram analysis, CSV/Excel upload, and SEM-DSC correlations."""

from __future__ import annotations

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns
import streamlit as st

from core.dsc import (
    DSC_PARAM_COLS,
    correlate_sem_with_dsc,
    load_dsc_table,
    scan_and_analyze_dsc_folder,
)
from core.kinetics import aggregate_kinetics_table
from ui import plot_utils, state


def _run_dsc_scan(dsc_dir: str) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, dict[str, object]]]:
    """Run raw TA Instruments DSC scan with smart auto-baseline and active per-file overrides."""
    rep_df, agg_dsc_df, curves = scan_and_analyze_dsc_folder(
        dsc_dir,
        auto_baseline=True,
        per_file_overrides=state.get_dsc_per_file_overrides(),
    )
    state.set_dsc_raw_data(rep_df, agg_dsc_df, curves)
    return rep_df, agg_dsc_df, curves


def _render_per_file_override_controls(
    rep_df: pd.DataFrame,
    review_files: list[str],
    dsc_dir: str,
    allow_all_default: bool = False,
) -> None:
    """Render targeted per-file baseline override sliders and immediate recompute buttons."""
    all_files = rep_df["filename"].astype(str).tolist()
    overrides = state.get_dsc_per_file_overrides()

    show_all = allow_all_default or not review_files
    if review_files and not allow_all_default:
        show_all = st.checkbox(
            "Show all files in override selector",
            value=False,
            key="dsc_override_show_all",
        )

    if show_all:
        choices = review_files + [f for f in all_files if f not in review_files]
    else:
        choices = list(review_files)

    if not choices:
        choices = all_files

    sel_file = st.selectbox(
        "Select DSC File for Baseline Override",
        options=choices,
        key="dsc_override_file",
    )
    row_match = rep_df[rep_df["filename"] == sel_file]
    cur_t_lo = (
        float(row_match["T_lo_used"].iloc[0])
        if not row_match.empty and pd.notna(row_match["T_lo_used"].iloc[0])
        else 22.2
    )
    cur_t_hi = (
        float(row_match["T_hi_used"].iloc[0])
        if not row_match.empty and pd.notna(row_match["T_hi_used"].iloc[0])
        else 41.0
    )

    default_low = overrides.get(
        sel_file,
        (
            (round(max(18.0, cur_t_lo - 0.5), 1), round(min(28.0, cur_t_lo + 0.5), 1)),
            (round(max(35.0, cur_t_hi - 1.5), 1), round(min(48.0, cur_t_hi + 1.5), 1)),
        ),
    )

    c1, c2 = st.columns(2)
    with c1:
        ov_low = st.slider(
            "Low Baseline (°C)",
            18.0,
            28.0,
            default_low[0],
            step=0.2,
            key=f"dsc_ov_low_{sel_file}",
        )
    with c2:
        ov_high = st.slider(
            "High Baseline (°C)",
            35.0,
            48.0,
            default_low[1],
            step=0.5,
            key=f"dsc_ov_high_{sel_file}",
        )

    b1, b2 = st.columns(2)
    with b1:
        if st.button("Apply Override & Recompute", key="dsc_apply_override", width="stretch"):
            state.set_dsc_file_override(sel_file, ov_low, ov_high)
            _run_dsc_scan(dsc_dir)
            state.set_dsc_override_notice(
                f"Applied manual override ({ov_low[0]:.1f}–{ov_low[1]:.1f} °C / "
                f"{ov_high[0]:.1f}–{ov_high[1]:.1f} °C) to {sel_file} and recomputed."
            )
            st.rerun()
    with b2:
        if st.button(
            "Reset Override",
            disabled=(sel_file not in overrides),
            key="dsc_reset_override",
            width="stretch",
        ):
            state.clear_dsc_file_override(sel_file)
            st.session_state.pop(f"dsc_ov_low_{sel_file}", None)
            st.session_state.pop(f"dsc_ov_high_{sel_file}", None)
            _run_dsc_scan(dsc_dir)
            state.set_dsc_override_notice(
                f"Reset manual override for {sel_file} back to automatic baseline detection."
            )
            st.rerun()


def _render_thermogram_inspector(
    dsc_rep_df: pd.DataFrame,
    dsc_curves: dict[str, dict[str, object]],
) -> None:
    st.subheader("Thermogram QA Inspector")
    ok_rows = dsc_rep_df.copy()
    treatments = sorted(ok_rows["treatment"].unique())
    c1, c2, c3 = st.columns(3)
    with c1:
        sel_trt = st.selectbox("Treatment", treatments, key="dsc_qa_trt")
    trt_rows = ok_rows[ok_rows["treatment"] == sel_trt]
    weeks = sorted(int(w) for w in trt_rows["week"].unique())
    with c2:
        sel_wk = st.selectbox("Week", weeks, key="dsc_qa_wk")
    wk_rows = trt_rows[trt_rows["week"] == sel_wk].sort_values("replicate")
    rep_opts = ["Overlay All Replicates"] + [
        f"Rep {int(r['replicate'])} — {r['filename']}" for _, r in wk_rows.iterrows()
    ]
    with c3:
        sel_rep = st.selectbox("Replicate View", rep_opts, key="dsc_qa_rep")

    fig, ax = plt.subplots(figsize=(9.2, 4.8))
    if sel_rep == "Overlay All Replicates":
        for _, row in wk_rows.iterrows():
            fname = str(row["filename"])
            payload = dsc_curves.get(fname)
            if not payload:
                continue
            T = payload["T"]
            hf = payload["hf_W_g"]
            qc_lbl = str(row.get("qc_flag", row["qc_status"]))
            lbl = f"Rep {int(row['replicate'])} ({qc_lbl})"
            ax.plot(T, hf, lw=1.4, label=lbl)
            if row["qc_status"] == "OK" and "baseline" in payload:
                ax.plot(T, payload["baseline"], ls="--", lw=0.9, alpha=0.6)
        ax.set_title(f"DSC Thermograms — {sel_trt}, Week {sel_wk} (Endothermic Down)")
    else:
        idx_pos = rep_opts.index(sel_rep) - 1
        row = wk_rows.iloc[idx_pos]
        fname = str(row["filename"])
        payload = dsc_curves.get(fname)
        if payload:
            T = payload["T"]
            hf = payload["hf_W_g"]
            base = payload["baseline"]
            ax.plot(T, hf, color="#1B365D", lw=1.6, label=f"Heat Flow ({fname})")
            if row["qc_status"] == "OK":
                b_mode = str(row.get("baseline_mode", "Auto"))
                ax.plot(
                    T,
                    base,
                    color="#64748B",
                    ls="--",
                    lw=1.2,
                    label=f"Linear Baseline ({b_mode}: {payload['T_lo']:.1f}–{payload['T_hi']:.1f} °C)",
                )
                if np.isfinite(payload.get("hf_lo", np.nan)) and np.isfinite(payload.get("hf_hi", np.nan)):
                    ax.scatter(
                        [payload["T_lo"], payload["T_hi"]],
                        [payload["hf_lo"], payload["hf_hi"]],
                        color="#0F172A",
                        s=38,
                        zorder=5,
                        label="Baseline Anchors",
                    )
                in_win = (T >= payload["T_lo"]) & (T <= payload["T_hi"]) & (hf < base)
                ax.fill_between(
                    T,
                    hf,
                    base,
                    where=in_win,
                    color="#2B6C7A",
                    alpha=0.22,
                    label=f"ΔH = {row['Delta_H_J_g']:.2f} J/g",
                )
                ax.axvline(payload["T_onset_C"], color="#D97706", ls=":", lw=1.4, label=f"T_onset = {payload['T_onset_C']:.2f} °C")
                ax.axvline(payload["T_peak_C"], color="#DC2626", ls="-.", lw=1.4, label=f"T_peak = {payload['T_peak_C']:.2f} °C")
        qc_tag = str(row.get("qc_flag", row["qc_status"]))
        bim_tag = " | Bimodal" if bool(row.get("is_bimodal", False)) else ""
        ax.set_title(
            f"DSC Thermogram QA — {sel_trt} Week {sel_wk} Rep {int(row['replicate'])} "
            f"[{qc_tag}{bim_tag}]"
        )

    ax.set_xlabel("Temperature (°C)")
    ax.set_ylabel("Normalized Heat Flow (W/g)")
    ax.grid(True, alpha=0.25)
    ax.legend(fontsize=8.5, frameon=True)
    fig.tight_layout()
    plot_utils.render_and_register_fig(
        fig,
        filename_base=f"dsc_thermogram_{sel_trt}_W{sel_wk}",
        caption="Endothermic melting peaks point downward (TA Instruments convention).",
    )


def _render_dsc_evolution(dsc_agg_df: pd.DataFrame) -> None:
    st.subheader("DSC Thermodynamic Evolution vs. Storage Time")
    param = st.selectbox("DSC Parameter", DSC_PARAM_COLS, index=1, key="dsc_evo_param")
    mean_col = f"{param}_mean"
    sd_col = f"{param}_sd"
    if mean_col not in dsc_agg_df.columns:
        return

    treatments = sorted(dsc_agg_df["treatment"].unique())
    colors = plot_utils.treatment_colors(treatments)

    fig, ax = plt.subplots(figsize=(9.2, 4.8))
    for trt in treatments:
        sub = dsc_agg_df[dsc_agg_df["treatment"] == trt].sort_values("week")
        ax.errorbar(
            sub["week"],
            sub[mean_col],
            yerr=sub[sd_col],
            fmt="o-",
            color=colors[trt],
            capsize=3,
            lw=1.7,
            markersize=5.5,
            label=trt,
        )
    ax.set_title(f"DSC {param} vs. Storage Time")
    ax.set_xlabel("Storage Time (Weeks)")
    ax.set_ylabel(param)
    ax.grid(True, alpha=0.25)
    ax.legend(ncol=2, frameon=True)
    fig.tight_layout()
    plot_utils.render_and_register_fig(
        fig,
        filename_base=f"dsc_evolution_{param}",
        caption="Mean ± SD across DSC replicates (incomplete/aborted runs excluded).",
    )


def _render_all_samples_dsc_table(
    rep_df: pd.DataFrame,
    agg_dsc_df: Optional[pd.DataFrame],
) -> None:
    """Display full DSC thermodynamic parameter table for all samples with direct CSV download."""
    st.subheader("All Samples — DSC Thermodynamic Parameters")
    view_mode = st.radio(
        "Table View",
        options=["Weekly Means ± SD (All Treatments)", "All Individual Replicates"],
        horizontal=True,
        key="dsc_all_samples_view",
    )

    if (
        view_mode == "Weekly Means ± SD (All Treatments)"
        and agg_dsc_df is not None
        and not agg_dsc_df.empty
    ):
        ordered_cols = [c for c in ["treatment", "week", "n_replicates"] if c in agg_dsc_df.columns]
        for col in DSC_PARAM_COLS:
            for suffix in ("_mean", "_sd"):
                cname = f"{col}{suffix}"
                if cname in agg_dsc_df.columns:
                    ordered_cols.append(cname)
        summary_df = agg_dsc_df[ordered_cols].copy()

        if "qc_flag" in rep_df.columns:
            qc_map = (
                rep_df.groupby(["treatment", "week"])["qc_flag"]
                .apply(
                    lambda s: "OK"
                    if (s.astype(str) == "OK").all()
                    else ", ".join(sorted(set(s.astype(str))))
                )
                .to_dict()
            )
            summary_df["qc_flag"] = [
                qc_map.get((str(r["treatment"]), int(r["week"])), "OK")
                for _, r in summary_df.iterrows()
            ]

        st.dataframe(summary_df.round(3), width="stretch", hide_index=True)
        st.download_button(
            label="📥 Download DSC Parameters Table (CSV)",
            data=summary_df.to_csv(index=False).encode("utf-8"),
            file_name="dsc_all_samples_summary.csv",
            mime="text/csv",
            type="primary",
            key="dl_dsc_all_samples_csv",
        )
    else:
        rep_cols = [
            c
            for c in [
                "filename",
                "treatment",
                "week",
                "replicate",
                *DSC_PARAM_COLS,
                "T_lo_used",
                "T_hi_used",
                "is_bimodal",
                "qc_flag",
                "baseline_mode",
            ]
            if c in rep_df.columns
        ]
        rep_view = rep_df[rep_cols].copy()
        st.dataframe(rep_view.round(3), width="stretch", hide_index=True)
        st.download_button(
            label="📥 Download DSC Parameters Table (CSV)",
            data=rep_view.to_csv(index=False).encode("utf-8"),
            file_name="dsc_all_samples_replicates.csv",
            mime="text/csv",
            type="primary",
            key="dl_dsc_all_samples_csv",
        )


def render() -> None:
    st.header("4. DSC Correlation")
    st.caption(
        "Automatic pre-melting plateau baseline detection on raw TA Instruments Discovery DSC (.txt) "
        "thermograms, targeted QC review, and pooled or per-treatment SEM–DSC correlations."
    )

    summary = state.get_dataset_summary()
    active_scale = state.get_active_scale()
    metrics_df = state.get_metrics_df(active_scale)
    cfg = state.get_analysis_config()

    mode = st.radio(
        "DSC Input Mode",
        options=["Raw TA Instruments DSC Folder (.txt)", "Upload Pre-Computed CSV / Excel"],
        horizontal=True,
        key="dsc_input_mode",
    )

    if mode == "Raw TA Instruments DSC Folder (.txt)":
        c_dir, c_btn = st.columns([3.5, 1.5], vertical_alignment="bottom")
        with c_dir:
            dsc_dir_input = st.text_input(
                "DSC Thermogram Folder",
                value=state.get_dsc_dir(),
                help="Folder containing TA Instruments .txt files named like <treatment>W<week>r<rep>.txt",
            )
        with c_btn:
            scan_dsc_btn = st.button("🔥 Scan & Analyze Raw DSC Folder", type="primary", width="stretch")

        if scan_dsc_btn:
            state.set_dsc_dir(dsc_dir_input.strip() or "DSC")
            try:
                with st.spinner("Auto-detecting DSC baselines and integrating TA Instruments thermograms..."):
                    rep_df, _, _ = _run_dsc_scan(state.get_dsc_dir())
                st.success(f"Parsed {len(rep_df)} DSC files from '{state.get_dsc_dir()}'.")
            except Exception as exc:
                st.error(f"Failed to scan DSC folder: {exc}")
                return

        rep_df, agg_dsc_df, curves = state.get_dsc_raw_data()
        if rep_df is not None and not rep_df.empty:
            override_notice = state.pop_dsc_override_notice()
            if override_notice:
                st.toast(override_notice, icon="✅")
                st.success(override_notice)

            n_total = len(rep_df)
            n_complete = int((rep_df["qc_status"] == "OK").sum())
            qc_flags = rep_df["qc_flag"].astype(str) if "qc_flag" in rep_df.columns else rep_df["qc_status"].astype(str)
            is_bim = (
                rep_df["is_bimodal"].fillna(False).astype(bool)
                if "is_bimodal" in rep_df.columns
                else pd.Series(False, index=rep_df.index)
            )
            n_ok_qc = int(qc_flags.isin(["OK", "OK (Manual)"]).sum())
            n_bimodal = int(is_bim.sum())
            needs_review_df = rep_df[qc_flags == "Review Baseline"].copy()
            n_review = len(needs_review_df)
            trts = sorted(rep_df["treatment"].unique())
            wks = sorted(int(w) for w in rep_df["week"].unique())

            k1, k2, k3, k4, k5 = st.columns(5)
            k1.metric("Files Parsed", n_total)
            k2.metric("Baseline QC OK", n_ok_qc)
            k3.metric("Needs Review", n_review)
            k4.metric("Treatments", len(trts))
            k5.metric("Weeks Covered", f"{min(wks)}–{max(wks)}" if wks else "—")

            notes: list[str] = []
            if 0 not in wks:
                notes.append("Week 0 (`control`) is not present in this DSC folder.")
            if summary is not None:
                missing_wks = sorted(set(summary.weeks) - set(wks) - {0})
                if missing_wks:
                    notes.append(f"SEM weeks absent from DSC: {missing_wks}.")
            n_inc = n_total - n_complete
            if n_inc > 0:
                inc_names = rep_df.loc[rep_df["qc_status"] != "OK", "filename"].tolist()
                notes.append(f"Excluded {n_inc} incomplete/aborted run(s): {', '.join(inc_names)}.")
            if notes:
                st.info(" ".join(notes))

            active_overrides = state.get_dsc_per_file_overrides()
            if n_review == 0:
                if active_overrides:
                    st.success(
                        f"All {n_total} DSC curves passed baseline QC "
                        f"({len(active_overrides)} manual override(s) active)."
                    )
                else:
                    st.success(f"All {n_total} DSC curves passed automatic baseline QC.")
                if n_bimodal > 0:
                    st.caption(
                        f"Informational: {n_bimodal} bimodal melting curve(s) detected "
                        "(normal for multi-polymorph chocolate); manual per-file override available below if needed."
                    )
                with st.expander("Manual Per-File Baseline Override (Optional)", expanded=False):
                    _render_per_file_override_controls(
                        rep_df,
                        review_files=[],
                        dsc_dir=state.get_dsc_dir(),
                        allow_all_default=True,
                    )
            else:
                st.subheader("⚠️ Curves Needing Baseline Review")
                st.warning(f"{n_review} curve(s) need baseline review.")
                if n_bimodal > 0:
                    st.caption(
                        f"Informational: {n_bimodal} bimodal melting curve(s) detected "
                        "(normal for multi-polymorph chocolate; not counted as QC failures)."
                    )
                show_cols = [
                    c
                    for c in [
                        "filename",
                        "treatment",
                        "week",
                        "replicate",
                        "T_lo_used",
                        "T_hi_used",
                        "T_onset_C",
                        "T_peak_C",
                        "Delta_H_J_g",
                        "baseline_overshoot_pct",
                        "is_bimodal",
                        "qc_flag",
                        "baseline_mode",
                    ]
                    if c in needs_review_df.columns
                ]
                st.dataframe(needs_review_df[show_cols].round(3), width="stretch", hide_index=True)
                with st.expander("Targeted Per-File Baseline Override", expanded=True):
                    _render_per_file_override_controls(
                        rep_df,
                        review_files=needs_review_df["filename"].astype(str).tolist(),
                        dsc_dir=state.get_dsc_dir(),
                        allow_all_default=False,
                    )

            _render_thermogram_inspector(rep_df, curves)
            if agg_dsc_df is not None and not agg_dsc_df.empty:
                _render_dsc_evolution(agg_dsc_df)
            _render_all_samples_dsc_table(rep_df, agg_dsc_df)

    else:
        if summary is not None:
            tmpl_rows: list[dict[str, object]] = []
            if summary.has_shared_control:
                tmpl_rows.append(
                    {
                        "treatment": "control",
                        "week": 0,
                        "T_onset_C": "",
                        "T_peak_C": "",
                        "FWHM_C": "",
                        "Delta_H_J_g": "",
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
                            "FWHM_C": "",
                            "Delta_H_J_g": "",
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
                dsc_df_up = load_dsc_table(uploaded)
                state.set_dsc_df(dsc_df_up)
                st.success(f"Loaded {len(dsc_df_up)} DSC rows.")
            except Exception as exc:
                st.error(f"Could not parse DSC file: {exc}")
                return

    dsc_df = state.get_dsc_df()
    if dsc_df is None or dsc_df.empty:
        st.info("Scan a raw DSC folder or upload a DSC CSV/Excel file above to compute SEM–DSC correlations.")
        return

    if metrics_df is None or metrics_df.empty:
        st.warning(
            f"Run surface roughness analysis for `{active_scale}` in **2. Roughness & Pseudo-AFM** "
            "before correlating with SEM."
        )
        return

    st.divider()
    st.subheader(f"SEM × DSC Correlation Analysis (`{active_scale}`)")

    exclude_hv = cfg.exclude_hv_mismatch_from_fits
    scope = st.radio(
        "Correlation Scope",
        options=["All Treatments (Pooled)", "Per-Treatment (Within-Group Aging)"],
        horizontal=True,
        key="dsc_corr_scope",
    )
    is_per_trt = scope == "Per-Treatment (Within-Group Aging)"

    sem_agg_df = aggregate_kinetics_table(metrics_df, include_shared_control=True)
    corr_df, merged_df = correlate_sem_with_dsc(
        sem_agg_df,
        dsc_df,
        exclude_hv_mismatch=exclude_hv,
        per_treatment=is_per_trt,
    )
    state.set_dsc_results(corr_df, merged_df)

    if corr_df.empty or merged_df.empty:
        st.warning("No overlapping `(treatment, week)` pairs with ≥ 3 valid points were found.")
        return

    hv_msg = (
        "HV-mismatched weeks excluded per global sidebar policy"
        if exclude_hv
        else "Including HV-mismatched weeks per global sidebar policy"
    )
    has_w0 = bool((merged_df["week"] == 0).any())
    w0_msg = "including shared Week 0 (`control`)" if has_w0 else "without Week 0 (`control`)"
    st.caption(f"Matched **{len(merged_df)}** overlapping `(treatment, week)` pairs ({hv_msg}, {w0_msg}).")

    if not is_per_trt:
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
            ax_hm.set_title(f"SEM × DSC Pooled Correlation Matrix ({active_scale})")
            ax_hm.set_xlabel("DSC Parameter")
            ax_hm.set_ylabel("SEM Metric")
            fig_hm.tight_layout()
            plot_utils.render_and_register_fig(
                fig_hm,
                filename_base=f"dsc_heatmap_{active_scale}_pooled",
            )

        with col_sc:
            sem_choices = sorted(corr_df["sem_metric"].unique())
            dsc_choices = sorted(corr_df["dsc_parameter"].unique())
            sel_sem = st.selectbox("SEM Metric", sem_choices, key="dsc_sem_sel")
            sel_dsc = st.selectbox("DSC Parameter", dsc_choices, key="dsc_par_sel")

            x_col = f"{sel_sem}_mean" if f"{sel_sem}_mean" in merged_df.columns else sel_sem
            y_col = f"{sel_dsc}_mean" if f"{sel_dsc}_mean" in merged_df.columns else sel_dsc
            pair_df = merged_df[["treatment", "week", x_col, y_col]].dropna()
            match = corr_df[
                (corr_df["sem_metric"] == sel_sem) & (corr_df["dsc_parameter"] == sel_dsc)
            ]

            fig_sc, ax_sc = plt.subplots(figsize=(6.5, 4.8))
            colors = plot_utils.treatment_colors(sorted(pair_df["treatment"].unique()))
            for trt, grp in pair_df.groupby("treatment"):
                ax_sc.scatter(
                    grp[x_col],
                    grp[y_col],
                    color=colors[str(trt)],
                    s=65,
                    alpha=0.85,
                    label=str(trt),
                )
            if len(pair_df) >= 2:
                xv = pair_df[x_col].to_numpy(dtype=float)
                yv = pair_df[y_col].to_numpy(dtype=float)
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
            fig_sc.tight_layout()
            plot_utils.render_and_register_fig(
                fig_sc,
                filename_base=f"dsc_scatter_{active_scale}_{sel_sem}_vs_{sel_dsc}",
            )
    else:
        avail_trts = sorted(corr_df["treatment"].unique())
        c_trt, c_all = st.columns([2, 1], vertical_alignment="bottom")
        with c_trt:
            sel_trt = st.selectbox("Select Treatment", avail_trts, key="dsc_corr_trt_sel")
        with c_all:
            show_all = st.checkbox("Show all treatments in table", value=False, key="dsc_corr_show_all")

        trt_corr_df = corr_df[corr_df["treatment"] == sel_trt].reset_index(drop=True)
        trt_merged_df = merged_df[merged_df["treatment"] == sel_trt].sort_values("week")

        display_tbl = corr_df if show_all else trt_corr_df
        st.dataframe(display_tbl.round(4), width="stretch", hide_index=True)

        col_hm, col_sc = st.columns(2)
        with col_hm:
            piv_r = trt_corr_df.pivot(index="sem_metric", columns="dsc_parameter", values="pearson_r")
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
            ax_hm.set_title(f"{sel_trt} — Within-Group SEM × DSC ({active_scale})")
            ax_hm.set_xlabel("DSC Parameter")
            ax_hm.set_ylabel("SEM Metric")
            fig_hm.tight_layout()
            plot_utils.render_and_register_fig(
                fig_hm,
                filename_base=f"dsc_heatmap_{active_scale}_{sel_trt}",
            )

        with col_sc:
            sem_choices = sorted(trt_corr_df["sem_metric"].unique())
            dsc_choices = sorted(trt_corr_df["dsc_parameter"].unique())
            sel_sem = st.selectbox("SEM Metric", sem_choices, key="dsc_pt_sem_sel")
            sel_dsc = st.selectbox("DSC Parameter", dsc_choices, key="dsc_pt_par_sel")

            x_col = f"{sel_sem}_mean" if f"{sel_sem}_mean" in trt_merged_df.columns else sel_sem
            y_col = f"{sel_dsc}_mean" if f"{sel_dsc}_mean" in trt_merged_df.columns else sel_dsc
            pair_df = trt_merged_df[["week", x_col, y_col]].dropna()
            match = trt_corr_df[
                (trt_corr_df["sem_metric"] == sel_sem) & (trt_corr_df["dsc_parameter"] == sel_dsc)
            ]

            fig_sc, ax_sc = plt.subplots(figsize=(6.5, 4.8))
            trt_color = plot_utils.treatment_colors(avail_trts).get(sel_trt, "#1B365D")
            ax_sc.scatter(
                pair_df[x_col],
                pair_df[y_col],
                color=trt_color,
                s=75,
                alpha=0.9,
                label=f"{sel_trt} weekly means",
            )
            for _, prow in pair_df.iterrows():
                ax_sc.annotate(
                    f"W{int(prow['week'])}",
                    (float(prow[x_col]), float(prow[y_col])),
                    textcoords="offset points",
                    xytext=(5, 4),
                    fontsize=8,
                )
            if len(pair_df) >= 2:
                xv = pair_df[x_col].to_numpy(dtype=float)
                yv = pair_df[y_col].to_numpy(dtype=float)
                if np.std(xv) > 1e-12:
                    m_slope, b_int = np.polyfit(xv, yv, 1)
                    x_line = np.linspace(xv.min(), xv.max(), 100)
                    ax_sc.plot(x_line, m_slope * x_line + b_int, "k--", lw=1.4)

            ann = ""
            if not match.empty:
                r_val = float(match["pearson_r"].iloc[0])
                p_val = float(match["p_pearson"].iloc[0])
                n_val = int(match["n_pairs"].iloc[0])
                ann = f" (r = {r_val:.3f}, p = {p_val:.2e}, n = {n_val})"
            ax_sc.set_title(f"{sel_trt}: {sel_sem} vs. {sel_dsc}{ann}")
            ax_sc.set_xlabel(sel_sem)
            ax_sc.set_ylabel(sel_dsc)
            ax_sc.grid(True, alpha=0.25)
            ax_sc.legend(frameon=True)
            fig_sc.tight_layout()
            plot_utils.render_and_register_fig(
                fig_sc,
                filename_base=f"dsc_scatter_{active_scale}_{sel_trt}_{sel_sem}_vs_{sel_dsc}",
            )
