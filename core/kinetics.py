"""Kinetic modeling, treatment ranking, statistical comparison, and PCA ordination.

Strictly pure Python / NumPy / SciPy / pandas / scikit-learn (ZERO ``streamlit`` imports).
"""

from __future__ import annotations

import itertools
import math
import warnings
from typing import Any, Optional

import numpy as np
import pandas as pd
from scipy.optimize import OptimizeWarning, curve_fit
from scipy.stats import f_oneway, kruskal, mannwhitneyu, ttest_ind
from sklearn.decomposition import PCA
from sklearn.preprocessing import StandardScaler

from core.models import KineticFitResult

AGGREGATE_METRIC_COLS: list[str] = [
    "cbi_score",
    "geom_bloom_index",
    "bloom_coverage_pct",
    "trnr_relief",
    "loc_trnr_median",
    "loc_trnr_p90",
    "meso_snr",
    "grad_snr",
    "blade_index",
    "anisotropy_coh",
    "psd_struct_log_snr",
    "psd_beta",
    "corr_len_um",
]

PCA_FEATURE_COLS: list[str] = [
    "trnr_relief",
    "loc_trnr_median",
    "loc_trnr_p90",
    "meso_snr",
    "grad_snr",
    "blade_index",
    "anisotropy_coh",
    "psd_struct_log_snr",
    "corr_len_um",
]


def aggregate_kinetics_table(
    metrics_df: pd.DataFrame,
    include_shared_control: bool = True,
) -> pd.DataFrame:
    """Aggregate image-level metrics per ``(treatment, week)`` with optional Week 0 control expansion."""
    if metrics_df.empty:
        return pd.DataFrame()

    df = metrics_df.copy()
    active_treatments = sorted(
        {
            str(t)
            for t in df["treatment"].dropna().unique()
            if str(t).strip().lower() != "control"
        }
    )

    if include_shared_control and active_treatments:
        ctrl_mask = (
            df["treatment"].astype(str).str.strip().str.lower() == "control"
        ) & (df["week"] == 0)
        ctrl_rows = df.loc[ctrl_mask]

        parts = [df.loc[~ctrl_mask]]
        if not ctrl_rows.empty:
            for trt in active_treatments:
                has_own_w0 = (
                    (df["treatment"] == trt) & (df["week"] == 0)
                ).any()
                if not has_own_w0:
                    c_copy = ctrl_rows.copy()
                    c_copy["treatment"] = trt
                    parts.append(c_copy)
        df = pd.concat(parts, ignore_index=True)

    available_metrics = [c for c in AGGREGATE_METRIC_COLS if c in df.columns]
    has_hv = "hv_mismatch" in df.columns

    rows: list[dict[str, Any]] = []
    for (trt, wk), grp in df.groupby(["treatment", "week"], sort=True):
        n_rep = int(len(grp))
        entry: dict[str, Any] = {
            "treatment": str(trt),
            "week": int(wk),
            "n": n_rep,
            "any_hv_mismatch": bool(grp["hv_mismatch"].any()) if has_hv else False,
        }
        for col in available_metrics:
            vals = pd.to_numeric(grp[col], errors="coerce").dropna().to_numpy(dtype=np.float64)
            if vals.size == 0:
                entry[f"{col}_mean"] = float("nan")
                entry[f"{col}_sd"] = float("nan")
                entry[f"{col}_sem"] = float("nan")
                entry[f"{col}_min"] = float("nan")
                entry[f"{col}_max"] = float("nan")
            else:
                mean_v = float(np.mean(vals))
                sd_v = float(np.std(vals, ddof=1)) if vals.size > 1 else 0.0
                sem_v = sd_v / math.sqrt(vals.size) if vals.size > 1 else 0.0
                entry[f"{col}_mean"] = mean_v
                entry[f"{col}_sd"] = sd_v
                entry[f"{col}_sem"] = sem_v
                entry[f"{col}_min"] = float(np.min(vals))
                entry[f"{col}_max"] = float(np.max(vals))
        rows.append(entry)

    out = pd.DataFrame(rows)
    if not out.empty:
        out = out.sort_values(["treatment", "week"]).reset_index(drop=True)
    return out


def _logistic_4p(
    t: np.ndarray,
    y0: float,
    y_max: float,
    k: float,
    t_half: float,
) -> np.ndarray:
    arg = np.clip(-k * (t - t_half), -60.0, 60.0)
    return y0 + (y_max - y0) / (1.0 + np.exp(arg))


