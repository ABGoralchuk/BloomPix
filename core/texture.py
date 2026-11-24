"""Brightness/contrast-invariant SEM roughness, Pseudo-AFM, 2D FFT PSD, and CBI engine.

Strictly pure Python / NumPy / SciPy / scikit-image / pandas (ZERO ``streamlit`` imports).
"""

from __future__ import annotations

import inspect
import math
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
from typing import Any, Callable, Optional

import numpy as np
import pandas as pd
from scipy.ndimage import binary_erosion, gaussian_filter
from skimage.filters import sato, scharr_h, scharr_v

from core.artifacts import build_valid_mask
from core.io_loader import expand_shared_control_for_treatment, load_sem_image
from core.models import (
    AnalysisConfig,
    ArtifactMask,
    Calibration,
    RoughnessMetrics,
    SEMImageRecord,
)
from core.preprocessing import compute_image_qc, flatten_illumination, make_display_image

CORE_CBI_METRICS: list[str] = [
    "trnr_relief",
    "loc_trnr_median",
    "meso_snr",
    "grad_snr",
    "blade_index",
    "anisotropy_coh",
    "psd_struct_log_snr",
    "corr_len_um",
]

GEOM_CBI_METRICS: list[str] = [
    "anisotropy_coh",
    "corr_len_um",
    "psd_beta",
]


def _masked_gaussian(
    arr: np.ndarray,
    valid: np.ndarray,
    sigma: float,
) -> np.ndarray:
    """Apply Gaussian smoothing with normalized convolution over ``valid`` pixels."""
    if valid.all():
        return gaussian_filter(arr, sigma=sigma, mode="reflect")
    weights = valid.astype(np.float64)
    num = gaussian_filter(arr * weights, sigma=sigma, mode="reflect")
    den = gaussian_filter(weights, sigma=sigma, mode="reflect")
    out = np.zeros_like(arr, dtype=np.float64)
    good = den > 1e-6
    out[good] = num[good] / den[good]
    return out


def _masked_gaussian_local_std(
    arr: np.ndarray,
    valid: np.ndarray,
    sigma_px: float,
) -> np.ndarray:
    """Compute smooth isotropic Gaussian-weighted local standard deviation over ``valid`` pixels."""
    if valid.all():
        lm = gaussian_filter(arr, sigma=sigma_px, mode="reflect")
        lsq = gaussian_filter(arr * arr, sigma=sigma_px, mode="reflect")
        return np.sqrt(np.maximum(lsq - lm * lm, 0.0))

    weights = valid.astype(np.float64)
    arr_v = np.where(valid, arr, 0.0)
    w_sum = gaussian_filter(weights, sigma=sigma_px, mode="reflect")
    safe_w = np.maximum(w_sum, 1e-6)
    lm = gaussian_filter(arr_v, sigma=sigma_px, mode="reflect") / safe_w
    lsq = gaussian_filter(arr_v * arr_v, sigma=sigma_px, mode="reflect") / safe_w
    loc_var = np.where(w_sum > 1e-6, np.maximum(lsq - lm * lm, 0.0), 0.0)
    return np.sqrt(loc_var)


