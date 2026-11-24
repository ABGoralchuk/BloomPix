"""Generate transparent studio PNG and multi-size ICO icons for BloomPix."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Optional

import numpy as np
from PIL import Image, ImageDraw

ICO_SIZES: list[tuple[int, int]] = [
    (16, 16),
    (24, 24),
    (32, 32),
    (48, 48),
    (64, 64),
    (128, 128),
    (256, 256),
]


def _extract_rounded_square_rgba(img: Image.Image) -> Image.Image:
    """Crop tightly to the icon foreground and apply crisp transparent corners."""
    rgba = img.convert("RGBA")
    arr = np.asarray(rgba)
    alpha = arr[:, :, 3]

    # Check if the source already provides transparent corners (e.g., studio PNG).
    corners = (alpha[0, 0], alpha[0, -1], alpha[-1, 0], alpha[-1, -1])
    if max(int(c) for c in corners) == 0 and int(alpha.max()) > 16:
        ys, xs = np.where(alpha > 16)
        if ys.size > 0 and xs.size > 0:
            x0, x1 = int(xs.min()), int(xs.max()) + 1
            y0, y1 = int(ys.min()), int(ys.max()) + 1
            return rgba.crop((x0, y0, x1, y1))

    # Opaque background path (e.g., logo.jpeg with dark outer border & drop shadow).
    rgb = arr[:, :, :3].astype(np.float64)
    gray = 0.299 * rgb[:, :, 0] + 0.587 * rgb[:, :, 1] + 0.114 * rgb[:, :, 2]

    h, w = gray.shape
    strip = max(1, min(10, h // 10, w // 10))
    border_pixels = np.concatenate(
        [
            gray[:strip, :].ravel(),
            gray[-strip:, :].ravel(),
            gray[:, :strip].ravel(),
            gray[:, -strip:].ravel(),
        ]
    )
    bg_level = float(np.median(border_pixels))
    fg_mask = gray > (bg_level + 11.0)

    # Trim sparse outer shadow fuzz by requiring meaningful row/column support.
    row_counts = fg_mask.sum(axis=1)
    col_counts = fg_mask.sum(axis=0)
    valid_rows = np.where(row_counts >= max(3, int(0.05 * w)))[0]
    valid_cols = np.where(col_counts >= max(3, int(0.05 * h)))[0]

    if valid_rows.size == 0 or valid_cols.size == 0:
        valid_rows, valid_cols = np.where(fg_mask)

    if valid_rows.size == 0 or valid_cols.size == 0:
        raise ValueError("Could not detect foreground icon bounds from input image.")

    y0, y1 = int(valid_rows.min()), int(valid_rows.max()) + 1
    x0, x1 = int(valid_cols.min()), int(valid_cols.max()) + 1

    cropped_rgb = rgba.crop((x0, y0, x1, y1)).convert("RGB")
    cw, ch = cropped_rgb.size

    # 4x supersampled antialiased rounded-rectangle alpha mask.
    ss = 4
    ss_w, ss_h = cw * ss, ch * ss
    radius_ss = max(1, round(0.195 * min(cw, ch) * ss))
    mask_ss = Image.new("L", (ss_w, ss_h), 0)
    draw = ImageDraw.Draw(mask_ss)
    draw.rounded_rectangle([0, 0, ss_w - 1, ss_h - 1], radius=radius_ss, fill=255)
    alpha_mask = mask_ss.resize((cw, ch), Image.Resampling.LANCZOS)

    result = cropped_rgb.convert("RGBA")
    result.putalpha(alpha_mask)
    return result


def build_studio_icons(
    input_path: str | Path,
    out_png: str | Path = "assets/bloompix.png",
    out_ico: str | Path = "assets/bloompix.ico",
    size: int = 512,
    padding_frac: float = 0.02,
) -> tuple[Path, Path]:
    """Build a transparent square PNG and multi-size Windows ICO from ``input_path``."""
    src = Path(input_path)
    if not src.exists():
        raise FileNotFoundError(f"Source icon image not found: {src}")

    with Image.open(src) as img:
        fg = _extract_rounded_square_rgba(img)

    target_box = max(1, round(size * (1.0 - 2.0 * padding_frac)))
    fg_w, fg_h = fg.size
    scale = min(target_box / fg_w, target_box / fg_h)
    new_w = max(1, round(fg_w * scale))
    new_h = max(1, round(fg_h * scale))
    resized = fg.resize((new_w, new_h), Image.Resampling.LANCZOS)

    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    offset_x = (size - new_w) // 2
    offset_y = (size - new_h) // 2
    canvas.paste(resized, (offset_x, offset_y), resized)

    png_path = Path(out_png)
    ico_path = Path(out_ico)
    png_path.parent.mkdir(parents=True, exist_ok=True)
    ico_path.parent.mkdir(parents=True, exist_ok=True)

    canvas.save(png_path, format="PNG")
    canvas.save(ico_path, format="ICO", sizes=ICO_SIZES)
    return png_path, ico_path


def _resolve_default_input(project_root: Path) -> Path:
    for candidate in ("logo.jpeg", "logo.jpg", "logo.png"):
        path = project_root / candidate
        if path.exists():
            return path
    raise FileNotFoundError(
        "No source logo found in project root (expected logo.jpeg or logo.png)."
    )


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Build transparent BloomPix icons.")
    parser.add_argument("--input", type=Path, default=None, help="Source logo path.")
    parser.add_argument("--out-png", type=Path, default=Path("assets/bloompix.png"))
    parser.add_argument("--out-ico", type=Path, default=Path("assets/bloompix.ico"))
    parser.add_argument("--size", type=int, default=512)
    parser.add_argument("--padding", type=float, default=0.02)
    args = parser.parse_args(argv)

    project_root = Path(__file__).resolve().parent.parent
    src = args.input or _resolve_default_input(project_root)
    png_path, ico_path = build_studio_icons(
        input_path=src,
        out_png=args.out_png,
        out_ico=args.out_ico,
        size=args.size,
        padding_frac=args.padding,
    )
    print(f"Generated {png_path} and {ico_path} from {src}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
