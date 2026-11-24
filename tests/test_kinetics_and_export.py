"""Unit tests for kinetic modeling, ranking, statistics, PCA, DSC correlation, and exports."""

from __future__ import annotations

import ast
import io
import json
import math
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from core.dsc import correlate_sem_with_dsc, load_dsc_table
from core.export_engine import (
    build_analysis_report_md,
    build_complete_publication_archive,
    build_export_zip,
    build_individual_heatmaps_zip,
    build_settings_json,
)
from core.kinetics import (
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
    SEMImageRecord,
)


def _make_synthetic_metrics_df() -> pd.DataFrame:
    """Create synthetic multi-treatment dataset with shared Week 0 control & HV outliers."""
    weeks = list(range(0, 17))
    rows: list[dict[str, object]] = []

    def _add_row(trt: str, wk: int, rep: int, cbi: float, hv_mis: bool = False) -> None:
        scale_factor = max(cbi, 0.0) / 100.0
        rows.append(
            {
                "image_id": f"{wk}/{trt}_W{wk}_{rep}.tif",
                "treatment": trt,
                "week": wk,
                "scale_label": "50um",
                "replicate": rep,
                "hv_kv": 10.0 if hv_mis else 5.0,
                "hv_mismatch": hv_mis,
                "cbi_score": cbi,
                "geom_bloom_index": cbi * 0.8,
                "bloom_coverage_pct": float(np.clip(5.0 + cbi * 0.7, 0.0, 98.0)),
                "trnr_relief": 2.5 + scale_factor * 6.0,
                "loc_trnr_median": 2.0 + scale_factor * 4.0,
                "loc_trnr_p90": 3.5 + scale_factor * 7.0,
                "meso_snr": 1.5 + scale_factor * 4.5,
                "grad_snr": 3.0 + scale_factor * 5.0,
                "blade_index": 0.4 + scale_factor * 1.4,
                "anisotropy_coh": 0.35 + scale_factor * 0.25,
                "psd_struct_log_snr": 1.2 + scale_factor * 1.1,
                "psd_beta": 1.4 + scale_factor * 0.5,
                "corr_len_um": 0.35 + scale_factor * 0.45,
            }
        )

    # Shared Week 0 control
    for rep in (1, 2):
        _add_row("control", 0, rep, cbi=0.0)

    k = 0.8
    thalf_fast = 5.0 + math.log(9.0) / k
    thalf_slow = 11.0 + math.log(9.0) / k

    for wk in weeks[1:]:
        is_hv = wk in (5, 6)
        cbi_fast = 120.0 / (1.0 + math.exp(-k * (wk - thalf_fast)))
        cbi_slow = 100.0 / (1.0 + math.exp(-k * (wk - thalf_slow)))
        cbi_supp = 2.0 + 0.15 * wk  # Max ~ 4.4 (< 20 -> Suppressed)

        for rep, offset in ((1, -1.2), (2, 1.2)):
            # Inject large distortion on HV_Mismatch weeks 5 & 6 to verify exclusion works
            hv_bump = 80.0 if is_hv else 0.0
            _add_row("Fast", wk, rep, cbi_fast + offset + hv_bump, hv_mis=is_hv)
            _add_row("Slow", wk, rep, cbi_slow + offset + hv_bump, hv_mis=is_hv)
            _add_row("Suppressed", wk, rep, max(0.0, cbi_supp + 0.3 * offset) + hv_bump, hv_mis=is_hv)

    return pd.DataFrame(rows)


def test_zero_streamlit_imports_in_stage3_core() -> None:
    core_dir = Path(__file__).resolve().parent.parent / "core"
    for mod_name in ("kinetics.py", "dsc.py", "export_engine.py", "report_plots.py"):
        py_file = core_dir / mod_name
        tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert not alias.name.startswith("streamlit")
            elif isinstance(node, ast.ImportFrom):
                assert not (node.module or "").startswith("streamlit")


