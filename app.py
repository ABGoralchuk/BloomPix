"""BloomPix — Chocolate Surface SEM Fat-Bloom Analyzer (Streamlit Entrypoint)."""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from core.io_loader import scan_dataset
from core.version import get_build_label
from ui import help_docs, state, tab_data, tab_dsc, tab_export, tab_kinetics, tab_roughness

_ICON_PATH = Path(__file__).resolve().parent / "assets" / "bloompix.png"
TAB_NAMES: list[str] = [
    "1. Data & Metadata",
    "2. Roughness & Pseudo-AFM",
    "3. Kinetics & Comparison",
    "4. DSC Correlation",
    "5. Export & Report",
]

st.set_page_config(
    page_title="BloomPix — SEM Fat Bloom Analyzer",
    page_icon=str(_ICON_PATH) if _ICON_PATH.exists() else "🔬",
    layout="wide",
    initial_sidebar_state="expanded",
)


def _auto_scan_default_data() -> None:
    if state.get_dataset_summary() is not None:
        return
    data_path = Path(state.get_data_dir())
    if not data_path.is_dir():
        return
    has_subdirs = any(p.is_dir() and not p.name.startswith(".") for p in data_path.iterdir())
    if not has_subdirs:
        return
    try:
        summary = scan_dataset(data_path)
        if summary.records:
            state.set_dataset_summary(summary)
    except Exception:
        pass


def _render_sidebar() -> None:
    with st.sidebar:
        if _ICON_PATH.exists():
            st.image(str(_ICON_PATH), width=110)
        st.title("BloomPix")
        st.caption("SEM Chocolate Fat Bloom & Surface Roughness Analyzer")
        st.divider()

        summary = state.get_dataset_summary()
        cfg = state.get_analysis_config()

        if summary is None:
            st.info("No dataset scanned yet. Open **1. Data & Metadata** to scan a folder.")
        else:
            hv_outliers = sum(1 for r in summary.records if r.hv_mismatch)
            active_scale = state.get_active_scale()
            active_n = sum(
                1 for r in summary.records if r.scale_label == active_scale and not r.excluded
            )
            st.subheader("Dataset Status")
            st.markdown(
                f"- **Total images:** `{len(summary.records)}`\n"
                f"- **Active scale (`{active_scale}`):** `{active_n}` images\n"
                f"- **Treatments:** `{', '.join(summary.treatments) or 'control only'}`\n"
                f"- **Dominant HV:** `{summary.dominant_hv_kv or 'N/A'} kV`\n"
                f"- **HV_Mismatch flagged:** `{hv_outliers}`"
            )

            if summary.scales:
                cur_idx = (
                    summary.scales.index(active_scale)
                    if active_scale in summary.scales
                    else 0
                )
                chosen_scale = st.radio(
                    "Active Analysis Scale",
                    options=summary.scales,
                    index=cur_idx,
                    help="Magnification scales are analyzed independently and never mixed in kinetic curves.",
                )
                if chosen_scale != active_scale:
                    state.set_active_scale(chosen_scale)
                    st.rerun()

        st.divider()
        st.subheader("Global HV Policy")
        excl_hv = st.checkbox(
            "Exclude HV-mismatched weeks (e.g., 10 kV) from kinetic fits",
            value=cfg.exclude_hv_mismatch_from_fits,
        )
        show_hv = st.checkbox(
            "Show HV-mismatched points on plots (flagged marker)",
            value=cfg.include_hv_mismatch_in_plots,
        )
        if (
            excl_hv != cfg.exclude_hv_mismatch_from_fits
            or show_hv != cfg.include_hv_mismatch_in_plots
        ):
            cfg.exclude_hv_mismatch_from_fits = excl_hv
            cfg.include_hv_mismatch_in_plots = show_hv
            st.session_state["kinetics_cache"].clear()
            state.clear_publication_archive()

        st.divider()
        help_docs.render_sidebar_help(TAB_NAMES)

        st.divider()
        st.caption(f"Build: `{get_build_label()}`")


def main() -> None:
    state.init_state()
    _auto_scan_default_data()
    _render_sidebar()

    tabs = st.tabs(TAB_NAMES)
    with tabs[0]:
        tab_data.render()
    with tabs[1]:
        tab_roughness.render()
    with tabs[2]:
        tab_kinetics.render()
    with tabs[3]:
        tab_dsc.render()
    with tabs[4]:
        tab_export.render()


if __name__ == "__main__":
    main()
