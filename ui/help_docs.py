"""Context-aware SOP & Methodology documentation viewer synchronized with docs/*.docx."""

from __future__ import annotations

import zipfile
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional
from xml.etree import ElementTree as ET

import streamlit as st
from docx import Document

_DOCS_DIR = Path(__file__).resolve().parent.parent / "docs"
SOP_DOCX_PATH = _DOCS_DIR / "SOP.docx"
METHODOLOGY_DOCX_PATH = _DOCS_DIR / "Methodology.docx"

TOPIC_DOCS: dict[str, dict[str, Any]] = {
    "1. Data & Metadata": {
        "sop_marker": "2.1 Tab 1",
        "sop_end_marker": "2.2 Tab 2",
        "sop_steps": [
            "Verify the dataset directory (default: `data/`) and click **Scan Dataset**.",
            "Confirm replicate counts in the compact **Replicate Coverage Matrix** (`Week × Treatment`).",
            "Check **HV & Calibration Audit** for `HV_Mismatch` flags (e.g., `10 kV` vs `5 kV`) and databar crop height.",
            "Exclude defective scans or rename treatments via **metadata_override.csv**.",
        ],
        "meth_marker": "1. General Overview",
        "meth_end_marker": "2. Preprocessing",
        "methodology_summary": (
            "Parses Thermo Fisher Tag 34682 (`PixelWidth`, `HFW`, `ResolutionX`, `ResolutionY`, `HV`, `WD`), "
            "crops the bottom databar before analysis, and tracks raster quantization uncertainty."
        ),
        "equations": [
            r"u_{\text{raster}} = \frac{\mu\text{m/px}}{\sqrt{12}} \quad [\mu\text{m}]",
        ],
    },
    "2. Roughness & Pseudo-AFM": {
        "sop_marker": "2.2 Tab 2",
        "sop_end_marker": "2.3 Tab 3",
        "sop_steps": [
            "Click **Run Surface Roughness Analysis** to compute all invariant metrics for the active scale.",
            "In **Single Treatment (All Weeks)**, pick Treatment, Replicate, and Heatmap Type (`Pseudo-AFM` or `Sato`), then click **Generate All-Weeks Heatmaps & PSD**.",
            "Download the combined 300-DPI grid, individual week PNGs (ZIP), and 2D FFT Radial PSD table (CSV).",
            "Use **Compare Two Treatments** for shared-colorbar side-by-side inspection.",
        ],
        "meth_marker": "3. Surface Roughness",
        "meth_end_marker": "4. Kinetic Modeling",
        "methodology_summary": (
            "Anchors amplitude, slope, and smooth isotropic Gaussian Pseudo-AFM local roughness (`σ = 1.0 µm`) "
            "to Immerkaer detector noise `σ_noise`, ensuring exact invariance to `I' = a·I + b`."
        ),
        "equations": [
            r"\sigma_{\text{noise}} = \frac{\text{median}(|I * K_{\text{Im}}|) / 0.6745}{6}",
            r"\text{LocTRNR}(x, y) = \frac{\sqrt{\max\left(G_{\sigma}(I_{\text{topo}}^2) - [G_{\sigma}(I_{\text{topo}})]^2,\; 0\right)}}{\sigma_{\text{noise}}}",
            r"\text{CBI} = \frac{1}{8} \sum_{m=1}^{8} \max\!\left(\frac{x_m - \mu_{m,\text{ctrl}}}{P_{95,m} - \mu_{m,\text{ctrl}}} \times 100,\; -20\right)",
        ],
    },
    "3. Kinetics & Comparison": {
        "sop_marker": "2.3 Tab 3",
        "sop_end_marker": "2.4 Tab 4",
        "sop_steps": [
            "Verify the sidebar **Global HV Policy** (exclude `HV_Mismatch` weeks from fits by default).",
            "Select a **Kinetic Metric** (`CBI`, `Bloom Coverage %`, etc.) and export **Displayed Kinetic Data (CSV)**.",
            "Inspect the **Treatment Ranking** table (`Rank #1` = lowest `AUC_norm`) and download **Heatmap Matrix (CSV)**.",
            "Inspect **2D PCA** trajectories and set **Statistical Comparison Min Week** for ANOVA / Kruskal–Wallis tests.",
        ],
        "meth_marker": "4. Kinetic Modeling",
        "meth_end_marker": "5. Optional DSC",
        "methodology_summary": (
            "Fits a bounded 4-parameter logistic curve (`R² ≥ 0.50`, `k < 4.95`), classifies suppressed (`ΔCBI < 20`) "
            "and mild-drift trajectories safely, ranks treatments by normalized `AUC`, and runs 2D PCA & ANOVA."
        ),
        "equations": [
            r"y(t) = y_0 + \frac{y_{\max} - y_0}{1 + \exp\left(-k\,(t - t_{1/2})\right)}, \quad t_{\text{lag}} = \max\!\left(0,\; t_{1/2} - \frac{\ln 9}{k}\right)",
            r"\text{AUC}_{\text{norm}} = \frac{1}{t_{\max} - t_{\min}} \int_{t_{\min}}^{t_{\max}} y(t)\,dt",
        ],
    },
    "4. DSC Correlation": {
        "sop_marker": "2.4 Tab 4",
        "sop_end_marker": "2.5 Tab 5",
        "sop_steps": [
            "In **Raw TA Instruments DSC Folder (.txt)**, point to `data/DSC` (`<treatment>W<week>r<rep>.txt` and `controlr<rep>.txt`) and click **Scan & Analyze Raw DSC Folder** — pre-melting and post-melting baselines are detected automatically.",
            "Confirm **Baseline QC OK** vs **Needs Review** (`overshoot > 5%` or `T_onset < T_lo + 0.05 °C`; bimodal curves are purely informational); apply targeted per-file overrides only when flagged (resolved runs become `OK (Manual)`).",
            "Inspect raw curves in **Thermogram QA Inspector**, view trends in **DSC Thermodynamic Evolution**, and export the **All Samples — DSC Thermodynamic Parameters** table (Weekly Means ± SD or Individual Replicates) directly below as CSV.",
            "Choose **Correlation Scope** (`All Treatments (Pooled)` vs `Per-Treatment (Within-Group Aging)`) while respecting the global sidebar **HV exclusion policy**.",
        ],
        "meth_marker": "5. Optional DSC",
        "meth_end_marker": None,
        "methodology_summary": (
            "Anchors the flattest pre-melting plateau within `0.006 W/g` of the `21.6–23.0 °C` 90th-percentile level "
            "(strictly avoiding post-drop shoulders) and post-melting baseline in `38.0–45.0 °C`, flags true baseline "
            "issues (`overshoot > 5%` or `T_onset < T_lo + 0.05 °C`), computes ASTM E794 parameters, and runs Pooled or "
            "Per-Treatment SEM×DSC correlations excluding HV-mismatched weeks."
        ),
        "equations": [
            r"T_{\text{onset}} = T^*_{\text{lead}} - \frac{\text{endo}_{\text{smooth}}(T^*_{\text{lead}})}{(d\,\text{endo}_{\text{smooth}}/dT)\big|_{T^*_{\text{lead}}}}",
            r"\Delta H = \int_{t_{\text{lo}}}^{t_{\text{hi}}} \max\big(HF_{\text{base}}(t) - HF(t),\; 0\big)\,dt \quad [\text{J/g}], \quad F_{>34^\circ\text{C}} = 100 \times \frac{\Delta H_{T \ge 34^\circ\text{C}}}{\Delta H}",
            r"r = \frac{\sum_{i=1}^{n}(x_i - \bar{x})(y_i - \bar{y})}{\sqrt{\sum_{i=1}^{n}(x_i - \bar{x})^2}\sqrt{\sum_{i=1}^{n}(y_i - \bar{y})^2}}, \quad \rho = 1 - \frac{6\sum_{i=1}^{n} d_i^2}{n(n^2 - 1)}",
        ],
    },
    "5. Export & Report": {
        "sop_marker": "2.5 Tab 5",
        "sop_end_marker": "3. Troubleshooting",
        "sop_steps": [
            "Preview `analysis_report.md` and `settings.json` in Section 1.",
            "Choose **Heatmap & PSD Replicate Scope**, confirm **Statistical Comparison Min Week**, and optionally toggle individual per-week 300-DPI PNGs.",
            "Click **Build Complete Publication Archive** to generate 300-DPI Pseudo-AFM, Sato, PSD, PCA, and all 8 kinetic metric figures & CSVs across every discovered treatment.",
            "Click **Download Complete Publication Archive (ZIP)** once the manifest summary appears.",
        ],
        "meth_marker": "5. Optional DSC",
        "meth_end_marker": None,
        "methodology_summary": (
            "Generates a complete study-agnostic package: per-treatment 300-DPI Pseudo-AFM & Sato grids, "
            "2D FFT Radial PSD (`µm⁻¹`), all 8 kinetic metrics with ANOVA/Kruskal–Wallis & pairwise tests, "
            "2D PCA, `settings.json` (`pseudo_afm_gaussian_sigma_um = 1.0 µm`), and `analysis_report.md`."
        ),
        "equations": [],
    },
}


