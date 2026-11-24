"""Unit tests for core data contracts, study-agnostic SEM I/O, and icon generation."""

from __future__ import annotations

import ast
import math
from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageDraw
from PIL.TiffImagePlugin import ImageFileDirectory_v2

from core.io_loader import (
    detect_databar_height,
    expand_shared_control_for_treatment,
    load_sem_image,
    parse_fei_tiff_metadata,
    parse_filename_metadata,
    save_metadata_overrides,
    scan_dataset,
)
from scripts.build_icons import ICO_SIZES, build_studio_icons


def _write_fei_mock_tiff(
    path: Path,
    hv_v: float = 5000.0,
    pixel_width_m: float = 1.07917e-7,
    hfw_m: float = 0.00016576,
    res_x: int = 1536,
    res_y: int = 1024,
    databar_h: int = 70,
    user_text: str = "Sample",
) -> None:
    """Create a synthetic 16-bit grayscale TIFF with FEI Tag 34682 and bright databar."""
    total_h = res_y + databar_h
    arr = np.zeros((total_h, res_x), dtype=np.uint16)
    gradient = np.linspace(1000, 40000, res_x, dtype=np.uint16)
    arr[:res_y, :] = np.tile(gradient, (res_y, 1))
    arr[res_y:, :] = 65535  # Bright sentinel values in databar that must be cropped out

    ini_text = (
        "[User]\n"
        f"UserText={user_text}\n"
        "[Beam]\n"
        f"HV={hv_v}\n"
        "[EBeam]\n"
        f"HV={hv_v}\n"
        f"HFW={hfw_m}\n"
        "WD=0.0105\n"
        "[Scan]\n"
        f"PixelWidth={pixel_width_m}\n"
        "[EScan]\n"
        f"PixelWidth={pixel_width_m}\n"
        "[Image]\n"
        f"ResolutionX={res_x}\n"
        f"ResolutionY={res_y}\n"
        "[Detectors]\n"
        "Name=ETD\n"
        "[ETD]\n"
        "Contrast=60.5\n"
        "Brightness=44.2\n"
        "Signal=SE\n"
    )
    ifd = ImageFileDirectory_v2()
    ifd[34682] = ini_text
    ifd.tagtype[34682] = 2  # ASCII

    img = Image.fromarray(arr)
    img.save(path, format="TIFF", tiffinfo=ifd)


def test_zero_streamlit_imports_in_core() -> None:
    core_dir = Path(__file__).resolve().parent.parent / "core"
    py_files = sorted(core_dir.glob("*.py"))
    assert len(py_files) >= 3
    for py_file in py_files:
        tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert not alias.name.startswith("streamlit"), (
                        f"Forbidden streamlit import in {py_file.name}"
                    )
            elif isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                assert not mod.startswith("streamlit"), (
                    f"Forbidden streamlit import in {py_file.name}"
                )


def test_fei_16bit_tiff_metadata_and_exact_crop(tmp_path: Path) -> None:
    tif_path = tmp_path / "ANFW1_50um_5.00kV_0001.tif"
    _write_fei_mock_tiff(tif_path, user_text="ANFW1")

    meta = parse_fei_tiff_metadata(tif_path)
    cal = meta["calibration"]

    assert meta["bit_depth"] == 16
    assert meta["hv_kv"] == pytest.approx(5.0)
    assert meta["wd_mm"] == pytest.approx(10.5)
    assert meta["sem_contrast"] == pytest.approx(60.5)
    assert meta["sem_brightness"] == pytest.approx(44.2)
    assert meta["detector"] == "ETD (SE)"
    assert meta["user_text"] == "ANFW1"

    assert cal.source == "fei_tag_34682"
    assert cal.um_per_px == pytest.approx(0.107917, rel=1e-6)
    assert cal.hfw_um == pytest.approx(165.76, rel=1e-6)
    assert cal.res_x == 1536
    assert cal.res_y == 1024
    assert cal.databar_height_px == 70
    assert cal.u_raster_um == pytest.approx(0.107917 / math.sqrt(12.0), rel=1e-6)

    arr, loaded_cal = load_sem_image(tif_path)
    assert loaded_cal == cal
    assert arr.shape == (1024, 1536)
    assert arr.dtype == np.float64
    assert float(arr.max()) <= 40000.0


