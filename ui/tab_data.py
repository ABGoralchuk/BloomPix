"""Tab 1: Dataset discovery, compact coverage matrix, HV/calibration audit, and metadata overrides."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

from core.io_loader import save_metadata_overrides, scan_dataset
from ui import state


def render() -> None:
    st.header("1. Data & Metadata")
    st.caption(
        "Study-agnostic SEM micrograph discovery, Thermo Fisher Tag 34682 calibration parsing, "
        "HV consistency audit, and editable metadata overrides."
    )

    col_path, col_btn = st.columns([4, 1], vertical_alignment="bottom")
    with col_path:
        data_dir_input = st.text_input(
            "Dataset Root Directory",
            value=state.get_data_dir(),
            help="Expected subfolders: data/control/, data/1/, data/2/, ..., data/N/",
        )
    with col_btn:
        scan_clicked = st.button("🔍 Scan Dataset", type="primary", width="stretch")

    if scan_clicked:
        state.set_data_dir(data_dir_input.strip() or "data")
        try:
            summary = scan_dataset(state.get_data_dir())
            state.set_dataset_summary(summary)
            state.invalidate_downstream()
            st.success(f"Scanned {len(summary.records)} SEM images from '{summary.root_dir}'.")
        except Exception as exc:
            st.error(f"Failed to scan dataset: {exc}")
            return

    summary = state.get_dataset_summary()
    if summary is None:
        st.warning("No dataset loaded. Enter a valid directory and click **Scan Dataset**.")
        return

    active_scale = state.get_active_scale()
    active_records = [
        r for r in summary.records if r.scale_label == active_scale and not r.excluded
    ]
    hv_mismatch_count = sum(1 for r in summary.records if r.hv_mismatch)

    k1, k2, k3, k4, k5, k6 = st.columns(6)
    k1.metric("Total Images", len(summary.records))
    k2.metric(f"{active_scale} Active", len(active_records))
    k3.metric("Treatments", len(summary.treatments))
    k4.metric("Weeks", f"{min(summary.weeks)}–{max(summary.weeks)}" if summary.weeks else "—")
    k5.metric("Dominant HV", f"{summary.dominant_hv_kv:.1f} kV" if summary.dominant_hv_kv else "N/A")
    k6.metric("HV_Mismatch", hv_mismatch_count)

    st.subheader(f"Replicate Coverage Matrix (`{active_scale}`)")
    matrix_rows: list[dict[str, int]] = []
    for wk in summary.weeks:
        row: dict[str, int] = {"Week": wk}
        if summary.has_shared_control:
            row["control"] = sum(
                1 for r in active_records if r.week == wk and r.is_shared_control
            )
        for trt in summary.treatments:
            row[trt] = sum(
                1 for r in active_records if r.week == wk and r.treatment == trt
            )
        matrix_rows.append(row)

    col_cov, _ = st.columns([2, 3])
    with col_cov:
        st.dataframe(pd.DataFrame(matrix_rows), width="content", hide_index=True)

    st.subheader(f"HV & Calibration Audit (`{active_scale}`)")
    audit_df = pd.DataFrame(
        [
            {
                "Filename": r.filename,
                "Treatment": r.treatment,
                "Week": r.week,
                "HV (kV)": r.hv_kv,
                "WD (mm)": None if r.wd_mm is None else round(r.wd_mm, 3),
                "um_per_px": round(r.calibration.um_per_px, 6),
                "Databar (px)": r.calibration.databar_height_px,
                "HV_Mismatch": r.hv_mismatch,
            }
            for r in active_records
        ]
    )
    show_hv_only = st.checkbox("Show only HV-mismatched files", value=False)
    audit_view = audit_df[audit_df["HV_Mismatch"]] if show_hv_only else audit_df
    st.dataframe(audit_view, width="stretch", hide_index=True)

    st.subheader("Editable Dataset Metadata (`metadata_override.csv`)")
    meta_df = pd.DataFrame(
        [
            {
                "image_id": r.image_id,
                "treatment": r.treatment,
                "week": r.week,
                "scale_label": r.scale_label,
                "replicate": r.replicate,
                "hv_kv": r.hv_kv,
                "um_per_px": round(r.calibration.um_per_px, 6),
                "cal_source": r.calibration.source,
                "hv_mismatch": r.hv_mismatch,
                "excluded": r.excluded,
            }
            for r in summary.records
        ]
    )

    edited_df = st.data_editor(
        meta_df,
        width="stretch",
        hide_index=True,
        disabled=[
            "image_id",
            "replicate",
            "hv_kv",
            "um_per_px",
            "cal_source",
            "hv_mismatch",
        ],
        key="metadata_editor",
    )

    if st.button("Save Overrides to metadata_override.csv", width="content"):
        by_id = {r.image_id: r for r in summary.records}
        for _, erow in edited_df.iterrows():
            rec = by_id.get(str(erow["image_id"]))
            if rec is None:
                continue
            rec.treatment = str(erow["treatment"]).strip()
            rec.week = int(erow["week"])
            rec.scale_label = str(erow["scale_label"]).strip()
            rec.excluded = bool(erow["excluded"])
            rec.is_control = rec.week == 0
            rec.is_shared_control = rec.treatment.lower() == "control" and rec.week == 0

        override_path = Path(summary.root_dir) / "metadata_override.csv"
        save_metadata_overrides(summary.records, override_path)
        refreshed = scan_dataset(summary.root_dir, override_csv=override_path)
        state.set_dataset_summary(refreshed)
        state.invalidate_downstream()
        st.success(f"Saved overrides to {override_path} and refreshed dataset.")
        st.rerun()
