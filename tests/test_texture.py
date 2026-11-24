"""Unit tests for preprocessing, artifact masking, invariance, and roughness metrics."""

from __future__ import annotations

import ast
from pathlib import Path

import numpy as np
import pytest
from scipy.ndimage import gaussian_filter

from core.artifacts import build_valid_mask, detect_surface_artifacts
from core.models import AnalysisConfig, ArtifactMask, Calibration
from core.preprocessing import estimate_noise_std, flatten_illumination, make_display_image
from core.texture import compute_composite_bloom_index, compute_image_roughness


def _make_calibration(um_per_px: float = 0.107917, width: int = 768, height: int = 512) -> Calibration:
    return Calibration(
        um_per_px=um_per_px,
        hfw_um=um_per_px * width,
        res_x=width,
        res_y=height,
        databar_height_px=0,
        source="fei_tag_34682",
    )


def _synthetic_bloom_surface(
    height: int = 512,
    width: int = 768,
    seed: int = 123,
    with_crystals: bool = True,
    noise_std: float = 120.0,
) -> np.ndarray:
    """Generate a synthetic 16-bit-like SEM chocolate surface with optional needle blades."""
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:height, 0:width].astype(np.float64)

    # Gentle macro illumination gradient + detector noise
    macro = 20000.0 + 1800.0 * (xx / width - 0.5) - 1400.0 * (yy / height - 0.5)
    noise = rng.normal(0.0, noise_std, size=(height, width))
    img = macro + noise

    if with_crystals:
        # Mesoscale crystal clusters
        clusters = gaussian_filter(rng.normal(0.0, 1.0, size=(height, width)), sigma=10.0)
        img += clusters * 6000.0

        # Protruding anisotropic crystal blades / needles
        blades = np.zeros((height, width), dtype=np.float64)
        for _ in range(90):
            cy = rng.uniform(30, height - 30)
            cx = rng.uniform(30, width - 30)
            theta = rng.normal(0.45, 0.22)
            length = rng.uniform(22.0, 48.0)
            half_w = rng.uniform(1.6, 2.8)
            dy = yy - cy
            dx = xx - cx
            u = dx * np.cos(theta) + dy * np.sin(theta)
            v = -dx * np.sin(theta) + dy * np.cos(theta)
            blade = np.exp(-0.5 * ((u / (0.5 * length)) ** 2 + (v / half_w) ** 2))
            blades += blade * rng.uniform(2200.0, 4200.0)
        img += blades

    return img


def test_zero_streamlit_imports_in_stage2_core() -> None:
    core_dir = Path(__file__).resolve().parent.parent / "core"
    for mod_name in ("preprocessing.py", "artifacts.py", "texture.py"):
        py_file = core_dir / mod_name
        tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert not alias.name.startswith("streamlit")
            elif isinstance(node, ast.ImportFrom):
                assert not (node.module or "").startswith("streamlit")


def test_linear_brightness_contrast_invariance() -> None:
    img = _synthetic_bloom_surface(height=512, width=768, seed=7, with_crystals=True)
    # Keep strictly inside [1000, 62000] under affine transforms
    img = np.clip(img, 4000.0, 28000.0)
    cal = _make_calibration(um_per_px=0.107917, width=768, height=512)
    cfg = AnalysisConfig()

    base, _ = compute_image_roughness(img, cal, config=cfg, bloom_cov_threshold=4.5)
    t1, _ = compute_image_roughness(1.75 * img + 9000.0, cal, config=cfg, bloom_cov_threshold=4.5)
    t2, _ = compute_image_roughness(0.45 * img + 1500.0, cal, config=cfg, bloom_cov_threshold=4.5)

    assert t1.noise_sigma == pytest.approx(1.75 * base.noise_sigma, rel=1e-6)
    assert t2.noise_sigma == pytest.approx(0.45 * base.noise_sigma, rel=1e-6)

    metric_names = [
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
        "bloom_coverage_pct",
    ]
    for variant in (t1, t2):
        for name in metric_names:
            v0 = getattr(base, name)
            v1 = getattr(variant, name)
            rel_err = abs(v1 - v0) / max(abs(v0), 1e-9)
            assert rel_err < 5e-4, f"{name} violated <0.05% invariance: {v0} vs {v1}"