def test_universal_fallback_databar_detection_and_blank_guard(tmp_path: Path) -> None:
    rng = np.random.default_rng(42)
    body = rng.normal(loc=140.0, scale=22.0, size=(340, 512)).clip(20, 255).astype(np.uint8)
    sep = np.full((1, 512), 255, dtype=np.uint8)
    banner = np.zeros((59, 512), dtype=np.uint8)
    banner[15:30, 40:200] = 240  # Mock scale bar text inside dark banner
    combined = np.vstack([body, sep, banner])

    png_path = tmp_path / "JEOL_50um_5.0kV.png"
    Image.fromarray(combined).save(png_path)

    meta = parse_fei_tiff_metadata(png_path)
    cal = meta["calibration"]
    assert cal.source == "uncalibrated"
    assert cal.databar_height_px == 60
    assert cal.res_x == 512
    assert cal.res_y == 340
    assert meta["hv_kv"] == pytest.approx(5.0)

    arr, _ = load_sem_image(png_path)
    assert arr.shape == (340, 512)

    # Blank uniform frame and pure textured frame without databar must return 0.
    assert detect_databar_height(np.full((400, 512), 120.0)) == 0
    pure_tex = rng.normal(loc=130.0, scale=20.0, size=(400, 512))
    assert detect_databar_height(pure_tex) == 0


def test_study_agnostic_filename_and_folder_parsing() -> None:
    c1 = parse_filename_metadata("control_50um_5.00kV_4545.tiff", "control")
    assert c1["treatment"] == "control"
    assert c1["week"] == 0
    assert c1["is_control"] is True
    assert c1["is_shared_control"] is True
    assert c1["scale_label"] == "50um"
    assert c1["filename_hv_kv"] == pytest.approx(5.0)

    c2 = parse_filename_metadata("ANFW0_50um_5.00kV_0001.tif", "control")
    assert c2["treatment"] == "ANF"
    assert c2["week"] == 0
    assert c2["is_control"] is True
    assert c2["is_shared_control"] is False

    p1 = parse_filename_metadata("DarkChocW4_50um_5.00kV_001.tif", "4")
    assert p1["treatment"] == "DarkChoc"
    assert p1["week"] == 4
    assert p1["is_control"] is False
    assert p1["scale_label"] == "50um"

    p2 = parse_filename_metadata("MilkChoc_200um_5.00kV_002.tiff", "3")
    assert p2["treatment"] == "MilkChoc"
    assert p2["week"] == 3
    assert p2["scale_label"] == "200um"

    p3 = parse_filename_metadata("CNFW26Br4_50um_5.00kV_7745.tif", "26")
    assert p3["treatment"] == "CNF"
    assert p3["week"] == 26
    assert p3["scale_label"] == "50um"

    p4 = parse_filename_metadata("AWFW2_50um__5.00kV_6454.tif", "2")
    assert p4["treatment"] == "AWF"
    assert p4["week"] == 2
    assert p4["scale_label"] == "50um"


