"""Publication-grade Matplotlib helpers and 300-DPI figure registration."""

from __future__ import annotations

import io
import re
from typing import Optional

import matplotlib
import matplotlib.pyplot as plt
import streamlit as st
from matplotlib.figure import Figure

from core.models import Calibration
from ui import state


def sanitize_filename(name: str) -> str:
    """Convert an arbitrary label into a safe filesystem stem."""
    clean = re.sub(r"[^A-Za-z0-9._-]+", "_", name.strip())
    return clean.strip("_") or "figure"


def make_spatial_extent(calibration: Calibration) -> tuple[list[float], str]:
    """Return ``([0, width, height, 0], unit_label)`` in micrometers (or pixels if uncalibrated)."""
    if calibration.um_per_px > 0.0:
        w_um = calibration.res_x * calibration.um_per_px
        h_um = calibration.res_y * calibration.um_per_px
        return [0.0, float(w_um), float(h_um), 0.0], "µm"
    return [0.0, float(calibration.res_x), float(calibration.res_y), 0.0], "px (uncalibrated)"


def treatment_colors(treatments: list[str]) -> dict[str, tuple[float, float, float, float]]:
    """Assign deterministic publication colors using ``matplotlib.colormaps``."""
    cmap = matplotlib.colormaps["tab10"]
    return {trt: cmap(idx % 10) for idx, trt in enumerate(sorted(treatments))}


def fig_to_png_bytes(fig: Figure, dpi: int = 300) -> bytes:
    """Render a Matplotlib figure to PNG bytes at ``dpi`` DPI."""
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=dpi, bbox_inches="tight")
    return buf.getvalue()


def render_and_register_fig(
    fig: Figure,
    filename_base: str,
    caption: Optional[str] = None,
    dpi: int = 300,
    download_label: Optional[str] = None,
) -> bytes:
    """Display a figure in Streamlit, register 300-DPI PNG for ZIP export, and close it."""
    safe_stem = sanitize_filename(filename_base)
    filename = f"{safe_stem}.png"
    try:
        png_bytes = fig_to_png_bytes(fig, dpi=dpi)
        state.register_exported_figure(filename, png_bytes)
        st.pyplot(fig, width="stretch")
        if caption:
            st.caption(caption)
        st.download_button(
            label=download_label or f"Download {filename} ({dpi} DPI)",
            data=png_bytes,
            file_name=filename,
            mime="image/png",
            key=f"dl_{safe_stem}_{len(png_bytes)}",
        )
        return png_bytes
    finally:
        plt.close(fig)