def test_kinetics_shared_control_fitting_and_ranking() -> None:
    df = _make_synthetic_metrics_df()
    agg = aggregate_kinetics_table(df, include_shared_control=True)

    # All 3 treatments must share identical Week 0 baseline
    w0 = agg[agg["week"] == 0]
    assert set(w0["treatment"]) == {"Fast", "Slow", "Suppressed"}
    assert (w0["cbi_score_mean"] == 0.0).all()

    results, curves = fit_treatment_kinetics(
        agg, scale_label="50um", metric_col="cbi_score", exclude_hv_mismatch=True
    )
    assert [r.treatment for r in results] == ["Suppressed", "Slow", "Fast"]
    assert [r.rank for r in results] == [1, 2, 3]

    by_trt = {r.treatment: r for r in results}
    assert by_trt["Suppressed"].fit_status == "Suppressed / No Bloom Onset"
    assert by_trt["Suppressed"].t_lag_weeks is None
    assert by_trt["Suppressed"].excluded_hv_weeks == [5, 6]

    assert by_trt["Slow"].fit_status == "Fitted"
    assert by_trt["Slow"].t_lag_weeks == pytest.approx(11.0, abs=1.0)
    assert by_trt["Slow"].r_squared is not None and by_trt["Slow"].r_squared > 0.95

    assert by_trt["Fast"].fit_status == "Fitted"
    assert by_trt["Fast"].t_lag_weeks == pytest.approx(5.0, abs=1.0)
    assert by_trt["Fast"].r_squared is not None and by_trt["Fast"].r_squared > 0.95

    for trt in ("Fast", "Slow", "Suppressed"):
        tx, ty = curves[trt]
        assert tx.size == 200 and ty.size == 200


def test_mild_non_sigmoidal_drift_and_sustained_onset() -> None:
    weeks = [0, 1, 2, 3, 4, 8, 12, 16]
    # Transient single-week spike at Week 2 (CBI=30) followed by drop and mild drift -> NO sustained onset
    noisy_drift = [0.0, 4.0, 30.0, 8.0, -5.0, 10.0, 14.0, 18.0]
    # Non-sigmoidal erratic trajectory (R² < 0.50) staying >= 25 for 2+ consecutive weeks at Week 8 & 12
    sustained_drift = [0.0, 2.0, 42.0, 4.0, 5.0, 38.0, 32.0, 10.0]

    rows = []
    for wk, y_n, y_s in zip(weeks, noisy_drift, sustained_drift):
        rows.append(
            {
                "treatment": "NoisyMild",
                "week": wk,
                "n": 2,
                "any_hv_mismatch": False,
                "cbi_score_mean": y_n,
            }
        )
        rows.append(
            {
                "treatment": "SustainedDrift",
                "week": wk,
                "n": 2,
                "any_hv_mismatch": False,
                "cbi_score_mean": y_s,
            }
        )

    agg_df = pd.DataFrame(rows)
    fits, _ = fit_treatment_kinetics(agg_df, scale_label="50um", metric_col="cbi_score")
    by_trt = {r.treatment: r for r in fits}

    assert by_trt["NoisyMild"].fit_status == "Mild / Non-Sigmoidal Drift"
    assert by_trt["NoisyMild"].t_lag_weeks is None
    assert by_trt["NoisyMild"].t_half_weeks is None

    assert by_trt["SustainedDrift"].fit_status == "Mild / Non-Sigmoidal Drift"
    assert by_trt["SustainedDrift"].t_lag_weeks is not None
    assert 4.0 < by_trt["SustainedDrift"].t_lag_weeks <= 8.0


def test_treatment_statistics_and_pca() -> None:
    df = _make_synthetic_metrics_df()
    stats = compute_treatment_statistics(
        df, metric_col="cbi_score", exclude_hv_mismatch=True, min_week=8
    )
    assert stats["anova_p"] < 0.01
    assert stats["kruskal_p"] < 0.01

    pw = stats["pairwise_df"]
    fast_vs_supp = pw[
        ((pw["treatment_a"] == "Fast") & (pw["treatment_b"] == "Suppressed"))
        | ((pw["treatment_a"] == "Suppressed") & (pw["treatment_b"] == "Fast"))
    ]
    assert len(fast_vs_supp) == 1
    assert float(fast_vs_supp["p_welch"].iloc[0]) < 0.01

    pca_res = compute_morphology_pca(df, exclude_hv_mismatch=True)
    assert len(pca_res["loadings_df"]) == len(PCA_FEATURE_COLS)
    # 2 control + 3 treatments * 14 non-HV weeks * 2 replicates = 86 rows
    assert pca_res["n_samples"] == 86
    ev1, ev2 = pca_res["explained_variance_ratio"]
    assert ev1 > 0.7 and (ev1 + ev2) <= 1.0 + 1e-9