def _sustained_onset_time(
    t: np.ndarray,
    y: np.ndarray,
    metric_col: str,
    y_start: float,
    max_obs: float,
) -> Optional[float]:
    """Return onset time only if ``y`` shows a sustained crossing (>=2 consecutive weeks)."""
    if len(t) < 2:
        return None

    if metric_col == "cbi_score":
        abs_thresh = 25.0
    elif metric_col == "bloom_coverage_pct":
        abs_thresh = 15.0
    else:
        if max_obs <= y_start:
            return None
        abs_thresh = y_start + 0.50 * (max_obs - y_start)

    for idx in range(1, len(t)):
        if y[idx] >= abs_thresh:
            sustained = (
                (idx + 1 < len(t) and y[idx + 1] >= abs_thresh)
                or (idx == len(t) - 1 and y[idx - 1] >= abs_thresh)
            )
            if not sustained:
                continue
            if y[idx - 1] < abs_thresh:
                dy = float(y[idx] - y[idx - 1])
                if dy > 1e-12:
                    frac = (abs_thresh - float(y[idx - 1])) / dy
                    return float(
                        t[idx - 1] + np.clip(frac, 0.0, 1.0) * (t[idx] - t[idx - 1])
                    )
            return float(t[idx])
    return None


def _is_suppressed_trajectory(
    metric_col: str,
    y_start: float,
    max_observed: float,
) -> bool:
    if metric_col == "cbi_score":
        return (max_observed - y_start) < 20.0
    if metric_col == "bloom_coverage_pct":
        return max_observed < 15.0
    return (max_observed - y_start) < 1e-6


