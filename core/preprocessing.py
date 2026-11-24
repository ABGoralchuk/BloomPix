"""Vectorized SEM preprocessing, noise estimation, QC, and illumination flattening.

Strictly pure Python / NumPy / SciPy (ZERO ``streamlit`` imports).
"""

from __future__ import annotations

from typing import Optional

import numpy as np
from scipy.ndimage import binary_erosion, convolve, gaussian_filter, zoom

_IMMERKAER_KERNEL = np.array(
    [
        [1.0, -2.0, 1.0],
        [-2.0, 4.0, -2.0],
        [1.0, -2.0, 1.0],
    ],
    dtype=np.float64,
)


def estimate_noise_std(
    img_raw: np.ndarray,
    valid_mask: Optional[np.ndarray] = None,
) -> float:
    """Estimate additive detector noise sigma via Immerkaer (1996) 3x3 Laplacian MAD.

    Scales linearly with multiplicative contrast factor ``a`` under ``I' = a * I + b``
    and is invariant to additive brightness offset ``b``.
    """
    img = np.asarray(img_raw, dtype=np.float64)
    if img.ndim != 2 or img.shape[0] < 3 or img.shape[1] < 3:
        raise ValueError(f"Expected 2D image with shape >= (3, 3), got {img.shape}")

    conv = convolve(img, _IMMERKAER_KERNEL, mode="reflect")

    inner = np.zeros(img.shape, dtype=bool)
    inner[1:-1, 1:-1] = True

    if valid_mask is not None:
        vm = np.asarray(valid_mask, dtype=bool)
        if vm.shape != img.shape:
            raise ValueError(f"valid_mask shape {vm.shape} != image shape {img.shape}")
        eroded = binary_erosion(vm, structure=np.ones((3, 3), dtype=bool), border_value=0)
        sample_mask = inner & eroded
        if not sample_mask.any():
            sample_mask = inner & vm
        if not sample_mask.any():
            sample_mask = inner
    else:
        sample_mask = inner

    mad = float(np.median(np.abs(conv[sample_mask])))
    sigma_n = (mad / 0.6745) / 6.0
    return max(sigma_n, 1e-9)


def compute_image_qc(
    img_raw: np.ndarray,
    bit_depth: int = 16,
    valid_mask: Optional[np.ndarray] = None,
) -> dict[str, float]:
    """Compute image quality diagnostics over the valid (unmasked) micrograph area."""
    img = np.asarray(img_raw, dtype=np.float64)
    if valid_mask is not None:
        vm = np.asarray(valid_mask, dtype=bool)
        if vm.shape != img.shape:
            raise ValueError(f"valid_mask shape {vm.shape} != image shape {img.shape}")
        valid_area_pct = float(vm.mean() * 100.0)
        vals = img[vm] if vm.any() else img.ravel()
    else:
        valid_area_pct = 100.0
        vals = img.ravel()

    sat_thresh = 65500.0 if bit_depth >= 16 else 254.0
    dark_thresh = 5.0 if bit_depth >= 16 else 1.0

    saturated_pct = float(np.mean(vals >= sat_thresh) * 100.0)
    dark_clip_pct = float(np.mean(vals <= dark_thresh) * 100.0)
    p1, p99 = np.percentile(vals, [1.0, 99.0])
    dynamic_range_p99_p1 = float(p99 - p1)
    noise_sigma = estimate_noise_std(img, valid_mask=valid_mask)

    return {
        "noise_sigma": noise_sigma,
        "saturated_pct": saturated_pct,
        "dark_clip_pct": dark_clip_pct,
        "dynamic_range_p99_p1": dynamic_range_p99_p1,
        "valid_area_pct": valid_area_pct,
    }


def flatten_illumination(
    img_raw: np.ndarray,
    bg_sigma_frac: float = 0.12,
    valid_mask: Optional[np.ndarray] = None,
) -> np.ndarray:
    """Remove macro illumination shading/tilt via mask-aware Gaussian background subtraction."""
    img = np.asarray(img_raw, dtype=np.float64)
    height, width = img.shape
    sigma = max(float(max(height, width)) * float(bg_sigma_frac), 1.0)

    work = img
    if valid_mask is not None:
        vm = np.asarray(valid_mask, dtype=bool)
        if vm.shape != img.shape:
            raise ValueError(f"valid_mask shape {vm.shape} != image shape {img.shape}")
        if not vm.all() and vm.any():
            work = img.copy()
            work[~vm] = float(np.median(img[vm]))

    # Downsampled 4x background estimation preserves exact linearity in (a*I + b)
    # while eliminating slow large-kernel convolution on 1k-4k SEM micrographs.
    if sigma >= 20.0 and min(height, width) >= 128:
        ds = zoom(work, 0.25, order=1, mode="reflect")
        ds_bg = gaussian_filter(ds, sigma=sigma * 0.25, mode="reflect")
        bg = zoom(
            ds_bg,
            (height / ds_bg.shape[0], width / ds_bg.shape[1]),
            order=1,
            mode="reflect",
        )
        if bg.shape != img.shape:
            bg = bg[:height, :width]
    else:
        bg = gaussian_filter(work, sigma=sigma, mode="reflect")

    return img - bg


def make_display_image(
    img_raw: np.ndarray,
    p_low: float = 1.0,
    p_high: float = 99.0,
) -> np.ndarray:
    """Create a ``[0, 1]`` float32 contrast-stretched copy strictly for UI display/QA overlays."""
    img = np.asarray(img_raw, dtype=np.float64)
    lo, hi = np.percentile(img, [p_low, p_high])
    if not np.isfinite(lo) or not np.isfinite(hi) or hi <= lo:
        return np.zeros(img.shape, dtype=np.float32)
    stretched = np.clip((img - lo) / (hi - lo), 0.0, 1.0)
    return stretched.astype(np.float32)
