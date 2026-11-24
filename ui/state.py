"""Centralized typed Streamlit session-state management for BloomPix."""

from __future__ import annotations

from typing import Any, Optional

import pandas as pd
import streamlit as st

from core.models import AnalysisConfig, ArtifactMask, DatasetSummary

_DEFAULTS: dict[str, Any] = {
    "data_dir": "data",
    "dataset_summary": None,
    "active_scale": "50um",
    "analysis_config": None,
    "artifact_masks": {},
    "metrics_df_by_scale": {},
    "scale_cal_info": {},
    "kinetics_cache": {},
    "week_maps_cache": {},
    "dsc_df": None,
    "dsc_corr_df": None,
    "dsc_merged_df": None,
    "exported_figures": {},
    "exported_tables": {},
    "publication_archive_cache": {},
    "stats_min_week": 8,
    "qc_verified": False,
}


def init_state() -> None:
    """Initialize all expected BloomPix session-state keys cleanly."""
    for key, val in _DEFAULTS.items():
        if key not in st.session_state:
            if key == "analysis_config":
                st.session_state[key] = AnalysisConfig()
            elif isinstance(val, dict):
                st.session_state[key] = {}
            else:
                st.session_state[key] = val


def get_data_dir() -> str:
    init_state()
    return str(st.session_state["data_dir"])


def set_data_dir(path: str) -> None:
    init_state()
    st.session_state["data_dir"] = path


def get_dataset_summary() -> Optional[DatasetSummary]:
    init_state()
    return st.session_state["dataset_summary"]


def set_dataset_summary(summary: Optional[DatasetSummary]) -> None:
    init_state()
    st.session_state["dataset_summary"] = summary
    if summary is not None and summary.scales:
        cur = st.session_state["active_scale"]
        if cur not in summary.scales:
            default_scale = "50um" if "50um" in summary.scales else summary.scales[0]
            set_active_scale(default_scale)


def get_active_scale() -> str:
    init_state()
    return str(st.session_state["active_scale"])


def set_active_scale(scale: str) -> None:
    init_state()
    st.session_state["active_scale"] = scale
    cfg: AnalysisConfig = st.session_state["analysis_config"]
    cfg.active_scale = scale


def get_analysis_config() -> AnalysisConfig:
    init_state()
    return st.session_state["analysis_config"]


def get_artifact_masks() -> dict[str, ArtifactMask]:
    init_state()
    return st.session_state["artifact_masks"]


def get_artifact_mask(image_id: str) -> ArtifactMask:
    masks = get_artifact_masks()
    if image_id not in masks:
        masks[image_id] = ArtifactMask(image_id=image_id, auto_mask_pores=False)
    return masks[image_id]


def set_artifact_mask(mask: ArtifactMask) -> None:
    masks = get_artifact_masks()
    masks[mask.image_id] = mask


def clear_artifact_mask(image_id: str) -> None:
    masks = get_artifact_masks()
    masks.pop(image_id, None)


def get_metrics_df(scale: Optional[str] = None) -> Optional[pd.DataFrame]:
    init_state()
    sc = scale or get_active_scale()
    return st.session_state["metrics_df_by_scale"].get(sc)


def get_scale_cal_info(scale: Optional[str] = None) -> dict[str, Any]:
    init_state()
    sc = scale or get_active_scale()
    return st.session_state["scale_cal_info"].get(sc, {})


def set_scale_results(
    scale: str,
    metrics_df: pd.DataFrame,
    cal_info: dict[str, Any],
) -> None:
    init_state()
    st.session_state["metrics_df_by_scale"][scale] = metrics_df
    st.session_state["scale_cal_info"][scale] = cal_info
    st.session_state["kinetics_cache"].pop(scale, None)
    st.session_state["publication_archive_cache"].pop(scale, None)
    st.session_state["dsc_corr_df"] = None
    st.session_state["dsc_merged_df"] = None


def get_stats_min_week() -> int:
    init_state()
    return int(st.session_state["stats_min_week"])


def set_stats_min_week(min_week: int) -> None:
    init_state()
    st.session_state["stats_min_week"] = int(min_week)


def get_publication_archive(scale: Optional[str] = None) -> Optional[dict[str, Any]]:
    init_state()
    sc = scale or get_active_scale()
    return st.session_state["publication_archive_cache"].get(sc)