def fit_treatment_kinetics(
    agg_df: pd.DataFrame,
    scale_label: str,
    metric_col: str = "cbi_score",
    exclude_hv_mismatch: bool = True,
) -> tuple[list[KineticFitResult], dict[str, tuple[np.ndarray, np.ndarray]]]:
    """Fit bounded 4-parameter logistic bloom kinetics and rank treatments."""
    if agg_df.empty:
        return [], {}

    val_col = f"{metric_col}_mean" if f"{metric_col}_mean" in agg_df.columns else metric_col
    if val_col not in agg_df.columns:
        raise ValueError(f"Metric column '{val_col}' not found in aggregated table.")

    results: list[KineticFitResult] = []
    curves: dict[str, tuple[np.ndarray, np.ndarray]] = {}

    for trt in sorted(agg_df["treatment"].astype(str).unique()):
        sub = agg_df[agg_df["treatment"].astype(str) == trt].sort_values("week")
        if exclude_hv_mismatch and "any_hv_mismatch" in sub.columns:
            excluded_hv_weeks = sorted(
                int(w) for w in sub.loc[sub["any_hv_mismatch"].astype(bool), "week"].unique()
            )
            fit_df = sub.loc[~sub["any_hv_mismatch"].astype(bool)]
        else:
            excluded_hv_weeks = []
            fit_df = sub

        t_raw = pd.to_numeric(fit_df["week"], errors="coerce").to_numpy(dtype=np.float64)
        y_raw = pd.to_numeric(fit_df[val_col], errors="coerce").to_numpy(dtype=np.float64)
        valid = np.isfinite(t_raw) & np.isfinite(y_raw)
        t = t_raw[valid]
        y = y_raw[valid]

        if t.size == 0:
            results.append(
                KineticFitResult(
                    treatment=trt,
                    scale_label=scale_label,
                    metric_name=metric_col,
                    fit_status="Insufficient Points",
                    y0=0.0,
                    y_max=0.0,
                    k_rate=0.0,
                    t_lag_weeks=None,
                    t_half_weeks=None,
                    r_squared=None,
                    auc=0.0,
                    auc_norm_per_week=0.0,
                    late_stage_mean=0.0,
                    late_stage_sd=0.0,
                    max_observed=0.0,
                    n_weeks_fitted=0,
                    excluded_hv_weeks=excluded_hv_weeks,
                )
            )
            curves[trt] = (np.array([], dtype=np.float64), np.array([], dtype=np.float64))
            continue

        t_min = float(t[0])
        t_max = float(t[-1])
        span = max(t_max - t_min, 1.0)
        auc = float(np.trapezoid(y, t)) if t.size >= 2 else 0.0
        auc_norm = auc / span

        late_mask = t >= (t_max - 4.0)
        if int(late_mask.sum()) < 2:
            late_vals = y[-min(3, y.size) :]
        else:
            late_vals = y[late_mask]
        late_mean = float(np.mean(late_vals))
        late_sd = float(np.std(late_vals, ddof=1)) if late_vals.size > 1 else 0.0

        y_start = float(y[0])
        max_obs = float(np.max(y))
        t_grid = np.linspace(t_min, t_max, 200) if t.size >= 2 else t.copy()

        if t.size < 4:
            curves[trt] = (t_grid, np.interp(t_grid, t, y))
            results.append(
                KineticFitResult(
                    treatment=trt,
                    scale_label=scale_label,
                    metric_name=metric_col,
                    fit_status="Insufficient Points",
                    y0=y_start,
                    y_max=max_obs,
                    k_rate=0.0,
                    t_lag_weeks=None,
                    t_half_weeks=None,
                    r_squared=None,
                    auc=auc,
                    auc_norm_per_week=auc_norm,
                    late_stage_mean=late_mean,
                    late_stage_sd=late_sd,
                    max_observed=max_obs,
                    n_weeks_fitted=int(t.size),
                    excluded_hv_weeks=excluded_hv_weeks,
                )
            )
            continue

        if _is_suppressed_trajectory(metric_col, y_start, max_obs):
            curves[trt] = (t_grid, np.full_like(t_grid, float(np.mean(y))))
            results.append(
                KineticFitResult(
                    treatment=trt,
                    scale_label=scale_label,
                    metric_name=metric_col,
                    fit_status="Suppressed / No Bloom Onset",
                    y0=y_start,
                    y_max=max_obs,
                    k_rate=0.0,
                    t_lag_weeks=None,
                    t_half_weeks=None,
                    r_squared=None,
                    auc=auc,
                    auc_norm_per_week=auc_norm,
                    late_stage_mean=late_mean,
                    late_stage_sd=late_sd,
                    max_observed=max_obs,
                    n_weeks_fitted=int(t.size),
                    excluded_hv_weeks=excluded_hv_weeks,
                )
            )
            continue

        # Bounded 4-parameter logistic fit with multi-start initialization
        max_thalf = max(2.0 * t_max, 2.0)
        if metric_col == "cbi_score":
            lower = [-25.0, 15.0, 0.05, 0.5]
            upper = [30.0, max(250.0, max_obs * 1.5), 5.0, max_thalf]
        elif metric_col == "bloom_coverage_pct":
            lower = [0.0, 15.0, 0.05, 0.5]
            upper = [30.0, 105.0, 5.0, max_thalf]
        else:
            y_min_obs = float(np.min(y))
            amp = max(max_obs - y_min_obs, 1e-3)
            lower = [y_min_obs - 0.5 * amp, y_min_obs + 0.1 * amp, 0.05, 0.5]
            upper = [y_min_obs + 0.5 * amp, max_obs + 1.5 * amp, 5.0, max_thalf]

        y0_init = float(np.clip(y_start, lower[0] + 1e-3, upper[0] - 1e-3))
        ymax_init = float(np.clip(max(max_obs, y0_init + 1.0), lower[1] + 1e-3, upper[1] - 1e-3))

        best_popt: Optional[np.ndarray] = None
        best_ssr = float("inf")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", OptimizeWarning)
            for th_frac in (0.30, 0.55, 0.75, 1.0):
                for k_init in (0.35, 1.0):
                    th_init = float(np.clip(t_max * th_frac, lower[3] + 1e-3, upper[3] - 1e-3))
                    p0 = [y0_init, ymax_init, k_init, th_init]
                    try:
                        popt, _ = curve_fit(
                            _logistic_4p,
                            t,
                            y,
                            p0=p0,
                            bounds=(lower, upper),
                            maxfev=6000,
                        )
                        pred = _logistic_4p(t, *popt)
                        ssr = float(np.sum((y - pred) ** 2))
                        if np.isfinite(ssr) and ssr < best_ssr:
                            best_ssr = ssr
                            best_popt = popt
                    except Exception:
                        continue

        ss_tot = float(np.sum((y - np.mean(y)) ** 2))
        if best_popt is not None:
            r2 = 1.0 - best_ssr / max(ss_tot, 1e-12)
        else:
            r2 = float("nan")

        if best_popt is not None and np.isfinite(r2) and r2 >= 0.50 and float(best_popt[2]) < 4.95:
            y0_fit, ymax_fit, k_fit, thalf_fit = (float(v) for v in best_popt)
            t_lag = max(0.0, thalf_fit - math.log(9.0) / max(k_fit, 1e-6))
            curves[trt] = (t_grid, _logistic_4p(t_grid, y0_fit, ymax_fit, k_fit, thalf_fit))
            results.append(
                KineticFitResult(
                    treatment=trt,
                    scale_label=scale_label,
                    metric_name=metric_col,
                    fit_status="Fitted",
                    y0=y0_fit,
                    y_max=ymax_fit,
                    k_rate=k_fit,
                    t_lag_weeks=t_lag,
                    t_half_weeks=thalf_fit,
                    r_squared=float(r2),
                    auc=auc,
                    auc_norm_per_week=auc_norm,
                    late_stage_mean=late_mean,
                    late_stage_sd=late_sd,
                    max_observed=max_obs,
                    n_weeks_fitted=int(t.size),
                    excluded_hv_weeks=excluded_hv_weeks,
                )
            )
        else:
            t_lag_sustained = _sustained_onset_time(
                t, y, metric_col=metric_col, y_start=y_start, max_obs=max_obs
            )
            curves[trt] = (t_grid, np.interp(t_grid, t, y))
            results.append(
                KineticFitResult(
                    treatment=trt,
                    scale_label=scale_label,
                    metric_name=metric_col,
                    fit_status="Mild / Non-Sigmoidal Drift",
                    y0=y_start,
                    y_max=max_obs,
                    k_rate=0.0,
                    t_lag_weeks=t_lag_sustained,
                    t_half_weeks=None,
                    r_squared=float(r2) if np.isfinite(r2) else None,
                    auc=auc,
                    auc_norm_per_week=auc_norm,
                    late_stage_mean=late_mean,
                    late_stage_sd=late_sd,
                    max_observed=max_obs,
                    n_weeks_fitted=int(t.size),
                    excluded_hv_weeks=excluded_hv_weeks,
                )
            )

    results.sort(key=lambda r: (r.auc_norm_per_week, r.late_stage_mean))
    for idx, res in enumerate(results, start=1):
        res.rank = idx

    return results, curves


