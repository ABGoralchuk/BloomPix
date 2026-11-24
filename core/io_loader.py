"""Study-agnostic SEM image loader, FEI Tag 34682 parser, and dataset scanner.

Strictly pure Python (ZERO ``streamlit`` imports).
"""

from __future__ import annotations

import csv
import re
from collections import Counter
from pathlib import Path
from typing import Any, Optional

import numpy as np
from PIL import Image

from core.models import Calibration, DatasetSummary, SEMImageRecord

SUPPORTED_EXTENSIONS: set[str] = {".tif", ".tiff", ".png", ".jpg", ".jpeg"}

_OVERRIDE_FIELDS: list[str] = [
    "image_id",
    "treatment",
    "week",
    "is_control",
    "is_shared_control",
    "scale_label",
    "excluded",
    "um_per_px",
]

_SCALE_RE = re.compile(
    r"(?:^|[_\-\s])(\d+(?:\.\d+)?)\s*(um|µm|μm|nm|mm)(?=[_\-\s.]|$)",
    re.IGNORECASE,
)
_KV_RE = re.compile(
    r"(?:^|[_\-\s])(\d+(?:\.\d+)?)\s*kV(?=[_\-\s.]|$)",
    re.IGNORECASE,
)
_SHARED_CONTROL_RE = re.compile(
    r"^(?:control|ctrl)(?:[\s_-]*\d+)?$",
    re.IGNORECASE,
)
_TREATMENT_WEEK_RE = re.compile(r"^(.+?)[_-]?[Ww](\d+)(?:[^0-9].*)?$")


def detect_databar_height(arr: np.ndarray) -> int:
    """Detect uniform bottom instrument databar height in pixels when metadata is absent.

    Returns ``0`` for uniform blank frames or micrographs without a bottom banner.
    """
    if arr.ndim == 3:
        arr = (
            0.299 * arr[:, :, 0].astype(np.float64)
            + 0.587 * arr[:, :, 1].astype(np.float64)
            + 0.114 * arr[:, :, 2].astype(np.float64)
        )
    else:
        arr = np.asarray(arr, dtype=np.float64)

    height, width = arr.shape
    if height < 128 or width < 32:
        return 0

    body_end = int(0.75 * height)
    body = arr[:body_end, :]
    body_std = float(body.std())
    if body_std < 1e-6:
        return 0

    body_mean = float(body.mean())
    body_median = float(np.median(body))
    body_range = float(body.max() - body.min())
    row_std = arr.std(axis=1)
    row_mean = arr.mean(axis=1)

    min_banner = 20
    max_banner = height - body_end

    # Pass 1: look for a crisp horizontal separator line above a distinct bottom banner.
    sep_thresh = max(1e-6, 0.005 * body_std)
    for row_idx in range(body_end, height - min_banner + 1):
        if row_std[row_idx] <= sep_thresh:
            banner = arr[row_idx + 1 :, :] if row_idx + 1 < height else arr[row_idx:, :]
            banner_med = float(np.median(banner))
            banner_mean = float(banner.mean())
            if (
                abs(banner_med - body_median) > 0.35 * body_std
                or abs(banner_mean - body_mean) > 0.35 * body_std
            ):
                return height - row_idx

    # Pass 2: contiguous near-uniform dark/constant bottom banner without a separator line.
    uniform_thresh = max(1e-6, 0.02 * body_std)
    dark_thresh = float(arr.min()) + 0.05 * max(body_range, 1.0)
    banner_rows = 0
    for row_idx in range(height - 1, body_end - 1, -1):
        row = arr[row_idx, :]
        is_uniform = row_std[row_idx] <= uniform_thresh
        is_mostly_dark = (
            float(np.percentile(row, 80)) <= dark_thresh
            and row_mean[row_idx] < body_mean - 0.5 * body_std
        )
        if is_uniform or is_mostly_dark:
            banner_rows += 1
        else:
            break

    if min_banner <= banner_rows <= max_banner:
        return banner_rows
    return 0


def _parse_ini_sections(raw_text: str) -> dict[str, dict[str, str]]:
    """Parse FEI Tag 34682 INI metadata text into ``{section: {key: value}}``."""
    sections: dict[str, dict[str, str]] = {}
    current = ""
    for line in raw_text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("[") and stripped.endswith("]"):
            current = stripped[1:-1].strip()
            sections.setdefault(current, {})
            continue
        if "=" in stripped:
            key, val = stripped.split("=", 1)
            sections.setdefault(current, {})[key.strip()] = val.strip()
    return sections


