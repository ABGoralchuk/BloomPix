"""Context-aware SOP & Methodology documentation viewer backed by docs/*.md and docs/*.docx."""

from __future__ import annotations

import zipfile
from functools import lru_cache
from pathlib import Path
from typing import Optional
from xml.etree import ElementTree as ET

import streamlit as st
from docx import Document

_DOCS_DIR = Path(__file__).resolve().parent.parent / "docs"
SOP_DOCX_PATH = _DOCS_DIR / "SOP.docx"
METHODOLOGY_DOCX_PATH = _DOCS_DIR / "Methodology.docx"
SOP_MD_PATH = _DOCS_DIR / "SOP_quick.md"
METHODOLOGY_MD_PATH = _DOCS_DIR / "Methodology_quick.md"

TOPIC_DOCS: dict[str, dict[str, Optional[str]]] = {
    "1. Data & Metadata": {
        "sop_marker": "2.1 Tab 1",
        "sop_end_marker": "2.2 Tab 2",
        "meth_marker": "1. General Overview",
        "meth_end_marker": "2. Preprocessing",
    },
    "2. Roughness & Pseudo-AFM": {
        "sop_marker": "2.2 Tab 2",
        "sop_end_marker": "2.3 Tab 3",
        "meth_marker": "3. Surface Roughness",
        "meth_end_marker": "4. Kinetic Modeling",
    },
    "3. Kinetics & Comparison": {
        "sop_marker": "2.3 Tab 3",
        "sop_end_marker": "2.4 Tab 4",
        "meth_marker": "4. Kinetic Modeling",
        "meth_end_marker": "5. Optional DSC",
    },
    "4. DSC Correlation": {
        "sop_marker": "2.4 Tab 4",
        "sop_end_marker": "2.5 Tab 5",
        "meth_marker": "5. Optional DSC",
        "meth_end_marker": None,
    },
    "5. Export & Report": {
        "sop_marker": "2.5 Tab 5",
        "sop_end_marker": "3. Troubleshooting",
        "meth_marker": "5. Optional DSC",
        "meth_end_marker": None,
    },
}


@lru_cache(maxsize=8)
def load_md_sections(filepath: str | Path) -> dict[str, str]:
    """Load and split a Markdown reference file into sections keyed by ``## <Tab Name>`` headers."""
    path = Path(filepath)
    if not path.exists():
        return {}

    sections: dict[str, str] = {}
    current_key: Optional[str] = None
    buf: list[str] = []

    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            if current_key is not None:
                sections[current_key] = "\n".join(buf).strip()
            current_key = line[3:].strip()
            buf = []
        elif current_key is not None:
            buf.append(line)

    if current_key is not None:
        sections[current_key] = "\n".join(buf).strip()

    return sections


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
    sop_sections = load_md_sections(str(SOP_MD_PATH))
    meth_sections = load_md_sections(str(METHODOLOGY_MD_PATH))

    choices = [
        name for name in tab_names if name in sop_sections or name in meth_sections
    ] or list(sop_sections.keys()) or list(tab_names)
    selected = st.selectbox("Select Module Topic:", choices, key="sidebar_help_topic")

    with st.expander("📘 SOP (Standard Operating Procedure)", expanded=False):
        sop_md = sop_sections.get(selected, "")
        if sop_md:
            st.markdown(sop_md)
        else:
            st.warning(f"No quick SOP section found for '{selected}' in docs/SOP_quick.md.")

    with st.expander("📐 Methodology & Formulas", expanded=False):
        meth_md = meth_sections.get(selected, "")
        if meth_md:
            st.markdown(meth_md)
        else:
            st.warning(
                f"No quick Methodology section found for '{selected}' in docs/Methodology_quick.md."
            )

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
