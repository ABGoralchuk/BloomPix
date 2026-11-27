"""Differential Scanning Calorimetry (DSC) parser, thermodynamic engine, and SEM correlation.

Supports both raw TA Instruments Discovery DSC ``.txt`` thermograms and pre-computed CSV/Excel tables.
Strictly pure Python / NumPy / SciPy / pandas (ZERO ``streamlit`` imports).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd
from scipy.ndimage import gaussian_filter1d
from scipy.signal import find_peaks
from scipy.stats import pearsonr, spearmanr

from core.kinetics import AGGREGATE_METRIC_COLS

DSC_PARAM_COLS: list[str] = [
    "T_onset_C",
    "T_peak_C",
    "FWHM_C",
    "Delta_H_J_g",
]

_CTRL_FILE_RE = re.compile(
    r"^(?:control|ctrl)(?:[_\-]?w0+)?(?:[_\-]?r(\d+))?$",
    re.IGNORECASE,
)
_TRT_FILE_RE = re.compile(
    r"^(.+?)[_\-]?w(\d+)(?:[_\-]?r(\d+))?$",
    re.IGNORECASE,
)


def _trapz(y: np.ndarray, x: np.ndarray) -> float:
    if hasattr(np, "trapezoid"):
        return float(np.trapezoid(y, x))
    return float(np.trapz(y, x))  # pragma: no cover


def parse_dsc_filename(filename: str) -> dict[str, Any]:
    """Parse treatment, week, replicate, and control flag study-agnostically from DSC filename."""
    stem = Path(filename).stem.strip()
    m_ctrl = _CTRL_FILE_RE.fullmatch(stem)
    if m_ctrl:
        rep = int(m_ctrl.group(1)) if m_ctrl.group(1) else 1
        return {
            "treatment": "control",
            "week": 0,
            "replicate": rep,
            "is_control": True,
        }

    m_trt = _TRT_FILE_RE.fullmatch(stem)
    if m_trt and m_trt.group(1).strip("_- "):
        trt = m_trt.group(1).strip("_- ").upper()
        wk = int(m_trt.group(2))
        rep = int(m_trt.group(3)) if m_trt.group(3) else 1
        return {
            "treatment": trt,
            "week": wk,
            "replicate": rep,
            "is_control": wk == 0,
        }

    raise ValueError(
        f"Unrecognized DSC filename format '{filename}'. "
        "Expected '<treatment>W<week>r<rep>.txt' (e.g., anfw1r1.txt) or 'controlr1.txt'."
    )


def parse_ta_dsc_txt(filepath: str | Path) -> tuple[dict[str, str], pd.DataFrame]:
    """Read a TA Instruments tab-delimited ``.txt`` thermogram into metadata and curve DataFrame."""
    path = Path(filepath)
    if not path.exists():
        raise FileNotFoundError(f"DSC file not found: {path}")

    raw_bytes = path.read_bytes()
    text: Optional[str] = None
    for enc in ("utf-8-sig", "utf-8", "utf-16", "latin-1"):
        try:
            cand = raw_bytes.decode(enc)
            if "Temperature" in cand and "Heat Flow" in cand:
                text = cand
                break
        except Exception:
            continue
    if text is None:
        text = raw_bytes.decode("latin-1", errors="replace")

    lines = text.splitlines()
    metadata: dict[str, str] = {}
    hdr_idx: Optional[int] = None

    for idx, line in enumerate(lines):
        low = line.strip().lower()
        if low.startswith("time\ttemperature"):
            hdr_idx = idx
            break
        if "\t" in line:
            k, v = line.split("\t", 1)
            key = k.strip()
            if key and not key.startswith("["):
                metadata[key] = v.strip()

    if hdr_idx is None:
        raise ValueError(f"Could not find 'Time\\tTemperature\\tHeat Flow' header in {path.name}")

    rows: list[tuple[float, float, float]] = []
    # Skip hdr_idx (column names) and hdr_idx + 1 (units row: min / °C / W/g)
    for line in lines[hdr_idx + 2 :]:
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        t_s, temp_s, hf_s = parts[0].strip(), parts[1].strip(), parts[2].strip()
        if not t_s or not temp_s or not hf_s:
            continue
        try:
            t_val = float(t_s)
            temp_val = float(temp_s)
            hf_val = float(hf_s)
        except ValueError:
            continue
        if np.isfinite(t_val) and np.isfinite(temp_val) and np.isfinite(hf_val):
            rows.append((t_val, temp_val, hf_val))

    if not rows:
        raise ValueError(f"No valid numeric thermogram rows found in {path.name}")

    curve_df = pd.DataFrame(rows, columns=["time_min", "temp_C", "hf_W_g"])
    return metadata, curve_df


def _empty_dsc_params(
    qc_status: str,
    qc_flag: Optional[str] = None,
    baseline_mode: str = "Auto",
) -> dict[str, Any]:
    out: dict[str, Any] = {col: float("nan") for col in DSC_PARAM_COLS}
    out["T_lo_used"] = float("nan")
    out["T_hi_used"] = float("nan")
    out["baseline_overshoot_pct"] = float("nan")
    out["is_bimodal"] = False
    out["qc_flag"] = qc_flag or qc_status
    out["qc_status"] = qc_status
    out["baseline_mode"] = baseline_mode
    return out


def _find_smart_left_anchor(
    T: np.ndarray,
    hf: np.ndarray,
) -> Optional[tuple[float, float]]:
    """Locate the flattest high-level pre-melting plateau in [21.6, 24.2] °C (0.6 °C window)."""
    low_zone = (T >= 21.6) & (T <= 24.2)
    if int(low_zone.sum()) < 3:
        return None

    ref_zone = (T >= 21.6) & (T <= 23.0)
    hf_ref = (
        float(np.percentile(hf[ref_zone], 90))
        if int(ref_zone.sum()) >= 3
        else float(np.percentile(hf[low_zone], 90))
    )

    cands: list[tuple[float, float, float]] = []
    for w0 in np.arange(21.6, 23.601, 0.05):
        mask = (T >= float(w0)) & (T <= float(w0 + 0.6))
        if int(mask.sum()) < 5:
            continue
        tw = T[mask]
        hfw = hf[mask]
        slope_val = float(abs(np.polyfit(tw, hfw, 1)[0]))
        hf_med = float(np.median(hfw))
        t_med = float(np.median(tw))
        cands.append((slope_val, hf_med, t_med))

    if not cands:
        return float(np.median(T[low_zone])), float(np.median(hf[low_zone]))

    valid = [c for c in cands if c[1] >= hf_ref - 0.006]
    if valid:
        best = min(valid, key=lambda c: c[0])
    else:
        best = min(cands, key=lambda c: abs(c[1] - hf_ref))
    return float(best[2]), float(best[1])


def _find_smart_right_anchor(
    T: np.ndarray,
    hf: np.ndarray,
) -> Optional[tuple[float, float]]:
    """Locate the flattest post-melting baseline plateau in [38.0, 45.0] °C (1.5 °C window)."""
    high_zone = (T >= 38.0) & (T <= 45.0)
    if int(high_zone.sum()) < 3:
        return None

    best_score = float("inf")
    best_pair: Optional[tuple[float, float]] = None
    for w0 in np.arange(38.0, 43.501, 0.1):
        mask = (T >= float(w0)) & (T <= float(w0 + 1.5))
        if int(mask.sum()) < 5:
            continue
        tw = T[mask]
        hfw = hf[mask]
        poly = np.polyfit(tw, hfw, 1)
        abs_slope = float(abs(poly[0]))
        resid_std = float(np.std(hfw - np.polyval(poly, tw)))
        score = abs_slope + 0.5 * resid_std
        if score < best_score:
            best_score = score
            best_pair = (float(np.median(tw)), float(np.median(hfw)))

    if best_pair is None:
        return float(np.median(T[high_zone])), float(np.median(hf[high_zone]))
    return best_pair


def compute_dsc_thermodynamics(
    curve_df: pd.DataFrame,
    base_low: tuple[float, float] = (22.5, 24.5),
    base_high: tuple[float, float] = (38.0, 44.0),
    auto_baseline: bool = True,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Compute baseline-corrected ASTM E794 melting parameters from a TA DSC curve."""
    b_mode = "Auto" if auto_baseline else "Manual Override"
    work = curve_df[["time_min", "temp_C", "hf_W_g"]].dropna().copy()
    if work.empty:
        return (
            _empty_dsc_params("Incomplete / Aborted Run", baseline_mode=b_mode),
            {"qc_status": "Incomplete / Aborted Run", "qc_flag": "Incomplete / Aborted Run", "baseline_mode": b_mode},
        )

    work["temp_round"] = work["temp_C"].round(2)
    grouped = (
        work.groupby("temp_round", as_index=False)[["time_min", "temp_C", "hf_W_g"]]
        .mean()
        .sort_values("temp_C")
        .reset_index(drop=True)
    )

    T = grouped["temp_C"].to_numpy(dtype=np.float64)
    hf = grouped["hf_W_g"].to_numpy(dtype=np.float64)
    time_s = grouped["time_min"].to_numpy(dtype=np.float64) * 60.0

    if len(T) < 20:
        payload = {
            "T": T,
            "hf_W_g": hf,
            "baseline": np.full_like(T, np.nan),
            "endo": np.full_like(T, np.nan),
            "T_lo": float(T[0]),
            "T_hi": float(T[-1]),
            "hf_lo": float("nan"),
            "hf_hi": float("nan"),
            "T_lo_used": float("nan"),
            "T_hi_used": float("nan"),
            "baseline_overshoot_pct": float("nan"),
            "is_bimodal": False,
            "T_onset_C": float("nan"),
            "T_peak_C": float("nan"),
            "qc_flag": "Incomplete / Aborted Run",
            "qc_status": "Incomplete / Aborted Run",
            "baseline_mode": b_mode,
        }
        return _empty_dsc_params("Incomplete / Aborted Run", baseline_mode=b_mode), payload

    if auto_baseline:
        left_anchor = _find_smart_left_anchor(T, hf)
        right_anchor = _find_smart_right_anchor(T, hf)
        if left_anchor is None or right_anchor is None:
            payload = {
                "T": T,
                "hf_W_g": hf,
                "baseline": np.full_like(T, np.nan),
                "endo": np.full_like(T, np.nan),
                "T_lo": float(T[0]),
                "T_hi": float(T[-1]),
                "hf_lo": float("nan"),
                "hf_hi": float("nan"),
                "T_lo_used": float("nan"),
                "T_hi_used": float("nan"),
                "baseline_overshoot_pct": float("nan"),
                "is_bimodal": False,
                "T_onset_C": float("nan"),
                "T_peak_C": float("nan"),
                "qc_flag": "Incomplete / Aborted Run",
                "qc_status": "Incomplete / Aborted Run",
                "baseline_mode": b_mode,
            }
            return _empty_dsc_params("Incomplete / Aborted Run", baseline_mode=b_mode), payload
        T_lo, hf_lo = left_anchor
        T_hi, hf_hi = right_anchor
    else:
        low_mask = (T >= float(base_low[0])) & (T <= float(base_low[1]))
        high_mask = (T >= float(base_high[0])) & (T <= float(base_high[1]))
        if int(low_mask.sum()) < 3 or int(high_mask.sum()) < 3:
            payload = {
                "T": T,
                "hf_W_g": hf,
                "baseline": np.full_like(T, np.nan),
                "endo": np.full_like(T, np.nan),
                "T_lo": float(T[0]),
                "T_hi": float(T[-1]),
                "hf_lo": float("nan"),
                "hf_hi": float("nan"),
                "T_lo_used": float("nan"),
                "T_hi_used": float("nan"),
                "baseline_overshoot_pct": float("nan"),
                "is_bimodal": False,
                "T_onset_C": float("nan"),
                "T_peak_C": float("nan"),
                "qc_flag": "Incomplete / Aborted Run",
                "qc_status": "Incomplete / Aborted Run",
                "baseline_mode": b_mode,
            }
            return _empty_dsc_params("Incomplete / Aborted Run", baseline_mode=b_mode), payload
        T_lo = float(np.median(T[low_mask]))
        hf_lo = float(np.median(hf[low_mask]))
        T_hi = float(np.median(T[high_mask]))
        hf_hi = float(np.median(hf[high_mask]))

    if T_hi <= T_lo + 0.5:
        return _empty_dsc_params("Incomplete / Aborted Run", baseline_mode=b_mode), {
            "T": T,
            "hf_W_g": hf,
            "baseline": np.full_like(T, np.nan),
            "endo": np.full_like(T, np.nan),
            "T_lo": T_lo,
            "T_hi": T_hi,
            "hf_lo": hf_lo,
            "hf_hi": hf_hi,
            "T_lo_used": T_lo,
            "T_hi_used": T_hi,
            "baseline_overshoot_pct": float("nan"),
            "is_bimodal": False,
            "qc_flag": "Incomplete / Aborted Run",
            "qc_status": "Incomplete / Aborted Run",
            "baseline_mode": b_mode,
        }

    slope = (hf_hi - hf_lo) / (T_hi - T_lo)
    baseline = hf_lo + slope * (T - T_lo)
    # TA Instruments endothermic melting is negative (downward), so invert to positive signal.
    endo = baseline - hf

    in_win = (T >= T_lo) & (T <= T_hi)
    baseline_overshoot_pct = (
        float(np.mean(hf[in_win] > baseline[in_win] + 0.004) * 100.0)
        if in_win.any()
        else 0.0
    )

    T_grid = np.linspace(T_lo, T_hi, 1000, dtype=np.float64)
    endo_grid = np.interp(T_grid, T, endo)
    endo_smooth = gaussian_filter1d(endo_grid, sigma=6.0)

    i_peak = int(np.argmax(endo_smooth))
    peak_val = float(endo_smooth[i_peak])
    T_peak_C = float(T_grid[i_peak])

    if peak_val <= 1e-6:
        payload = {
            "T": T,
            "hf_W_g": hf,
            "baseline": baseline,
            "endo": endo,
            "T_lo": T_lo,
            "T_hi": T_hi,
            "hf_lo": hf_lo,
            "hf_hi": hf_hi,
            "T_lo_used": T_lo,
            "T_hi_used": T_hi,
            "baseline_overshoot_pct": baseline_overshoot_pct,
            "is_bimodal": False,
            "T_onset_C": float("nan"),
            "T_peak_C": T_peak_C,
            "qc_flag": "No Melting Peak",
            "qc_status": "No Melting Peak",
            "baseline_mode": b_mode,
        }
        empty_no_peak = _empty_dsc_params("No Melting Peak", baseline_mode=b_mode)
        empty_no_peak["T_lo_used"] = T_lo
        empty_no_peak["T_hi_used"] = T_hi
        empty_no_peak["baseline_overshoot_pct"] = baseline_overshoot_pct
        return empty_no_peak, payload

    dT_grid = float(T_grid[1] - T_grid[0])
    min_dist_pts = max(1, int(round(2.0 / max(dT_grid, 1e-6))))
    peaks_idx, _ = find_peaks(
        endo_smooth,
        prominence=0.15 * peak_val,
        distance=min_dist_pts,
    )
    is_bimodal = bool(len(peaks_idx) >= 2)

    d_endo = np.gradient(endo_smooth, T_grid)
    idx_all = np.arange(len(T_grid))

    # ASTM E794 extrapolated onset (steepest positive slope in 20%-80% leading edge)
    lead_mask = (
        (idx_all <= i_peak)
        & (endo_smooth >= 0.20 * peak_val)
        & (endo_smooth <= 0.80 * peak_val)
    )
    if lead_mask.any():
        lead_indices = np.where(lead_mask)[0]
        idx_on = int(lead_indices[int(np.argmax(d_endo[lead_indices]))])
        m_on = float(d_endo[idx_on])
        if m_on > 1e-9:
            T_onset_C = float(T_grid[idx_on] - endo_smooth[idx_on] / m_on)
            T_onset_C = float(np.clip(T_onset_C, T_lo, T_peak_C))
        else:
            T_onset_C = float(T_grid[int(lead_indices[0])])
    else:
        T_onset_C = T_lo

    # FWHM via half-maximum crossings
    half_val = 0.50 * peak_val
    left_below = np.where(endo_smooth[: i_peak + 1] <= half_val)[0]
    if left_below.size > 0 and left_below[-1] < i_peak:
        il = int(left_below[-1])
        dy = float(endo_smooth[il + 1] - endo_smooth[il])
        frac = (half_val - float(endo_smooth[il])) / dy if dy > 1e-12 else 0.0
        T_left = float(T_grid[il] + np.clip(frac, 0.0, 1.0) * (T_grid[il + 1] - T_grid[il]))
    else:
        T_left = T_lo

    right_below = np.where(endo_smooth[i_peak:] <= half_val)[0]
    if right_below.size > 0 and right_below[0] > 0:
        ir = i_peak + int(right_below[0])
        dy = float(endo_smooth[ir - 1] - endo_smooth[ir])
        frac = (half_val - float(endo_smooth[ir])) / dy if dy > 1e-12 else 0.0
        T_right = float(T_grid[ir] - np.clip(frac, 0.0, 1.0) * (T_grid[ir] - T_grid[ir - 1]))
    else:
        T_right = T_hi
    FWHM_C = max(0.0, T_right - T_left)

    # Melting enthalpy integrated over time in seconds (W/g * s = J/g)
    t_win = time_s[in_win]
    pos_endo = np.maximum(endo[in_win], 0.0)
    Delta_H_J_g = max(0.0, _trapz(pos_endo, t_win)) if len(t_win) >= 2 else 0.0

    if auto_baseline:
        needs_review = (
            (baseline_overshoot_pct > 5.0)
            or (T_onset_C < T_lo + 0.05)
            or (Delta_H_J_g <= 1.0)
            or (not np.isfinite(T_onset_C))
        )
        qc_flag = "Review Baseline" if needs_review else "OK"
    else:
        if (
            baseline_overshoot_pct <= 5.0
            and Delta_H_J_g > 1.0
            and np.isfinite(T_onset_C)
        ):
            qc_flag = "OK (Manual)"
        else:
            qc_flag = "Review Baseline"

    params: dict[str, Any] = {
        "T_onset_C": T_onset_C,
        "T_peak_C": T_peak_C,
        "FWHM_C": FWHM_C,
        "Delta_H_J_g": Delta_H_J_g,
        "T_lo_used": T_lo,
        "T_hi_used": T_hi,
        "baseline_overshoot_pct": baseline_overshoot_pct,
        "is_bimodal": is_bimodal,
        "qc_flag": qc_flag,
        "qc_status": "OK",
        "baseline_mode": b_mode,
    }
    payload = {
        "T": T,
        "hf_W_g": hf,
        "baseline": baseline,
        "endo": endo,
        "T_lo": T_lo,
        "T_hi": T_hi,
        "hf_lo": hf_lo,
        "hf_hi": hf_hi,
        "T_lo_used": T_lo,
        "T_hi_used": T_hi,
        "baseline_overshoot_pct": baseline_overshoot_pct,
        "is_bimodal": is_bimodal,
        "T_onset_C": T_onset_C,
        "T_peak_C": T_peak_C,
        "qc_flag": qc_flag,
        "qc_status": "OK",
        "baseline_mode": b_mode,
    }
    return params, payload