def _get_sec_str(
    sections: dict[str, dict[str, str]],
    sec_names: list[str],
    key: str,
) -> Optional[str]:
    key_low = key.lower()
    for sec in sec_names:
        mapping = sections.get(sec)
        if not mapping:
            continue
        if key in mapping and mapping[key] != "":
            return mapping[key]
        for k, v in mapping.items():
            if k.lower() == key_low and v != "":
                return v
    return None


def _get_sec_float(
    sections: dict[str, dict[str, str]],
    sec_names: list[str],
    key: str,
) -> Optional[float]:
    raw = _get_sec_str(sections, sec_names, key)
    if raw is None:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _get_sec_int(
    sections: dict[str, dict[str, str]],
    sec_names: list[str],
    key: str,
) -> Optional[int]:
    raw = _get_sec_str(sections, sec_names, key)
    if raw is None:
        return None
    try:
        return int(round(float(raw)))
    except ValueError:
        return None


def _bit_depth_from_mode(mode: str) -> int:
    if mode.startswith("I;16"):
        return 16
    if mode in ("I", "F"):
        return 32
    return 8


def _parse_kv_from_name(filename: str) -> Optional[float]:
    m = _KV_RE.search(Path(filename).stem)
    if not m:
        return None
    try:
        return float(m.group(1))
    except ValueError:
        return None


def parse_fei_tiff_metadata(filepath: str | Path) -> dict[str, Any]:
    """Parse Thermo Fisher / FEI TIFF Tag 34682 or fall back to universal detection."""
    path = Path(filepath)
    if not path.exists():
        raise FileNotFoundError(f"SEM image file not found: {path}")

    with Image.open(path) as img:
        img_width, img_height = img.size
        bit_depth = _bit_depth_from_mode(img.mode)
        tag_raw = img.tag_v2.get(34682) if hasattr(img, "tag_v2") else None

        if tag_raw is not None:
            if isinstance(tag_raw, bytes):
                raw_text = tag_raw.decode("utf-8", errors="replace")
            else:
                raw_text = str(tag_raw)
            sections = _parse_ini_sections(raw_text)

            pixel_width_m = _get_sec_float(sections, ["EScan", "Scan"], "PixelWidth")
            um_per_px = (
                pixel_width_m * 1e6
                if pixel_width_m is not None and pixel_width_m > 0.0
                else 0.0
            )
            res_x = _get_sec_int(sections, ["Image"], "ResolutionX") or img_width
            res_y = _get_sec_int(sections, ["Image"], "ResolutionY") or img_height
            if not (0 < res_x <= img_width):
                res_x = img_width
            if not (0 < res_y <= img_height):
                res_y = img_height

            databar_height_px = img_height - res_y if 0 < res_y < img_height else 0
            hfw_m = _get_sec_float(sections, ["EBeam"], "HFW")
            if hfw_m is not None and hfw_m > 0.0:
                hfw_um = hfw_m * 1e6
            elif um_per_px > 0.0:
                hfw_um = um_per_px * res_x
            else:
                hfw_um = 0.0

            hv_v = _get_sec_float(sections, ["EBeam", "Beam"], "HV")
            hv_kv = (hv_v / 1000.0) if hv_v is not None else _parse_kv_from_name(path.name)
            wd_m = _get_sec_float(sections, ["EBeam"], "WD")
            wd_mm = (wd_m * 1000.0) if wd_m is not None else None

            det_name = _get_sec_str(sections, ["Detectors"], "Name") or ""
            det_sec_candidates = [det_name, "ETD"] if det_name else ["ETD"]
            sem_contrast = _get_sec_float(sections, det_sec_candidates, "Contrast")
            sem_brightness = _get_sec_float(sections, det_sec_candidates, "Brightness")
            det_signal = _get_sec_str(sections, det_sec_candidates, "Signal") or ""
            detector = (
                f"{det_name} ({det_signal})" if det_name and det_signal else det_name
            )
            user_text = _get_sec_str(sections, ["User"], "UserText") or ""
            source = "fei_tag_34682" if um_per_px > 0.0 else "uncalibrated"
        else:
            sections = {}
            preview = _image_to_float64(img)
            databar_height_px = detect_databar_height(preview)
            res_x = img_width
            res_y = img_height - databar_height_px
            um_per_px = 0.0
            hfw_um = 0.0
            hv_kv = _parse_kv_from_name(path.name)
            wd_mm = None
            sem_contrast = None
            sem_brightness = None
            detector = ""
            user_text = ""
            source = "uncalibrated"

    calibration = Calibration(
        um_per_px=um_per_px,
        hfw_um=hfw_um,
        res_x=res_x,
        res_y=res_y,
        databar_height_px=databar_height_px,
        source=source,
    )
    return {
        "calibration": calibration,
        "bit_depth": bit_depth,
        "img_width": img_width,
        "img_height": img_height,
        "hv_kv": hv_kv,
        "wd_mm": wd_mm,
        "sem_contrast": sem_contrast,
        "sem_brightness": sem_brightness,
        "detector": detector,
        "user_text": user_text,
        "raw_sections": sections,
    }


