"""Differential Scanning Calorimetry (DSC) loader and SEM-DSC correlation engine.

Strictly pure Python / pandas / SciPy (ZERO ``streamlit`` imports).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd
from scipy.stats import pearsonr, spearmanr

from core.kinetics import AGGREGATE_METRIC_COLS


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
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Align aggregated SEM metrics with DSC thermal parameters and compute Pearson/Spearman r."""
    empty_corr = pd.DataFrame(
        columns=[
            "sem_metric",
            "dsc_parameter",
            "n_pairs",
            "pearson_r",
            "p_pearson",
            "spearman_rho",
            "p_spearman",
        ]
    )
    if agg_df.empty or dsc_df.empty:
        return empty_corr, pd.DataFrame()

    dsc_work = dsc_df.copy()
    active_trts = sorted(
        {
            str(t)
            for t in agg_df["treatment"].dropna().unique()
            if str(t).strip().lower() != "control"
        }
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

    merged_df = pd.merge(agg_df, dsc_work, on=["treatment", "week"], how="inner")
    if merged_df.empty:
        return empty_corr, merged_df

    dsc_params = [c for c in dsc_work.columns if c not in ("treatment", "week")]

    if sem_metrics is None:
        sem_cols = [
            f"{m}_mean"
            for m in AGGREGATE_METRIC_COLS
            if f"{m}_mean" in agg_df.columns
        ]
        if not sem_cols:
            sem_cols = [m for m in AGGREGATE_METRIC_COLS if m in agg_df.columns]
    else:
        sem_cols = [
            (f"{m}_mean" if f"{m}_mean" in merged_df.columns else m)
            for m in sem_metrics
        ]
        sem_cols = [c for c in sem_cols if c in merged_df.columns]

    rows: list[dict[str, Any]] = []
    for sem_col in sem_cols:
        for dsc_col in dsc_params:
            x = pd.to_numeric(merged_df[sem_col], errors="coerce").to_numpy(dtype=np.float64)
            y = pd.to_numeric(merged_df[dsc_col], errors="coerce").to_numpy(dtype=np.float64)
            valid = np.isfinite(x) & np.isfinite(y)
            if int(valid.sum()) < 3:
                continue
            xv = x[valid]
            yv = y[valid]
            if float(np.std(xv)) <= 1e-12 or float(np.std(yv)) <= 1e-12:
                continue

            pr, pp = pearsonr(xv, yv)
            sr, sp = spearmanr(xv, yv)
            rows.append(
                {
                    "sem_metric": sem_col[:-5] if sem_col.endswith("_mean") else sem_col,
                    "dsc_parameter": dsc_col,
                    "n_pairs": int(valid.sum()),
                    "pearson_r": float(pr),
                    "p_pearson": float(pp),
                    "spearman_rho": float(sr),
                    "p_spearman": float(sp),
                }
            )

    if not rows:
        return empty_corr, merged_df

    corr_df = pd.DataFrame(rows)
    corr_df["_abs_r"] = corr_df["pearson_r"].abs()
    corr_df = (
        corr_df.sort_values("_abs_r", ascending=False)
        .drop(columns=["_abs_r"])
        .reset_index(drop=True)
    )
    return corr_df, merged_df