def test_dsc_loader_and_correlation(tmp_path: Path) -> None:
    df = _make_synthetic_metrics_df()
    agg = aggregate_kinetics_table(df, include_shared_control=True)

    # Build strongly correlated DSC table (shared control + Fast/Slow/Suppressed weeks)
    dsc_rows = [{"Treatment": "control", "Week": 0, "Delta_H_J_g": 45.0, "T_peak_C": 33.2}]
    for _, row in agg[agg["week"].isin([2, 8, 12, 16])].iterrows():
        cbi = float(row["cbi_score_mean"])
        dsc_rows.append(
            {
                "Treatment": row["treatment"],
                "Week": f"W{int(row['week'])}",
                "Delta_H_J_g": 45.0 + 0.35 * cbi,
                "T_peak_C": 33.2 + 0.025 * cbi,
            }
        )
    dsc_src = pd.DataFrame(dsc_rows)

    csv_path = tmp_path / "dsc.csv"
    xlsx_path = tmp_path / "dsc.xlsx"
    dsc_src.to_csv(csv_path, index=False)
    dsc_src.to_excel(xlsx_path, index=False)

    dsc_csv = load_dsc_table(csv_path)
    dsc_xlsx = load_dsc_table(xlsx_path)
    assert len(dsc_csv) == len(dsc_xlsx)

    corr_df, merged_df = correlate_sem_with_dsc(agg, dsc_xlsx)
    assert not merged_df.empty
    top_r = float(corr_df["pearson_r"].abs().max())
    top_rho = float(corr_df["spearman_rho"].abs().max())
    assert top_r > 0.95
    assert top_rho > 0.90


def test_reproducible_export_zip(tmp_path: Path) -> None:
    df = _make_synthetic_metrics_df()
    agg = aggregate_kinetics_table(df, include_shared_control=True)
    fit_results, _ = fit_treatment_kinetics(agg, scale_label="50um", metric_col="cbi_score")
    stats = compute_treatment_statistics(df, metric_col="cbi_score", min_week=8)

    cal = Calibration(
        um_per_px=0.107917,
        hfw_um=165.76,
        res_x=1536,
        res_y=1024,
        databar_height_px=70,
        source="fei_tag_34682",
    )
    rec = SEMImageRecord(
        image_id="1/Fast_W1_1.tif",
        filepath=str(tmp_path / "Fast_W1_1.tif"),
        filename="Fast_W1_1.tif",
        folder_name="1",
        treatment="Fast",
        week=1,
        is_control=False,
        is_shared_control=False,
        scale_label="50um",
        replicate=1,
        hv_kv=5.0,
        wd_mm=10.5,
        sem_contrast=60.0,
        sem_brightness=44.0,
        detector="ETD",
        calibration=cal,
        bit_depth=16,
    )
    summary = DatasetSummary(
        root_dir=str(tmp_path),
        records=[rec],
        treatments=["Fast", "Slow", "Suppressed"],
        weeks=list(range(0, 17)),
        scales=["50um"],
        dominant_hv_kv=5.0,
        has_shared_control=True,
    )
    cfg = AnalysisConfig()
    masks = {"1/Fast_W1_1.tif": ArtifactMask(image_id="1/Fast_W1_1.tif", exclude_rects_um=[(1.0, 1.0, 5.0, 5.0)])}

    settings_json = build_settings_json(summary, cfg, {"bloom_cov_threshold": 5.87}, masks)
    parsed = json.loads(settings_json)
    assert parsed["analysis_config"]["active_scale"] == "50um"

    report_md = build_analysis_report_md(summary, cfg, fit_results, stats)
    assert "Kinetic Treatment Ranking" in report_md

    dsc_corr = pd.DataFrame(
        [{"sem_metric": "cbi_score", "dsc_parameter": "Delta_H_J_g", "n_pairs": 10, "pearson_r": 0.99, "p_pearson": 1e-8, "spearman_rho": 0.98, "p_spearman": 1e-7}]
    )
    zip_bytes = build_export_zip(
        metrics_df=df,
        agg_df=agg,
        fit_results=fit_results,
        settings_json=settings_json,
        report_md=report_md,
        figures={"kinetics_50um.png": b"\x89PNG\r\n\x1a\nMOCK"},
        dsc_corr_df=dsc_corr,
        extra_tables={"heatmap_matrix.csv": b"treatment,0,1\nFast,0,5\n"},
    )

    with zipfile.ZipFile(io.BytesIO(zip_bytes), mode="r") as zf:
        names = set(zf.namelist())
        assert {
            "settings.json",
            "analysis_report.md",
            "tables/image_metrics.csv",
            "tables/kinetics_aggregated.csv",
            "tables/kinetic_ranking.csv",
            "tables/dsc_correlations.csv",
            "tables/heatmap_matrix.csv",
            "figures/kinetics_50um.png",
        }.issubset(names)
        assert zf.read("figures/kinetics_50um.png").startswith(b"\x89PNG")