def scan_and_analyze_dsc_folder(
    dsc_dir: str | Path = "DSC",
    base_low: tuple[float, float] = (22.5, 24.5),
    base_high: tuple[float, float] = (38.0, 44.0),
    auto_baseline: bool = True,
    per_file_overrides: Optional[
        dict[str, tuple[tuple[float, float], tuple[float, float]]]
    ] = None,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, dict[str, Any]]]:
    """Scan TA Instruments ``.txt`` thermograms in ``dsc_dir`` and compute replicate & weekly tables."""
    root = Path(dsc_dir)
    if not root.exists():
        raise FileNotFoundError(f"DSC folder not found: {root}")

    txt_files = sorted(
        p
        for p in root.iterdir()
        if p.is_file() and not p.name.startswith(".") and p.suffix.lower() == ".txt"
    )
    if not txt_files:
        raise FileNotFoundError(f"No .txt DSC thermograms found in {root}")

    overrides = per_file_overrides or {}
    rep_rows: list[dict[str, Any]] = []
    dsc_curves: dict[str, dict[str, Any]] = {}

    for path in txt_files:
        name_meta = parse_dsc_filename(path.name)
        file_meta, curve_df = parse_ta_dsc_txt(path)
        if path.name in overrides:
            ov_low, ov_high = overrides[path.name]
            params, payload = compute_dsc_thermodynamics(
                curve_df,
                base_low=ov_low,
                base_high=ov_high,
                auto_baseline=False,
            )
            params["baseline_mode"] = "Manual Override"
            payload["baseline_mode"] = "Manual Override"
        else:
            params, payload = compute_dsc_thermodynamics(
                curve_df,
                base_low=base_low,
                base_high=base_high,
                auto_baseline=auto_baseline,
            )
            if not auto_baseline:
                params["baseline_mode"] = "Manual"
                payload["baseline_mode"] = "Manual"

        payload["treatment"] = name_meta["treatment"]
        payload["week"] = name_meta["week"]
        payload["replicate"] = name_meta["replicate"]
        payload["filename"] = path.name
        payload["sample_name"] = file_meta.get("Sample name", path.stem)
        payload["rundate"] = file_meta.get("rundate", "")
        dsc_curves[path.name] = payload

        rep_rows.append(
            {
                "filename": path.name,
                "treatment": name_meta["treatment"],
                "week": name_meta["week"],
                "replicate": name_meta["replicate"],
                "is_control": name_meta["is_control"],
                "rundate": file_meta.get("rundate", ""),
                **params,
            }
        )

    dsc_replicate_df = (
        pd.DataFrame(rep_rows)
        .sort_values(["treatment", "week", "replicate", "filename"])
        .reset_index(drop=True)
    )

    ok_df = dsc_replicate_df[dsc_replicate_df["qc_status"] == "OK"].copy()
    agg_rows: list[dict[str, Any]] = []
    if not ok_df.empty:
        for (trt, wk), grp in ok_df.groupby(["treatment", "week"], sort=True):
            entry: dict[str, Any] = {
                "treatment": str(trt),
                "week": int(wk),
                "n_replicates": int(len(grp)),
            }
            for col in DSC_PARAM_COLS:
                vals = pd.to_numeric(grp[col], errors="coerce").dropna().to_numpy(dtype=np.float64)
                if vals.size == 0:
                    entry[f"{col}_mean"] = float("nan")
                    entry[f"{col}_sd"] = float("nan")
                else:
                    entry[f"{col}_mean"] = float(np.mean(vals))
                    entry[f"{col}_sd"] = float(np.std(vals, ddof=1)) if vals.size > 1 else 0.0
            agg_rows.append(entry)

    dsc_agg_df = pd.DataFrame(agg_rows)
    if not dsc_agg_df.empty:
        dsc_agg_df = dsc_agg_df.sort_values(["treatment", "week"]).reset_index(drop=True)

    return dsc_replicate_df, dsc_agg_df, dsc_curves