@lru_cache(maxsize=8)
def read_docx_paragraphs(filepath: str | Path) -> list[str]:
    """Read non-empty paragraphs from a ``.docx`` file with an XML zip fallback."""
    path = Path(filepath)
    if not path.exists():
        return []

    try:
        doc = Document(str(path))
        paras = [p.text.strip() for p in doc.paragraphs if p.text and p.text.strip()]
        if paras:
            return paras
    except Exception:
        pass

    try:
        with zipfile.ZipFile(path, "r") as zf:
            xml_bytes = zf.read("word/document.xml")
        root = ET.fromstring(xml_bytes)
        ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
        out: list[str] = []
        for p_elem in root.findall(".//w:p", ns):
            texts = [t.text for t in p_elem.findall(".//w:t", ns) if t.text]
            joined = "".join(texts).strip()
            if joined:
                out.append(joined)
        return out
    except Exception:
        return []


def extract_docx_section(
    paragraphs: list[str],
    start_marker: str,
    end_marker: Optional[str] = None,
    max_items: int = 8,
) -> list[str]:
    """Extract paragraph excerpts between ``start_marker`` and ``end_marker``."""
    if not paragraphs:
        return []
    start_idx: Optional[int] = None
    low_start = start_marker.lower()
    low_end = end_marker.lower() if end_marker else None

    for idx, text in enumerate(paragraphs):
        if low_start in text.lower():
            start_idx = idx
            break
    if start_idx is None:
        return []

    items: list[str] = []
    for text in paragraphs[start_idx + 1 :]:
        if low_end and low_end in text.lower():
            break
        items.append(text)
        if len(items) >= max_items:
            break
    return items