def set_publication_archive(
    scale: str,
    zip_bytes: bytes,
    manifest: dict[str, Any],
    filename: str,
) -> None:
    init_state()
    st.session_state["publication_archive_cache"][scale] = {
        "zip_bytes": zip_bytes,
        "manifest": manifest,
        "filename": filename,
    }


def clear_publication_archive(scale: Optional[str] = None) -> None:
    init_state()
    if scale is None:
        st.session_state["publication_archive_cache"].clear()
    else:
        st.session_state["publication_archive_cache"].pop(scale, None)


def get_kinetics_cache(scale: Optional[str] = None) -> Optional[dict[str, Any]]:
    init_state()
    sc = scale or get_active_scale()
    return st.session_state["kinetics_cache"].get(sc)


def set_kinetics_cache(scale: str, payload: dict[str, Any]) -> None:
    init_state()
    st.session_state["kinetics_cache"][scale] = payload


def get_week_maps(
    scale: str,
    treatment: str,
    replicate: int,
) -> Optional[list[dict[str, Any]]]:
    init_state()
    return st.session_state["week_maps_cache"].get((scale, treatment, int(replicate)))


def set_week_maps(
    scale: str,
    treatment: str,
    replicate: int,
    entries: list[dict[str, Any]],
) -> None:
    init_state()
    st.session_state["week_maps_cache"][(scale, treatment, int(replicate))] = entries


def get_dsc_df() -> Optional[pd.DataFrame]:
    init_state()
    return st.session_state["dsc_df"]


def set_dsc_df(df: Optional[pd.DataFrame]) -> None:
    init_state()
    st.session_state["dsc_df"] = df
    st.session_state["dsc_corr_df"] = None
    st.session_state["dsc_merged_df"] = None


def get_dsc_results() -> tuple[Optional[pd.DataFrame], Optional[pd.DataFrame]]:
    init_state()
    return st.session_state["dsc_corr_df"], st.session_state["dsc_merged_df"]


def set_dsc_results(corr_df: pd.DataFrame, merged_df: pd.DataFrame) -> None:
    init_state()
    st.session_state["dsc_corr_df"] = corr_df
    st.session_state["dsc_merged_df"] = merged_df


def register_exported_figure(filename: str, png_bytes: bytes) -> None:
    init_state()
    st.session_state["exported_figures"][filename] = png_bytes


def get_exported_figures() -> dict[str, bytes]:
    init_state()
    return st.session_state["exported_figures"]


def register_exported_table(filename: str, csv_bytes: bytes) -> None:
    init_state()
    st.session_state["exported_tables"][filename] = csv_bytes


def get_exported_tables() -> dict[str, bytes]:
    init_state()
    return st.session_state["exported_tables"]


def is_qc_verified() -> bool:
    init_state()
    return bool(st.session_state["qc_verified"])


def set_qc_verified(flag: bool) -> None:
    init_state()
    st.session_state["qc_verified"] = bool(flag)


def invalidate_downstream(scale: Optional[str] = None) -> None:
    """Clear dependent cached metrics, maps, kinetics, DSC correlations, and stale exports."""
    init_state()
    if scale is None:
        st.session_state["metrics_df_by_scale"].clear()
        st.session_state["scale_cal_info"].clear()
        st.session_state["kinetics_cache"].clear()
        st.session_state["week_maps_cache"].clear()
        st.session_state["publication_archive_cache"].clear()
        st.session_state["exported_figures"].clear()
        st.session_state["exported_tables"].clear()
    else:
        st.session_state["metrics_df_by_scale"].pop(scale, None)
        st.session_state["scale_cal_info"].pop(scale, None)
        st.session_state["kinetics_cache"].pop(scale, None)
        st.session_state["publication_archive_cache"].pop(scale, None)
        wmap_cache = st.session_state["week_maps_cache"]
        for k in [key for key in list(wmap_cache.keys()) if key[0] == scale]:
            wmap_cache.pop(k, None)
        figs = st.session_state["exported_figures"]
        for fname in [k for k in list(figs.keys()) if scale in k]:
            figs.pop(fname, None)

    st.session_state["dsc_corr_df"] = None
    st.session_state["dsc_merged_df"] = None