def _parse_dsc_week(value: Any) -> int:
    text = str(value).strip().lower()
    if text in ("control", "ctrl", "baseline"):
        return 0
    m = re.fullmatch(r"(?:week[_\-\s]*|w[_\-\s]*)?(\d+)", text)
    if m:
        return int(m.group(1))
    try:
        return int(round(float(text)))
    except ValueError as exc:
        raise ValueError(f"Could not parse DSC week value: '{value}'") from exc


def load_dsc_table(file_or_path: Any) -> pd.DataFrame:
    """Load and validate a DSC CSV/Excel table with ``treatment``, ``week``, and thermal columns."""
    name = ""
    if isinstance(file_or_path, (str, Path)):
        path = Path(file_or_path)
        if not path.exists():
            raise FileNotFoundError(f"DSC table not found: {path}")
        name = path.name.lower()
        df = pd.read_excel(path) if name.endswith((".xlsx", ".xls")) else pd.read_csv(path)
    else:
        name = str(getattr(file_or_path, "name", "")).lower()
        if hasattr(file_or_path, "seek"):
            file_or_path.seek(0)
        df = (
            pd.read_excel(file_or_path)
            if name.endswith((".xlsx", ".xls"))
            else pd.read_csv(file_or_path)
        )

    df.columns = [str(c).strip() for c in df.columns]
    col_map: dict[str, str] = {}
    for col in df.columns:
        low = col.lower()
        if low in ("treatment", "sample", "group", "formulation"):
            col_map[col] = "treatment"
        elif low in ("week", "weeks", "time", "time_weeks"):
            col_map[col] = "week"
    df = df.rename(columns=col_map)

    if "treatment" not in df.columns or "week" not in df.columns:
        raise ValueError(
            "DSC table must contain 'treatment' and 'week' columns "
            f"(found: {list(df.columns)})."
        )

    df["treatment"] = df["treatment"].astype(str).str.strip()
    df["week"] = df["week"].apply(_parse_dsc_week).astype(int)

    thermal_cols: list[str] = []
    for col in df.columns:
        if col in ("treatment", "week"):
            continue
        converted = pd.to_numeric(df[col], errors="coerce")
        if converted.notna().any():
            df[col] = converted
            thermal_cols.append(col)

    if not thermal_cols:
        raise ValueError("DSC table must contain at least one numeric thermal parameter column.")

    return df[["treatment", "week"] + thermal_cols].copy()


