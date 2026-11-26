"""Pure-Python scientific engine for BloomPix SEM fat-bloom analysis.

Note: Modules inside ``core`` must NEVER import ``streamlit``.
"""

from core.artifacts import build_valid_mask, detect_surface_artifacts
from core.dsc import (
    DSC_PARAM_COLS,
    compute_dsc_thermodynamics,
    correlate_sem_with_dsc,
    load_dsc_table,
    parse_dsc_filename,
    parse_ta_dsc_txt,
    scan_and_analyze_dsc_folder,
)
from core.export_engine import (
    build_analysis_report_md,
    build_complete_publication_archive,
    build_export_zip,
    build_individual_heatmaps_zip,
    build_settings_json,
)
from core.report_plots import KINETIC_METRIC_CATALOG
from core.io_loader import (
    SUPPORTED_EXTENSIONS,
    detect_databar_height,
    expand_shared_control_for_treatment,
    load_metadata_overrides,
    load_sem_image,
    parse_fei_tiff_metadata,
    parse_filename_metadata,
    save_metadata_overrides,
    scan_dataset,
)
from core.kinetics import (
    AGGREGATE_METRIC_COLS,
    PCA_FEATURE_COLS,
    aggregate_kinetics_table,
    compute_morphology_pca,
    compute_treatment_statistics,
    fit_treatment_kinetics,
)
from core.models import (
    AnalysisConfig,
    ArtifactMask,
    Calibration,
    DatasetSummary,
    KineticFitResult,
    RoughnessMetrics,
    SEMImageRecord,
)
from core.preprocessing import (
    compute_image_qc,
    estimate_noise_std,
    flatten_illumination,
    make_display_image,
)
from core.texture import (
    CORE_CBI_METRICS,
    GEOM_CBI_METRICS,
    analyze_dataset_scale,
    calibrate_control_threshold,
    compute_composite_bloom_index,
    compute_image_roughness,
    compute_treatment_week_maps,
)
from core.version import APP_NAME, APP_VERSION, get_build_label, get_git_info

__all__ = [
    "AGGREGATE_METRIC_COLS",
    "APP_NAME",
    "APP_VERSION",
    "AnalysisConfig",
    "ArtifactMask",
    "CORE_CBI_METRICS",
    "Calibration",
    "DSC_PARAM_COLS",
    "DatasetSummary",
    "GEOM_CBI_METRICS",
    "KINETIC_METRIC_CATALOG",
    "KineticFitResult",
    "PCA_FEATURE_COLS",
    "RoughnessMetrics",
    "SEMImageRecord",
    "SUPPORTED_EXTENSIONS",
    "aggregate_kinetics_table",
    "analyze_dataset_scale",
    "build_analysis_report_md",
    "build_complete_publication_archive",
    "build_export_zip",
    "build_individual_heatmaps_zip",
    "build_settings_json",
    "build_valid_mask",
    "calibrate_control_threshold",
    "compute_composite_bloom_index",
    "compute_dsc_thermodynamics",
    "compute_image_qc",
    "compute_image_roughness",
    "compute_morphology_pca",
    "compute_treatment_statistics",
    "compute_treatment_week_maps",
    "correlate_sem_with_dsc",
    "detect_databar_height",
    "detect_surface_artifacts",
    "estimate_noise_std",
    "expand_shared_control_for_treatment",
    "fit_treatment_kinetics",
    "flatten_illumination",
    "get_build_label",
    "get_git_info",
    "load_dsc_table",
    "load_metadata_overrides",
    "load_sem_image",
    "make_display_image",
    "parse_fei_tiff_metadata",
    "parse_dsc_filename",
    "parse_filename_metadata",
    "parse_ta_dsc_txt",
    "save_metadata_overrides",
    "scan_and_analyze_dsc_folder",
    "scan_dataset",
]