def test_individual_heatmaps_zip_rendering() -> None:
    cal = Calibration(
        um_per_px=0.107917,
        hfw_um=165.76,
        res_x=64,
        res_y=48,
        databar_height_px=0,
        source="fei_tag_34682",
    )
    entries = [
        {
            "week": 0,
            "hv_kv": 5.0,
            "hv_mismatch": False,
            "calibration": cal,
            "loc_trnr_map": np.full((48, 64), 2.5, dtype=np.float64),
            "ridges_map": np.full((48, 64), 0.3, dtype=np.float64),
        },
        {
            "week": 5,
            "hv_kv": 10.0,
            "hv_mismatch": True,
            "calibration": cal,
            "loc_trnr_map": np.full((48, 64), 8.0, dtype=np.float64),
            "ridges_map": np.full((48, 64), 1.2, dtype=np.float64),
        },
    ]
    zip_bytes = build_individual_heatmaps_zip(
        entries,
        map_type="loc_trnr_map",
        treatment="CWF",
        scale_label="50um",
        shared_vmax=10.0,
        dpi=100,
    )
    with zipfile.ZipFile(io.BytesIO(zip_bytes), mode="r") as zf:
        names = sorted(zf.namelist())
        assert names == [
            "CWF_50um_week_00_loc_trnr_map.png",
            "CWF_50um_week_05_loc_trnr_map.png",
        ]
        for nm in names:
            assert zf.read(nm).startswith(b"\x89PNG")