def correlate_sem_with_dsc(
    agg_df: pd.DataFrame,
    dsc_df: pd.DataFrame,
    sem_metrics: Optional[list[str]] = None,
    exclude_hv_mismatch: bool = True,
    per_treatment: bool = False,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Align aggregated SEM metrics with DSC thermal parameters and compute Pearson/Spearman r."""
    cols = (
        [
            "treatment",
            "sem_metric",
            "dsc_parameter",
            "n_pairs",
            "pearson_r",
            "p_pearson",
            "spearman_rho",
            "p_spearman",
        ]
        if per_treatment
        else [
            "sem_metric",
            "dsc_parameter",
            "n_pairs",
            "pearson_r",
            "p_pearson",
            "spearman_rho",
            "p_spearman",
        ]
    )
    empty_corr = pd.DataFrame(columns=cols)
    if agg_df.empty or dsc_df.empty:
        return empty_corr, pd.DataFrame()

    agg_work = agg_df.copy()
    if exclude_hv_mismatch:
        if "any_hv_mismatch" in agg_work.columns:
            agg_work = agg_work[~agg_work["any_hv_mismatch"].fillna(False).astype(bool)].copy()
        elif "hv_mismatch" in agg_work.columns:
            agg_work = agg_work[~agg_work["hv_mismatch"].fillna(False).astype(bool)].copy()
    if agg_work.empty:
        return empty_corr, pd.DataFrame()

    dsc_work = dsc_df.copy()
    active_trts = sorted(
        {
            str(t)
            for t in agg_work["treatment"].dropna().unique()
            if str(t).strip().lower() != "control"
        }
    )

    # Align treatment casing if DSC treatments differ only in case
    trt_lookup = {t.lower(): t for t in active_trts}
    dsc_work["treatment"] = dsc_work["treatment"].astype(str).apply(
        lambda val: trt_lookup.get(val.strip().lower(), val.strip())
    )

    ctrl_dsc = dsc_work[
        (dsc_work["treatment"].astype(str).str.lower() == "control")
        & (dsc_work["week"] == 0)
    ]
    if not ctrl_dsc.empty and active_trts:
        parts = [
            dsc_work[
                ~(
                    (dsc_work["treatment"].astype(str).str.lower() == "control")
                    & (dsc_work["week"] == 0)
                )
            ]
        ]
        for trt in active_trts:
            has_own_w0 = (
                (dsc_work["treatment"] == trt) & (dsc_work["week"] == 0)
            ).any()
            if not has_own_w0:
                c_copy = ctrl_dsc.copy()
                c_copy["treatment"] = trt
                parts.append(c_copy)
        dsc_work = pd.concat(parts, ignore_index=True)

    merged_df = pd.merge(agg_work, dsc_work, on=["treatment", "week"], how="inner")
    if merged_df.empty:
        return empty_corr, merged_df

    ignore_cols = {
        "treatment",
        "week",
        "n_replicates",
        "n",
        "is_control",
        "qc_status",
        "qc_flag",
        "is_bimodal",
        "baseline_mode",
        "T_lo_used",
        "T_hi_used",
        "baseline_overshoot_pct",
        "replicate",
        "filename",
        "rundate",
    }
    dsc_params = [
        c
        for c in dsc_work.columns
        if c not in ignore_cols
        and not c.endswith(("_sd", "_sem", "_min", "_max"))
        and pd.api.types.is_numeric_dtype(dsc_work[c])
    ]

    if sem_metrics is None:
        sem_cols = [
            f"{m}_mean"
            for m in AGGREGATE_METRIC_COLS
            if f"{m}_mean" in agg_work.columns
        ]
        if not sem_cols:
            sem_cols = [m for m in AGGREGATE_METRIC_COLS if m in agg_work.columns]
    else:
        sem_cols = [
            (f"{m}_mean" if f"{m}_mean" in merged_df.columns else m)
            for m in sem_metrics
        ]
        sem_cols = [c for c in sem_cols if c in merged_df.columns]

    def _compute_pairs(sub_df: pd.DataFrame, trt_name: Optional[str] = None) -> list[dict[str, Any]]:
        out_rows: list[dict[str, Any]] = []
        for sem_col in sem_cols:
            for dsc_col in dsc_params:
                x = pd.to_numeric(sub_df[sem_col], errors="coerce").to_numpy(dtype=np.float64)
                y = pd.to_numeric(sub_df[dsc_col], errors="coerce").to_numpy(dtype=np.float64)
                valid = np.isfinite(x) & np.isfinite(y)
                if int(valid.sum()) < 3:
                    continue
                xv = x[valid]
                yv = y[valid]
                if float(np.std(xv)) <= 1e-12 or float(np.std(yv)) <= 1e-12:
                    continue

                pr, pp = pearsonr(xv, yv)
                sr, sp = spearmanr(xv, yv)
                clean_dsc = dsc_col[:-5] if dsc_col.endswith("_mean") else dsc_col
                rec: dict[str, Any] = {
                    "sem_metric": sem_col[:-5] if sem_col.endswith("_mean") else sem_col,
                    "dsc_parameter": clean_dsc,
                    "n_pairs": int(valid.sum()),
                    "pearson_r": float(pr),
                    "p_pearson": float(pp),
                    "spearman_rho": float(sr),
                    "p_spearman": float(sp),
                }
                if trt_name is not None:
                    rec = {"treatment": trt_name, **rec}
                out_rows.append(rec)
        return out_rows

    rows: list[dict[str, Any]] = []
    if per_treatment:
        for trt_val in sorted(merged_df["treatment"].dropna().unique()):
            sub = merged_df[merged_df["treatment"] == trt_val]
            rows.extend(_compute_pairs(sub, trt_name=str(trt_val)))
    else:
        rows.extend(_compute_pairs(merged_df, trt_name=None))

    if not rows:
        return empty_corr, merged_df

    corr_df = pd.DataFrame(rows)
    corr_df["_abs_r"] = corr_df["pearson_r"].abs()
    if per_treatment:
        corr_df = (
            corr_df.sort_values(["treatment", "_abs_r"], ascending=[True, False])
            .drop(columns=["_abs_r"])
            .reset_index(drop=True)
        )
    else:
        corr_df = (
            corr_df.sort_values("_abs_r", ascending=False)
            .drop(columns=["_abs_r"])
            .reset_index(drop=True)
        )
    return corr_df, merged_df