def _image_to_float64(img: Image.Image) -> np.ndarray:
    """Convert a PIL image to a 2D ``float64`` array preserving native 16-bit depth."""
    if img.mode.startswith("I;16") or img.mode in ("L", "I", "F"):
        arr = np.asarray(img, dtype=np.float64)
        if arr.ndim == 2:
            return arr
    rgb = img.convert("RGB")
    arr_rgb = np.asarray(rgb, dtype=np.float64)
    return (
        0.299 * arr_rgb[:, :, 0]
        + 0.587 * arr_rgb[:, :, 1]
        + 0.114 * arr_rgb[:, :, 2]
    )


def load_sem_image(
    filepath: str | Path,
    calibration: Optional[Calibration] = None,
) -> tuple[np.ndarray, Calibration]:
    """Load a raw SEM micrograph as ``float64`` and strictly crop out the databar."""
    path = Path(filepath)
    if not path.exists():
        raise FileNotFoundError(f"SEM image file not found: {path}")

    if calibration is None:
        meta = parse_fei_tiff_metadata(path)
        calibration = meta["calibration"]

    with Image.open(path) as img:
        arr = _image_to_float64(img)

    height, width = arr.shape
    if not (0 < calibration.res_y <= height and 0 < calibration.res_x <= width):
        raise ValueError(
            f"Invalid crop dimensions ({calibration.res_y}, {calibration.res_x}) "
            f"for image shape ({height}, {width}) in {path.name}"
        )

    cropped = np.ascontiguousarray(arr[: calibration.res_y, : calibration.res_x], dtype=np.float64)
    return cropped, calibration


def _parse_folder_week(folder_name: str) -> tuple[Optional[int], bool]:
    clean = folder_name.strip()
    low = clean.lower()
    if low in ("control", "ctrl"):
        return 0, True
    m_digits = re.fullmatch(r"(?:week[_\-\s]*)?(\d+)", low)
    if m_digits:
        wk = int(m_digits.group(1))
        return wk, (wk == 0)
    m_w = re.fullmatch(r"w[_\-]?(\d+)", low)
    if m_w:
        wk = int(m_w.group(1))
        return wk, (wk == 0)
    return None, False


def _normalize_scale_label(num_str: str, unit: str) -> str:
    u = unit.lower().replace("µ", "u").replace("μ", "u")
    return f"{num_str}{u}"


def parse_filename_metadata(filename: str, folder_name: str) -> dict[str, Any]:
    """Parse treatment, week, control status, nominal scale, and kV study-agnostically."""
    stem = Path(filename).stem
    folder_week, folder_is_control = _parse_folder_week(folder_name)

    scale_match = _SCALE_RE.search(stem)
    if scale_match:
        scale_label = _normalize_scale_label(scale_match.group(1), scale_match.group(2))
        prefix = stem[: scale_match.start()].strip("_- ")
    else:
        scale_label = "unknown"
        prefix = stem.split("_")[0].strip("_- ")

    filename_hv_kv = _parse_kv_from_name(filename)

    filename_week: Optional[int] = None
    is_shared_control = False

    if _SHARED_CONTROL_RE.fullmatch(prefix):
        treatment = "control"
        is_shared_control = True
    else:
        m_tw = _TREATMENT_WEEK_RE.match(prefix)
        if m_tw and m_tw.group(1).strip("_- "):
            treatment = m_tw.group(1).strip("_- ")
            filename_week = int(m_tw.group(2))
        else:
            treatment = prefix.split("_")[0].strip("_- ") or stem

    if folder_week is not None:
        week = folder_week
    elif filename_week is not None:
        week = filename_week
    else:
        week = 0

    is_control = bool(folder_is_control or is_shared_control or week == 0)
    if is_shared_control and week != 0:
        is_shared_control = False

    return {
        "treatment": treatment,
        "week": week,
        "is_control": is_control,
        "is_shared_control": is_shared_control,
        "scale_label": scale_label,
        "filename_hv_kv": filename_hv_kv,
    }


