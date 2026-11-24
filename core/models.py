"""Typed data contracts for the BloomPix scientific engine.

Strictly decoupled from Streamlit (zero ``streamlit`` imports).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Calibration:
    """Physical spatial calibration and raster uncertainty for an SEM micrograph."""

    um_per_px: float
    hfw_um: float
    res_x: int
    res_y: int
    databar_height_px: int
    source: str  # "fei_tag_34682" | "manual" | "uncalibrated"
    u_raster_um: float = 0.0

    def __post_init__(self) -> None:
        if self.u_raster_um == 0.0 and self.um_per_px > 0.0:
            self.u_raster_um = self.um_per_px / math.sqrt(12.0)


@dataclass
class SEMImageRecord:
    """Metadata and calibration record for one SEM micrograph in a study dataset."""

    image_id: str
    filepath: str
    filename: str
    folder_name: str
    treatment: str
    week: int
    is_control: bool
    is_shared_control: bool
    scale_label: str
    replicate: int
    hv_kv: Optional[float]
    wd_mm: Optional[float]
    sem_contrast: Optional[float]
    sem_brightness: Optional[float]
    detector: str
    calibration: Calibration
    bit_depth: int
    hv_mismatch: bool = False
    excluded: bool = False
    qc_flags: list[str] = field(default_factory=list)


@dataclass
class DatasetSummary:
    """Aggregated summary of all SEM micrographs discovered in a study directory."""

    root_dir: str
    records: list[SEMImageRecord]
    treatments: list[str]
    weeks: list[int]
    scales: list[str]
    dominant_hv_kv: Optional[float]
    has_shared_control: bool


@dataclass
class ArtifactMask:
    """Per-image exclusion regions (in physical micrometers) and pore masking flag."""

    image_id: str
    exclude_rects_um: list[tuple[float, float, float, float]] = field(default_factory=list)
    auto_mask_pores: bool = True


@dataclass
class AnalysisConfig:
    """Reproducible pipeline configuration for preprocessing, texture, and kinetics."""

    active_scale: str = "50um"
    include_hv_mismatch_in_plots: bool = True
    exclude_hv_mismatch_from_fits: bool = True
    bg_sigma_frac: float = 0.12
    topo_sigma_px: float = 1.5
    local_window_frac: float = 1.0 / 32.0
    auto_mask_pores: bool = False


@dataclass
class RoughnessMetrics:
    """Brightness/contrast-invariant surface roughness, spectral, and morphology metrics."""

    image_id: str
    treatment: str
    week: int
    scale_label: str
    replicate: int
    hv_kv: Optional[float]
    hv_mismatch: bool
    noise_sigma: float
    saturated_pct: float
    dark_clip_pct: float
    artifact_masked_pct: float
    valid_area_pct: float
    qc_status: str  # "OK" | "HV_Mismatch" | "Review"
    trnr_relief: float
    loc_trnr_median: float
    loc_trnr_p90: float
    meso_snr: float
    grad_snr: float
    blade_index: float
    anisotropy_coh: float
    psd_struct_log_snr: float
    psd_beta: float
    corr_len_um: float
    bloom_coverage_pct: float
    cbi_score: Optional[float] = None
    geom_bloom_index: Optional[float] = None


@dataclass
class KineticFitResult:
    """Fitted storage-time kinetic model summary for one treatment and metric."""

    treatment: str
    scale_label: str
    metric_name: str
    fit_status: str  # "Fitted" | "Empirical Onset" | "Suppressed / No Bloom Onset" | "Insufficient Points"
    y0: float
    y_max: float
    k_rate: float
    t_lag_weeks: Optional[float]
    t_half_weeks: Optional[float]
    r_squared: Optional[float]
    auc: float
    auc_norm_per_week: float
    late_stage_mean: float
    late_stage_sd: float
    max_observed: float
    n_weeks_fitted: int
    excluded_hv_weeks: list[int] = field(default_factory=list)
    rank: int = 0