def _compute_radial_psd(
    z_img: np.ndarray,
    um_per_px: float,
) -> tuple[np.ndarray, float, float]:
    """Compute physical 2D FFT radial PSD (cycles/um), structural log-SNR, and slope beta."""
    height, width = z_img.shape
    hann = np.outer(np.hanning(height), np.hanning(width))
    fft2d = np.fft.fftshift(np.fft.fft2(z_img * hann))
    p2d = fft2d.real * fft2d.real + fft2d.imag * fft2d.imag

    n_ref = min(height, width)
    max_r = max(n_ref // 2, 8)

    fy = np.fft.fftshift(np.fft.fftfreq(height, d=um_per_px))
    fx = np.fft.fftshift(np.fft.fftfreq(width, d=um_per_px))
    fr = np.hypot(fy[:, None], fx[None, :])

    df_ref = 1.0 / (n_ref * um_per_px)
    r_bin = np.rint(fr / df_ref).astype(np.int32)
    in_bounds = (r_bin >= 0) & (r_bin <= max_r)

    bins = r_bin[in_bounds]
    vals = p2d[in_bounds]
    sums = np.bincount(bins, weights=vals, minlength=max_r + 1)
    counts = np.bincount(bins, minlength=max_r + 1)
    radial_psd = np.where(counts > 0, sums / np.maximum(counts, 1), 0.0)
    freq_um_inv = np.arange(max_r + 1, dtype=np.float64) * df_ref

    s_lo = min(4, max_r - 1)
    s_hi = max(s_lo + 1, int(0.25 * max_r))
    n_lo = max(s_hi + 1, int(0.65 * max_r))
    n_hi = max(n_lo + 1, min(max_r, int(0.95 * max_r)))

    p_struct = max(float(np.mean(radial_psd[s_lo : s_hi + 1])), 1e-18)
    p_noise = max(float(np.mean(radial_psd[n_lo : n_hi + 1])), 1e-18)
    psd_struct_log_snr = float(np.log10(p_struct / p_noise))

    m_lo = min(5, max_r - 2)
    m_hi = max(m_lo + 2, int(0.35 * max_r))
    band_f = freq_um_inv[m_lo : m_hi + 1]
    band_p = radial_psd[m_lo : m_hi + 1]
    pos = (band_f > 0.0) & (band_p > 0.0)
    if int(pos.sum()) >= 3:
        slope, _ = np.polyfit(np.log10(band_f[pos]), np.log10(band_p[pos]), 1)
        psd_beta = float(-slope)
    else:
        psd_beta = 0.0

    peak_p = max(float(np.max(radial_psd[1:])), 1e-18) if max_r >= 1 else 1.0
    radial_psd_norm = radial_psd / peak_p
    return freq_um_inv, radial_psd_norm, psd_struct_log_snr, psd_beta


def _compute_corr_length_um(
    z_img: np.ndarray,
    valid_mask: np.ndarray,
    um_per_px: float,
) -> float:
    """Compute characteristic spatial correlation length (1/e decay of 2D ACF) in micrometers."""
    height, width = z_img.shape
    ac_raw = np.fft.fftshift(np.fft.irfft2(np.abs(np.fft.rfft2(z_img)) ** 2, s=(height, width)))
    if not valid_mask.all():
        vm_f = valid_mask.astype(np.float64)
        overlap = np.fft.fftshift(
            np.fft.irfft2(np.abs(np.fft.rfft2(vm_f)) ** 2, s=(height, width))
        )
        ac = ac_raw / np.maximum(overlap, 1.0)
    else:
        ac = ac_raw

    center_val = float(ac[height // 2, width // 2])
    if center_val <= 1e-12:
        return 0.0
    ac_norm = ac / center_val

    max_lag = max(8, min(height, width) // 4)
    yy = np.arange(height, dtype=np.float64) - (height // 2)
    xx = np.arange(width, dtype=np.float64) - (width // 2)
    rr = np.rint(np.hypot(yy[:, None], xx[None, :])).astype(np.int32)

    in_bounds = rr <= max_lag
    r_vals = rr[in_bounds]
    a_vals = ac_norm[in_bounds]
    sums = np.bincount(r_vals, weights=a_vals, minlength=max_lag + 1)
    counts = np.bincount(r_vals, minlength=max_lag + 1)
    acf_1d = np.where(counts > 0, sums / np.maximum(counts, 1), 0.0)

    target = 1.0 / math.e
    below = np.where(acf_1d[1:] <= target)[0]
    if below.size == 0:
        return float(max_lag * um_per_px)

    idx = int(below[0]) + 1
    y0 = float(acf_1d[idx - 1])
    y1 = float(acf_1d[idx])
    if y0 > y1:
        frac = (y0 - target) / (y0 - y1)
        r_decay_px = (idx - 1) + float(np.clip(frac, 0.0, 1.0))
    else:
        r_decay_px = float(idx)
    return float(r_decay_px * um_per_px)


def compute_image_roughness(
    img_raw: np.ndarray,
    calibration: Calibration,
    record: Optional[SEMImageRecord] = None,
    config: Optional[AnalysisConfig] = None,
    artifact_mask: Optional[ArtifactMask] = None,
    bloom_cov_threshold: Optional[float] = None,
    return_maps: bool = False,
) -> tuple[RoughnessMetrics, Optional[dict[str, np.ndarray]]]:
    """Compute brightness/contrast-invariant roughness, spectral, and morphology metrics."""
    cfg = config or AnalysisConfig()
    img = np.asarray(img_raw, dtype=np.float64)
    height, width = img.shape

    eff_artifact = artifact_mask
    if eff_artifact is None and cfg.auto_mask_pores:
        eff_artifact = ArtifactMask(
            image_id=record.image_id if record is not None else "image",
            auto_mask_pores=True,
        )

    bit_depth = (
        record.bit_depth
        if record is not None
        else (16 if float(np.max(img)) > 255.0 else 8)
    )
    valid_mask, mask_stats = build_valid_mask(
        shape=(height, width),
        calibration=calibration,
        artifact_mask=eff_artifact,
        img_raw=img,
        bit_depth=bit_depth,
    )

    qc = compute_image_qc(img, bit_depth=bit_depth, valid_mask=valid_mask)
    sigma_n = qc["noise_sigma"]

    img_flat = flatten_illumination(
        img,
        bg_sigma_frac=cfg.bg_sigma_frac,
        valid_mask=valid_mask,
    )
    valid_mean = float(np.mean(img_flat[valid_mask]))
    img_flat = img_flat - valid_mean
    if not valid_mask.all():
        img_flat[~valid_mask] = 0.0

    um_px = calibration.um_per_px if calibration.um_per_px > 0.0 else 0.108
    sigma_topo_px = max(1.2, 0.16 / um_px)
    sigma_small = max(1.5, 0.27 / um_px)
    sigma_large = max(10.0, 2.7 / um_px)
    loc_sigma_px = float(np.clip(1.0 / um_px, 4.0, min(height, width) / 16.0))
    sato_sigmas = [
        max(1.2, 0.16 / um_px),
        max(2.2, 0.32 / um_px),
        max(3.5, 0.54 / um_px),
    ]
    sigma_st = max(2.5, 0.38 / um_px)

    img_topo = _masked_gaussian(img_flat, valid_mask, sigma_topo_px)
    trnr_relief = float(np.std(img_topo[valid_mask]) / sigma_n)

    dog = _masked_gaussian(img_flat, valid_mask, sigma_small) - _masked_gaussian(
        img_flat, valid_mask, sigma_large
    )
    meso_snr = float(np.std(dog[valid_mask]) / sigma_n)

    gx = scharr_h(img_topo)
    gy = scharr_v(img_topo)
    gmag = np.hypot(gx, gy)
    if not valid_mask.all():
        grad_valid = binary_erosion(
            valid_mask, structure=np.ones((3, 3), dtype=bool), border_value=1
        )
        if not grad_valid.any():
            grad_valid = valid_mask
    else:
        grad_valid = valid_mask
    grad_snr = float(np.sqrt(np.mean(gmag[grad_valid] ** 2)) / sigma_n)

    topo_norm = (img_topo - float(np.mean(img_topo[valid_mask]))) / sigma_n
    if not valid_mask.all():
        topo_norm[~valid_mask] = 0.0

    ridges = sato(topo_norm, sigmas=sato_sigmas, black_ridges=False)
    blade_index = float(np.mean(ridges[valid_mask]))

    st_gx = gaussian_filter(topo_norm, sigma=1.0, order=[0, 1], mode="reflect")
    st_gy = gaussian_filter(topo_norm, sigma=1.0, order=[1, 0], mode="reflect")
    jxx = gaussian_filter(st_gx * st_gx, sigma=sigma_st, mode="reflect")
    jxy = gaussian_filter(st_gx * st_gy, sigma=sigma_st, mode="reflect")
    jyy = gaussian_filter(st_gy * st_gy, sigma=sigma_st, mode="reflect")
    coherency = np.sqrt((jxx - jyy) ** 2 + 4.0 * jxy * jxy) / np.maximum(
        jxx + jyy, 1e-12
    )
    anisotropy_coh = float(np.mean(coherency[valid_mask]))

    z_norm = img_flat / max(float(np.std(img_flat[valid_mask])), 1e-12)
    if not valid_mask.all():
        z_norm[~valid_mask] = 0.0
    freq_um_inv, radial_psd_norm, psd_struct_log_snr, psd_beta = _compute_radial_psd(
        z_norm, um_per_px=um_px
    )
    corr_len_um = _compute_corr_length_um(z_norm, valid_mask=valid_mask, um_per_px=um_px)

    loc_trnr_map = (
        _masked_gaussian_local_std(img_topo, valid=valid_mask, sigma_px=loc_sigma_px)
        / sigma_n
    )
    valid_loc = loc_trnr_map[valid_mask]
    loc_trnr_median = float(np.median(valid_loc))
    loc_trnr_p90 = float(np.percentile(valid_loc, 90.0))
    thresh = float(bloom_cov_threshold) if bloom_cov_threshold is not None else 6.0
    bloom_coverage_pct = float(np.mean(valid_loc > thresh) * 100.0)

    if record is not None and record.hv_mismatch:
        qc_status = "HV_Mismatch"
    elif (
        qc["valid_area_pct"] < 50.0
        or qc["saturated_pct"] > 5.0
        or qc["dark_clip_pct"] > 10.0
        or calibration.source == "uncalibrated"
        or mask_stats.get("warning") is not None
    ):
        qc_status = "Review"
    else:
        qc_status = "OK"

    metrics = RoughnessMetrics(
        image_id=record.image_id if record is not None else "image",
        treatment=record.treatment if record is not None else "unknown",
        week=record.week if record is not None else 0,
        scale_label=record.scale_label if record is not None else "unknown",
        replicate=record.replicate if record is not None else 1,
        hv_kv=record.hv_kv if record is not None else None,
        hv_mismatch=record.hv_mismatch if record is not None else False,
        noise_sigma=sigma_n,
        saturated_pct=qc["saturated_pct"],
        dark_clip_pct=qc["dark_clip_pct"],
        artifact_masked_pct=float(mask_stats["total_masked_pct"]),
        valid_area_pct=qc["valid_area_pct"],
        qc_status=qc_status,
        trnr_relief=trnr_relief,
        loc_trnr_median=loc_trnr_median,
        loc_trnr_p90=loc_trnr_p90,
        meso_snr=meso_snr,
        grad_snr=grad_snr,
        blade_index=blade_index,
        anisotropy_coh=anisotropy_coh,
        psd_struct_log_snr=psd_struct_log_snr,
        psd_beta=psd_beta,
        corr_len_um=corr_len_um,
        bloom_coverage_pct=bloom_coverage_pct,
    )

    if return_maps:
        maps = {
            "loc_trnr_map": loc_trnr_map,
            "valid_mask": valid_mask,
            "freq_um_inv": freq_um_inv,
            "radial_psd": radial_psd_norm,
            "ridges_map": ridges,
        }
        return metrics, maps
    return metrics, None


def calibrate_control_threshold(
    control_records: list[SEMImageRecord],
    config: AnalysisConfig,
    artifact_masks: Optional[dict[str, ArtifactMask]] = None,
) -> float:
    """Calibrate the Pseudo-AFM local roughness threshold (p95) from Week 0 controls."""
    if not control_records:
        return 6.0

    valid_vals: list[np.ndarray] = []
    for rec in control_records:
        img_raw, cal = load_sem_image(rec.filepath, rec.calibration)
        art_mask = artifact_masks.get(rec.image_id) if artifact_masks else None
        _, maps = compute_image_roughness(
            img_raw,
            cal,
            record=rec,
            config=config,
            artifact_mask=art_mask,
            return_maps=True,
        )
        if maps is not None:
            vm = maps["valid_mask"]
            loc_map = maps["loc_trnr_map"]
            if vm.any():
                valid_vals.append(loc_map[vm])

    if not valid_vals:
        return 6.0
    combined = np.concatenate(valid_vals)
    return float(np.percentile(combined, 95.0))


def _score_metric_group(
    metrics_list: list[RoughnessMetrics],
    base_records: list[RoughnessMetrics],
    pool_records: list[RoughnessMetrics],
    metric_names: list[str],
) -> list[float]:
    per_metric_scores: dict[str, list[float]] = {}
    for name in metric_names:
        base_vals = [
            float(getattr(m, name))
            for m in base_records
            if np.isfinite(getattr(m, name))
        ]
        pool_vals = [
            float(getattr(m, name))
            for m in pool_records
            if np.isfinite(getattr(m, name))
        ]
        if not base_vals or not pool_vals:
            continue
        m0 = float(np.mean(base_vals))
        m_hi = float(np.percentile(pool_vals, 95.0))
        denom = max(m_hi - m0, 1e-9)
        per_metric_scores[name] = [
            max((float(getattr(m, name)) - m0) / denom * 100.0, -20.0)
            for m in metrics_list
        ]

    if not per_metric_scores:
        return [0.0 for _ in metrics_list]

    keys = list(per_metric_scores.keys())
    return [
        float(np.mean([per_metric_scores[k][idx] for k in keys]))
        for idx in range(len(metrics_list))
    ]


def compute_composite_bloom_index(
    metrics_list: list[RoughnessMetrics],
) -> list[RoughnessMetrics]:
    """Populate ``cbi_score`` and ``geom_bloom_index`` anchored to Week 0 control (= 0)."""
    if not metrics_list:
        return []

    week0_normal = [m for m in metrics_list if m.week == 0 and not m.hv_mismatch]
    if week0_normal:
        base_records = week0_normal
    else:
        min_wk = min(m.week for m in metrics_list)
        base_records = [m for m in metrics_list if m.week == min_wk]

    normal_pool = [m for m in metrics_list if not m.hv_mismatch]
    pool_records = normal_pool if len(normal_pool) >= 5 else metrics_list

    cbi_scores = _score_metric_group(
        metrics_list, base_records, pool_records, CORE_CBI_METRICS
    )
    geom_scores = _score_metric_group(
        metrics_list, base_records, pool_records, GEOM_CBI_METRICS
    )

    for rec, cbi, geom in zip(metrics_list, cbi_scores, geom_scores):
        rec.cbi_score = cbi
        rec.geom_bloom_index = geom
    return metrics_list


def _invoke_progress(
    progress_callback: Optional[Callable[..., None]],
    done: int,
    total: int,
    rec: SEMImageRecord,
) -> None:
    if progress_callback is None:
        return
    try:
        n_params = len(inspect.signature(progress_callback).parameters)
    except (TypeError, ValueError):
        n_params = 2
    if n_params >= 3:
        progress_callback(done, total, rec)
    else:
        progress_callback(done, total)


def analyze_dataset_scale(
    records: list[SEMImageRecord],
    scale_label: str,
    config: Optional[AnalysisConfig] = None,
    artifact_masks: Optional[dict[str, ArtifactMask]] = None,
    progress_callback: Optional[Callable[..., None]] = None,
    max_workers: Optional[int] = None,
) -> tuple[pd.DataFrame, list[RoughnessMetrics], dict[str, object]]:
    """Run full brightness/contrast-invariant analysis across one magnification scale."""
    cfg = config or AnalysisConfig(active_scale=scale_label)
    active = [
        rec
        for rec in records
        if rec.scale_label == scale_label and not rec.excluded
    ]

    ctrl_normal = [rec for rec in active if rec.week == 0 and not rec.hv_mismatch]
    control_records = ctrl_normal or [rec for rec in active if rec.week == 0]
    bloom_cov_threshold = calibrate_control_threshold(
        control_records, cfg, artifact_masks=artifact_masks
    )

    total = len(active)
    workers = max_workers if max_workers is not None else min(4, os.cpu_count() or 1)

    def _compute_one(rec: SEMImageRecord) -> RoughnessMetrics:
        img_raw, cal = load_sem_image(rec.filepath, rec.calibration)
        art_mask = artifact_masks.get(rec.image_id) if artifact_masks else None
        m, _ = compute_image_roughness(
            img_raw,
            cal,
            record=rec,
            config=cfg,
            artifact_mask=art_mask,
            bloom_cov_threshold=bloom_cov_threshold,
            return_maps=False,
        )
        return m

    if workers > 1 and total > 1:
        ordered: list[Optional[RoughnessMetrics]] = [None] * total
        with ThreadPoolExecutor(max_workers=workers) as pool:
            future_map = {
                pool.submit(_compute_one, rec): (idx, rec)
                for idx, rec in enumerate(active)
            }
            done = 0
            for fut in as_completed(future_map):
                idx, rec = future_map[fut]
                ordered[idx] = fut.result()
                done += 1
                _invoke_progress(progress_callback, done, total, rec)
        metrics_list = [m for m in ordered if m is not None]
    else:
        metrics_list = []
        for idx, rec in enumerate(active, start=1):
            metrics_list.append(_compute_one(rec))
            _invoke_progress(progress_callback, idx, total, rec)

    compute_composite_bloom_index(metrics_list)
    metrics_df = pd.DataFrame([asdict(m) for m in metrics_list])

    cal_info: dict[str, object] = {
        "scale_label": scale_label,
        "n_images": len(metrics_list),
        "n_controls": len(control_records),
        "bloom_cov_threshold": bloom_cov_threshold,
    }
    return metrics_df, metrics_list, cal_info


def compute_treatment_week_maps(
    records: list[SEMImageRecord],
    treatment: str,
    scale_label: str,
    replicate: int = 1,
    config: Optional[AnalysisConfig] = None,
    bloom_cov_threshold: Optional[float] = None,
    artifact_masks: Optional[dict[str, ArtifactMask]] = None,
    max_workers: Optional[int] = None,
) -> list[dict[str, Any]]:
    """Compute Pseudo-AFM, Sato ridge, and 2D FFT PSD maps for all weeks of one treatment."""
    cfg = config or AnalysisConfig(active_scale=scale_label)
    series = expand_shared_control_for_treatment(
        records, treatment=treatment, scale_label=scale_label, include_excluded=False
    )
    if not series:
        return []

    by_week: dict[int, list[SEMImageRecord]] = {}
    for rec in series:
        by_week.setdefault(rec.week, []).append(rec)

    selected: list[SEMImageRecord] = []
    for wk in sorted(by_week.keys()):
        wk_recs = sorted(by_week[wk], key=lambda r: (r.replicate, r.filename.lower()))
        match = next((r for r in wk_recs if r.replicate == replicate), wk_recs[0])
        selected.append(match)

    if bloom_cov_threshold is None:
        ctrl_normal = [
            rec
            for rec in records
            if rec.scale_label == scale_label
            and not rec.excluded
            and rec.week == 0
            and not rec.hv_mismatch
        ]
        control_records = ctrl_normal or [
            rec
            for rec in records
            if rec.scale_label == scale_label and not rec.excluded and rec.week == 0
        ]
        bloom_cov_threshold = calibrate_control_threshold(
            control_records, cfg, artifact_masks=artifact_masks
        )

    def _compute_entry(rec: SEMImageRecord) -> dict[str, Any]:
        img_raw, cal = load_sem_image(rec.filepath, rec.calibration)
        art_mask = artifact_masks.get(rec.image_id) if artifact_masks else None
        m, maps = compute_image_roughness(
            img_raw,
            cal,
            record=rec,
            config=cfg,
            artifact_mask=art_mask,
            bloom_cov_threshold=bloom_cov_threshold,
            return_maps=True,
        )
        assert maps is not None
        return {
            "week": rec.week,
            "treatment": rec.treatment,
            "is_shared_control": rec.is_shared_control,
            "replicate": rec.replicate,
            "filename": rec.filename,
            "hv_kv": rec.hv_kv,
            "hv_mismatch": rec.hv_mismatch,
            "calibration": cal,
            "display_img": make_display_image(img_raw),
            "loc_trnr_map": maps["loc_trnr_map"],
            "ridges_map": maps["ridges_map"],
            "freq_um_inv": maps["freq_um_inv"],
            "radial_psd": maps["radial_psd"],
            "metrics": m,
        }

    total = len(selected)
    workers = max_workers if max_workers is not None else min(4, os.cpu_count() or 1)
    if workers > 1 and total > 1:
        ordered: list[Optional[dict[str, Any]]] = [None] * total
        with ThreadPoolExecutor(max_workers=workers) as pool:
            future_map = {
                pool.submit(_compute_entry, rec): idx for idx, rec in enumerate(selected)
            }
            for fut in as_completed(future_map):
                idx = future_map[fut]
                ordered[idx] = fut.result()
        return [item for item in ordered if item is not None]

    return [_compute_entry(rec) for rec in selected]