def test_complete_publication_archive_study_agnostic(tmp_path: Path) -> None:
    from PIL import Image
    from PIL.TiffImagePlugin import ImageFileDirectory_v2
    from core.io_loader import scan_dataset
    from core.report_plots import KINETIC_METRIC_CATALOG
    from core.texture import analyze_dataset_scale

    rng = np.random.default_rng(77)

    def _write_sem(path: Path, amp: float, hv_v: float = 5000.0) -> None:
        arr = (20000.0 + rng.normal(0.0, 120.0, size=(256, 384)) + amp * rng.normal(0.0, 1.0, size=(256, 384))).clip(1000, 60000).astype(np.uint16)
        ini = (
            "[Beam]\n"
            f"HV={hv_v}\n"
            "[EBeam]\n"
            f"HV={hv_v}\n"
            "HFW=0.00016576\n"
            "WD=0.0105\n"
            "[EScan]\n"
            "PixelWidth=1.07917e-07\n"
            "[Image]\n"
            "ResolutionX=384\n"
            "ResolutionY=256\n"
        )
        ifd = ImageFileDirectory_v2()
        ifd[34682] = ini
        ifd.tagtype[34682] = 2
        Image.fromarray(arr).save(path, format="TIFF", tiffinfo=ifd)

    (tmp_path / "control").mkdir()
    _write_sem(tmp_path / "control" / "control_50um_5.00kV_0001.tif", amp=50.0)

    for wk in (1, 2, 4, 8, 12):
        wk_dir = tmp_path / str(wk)
        wk_dir.mkdir()
        _write_sem(wk_dir / f"DarkChocW{wk}_50um_5.00kV_001.tif", amp=60.0)
        _write_sem(wk_dir / f"DarkChocW{wk}_50um_5.00kV_002.tif", amp=65.0)
        _write_sem(wk_dir / f"MilkChocW{wk}_50um_5.00kV_003.tif", amp=50.0 + wk * 90.0)
        _write_sem(wk_dir / f"MilkChocW{wk}_50um_5.00kV_004.tif", amp=55.0 + wk * 95.0)

    summary = scan_dataset(tmp_path)
    cfg = AnalysisConfig(active_scale="50um")
    metrics_df, _, cal_info = analyze_dataset_scale(summary.records, "50um", config=cfg)

    zip_bytes, manifest = build_complete_publication_archive(
        summary=summary,
        metrics_df=metrics_df,
        config=cfg,
        scale_label="50um",
        scale_cal_info=cal_info,
        stats_min_week=4,
        replicates_to_export=(1,),
        include_individual_week_maps=True,
        session_figures={"extra_compare.png": b"\x89PNG\r\n\x1a\nEXTRA"},
    )
    assert manifest["n_treatments"] == 2
    assert manifest["n_pngs"] > 20
    assert manifest["n_csvs"] > 40

    with zipfile.ZipFile(io.BytesIO(zip_bytes), mode="r") as zf:
        names = set(zf.namelist())
        assert {"settings.json", "analysis_report.md", "tables/image_metrics_all.csv", "tables/kinetics_aggregated_all.csv", "tables/pca_scores.csv", "tables/pca_loadings.csv", "figures/morphology_pca/morphology_pca_ordination.png", "figures/session_figures/extra_compare.png"}.issubset(names)

        for trt in ("DarkChoc", "MilkChoc"):
            assert f"tables/by_treatment/{trt}_image_metrics.csv" in names
            assert f"tables/by_treatment/{trt}_kinetics_summary.csv" in names
            assert f"tables/by_treatment/{trt}_rep1_fft_radial_psd.csv" in names
            assert f"figures/heatmaps_pseudo_afm/{trt}_rep1_pseudo_afm_all_weeks.png" in names
            assert f"figures/heatmaps_sato_blades/{trt}_rep1_sato_blades_all_weeks.png" in names
            assert f"figures/fft_radial_psd/{trt}_rep1_fft_radial_psd_all_weeks.png" in names
            assert f"figures/heatmaps_pseudo_afm/individual/{trt}_rep1/{trt}_50um_week_00_loc_trnr_map.png" in names
            assert f"figures/heatmaps_sato_blades/individual/{trt}_rep1/{trt}_50um_week_12_ridges_map.png" in names

        for metric_col, _ in KINETIC_METRIC_CATALOG:
            assert f"figures/kinetics_all_8_metrics/{metric_col}_kinetic_progression.png" in names
            assert f"figures/kinetics_all_8_metrics/{metric_col}_treatment_x_week_heatmap.png" in names
            assert f"tables/by_metric/{metric_col}_kinetic_data.csv" in names
            assert f"tables/by_metric/{metric_col}_heatmap_matrix.csv" in names
            assert f"tables/by_metric/{metric_col}_kinetic_ranking.csv" in names
            assert f"tables/by_metric/{metric_col}_stats_summary.csv" in names
            assert f"tables/by_metric/{metric_col}_stats_pairwise.csv" in names

        for nm in names:
            if nm.endswith(".png"):
                assert zf.read(nm).startswith(b"\x89PNG")
            elif nm.endswith(".csv"):
                assert len(zf.read(nm)) > 0