def render_sidebar_help(tab_names: list[str]) -> None:
    """Render context-aware SOP, Methodology, and downloadable .docx controls in sidebar."""
    st.subheader("SOP & Methodology Docs")
    choices = [name for name in tab_names if name in TOPIC_DOCS] or list(TOPIC_DOCS.keys())
    selected = st.selectbox("Select Module Topic:", choices, key="sidebar_help_topic")
    info = TOPIC_DOCS[selected]

    sop_paras = read_docx_paragraphs(SOP_DOCX_PATH)
    meth_paras = read_docx_paragraphs(METHODOLOGY_DOCX_PATH)

    with st.expander("📘 SOP (Standard Operating Procedure)", expanded=False):
        for step in info["sop_steps"]:
            st.markdown(f"- {step}")
        excerpt = extract_docx_section(
            sop_paras,
            start_marker=info["sop_marker"],
            end_marker=info.get("sop_end_marker"),
            max_items=4,
        )
        if excerpt:
            st.caption("From `docs/SOP.docx`:")
            for line in excerpt:
                st.caption(f"• {line}")

    with st.expander("📐 Methodology & Formulas", expanded=False):
        st.markdown(info["methodology_summary"])
        for eq in info.get("equations", []):
            st.latex(eq)
        meth_excerpt = extract_docx_section(
            meth_paras,
            start_marker=info["meth_marker"],
            end_marker=info.get("meth_end_marker"),
            max_items=3,
        )
        if meth_excerpt:
            st.caption("From `docs/Methodology.docx`:")
            for line in meth_excerpt:
                st.caption(line)

    c_sop, c_meth = st.columns(2)
    with c_sop:
        if SOP_DOCX_PATH.exists():
            st.download_button(
                label="SOP (.docx)",
                data=SOP_DOCX_PATH.read_bytes(),
                file_name="BloomPix_SOP.docx",
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                width="stretch",
                key="dl_sop_docx",
            )
    with c_meth:
        if METHODOLOGY_DOCX_PATH.exists():
            st.download_button(
                label="Methodology (.docx)",
                data=METHODOLOGY_DOCX_PATH.read_bytes(),
                file_name="BloomPix_Methodology.docx",
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                width="stretch",
                key="dl_meth_docx",
            )