def _parse_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in ("true", "1", "yes", "y"):
        return True
    if text in ("false", "0", "no", "n"):
        return False
    return default


def load_metadata_overrides(csv_path: str | Path) -> dict[str, dict[str, Any]]:
    """Load per-image manual overrides from ``metadata_override.csv``."""
    path = Path(csv_path)
    if not path.exists():
        return {}

    overrides: dict[str, dict[str, Any]] = {}
    with path.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            image_id = (row.get("image_id") or "").strip()
            if not image_id:
                continue
            entry: dict[str, Any] = {}
            if (row.get("treatment") or "").strip():
                entry["treatment"] = row["treatment"].strip()
            if (row.get("week") or "").strip():
                entry["week"] = int(row["week"].strip())
            if (row.get("is_control") or "").strip():
                entry["is_control"] = _parse_bool(row["is_control"])
            if (row.get("is_shared_control") or "").strip():
                entry["is_shared_control"] = _parse_bool(row["is_shared_control"])
            if (row.get("scale_label") or "").strip():
                entry["scale_label"] = row["scale_label"].strip()
            if (row.get("excluded") or "").strip():
                entry["excluded"] = _parse_bool(row["excluded"])
            if (row.get("um_per_px") or "").strip():
                val = float(row["um_per_px"].strip())
                if val > 0.0:
                    entry["um_per_px"] = val
            overrides[image_id] = entry
    return overrides


def save_metadata_overrides(
    records: list[SEMImageRecord],
    csv_path: str | Path,
) -> Path:
    """Persist editable dataset metadata overrides to CSV."""
    path = Path(csv_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=_OVERRIDE_FIELDS)
        writer.writeheader()
        for rec in records:
            um_str = (
                f"{rec.calibration.um_per_px:.8g}"
                if rec.calibration.um_per_px > 0.0
                else ""
            )
            writer.writerow(
                {
                    "image_id": rec.image_id,
                    "treatment": rec.treatment,
                    "week": rec.week,
                    "is_control": str(rec.is_control),
                    "is_shared_control": str(rec.is_shared_control),
                    "scale_label": rec.scale_label,
                    "excluded": str(rec.excluded),
                    "um_per_px": um_str,
                }
            )
    return path


def _folder_sort_key(path: Path) -> tuple[int, int, str]:
    week, is_ctrl = _parse_folder_week(path.name)
    if is_ctrl and week == 0:
        return (0, 0, path.name.lower())
    if week is not None:
        return (1, week, path.name.lower())
    return (2, 0, path.name.lower())


def _scale_sort_key(scale_label: str) -> tuple[int, float, str]:
    m = re.match(r"^(\d+(?:\.\d+)?)\s*(nm|um|mm)$", scale_label.lower())
    if not m:
        return (1, float("inf"), scale_label.lower())
    val = float(m.group(1))
    unit = m.group(2)
    mult = {"nm": 1e-3, "um": 1.0, "mm": 1e3}[unit]
    return (0, val * mult, scale_label.lower())