def test_physical_monotonicity_smooth_vs_bloomed() -> None:
    smooth = _synthetic_bloom_surface(height=512, width=768, seed=11, with_crystals=False)
    bloomed = _synthetic_bloom_surface(height=512, width=768, seed=11, with_crystals=True)
    cal = _make_calibration(um_per_px=0.107917, width=768, height=512)
    cfg = AnalysisConfig()

    m_smooth, _ = compute_image_roughness(smooth, cal, config=cfg)
    m_bloom, _ = compute_image_roughness(bloomed, cal, config=cfg)
    m_smooth.week = 0
    m_bloom.week = 16
    compute_composite_bloom_index([m_smooth, m_bloom])

    for name in (
        "trnr_relief",
        "loc_trnr_median",
        "meso_snr",
        "grad_snr",
        "blade_index",
        "anisotropy_coh",
        "psd_struct_log_snr",
        "cbi_score",
    ):
        assert getattr(m_bloom, name) > getattr(m_smooth, name), (
            f"Expected {name} higher on bloomed ({getattr(m_bloom, name)}) "
            f"than smooth ({getattr(m_smooth, name)})"
        )


def test_artifact_masking_recovery_and_conservative_auto_mask() -> None:
    clean = _synthetic_bloom_surface(height=512, width=768, seed=21, with_crystals=False)
    cal = _make_calibration(um_per_px=0.107917, width=768, height=512)
    cfg = AnalysisConfig()

    m_clean, _ = compute_image_roughness(clean, cal, config=cfg)

    corrupted = clean.copy()
    # Inject deep dark crater and bright charging blob inside [100:180, 120:220] & [300:360, 420:500]
    corrupted[100:180, 120:220] = 0.0
    corrupted[300:360, 420:500] = 65535.0

    m_corrupt, _ = compute_image_roughness(corrupted, cal, config=cfg)
    assert m_corrupt.trnr_relief > m_clean.trnr_relief * 3.0

    um_px = cal.um_per_px
    art = ArtifactMask(
        image_id="corrupted",
        exclude_rects_um=[
            (118 * um_px, 98 * um_px, 222 * um_px, 182 * um_px),
            (418 * um_px, 298 * um_px, 502 * um_px, 362 * um_px),
        ],
        auto_mask_pores=False,
    )
    m_recovered, _ = compute_image_roughness(corrupted, cal, config=cfg, artifact_mask=art)
    assert abs(m_recovered.trnr_relief - m_clean.trnr_relief) / m_clean.trnr_relief < 0.05
    assert abs(m_recovered.loc_trnr_median - m_clean.loc_trnr_median) / m_clean.loc_trnr_median < 0.05

    # Auto detector must catch charging blob + isolated crater on smooth surface
    auto_mask = detect_surface_artifacts(corrupted, um_per_px=um_px, bit_depth=16)
    assert auto_mask[330, 460]
    assert auto_mask[140, 170]

    # Auto detector must NOT falsely mask dense crystal bloom (< 3%)
    dense_bloom = np.clip(
        _synthetic_bloom_surface(height=512, width=768, seed=99, with_crystals=True),
        500.0,
        55000.0,
    )
    bloom_mask = detect_surface_artifacts(dense_bloom, um_per_px=um_px, bit_depth=16)
    assert float(bloom_mask.mean() * 100.0) < 3.0

    # Display helper must produce [0, 1] float32 without modifying input
    disp = make_display_image(corrupted)
    assert disp.dtype == np.float32
    assert float(disp.min()) >= 0.0 and float(disp.max()) <= 1.0


def test_physical_units_scaling_psd_and_corr_len() -> None:
    img = _synthetic_bloom_surface(height=512, width=768, seed=31, with_crystals=True)
    cal_1x = _make_calibration(um_per_px=0.1, width=768, height=512)
    cal_2x = _make_calibration(um_per_px=0.2, width=768, height=512)

    m1, maps1 = compute_image_roughness(img, cal_1x, return_maps=True)
    m2, maps2 = compute_image_roughness(img, cal_2x, return_maps=True)

    assert maps1 is not None and maps2 is not None
    np.testing.assert_allclose(maps2["freq_um_inv"], 0.5 * maps1["freq_um_inv"], rtol=1e-12)
    # Physical filter sizes adapt to um_per_px, while z_norm for corr_len_um is computed
    # directly from flattened raw image -> corr_len_um scales strictly by 2.0x.
    assert m2.corr_len_um == pytest.approx(2.0 * m1.corr_len_um, rel=1e-12)
    assert flatten_illumination(img).shape == img.shape
    vm, stats = build_valid_mask(img.shape, cal_1x)
    assert vm.all() and stats["total_masked_pct"] == 0.0
