"""Unit tests for raw TA Instruments DSC parser, thermodynamic engine, and SEM correlation."""

from __future__ import annotations

import ast
import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from core.dsc import (
    DSC_PARAM_COLS,
    compute_dsc_thermodynamics,
    correlate_sem_with_dsc,
    parse_dsc_filename,
    parse_ta_dsc_txt,
    scan_and_analyze_dsc_folder,
)
from core.kinetics import AGGREGATE_METRIC_COLS


def _write_synthetic_ta_dsc(
    path: Path,
    sample_name: str,
    t_peak: float = 33.5,
    sigma_c: float = 1.2,
    amp_w_g: float = 0.40,
    max_temp: float = 46.0,
) -> float:
    """Write a synthetic TA Instruments tab-delimited .txt file and return analytical ΔH (J/g)."""
    # Ramp rate = 1.0 °C/min -> 60 s per °C
    temps = np.linspace(21.0, max_temp, int((max_temp - 21.0) / 0.02) + 1)
    # Inject duplicate rounded temperatures (same T twice) to test dT==0 protection
    temps = np.sort(np.concatenate([temps, temps[::50]]))
    times_min = temps - 21.0  # 1.00 °C/min

    baseline = -0.02 - 0.001 * (temps - 21.0)
    peak = amp_w_g * np.exp(-0.5 * ((temps - t_peak) / sigma_c) ** 2)
    hf = baseline - peak  # Endothermic downward

    lines = [
        f"Filename\t{path.stem}",
        "Instrument name\tDSC2A-02116",
        "Operator\t",
        "rundate\t2026-06-01",
        f"Sample name\t{sample_name}",
        "proceduresegments\tRamp 1.00 °C/min to 50.00 °C",
        "[step]",
        "Ramp 1.00 °C/min to 50.00 °C",
        "Time\tTemperature\tHeat Flow (Normalized)",
        "min\t°C\tW/g",
        "0.00\t\t",
        "0.01\t20.50\t",
    ]
    for tm, tp, h in zip(times_min, temps, hf):
        lines.append(f"{tm:.4f}\t{tp:.4f}\t{h:.6f}")
    lines.extend(["25.50\t\t", ""])

    path.write_text("\n".join(lines), encoding="utf-8-sig")
    # Analytical integral of Gaussian peak in J/g: amp * sigma_c * sqrt(2*pi) * 60 s/°C
    return amp_w_g * sigma_c * math.sqrt(2.0 * math.pi) * 60.0