def scan_dataset(
    data_dir: str | Path = "data",
    override_csv: Optional[str | Path] = None,
) -> DatasetSummary:
    """Scan ``data_dir`` subfolders, parse metadata, audit HV consistency, and summarize."""
    root = Path(data_dir)
    if not root.exists():
        raise FileNotFoundError(f"Dataset directory not found: {root}")

    csv_path = Path(override_csv) if override_csv is not None else root / "metadata_override.csv"
    overrides = load_metadata_overrides(csv_path)

    subdirs = sorted(
        [p for p in root.iterdir() if p.is_dir() and not p.name.startswith(".")],
        key=_folder_sort_key,
    )

    records: list[SEMImageRecord] = []
    for subdir in subdirs:
        files = sorted(
            [
                f
                for f in subdir.iterdir()
                if f.is_file()
                and not f.name.startswith(".")
                and f.suffix.lower() in SUPPORTED_EXTENSIONS
            ],
            key=lambda p: p.name.lower(),
        )
        for img_path in files:
            rel_id = img_path.relative_to(root).as_posix()
            img_meta = parse_fei_tiff_metadata(img_path)
            name_meta = parse_filename_metadata(img_path.name, subdir.name)

            cal: Calibration = img_meta["calibration"]
            hv_kv = img_meta["hv_kv"]
            if hv_kv is None:
                hv_kv = name_meta["filename_hv_kv"]

            treatment = name_meta["treatment"]
            week = name_meta["week"]
            is_control = name_meta["is_control"]
            is_shared_control = name_meta["is_shared_control"]
            scale_label = name_meta["scale_label"]
            excluded = False

            if rel_id in overrides:
                ov = overrides[rel_id]
                treatment = ov.get("treatment", treatment)
                week = ov.get("week", week)
                is_control = ov.get("is_control", is_control)
                is_shared_control = ov.get("is_shared_control", is_shared_control)
                scale_label = ov.get("scale_label", scale_label)
                excluded = ov.get("excluded", excluded)
                if "um_per_px" in ov:
                    um_px = ov["um_per_px"]
                    cal = Calibration(
                        um_per_px=um_px,
                        hfw_um=um_px * cal.res_x,
                        res_x=cal.res_x,
                        res_y=cal.res_y,
                        databar_height_px=cal.databar_height_px,
                        source="manual",
                    )

            qc_flags: list[str] = []
            if cal.source == "uncalibrated":
                qc_flags.append("Uncalibrated")

            records.append(
                SEMImageRecord(
                    image_id=rel_id,
                    filepath=str(img_path),
                    filename=img_path.name,
                    folder_name=subdir.name,
                    treatment=treatment,
                    week=week,
                    is_control=is_control,
                    is_shared_control=is_shared_control,
                    scale_label=scale_label,
                    replicate=1,
                    hv_kv=hv_kv,
                    wd_mm=img_meta["wd_mm"],
                    sem_contrast=img_meta["sem_contrast"],
                    sem_brightness=img_meta["sem_brightness"],
                    detector=img_meta["detector"],
                    calibration=cal,
                    bit_depth=img_meta["bit_depth"],
                    hv_mismatch=False,
                    excluded=excluded,
                    qc_flags=qc_flags,
                )
            )

    # Assign deterministic 1-based replicate indices per (treatment, week, scale_label).
    records.sort(key=lambda r: (r.week, r.treatment.lower(), r.scale_label, r.filename.lower()))
    rep_counts: dict[tuple[str, int, str], int] = {}
    for rec in records:
        key = (rec.treatment, rec.week, rec.scale_label)
        rep_counts[key] = rep_counts.get(key, 0) + 1
        rec.replicate = rep_counts[key]

    # Compute statistical mode of accelerating voltage (HV, kV) and flag outliers.
    valid_hvs = [round(rec.hv_kv, 1) for rec in records if rec.hv_kv is not None]
    dominant_hv_kv: Optional[float] = (
        Counter(valid_hvs).most_common(1)[0][0] if valid_hvs else None
    )

    if dominant_hv_kv is not None:
        for rec in records:
            if rec.hv_kv is not None and abs(rec.hv_kv - dominant_hv_kv) > 0.25:
                rec.hv_mismatch = True
                if "HV_Mismatch" not in rec.qc_flags:
                    rec.qc_flags.append("HV_Mismatch")

    treatments = sorted(
        {rec.treatment for rec in records if not rec.is_shared_control}
    )
    weeks = sorted({rec.week for rec in records})
    scales = sorted({rec.scale_label for rec in records}, key=_scale_sort_key)
    has_shared_control = any(rec.is_shared_control for rec in records)

    return DatasetSummary(
        root_dir=str(root),
        records=records,
        treatments=treatments,
        weeks=weeks,
        scales=scales,
        dominant_hv_kv=dominant_hv_kv,
        has_shared_control=has_shared_control,
    )


def expand_shared_control_for_treatment(
    records: list[SEMImageRecord],
    treatment: str,
    scale_label: str,
    include_excluded: bool = False,
) -> list[SEMImageRecord]:
    """Return ordered records for ``treatment`` at ``scale_label``, prepending shared Week 0 controls if needed."""
    matching = [
        rec
        for rec in records
        if rec.scale_label == scale_label and (include_excluded or not rec.excluded)
    ]
    own_records = [rec for rec in matching if rec.treatment == treatment]
    has_own_week0 = any(rec.week == 0 for rec in own_records)

    if not has_own_week0:
        shared_controls = [
            rec for rec in matching if rec.is_shared_control and rec.week == 0
        ]
        combined = shared_controls + own_records
    else:
        combined = own_records

    combined.sort(key=lambda r: (r.week, r.replicate, r.filename.lower()))
    return combined
