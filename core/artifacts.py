"""Physical-unit ROI exclusion masks and conservative SEM surface artifact detection.

Strictly pure Python / NumPy / SciPy (ZERO ``streamlit`` imports).
"""

from __future__ import annotations

import math
from typing import Optional

import numpy as np
from scipy.ndimage import (
    binary_closing,
    binary_dilation,
    find_objects,
    label,
)

from core.models import ArtifactMask, Calibration
from core.preprocessing import flatten_illumination


def detect_surface_artifacts(
    img_raw: np.ndarray,
    um_per_px: float,
    bit_depth: int = 16,
) -> np.ndarray:
    """Conservatively detect saturated charging blobs and large isolated molding craters.

    Returns a boolean mask where ``True`` indicates pixels to exclude. Dense crystal
    bloom shadow networks are explicitly preserved.
    """
    img = np.asarray(img_raw, dtype=np.float64)
    height, width = img.shape

    sat_thresh = 65500.0 if bit_depth >= 16 else 254.0
    sat_mask = img >= sat_thresh
    if sat_mask.any():
        sat_mask = binary_dilation(sat_mask, iterations=2)

    img_flat = flatten_illumination(img, bg_sigma_frac=0.12)
    med = float(np.median(img_flat))
    mad_sigma = max(float(np.median(np.abs(img_flat - med))) * 1.4826, 1e-9)
    dark_cand = img_flat < (med - 4.0 * mad_sigma)

    eff_um = um_per_px if um_per_px > 0.0 else 0.108
    min_area_um2 = 15.0 if eff_um < 0.25 else 60.0
    min_area_px = max(100, int(round(min_area_um2 / (eff_um * eff_um))))

    crater_mask = np.zeros((height, width), dtype=bool)
    if int(dark_cand.sum()) >= min_area_px:
        labeled, n_comp = label(dark_cand)
        if n_comp > 0:
            counts = np.bincount(labeled.ravel())
            large_ids = np.where(counts[1:] >= min_area_px)[0] + 1
            if large_ids.size > 0:
                slices = find_objects(labeled)
                pad = 15
                for comp_id in large_ids:
                    comp_slice = slices[int(comp_id) - 1]
                    if comp_slice is None:
                        continue
                    sl_y, sl_x = comp_slice
                    bh = sl_y.stop - sl_y.start
                    bw = sl_x.stop - sl_x.start
                    area = int(counts[int(comp_id)])
                    solidity_proxy = area / max(bh * bw, 1)
                    if solidity_proxy < 0.30:
                        continue

                    y0 = max(0, sl_y.start - pad)
                    y1 = min(height, sl_y.stop + pad)
                    x0 = max(0, sl_x.start - pad)
                    x1 = min(width, sl_x.stop + pad)

                    local_comp = labeled[y0:y1, x0:x1] == int(comp_id)
                    local_dark = dark_cand[y0:y1, x0:x1]
                    dilated = binary_dilation(local_comp, iterations=pad)
                    annulus = dilated & (~local_comp)
                    annulus_density = (
                        float(local_dark[annulus].mean()) if annulus.any() else 0.0
                    )
                    if annulus_density < 0.15:
                        crater_mask[y0:y1, x0:x1] |= local_comp

        if crater_mask.any():
            crater_mask = binary_closing(crater_mask, iterations=1)
            crater_mask = binary_dilation(crater_mask, iterations=1)

    return sat_mask | crater_mask


def build_valid_mask(
    shape: tuple[int, int],
    calibration: Calibration,
    artifact_mask: Optional[ArtifactMask] = None,
    img_raw: Optional[np.ndarray] = None,
    bit_depth: int = 16,
) -> tuple[np.ndarray, dict[str, object]]:
    """Build a boolean ``valid_mask`` (``True`` = valid) combining manual ROIs and auto-masking."""
    height, width = shape
    manual_excl = np.zeros((height, width), dtype=bool)
    auto_excl = np.zeros((height, width), dtype=bool)

    if artifact_mask is not None and artifact_mask.exclude_rects_um:
        um_px = calibration.um_per_px if calibration.um_per_px > 0.0 else 1.0
        for x0_um, y0_um, x1_um, y1_um in artifact_mask.exclude_rects_um:
            xa, xb = (x0_um, x1_um) if x0_um <= x1_um else (x1_um, x0_um)
            ya, yb = (y0_um, y1_um) if y0_um <= y1_um else (y1_um, y0_um)
            c0 = max(0, min(width, int(math.floor(xa / um_px))))
            c1 = max(0, min(width, int(math.ceil(xb / um_px))))
            r0 = max(0, min(height, int(math.floor(ya / um_px))))
            r1 = max(0, min(height, int(math.ceil(yb / um_px))))
            if r1 > r0 and c1 > c0:
                manual_excl[r0:r1, c0:c1] = True

    if (
        artifact_mask is not None
        and artifact_mask.auto_mask_pores
        and img_raw is not None
    ):
        auto_excl = detect_surface_artifacts(
            img_raw,
            um_per_px=calibration.um_per_px,
            bit_depth=bit_depth,
        )

    total_excl = manual_excl | auto_excl
    warning: Optional[str] = None

    if 1.0 - float(total_excl.mean()) < 0.20:
        if 1.0 - float(manual_excl.mean()) >= 0.20:
            auto_excl = np.zeros((height, width), dtype=bool)
            total_excl = manual_excl.copy()
            warning = (
                "Auto artifact mask exceeded 80% of area and was disabled to preserve >=20% valid surface."
            )
        else:
            manual_excl = np.zeros((height, width), dtype=bool)
            auto_excl = np.zeros((height, width), dtype=bool)
            total_excl = np.zeros((height, width), dtype=bool)
            warning = (
                "Combined artifact mask exceeded 80% of area and was reset to preserve >=20% valid surface."
            )

    valid_mask = ~total_excl
    stats: dict[str, object] = {
        "manual_masked_pct": float(manual_excl.mean() * 100.0),
        "auto_masked_pct": float(auto_excl.mean() * 100.0),
        "total_masked_pct": float(total_excl.mean() * 100.0),
        "warning": warning,
    }
    return valid_mask, stats