def test_zero_streamlit_imports_in_core_dsc() -> None:
    dsc_path = Path(__file__).resolve().parent.parent / "core" / "dsc.py"
    tree = ast.parse(dsc_path.read_text(encoding="utf-8"), filename=str(dsc_path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert not alias.name.startswith("streamlit")
        elif isinstance(node, ast.ImportFrom):
            assert not (node.module or "").startswith("streamlit")


def test_parse_dsc_filename_variants() -> None:
    p1 = parse_dsc_filename("anfw1r1.txt")
    assert p1 == {"treatment": "ANF", "week": 1, "replicate": 1, "is_control": False}

    p2 = parse_dsc_filename("CWFW12R4.txt")
    assert p2 == {"treatment": "CWF", "week": 12, "replicate": 4, "is_control": False}

    p3 = parse_dsc_filename("ANF_W2_r3.txt")
    assert p3 == {"treatment": "ANF", "week": 2, "replicate": 3, "is_control": False}

    c1 = parse_dsc_filename("controlr1.txt")
    assert c1 == {"treatment": "control", "week": 0, "replicate": 1, "is_control": True}

    c2 = parse_dsc_filename("ControlW0r2.txt")
    assert c2 == {"treatment": "control", "week": 0, "replicate": 2, "is_control": True}


def test_synthetic_ta_dsc_thermodynamics_accuracy(tmp_path: Path) -> None:
    fpath = tmp_path / "anfw1r1.txt"
    expected_dh = _write_synthetic_ta_dsc(
        fpath, sample_name="ANFW1R1", t_peak=33.5, sigma_c=1.2, amp_w_g=0.40
    )

    meta, curve_df = parse_ta_dsc_txt(fpath)
    assert meta["Sample name"] == "ANFW1R1"
    assert len(curve_df) > 1000

    params, payload = compute_dsc_thermodynamics(curve_df)
    assert DSC_PARAM_COLS == ["T_onset_C", "T_peak_C", "FWHM_C", "Delta_H_J_g"]
    assert params["qc_status"] == "OK"
    assert params["T_peak_C"] == pytest.approx(33.5, abs=0.15)
    # Gaussian inflection tangent onset: T_peak - 2 * sigma_c ≈ 31.1 °C
    assert 30.5 <= params["T_onset_C"] <= 32.0
    # Gaussian FWHM = 2 * sqrt(2 * ln 2) * sigma_c ≈ 2.35482 * 1.2
    assert params["FWHM_C"] == pytest.approx(2.35482 * 1.2, rel=0.05)
    assert params["Delta_H_J_g"] == pytest.approx(expected_dh, rel=0.03)
    for removed_key in ("T_endset_C", "Delta_T_C", "High_Melt_gt34C_pct"):
        assert removed_key not in params
    assert "T_endset_C" not in payload
    for qc_key in (
        "T_lo_used",
        "T_hi_used",
        "baseline_overshoot_pct",
        "is_bimodal",
        "qc_flag",
        "baseline_mode",
    ):
        assert qc_key in params
    assert payload["qc_status"] == "OK"


def test_dsc_folder_incomplete_and_partial_week_sem_correlation(tmp_path: Path) -> None:
    # Build DSC folder WITHOUT control (Week 0) and WITHOUT Week 16, plus 1 aborted file
    for wk, tp in [(1, 32.5), (2, 32.9), (8, 33.6), (12, 34.2)]:
        _write_synthetic_ta_dsc(tmp_path / f"DarkChocW{wk}r1.txt", sample_name=f"DCW{wk}", t_peak=tp)
        _write_synthetic_ta_dsc(tmp_path / f"DarkChocW{wk}r2.txt", sample_name=f"DCW{wk}", t_peak=tp + 0.1)
    # Aborted run stopping at 25 °C
    _write_synthetic_ta_dsc(tmp_path / "DarkChocW8r3.txt", sample_name="DCW8R3", max_temp=25.0)
    # Hidden file that must be ignored
    (tmp_path / "._DarkChocW1r1.txt").write_text("garbage", encoding="utf-8")

    rep_df, agg_df, curves = scan_and_analyze_dsc_folder(tmp_path)
    assert len(rep_df) == 9
    assert int((rep_df["qc_status"] == "OK").sum()) == 8
    assert int((rep_df["qc_status"] == "Incomplete / Aborted Run").sum()) == 1
    assert len(agg_df) == 4  # Weeks 1, 2, 8, 12
    assert set(agg_df["week"]) == {1, 2, 8, 12}
    assert "DarkChocW8r3.txt" in curves
    for col in DSC_PARAM_COLS:
        assert f"{col}_mean" in agg_df.columns
        assert f"{col}_sd" in agg_df.columns
    for removed_key in ("T_endset_C", "Delta_T_C", "High_Melt_gt34C_pct"):
        assert removed_key not in rep_df.columns
        assert f"{removed_key}_mean" not in agg_df.columns

    # Partial-week SEM table (includes Week 0 and Week 16 that are absent in DSC)
    sem_agg_df = pd.DataFrame(
        [
            {"treatment": "DARKCHOC", "week": 0, "cbi_score_mean": 0.0, "trnr_relief_mean": 2.0},
            {"treatment": "DARKCHOC", "week": 1, "cbi_score_mean": 10.0, "trnr_relief_mean": 2.5},
            {"treatment": "DARKCHOC", "week": 2, "cbi_score_mean": 25.0, "trnr_relief_mean": 3.2},
            {"treatment": "DARKCHOC", "week": 8, "cbi_score_mean": 55.0, "trnr_relief_mean": 4.8},
            {"treatment": "DARKCHOC", "week": 12, "cbi_score_mean": 85.0, "trnr_relief_mean": 6.2},
            {"treatment": "DARKCHOC", "week": 16, "cbi_score_mean": 110.0, "trnr_relief_mean": 7.5},
        ]
    )
    corr_df, merged_df = correlate_sem_with_dsc(sem_agg_df, agg_df)
    assert len(merged_df) == 4
    assert not corr_df.empty
    assert not corr_df["pearson_r"].isna().any()
    assert float(corr_df["pearson_r"].abs().max()) > 0.95


def test_auto_baseline_bimodal_early_melting() -> None:
    # Synthetic thermogram:
    # - 20.8-21.5 °C: steep equilibration transient (must be avoided)
    # - 21.8-22.8 °C: clean pre-melting flat plateau (~ -0.025 W/g)
    # - 23.2 °C+: early drop into bimodal melting peaks at 28.0 °C & 32.0 °C
    # - 38.0-45.0 °C: clean post-melting plateau (~ -0.030 W/g)
    temps = np.linspace(20.8, 45.0, int((45.0 - 20.8) / 0.02) + 1)
    times_min = temps - 20.8  # 1.00 °C/min -> 60 s/°C

    baseline = -0.025 - 0.0002 * (temps - 21.8)
    transient = 0.055 * np.exp(-((np.maximum(temps - 20.8, 0.0)) / 0.22) ** 2) * (temps < 21.6)
    peak1 = 0.28 * np.exp(-0.5 * ((temps - 28.0) / 1.4) ** 2)
    peak2 = 0.35 * np.exp(-0.5 * ((temps - 32.0) / 0.85) ** 2)
    hf = baseline + transient - peak1 - peak2

    curve_df = pd.DataFrame({"time_min": times_min, "temp_C": temps, "hf_W_g": hf})
    expected_dh = (0.28 * 1.4 + 0.35 * 0.85) * math.sqrt(2.0 * math.pi) * 60.0

    params, payload = compute_dsc_thermodynamics(curve_df, auto_baseline=True)
    assert 21.6 <= params["T_lo_used"] <= 22.9
    assert 38.0 <= params["T_hi_used"] <= 45.0
    assert params["is_bimodal"] is True
    assert params["qc_flag"] == "OK"
    assert params["qc_status"] == "OK"
    assert params["baseline_mode"] == "Auto"
    assert params["Delta_H_J_g"] == pytest.approx(expected_dh, rel=0.05)
    assert payload["is_bimodal"] is True
    assert payload["qc_flag"] == "OK"


def test_per_file_override_in_folder_scan(tmp_path: Path) -> None:
    _write_synthetic_ta_dsc(tmp_path / "AWFW1r1.txt", sample_name="AWFW1R1", t_peak=32.8)
    _write_synthetic_ta_dsc(tmp_path / "AWFW2r1.txt", sample_name="AWFW2R1", t_peak=33.4)

    overrides = {"AWFW1r1.txt": ((23.1, 24.1), (39.0, 43.0))}
    rep_df, _, curves = scan_and_analyze_dsc_folder(
        tmp_path,
        auto_baseline=True,
        per_file_overrides=overrides,
    )
    row1 = rep_df[rep_df["filename"] == "AWFW1r1.txt"].iloc[0]
    row2 = rep_df[rep_df["filename"] == "AWFW2r1.txt"].iloc[0]

    assert row1["baseline_mode"] == "Manual Override"
    assert row1["qc_flag"] == "OK (Manual)"
    assert 23.0 <= float(row1["T_lo_used"]) <= 24.2
    assert curves["AWFW1r1.txt"]["baseline_mode"] == "Manual Override"
    assert curves["AWFW1r1.txt"]["qc_flag"] == "OK (Manual)"
    assert row2["baseline_mode"] == "Auto"
    assert int((rep_df["qc_flag"] == "Review Baseline").sum()) == 0


def test_auto_baseline_avoids_early_shoulder_drop() -> None:
    # Plateau at -0.020 W/g across [21.6, 22.8] °C, sharp early drop around 23.1-23.3 °C down to
    # a flat lower shoulder at -0.045 W/g (23.5-24.2 °C), then main peak at 31.5 °C.
    temps = np.linspace(21.6, 45.0, int((45.0 - 21.6) / 0.02) + 1)
    times_min = temps - 21.6

    step_drop = 0.025 / (1.0 + np.exp(-(temps - 23.2) / 0.08))
    main_peak = 0.35 * np.exp(-0.5 * ((temps - 31.5) / 1.1) ** 2)
    hf = -0.020 - step_drop - main_peak

    curve_df = pd.DataFrame({"time_min": times_min, "temp_C": temps, "hf_W_g": hf})
    params, _ = compute_dsc_thermodynamics(curve_df, auto_baseline=True)
    assert 21.6 <= params["T_lo_used"] <= 22.9
    assert params["qc_flag"] == "OK"


def test_clean_bimodal_near_onset_is_ok() -> None:
    # Bimodal curve where 1st peak starts gently ~0.20 °C after T_lo with 0% baseline overshoot
    temps = np.linspace(21.6, 45.0, int((45.0 - 21.6) / 0.02) + 1)
    times_min = temps - 21.6

    baseline = -0.020 - 0.0001 * (temps - 21.6)
    peak1 = 0.16 * np.exp(-0.5 * ((temps - 24.4) / 0.85) ** 2)
    peak2 = 0.32 * np.exp(-0.5 * ((temps - 31.2) / 0.90) ** 2)
    hf = baseline - peak1 - peak2

    curve_df = pd.DataFrame({"time_min": times_min, "temp_C": temps, "hf_W_g": hf})
    params, _ = compute_dsc_thermodynamics(curve_df, auto_baseline=True)
    assert params["is_bimodal"] is True
    assert params["baseline_overshoot_pct"] == pytest.approx(0.0, abs=0.5)
    assert params["qc_flag"] == "OK"


def test_correlate_sem_with_dsc_hv_exclusion_and_per_treatment() -> None:
    sem_rows = []
    dsc_rows = [{"treatment": "control", "week": 0, "Delta_H_J_g_mean": 90.0}]
    for trt, slope in [("CWF", 4.0), ("AWF", 6.0)]:
        sem_rows.append(
            {
                "treatment": trt,
                "week": 0,
                "cbi_score_mean": 0.0,
                "any_hv_mismatch": False,
            }
        )
        for wk in [1, 2, 5, 6, 8, 12]:
            hv_bad = wk in (5, 6)
            true_cbi = slope * wk
            # Corrupt HV-mismatched weeks strongly so excluding them restores r ~ 1.0
            cbi_val = 200.0 if hv_bad else true_cbi
            sem_rows.append(
                {
                    "treatment": trt,
                    "week": wk,
                    "cbi_score_mean": cbi_val,
                    "any_hv_mismatch": hv_bad,
                }
            )
            dsc_rows.append(
                {
                    "treatment": trt,
                    "week": wk,
                    "Delta_H_J_g_mean": 90.0 + 1.5 * wk,
                }
            )

    sem_agg_df = pd.DataFrame(sem_rows)
    dsc_agg_df = pd.DataFrame(dsc_rows)

    # Pooled WITHOUT HV exclusion: corrupted by Weeks 5 & 6
    corr_with_hv, merged_with_hv = correlate_sem_with_dsc(
        sem_agg_df, dsc_agg_df, exclude_hv_mismatch=False, per_treatment=False
    )
    assert len(merged_with_hv) == 14  # 2 treatments * 7 weeks (0,1,2,5,6,8,12)
    assert float(corr_with_hv["pearson_r"].iloc[0]) < 0.7

    # Per-treatment WITH HV exclusion: restores exact correlation on clean weeks (0,1,2,8,12 -> n=5)
    corr_pt, merged_pt = correlate_sem_with_dsc(
        sem_agg_df, dsc_agg_df, exclude_hv_mismatch=True, per_treatment=True
    )
    assert "treatment" in corr_pt.columns
    assert set(corr_pt["treatment"]) == {"AWF", "CWF"}
    assert len(merged_pt) == 10  # 2 treatments * 5 clean weeks
    assert (corr_pt["n_pairs"] == 5).all()
    assert (corr_pt["pearson_r"] > 0.99).all()


def test_correlate_sem_with_dsc_13x4_pairs() -> None:
    weeks = [0, 1, 2, 4, 8, 12]
    sem_rows = []
    dsc_rows = []
    for idx, wk in enumerate(weeks):
        sem_rec: dict[str, object] = {
            "treatment": "ANF",
            "week": wk,
            "any_hv_mismatch": False,
        }
        for m_i, m in enumerate(AGGREGATE_METRIC_COLS):
            sem_rec[f"{m}_mean"] = 1.0 + wk * (0.5 + 0.1 * m_i)
        sem_rows.append(sem_rec)

        dsc_rows.append(
            {
                "treatment": "ANF",
                "week": wk,
                "T_onset_C_mean": 28.0 + 0.2 * wk,
                "T_peak_C_mean": 32.0 + 0.25 * wk,
                "FWHM_C_mean": 3.0 + 0.1 * wk + 0.02 * (idx % 2),
                "Delta_H_J_g_mean": 85.0 + 1.1 * wk,
            }
        )

    corr_df, merged_df = correlate_sem_with_dsc(
        pd.DataFrame(sem_rows),
        pd.DataFrame(dsc_rows),
        exclude_hv_mismatch=True,
        per_treatment=False,
    )
    assert len(AGGREGATE_METRIC_COLS) == 13
    assert len(merged_df) == len(weeks)
    assert len(corr_df) == 13 * 4
    assert sorted(corr_df["dsc_parameter"].unique()) == sorted(DSC_PARAM_COLS)