def test_scan_dataset_hv_mismatch_hidden_files_and_shared_control(tmp_path: Path) -> None:
    (tmp_path / "control").mkdir()
    (tmp_path / "1").mkdir()
    (tmp_path / "5").mkdir()

    # Shared control + per-treatment Week 0 for MilkChoc only
    _write_fei_mock_tiff(tmp_path / "control" / "control_50um_5.00kV_0001.tiff", hv_v=5000.0)
    _write_fei_mock_tiff(tmp_path / "control" / "MilkChocW0_50um_5.00kV_0002.tif", hv_v=5000.0)
    # Hidden macOS resource fork file that must be ignored
    _write_fei_mock_tiff(tmp_path / "control" / "._control_50um_5.00kV_0001.tiff", hv_v=5000.0)

    # Week 1 at 5 kV
    _write_fei_mock_tiff(tmp_path / "1" / "DarkChocW1_50um_5.00kV_0010.tif", hv_v=5000.0)
    _write_fei_mock_tiff(tmp_path / "1" / "DarkChocW1_50um_5.00kV_0011.tif", hv_v=5000.0)
    _write_fei_mock_tiff(tmp_path / "1" / "MilkChocW1_50um_5.00kV_0012.tif", hv_v=5000.0)

    # Week 5 HV mismatch outliers at 10 kV
    _write_fei_mock_tiff(tmp_path / "5" / "DarkChocW5_50um_10.00kV_0020.tif", hv_v=10000.0)
    _write_fei_mock_tiff(tmp_path / "5" / "MilkChocW5_50um_10.00kV_0021.tif", hv_v=10000.0)

    summary = scan_dataset(tmp_path)
    assert len(summary.records) == 7
    assert summary.treatments == ["DarkChoc", "MilkChoc"]
    assert summary.weeks == [0, 1, 5]
    assert summary.scales == ["50um"]
    assert summary.dominant_hv_kv == pytest.approx(5.0)
    assert summary.has_shared_control is True

    mismatched = [r for r in summary.records if r.hv_mismatch]
    assert len(mismatched) == 2
    assert all("HV_Mismatch" in r.qc_flags for r in mismatched)
    assert all(r.week == 5 for r in mismatched)

    # DarkChoc should inherit shared control at Week 0
    dark_series = expand_shared_control_for_treatment(summary.records, "DarkChoc", "50um")
    assert [r.week for r in dark_series] == [0, 1, 1, 5]
    assert dark_series[0].is_shared_control is True

    # MilkChoc has its own Week 0, so shared control must NOT be duplicated
    milk_series = expand_shared_control_for_treatment(summary.records, "MilkChoc", "50um")
    assert [r.week for r in milk_series] == [0, 1, 5]
    assert milk_series[0].is_shared_control is False


def test_metadata_override_csv_roundtrip(tmp_path: Path) -> None:
    (tmp_path / "1").mkdir()
    _write_fei_mock_tiff(tmp_path / "1" / "SampleAW1_50um_5.00kV_0001.tif")
    _write_fei_mock_tiff(tmp_path / "1" / "SampleBW1_50um_5.00kV_0002.tif")

    summary = scan_dataset(tmp_path)
    rec0 = summary.records[0]
    rec0.treatment = "RenamedTrt"
    rec0.week = 2
    rec0.excluded = True
    rec0.calibration.um_per_px = 0.25

    csv_path = tmp_path / "metadata_override.csv"
    save_metadata_overrides(summary.records, csv_path)

    reloaded = scan_dataset(tmp_path, override_csv=csv_path)
    by_id = {r.image_id: r for r in reloaded.records}
    updated = by_id[rec0.image_id]
    assert updated.treatment == "RenamedTrt"
    assert updated.week == 2
    assert updated.excluded is True
    assert updated.calibration.source == "manual"
    assert updated.calibration.um_per_px == pytest.approx(0.25)
    assert updated.calibration.hfw_um == pytest.approx(0.25 * 1536)


def test_build_studio_icons_from_opaque_jpeg(tmp_path: Path) -> None:
    src = Image.new("RGB", (600, 600), (16, 18, 22))
    draw = ImageDraw.Draw(src)
    draw.rounded_rectangle([60, 60, 540, 540], radius=90, fill=(140, 95, 70))
    jpeg_path = tmp_path / "logo.jpeg"
    src.save(jpeg_path, format="JPEG", quality=95)

    out_png = tmp_path / "bloompix.png"
    out_ico = tmp_path / "bloompix.ico"
    build_studio_icons(jpeg_path, out_png=out_png, out_ico=out_ico)

    assert out_png.exists() and out_png.stat().st_size > 0
    assert out_ico.exists() and out_ico.stat().st_size > 0

    with Image.open(out_png) as png_img:
        assert png_img.size == (512, 512)
        assert png_img.mode == "RGBA"
        arr = np.asarray(png_img)
        assert arr[0, 0, 3] == 0
        assert arr[0, -1, 3] == 0
        assert arr[-1, 0, 3] == 0
        assert arr[-1, -1, 3] == 0
        assert arr[256, 256, 3] == 255

    with Image.open(out_ico) as ico_img:
        assert set(ICO_SIZES).issubset(ico_img.info.get("sizes", set()))