def compute_treatment_statistics(
    metrics_df: pd.DataFrame,
    metric_col: str = "cbi_score",
    exclude_hv_mismatch: bool = True,
    min_week: int = 8,
) -> dict[str, Any]:
    """Compare post-induction treatments using ANOVA, Kruskal-Wallis, Welch t, and Mann-Whitney U."""
    empty_summary = pd.DataFrame(
        columns=["treatment", "n", "mean", "sd", "median", "iqr"]
    )
    empty_pair = pd.DataFrame(
        columns=[
            "treatment_a",
            "treatment_b",
            "n_a",
            "n_b",
            "mean_a",
            "mean_b",
            "mean_diff",
            "t_welch",
            "p_welch",
            "u_stat",
            "p_mannwhitney",
        ]
    )

    if metrics_df.empty or metric_col not in metrics_df.columns:
        return {
            "metric_col": metric_col,
            "min_week": min_week,
            "n_observations": 0,
            "anova_f": float("nan"),
            "anova_p": float("nan"),
            "kruskal_h": float("nan"),
            "kruskal_p": float("nan"),
            "group_summary_df": empty_summary,
            "pairwise_df": empty_pair,
        }

    df = metrics_df.copy()
    mask = (
        (df["treatment"].astype(str).str.strip().str.lower() != "control")
        & (pd.to_numeric(df["week"], errors="coerce") >= min_week)
    )
    if exclude_hv_mismatch and "hv_mismatch" in df.columns:
        mask &= ~df["hv_mismatch"].astype(bool)

    df = df.loc[mask].copy()
    df[metric_col] = pd.to_numeric(df[metric_col], errors="coerce")
    df = df.dropna(subset=[metric_col])

    if df.empty:
        return {
            "metric_col": metric_col,
            "min_week": min_week,
            "n_observations": 0,
            "anova_f": float("nan"),
            "anova_p": float("nan"),
            "kruskal_h": float("nan"),
            "kruskal_p": float("nan"),
            "group_summary_df": empty_summary,
            "pairwise_df": empty_pair,
        }

    groups: dict[str, np.ndarray] = {}
    summary_rows: list[dict[str, Any]] = []
    for trt, grp in df.groupby("treatment", sort=True):
        vals = grp[metric_col].to_numpy(dtype=np.float64)
        groups[str(trt)] = vals
        q25, q75 = np.percentile(vals, [25.0, 75.0])
        summary_rows.append(
            {
                "treatment": str(trt),
                "n": int(vals.size),
                "mean": float(np.mean(vals)),
                "sd": float(np.std(vals, ddof=1)) if vals.size > 1 else 0.0,
                "median": float(np.median(vals)),
                "iqr": float(q75 - q25),
            }
        )
    group_summary_df = pd.DataFrame(summary_rows)

    valid_groups = [v for v in groups.values() if v.size >= 2]
    anova_f = float("nan")
    anova_p = float("nan")
    kruskal_h = float("nan")
    kruskal_p = float("nan")

    if len(valid_groups) >= 2:
        try:
            f_stat, p_val = f_oneway(*valid_groups)
            anova_f, anova_p = float(f_stat), float(p_val)
        except Exception:
            pass
        try:
            h_stat, kw_p = kruskal(*valid_groups)
            kruskal_h, kruskal_p = float(h_stat), float(kw_p)
        except Exception:
            pass

    pairwise_rows: list[dict[str, Any]] = []
    trt_names = sorted(groups.keys())
    for t_a, t_b in itertools.combinations(trt_names, 2):
        va = groups[t_a]
        vb = groups[t_b]
        t_stat = float("nan")
        p_w = float("nan")
        u_stat = float("nan")
        p_mw = float("nan")

        if va.size >= 2 and vb.size >= 2:
            try:
                t_res = ttest_ind(va, vb, equal_var=False)
                t_stat, p_w = float(t_res.statistic), float(t_res.pvalue)
            except Exception:
                pass
        if va.size >= 1 and vb.size >= 1:
            try:
                mw_res = mannwhitneyu(va, vb, alternative="two-sided")
                u_stat, p_mw = float(mw_res.statistic), float(mw_res.pvalue)
            except Exception:
                pass

        pairwise_rows.append(
            {
                "treatment_a": t_a,
                "treatment_b": t_b,
                "n_a": int(va.size),
                "n_b": int(vb.size),
                "mean_a": float(np.mean(va)),
                "mean_b": float(np.mean(vb)),
                "mean_diff": float(np.mean(va) - np.mean(vb)),
                "t_welch": t_stat,
                "p_welch": p_w,
                "u_stat": u_stat,
                "p_mannwhitney": p_mw,
            }
        )

    pairwise_df = pd.DataFrame(pairwise_rows) if pairwise_rows else empty_pair
    if not pairwise_df.empty:
        pairwise_df = pairwise_df.sort_values("p_welch", na_position="last").reset_index(
            drop=True
        )

    return {
        "metric_col": metric_col,
        "min_week": min_week,
        "n_observations": int(len(df)),
        "anova_f": anova_f,
        "anova_p": anova_p,
        "kruskal_h": kruskal_h,
        "kruskal_p": kruskal_p,
        "group_summary_df": group_summary_df,
        "pairwise_df": pairwise_df,
    }


def compute_morphology_pca(
    metrics_df: pd.DataFrame,
    exclude_hv_mismatch: bool = True,
) -> dict[str, Any]:
    """Run 2D PCA ordination across the 9 invariant surface-roughness/morphology metrics."""
    features = [c for c in PCA_FEATURE_COLS if c in metrics_df.columns]
    if metrics_df.empty or len(features) < 2:
        return {
            "scores_df": pd.DataFrame(),
            "loadings_df": pd.DataFrame(),
            "explained_variance_ratio": (0.0, 0.0),
            "n_samples": 0,
            "features": features,
        }

    df = metrics_df.copy()
    if exclude_hv_mismatch and "hv_mismatch" in df.columns:
        df = df.loc[~df["hv_mismatch"].astype(bool)].copy()

    for col in features:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=features).reset_index(drop=True)

    if len(df) < 3:
        return {
            "scores_df": pd.DataFrame(),
            "loadings_df": pd.DataFrame(),
            "explained_variance_ratio": (0.0, 0.0),
            "n_samples": int(len(df)),
            "features": features,
        }

    x_raw = df[features].to_numpy(dtype=np.float64)
    x_scaled = StandardScaler().fit_transform(x_raw)
    pca = PCA(n_components=2)
    coords = pca.fit_transform(x_scaled)
    loadings = pca.components_.copy()

    # Align PC1 sign so positive PC1 reflects increased surface roughness / bloom
    if "trnr_relief" in features:
        trnr_idx = features.index("trnr_relief")
        if loadings[0, trnr_idx] < 0.0:
            loadings[0, :] *= -1.0
            coords[:, 0] *= -1.0

    id_cols = [
        c
        for c in (
            "image_id",
            "treatment",
            "week",
            "scale_label",
            "replicate",
            "hv_mismatch",
            "cbi_score",
        )
        if c in df.columns
    ]
    scores_df = df[id_cols].copy()
    scores_df["PC1"] = coords[:, 0]
    scores_df["PC2"] = coords[:, 1]

    loadings_df = pd.DataFrame(
        {
            "feature": features,
            "PC1": loadings[0, :],
            "PC2": loadings[1, :],
        }
    )

    ev = pca.explained_variance_ratio_
    return {
        "scores_df": scores_df,
        "loadings_df": loadings_df,
        "explained_variance_ratio": (float(ev[0]), float(ev[1])),
        "n_samples": int(len(df)),
        "features": features,
    }
