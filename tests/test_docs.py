"""Unit tests for Stage 5 documentation integrity, Unicode math compliance, and sidebar help."""

from __future__ import annotations

import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from docx import Document

from core.version import APP_VERSION
from ui.help_docs import (
    METHODOLOGY_DOCX_PATH,
    SOP_DOCX_PATH,
    TOPIC_DOCS,
    extract_docx_section,
    read_docx_paragraphs,
)

_RAW_LATEX_RE = re.compile(
    r"\\(?:frac|sqrt|mu|sigma|beta|rho|pm|le|ge|times|text|cdot|sum|int|approx|ln|log|mathbb|arg|left|right|bar)\b"
)


def _all_docx_strings(path: Path) -> list[str]:
    doc = Document(str(path))
    texts = [p.text for p in doc.paragraphs if p.text]
    for tbl in doc.tables:
        for row in tbl.rows:
            for cell in row.cells:
                if cell.text:
                    texts.append(cell.text)
    return texts


def test_app_version_is_1_1_1() -> None:
    assert APP_VERSION == "1.1.1"


def test_docx_exist_and_contain_zero_raw_latex() -> None:
    assert SOP_DOCX_PATH.exists() and SOP_DOCX_PATH.stat().st_size > 0
    assert METHODOLOGY_DOCX_PATH.exists() and METHODOLOGY_DOCX_PATH.stat().st_size > 0

    for doc_path in (SOP_DOCX_PATH, METHODOLOGY_DOCX_PATH):
        paras = read_docx_paragraphs(doc_path)
        assert len(paras) >= 20
        for line in _all_docx_strings(doc_path):
            assert not _RAW_LATEX_RE.search(line), (
                f"Raw LaTeX backslash found in {doc_path.name}: {line}"
            )


def test_topic_docs_markers_resolve_cleanly() -> None:
    expected_tabs = [
        "1. Data & Metadata",
        "2. Roughness & Pseudo-AFM",
        "3. Kinetics & Comparison",
        "4. DSC Correlation",
        "5. Export & Report",
    ]
    assert list(TOPIC_DOCS.keys()) == expected_tabs

    sop_paras = read_docx_paragraphs(SOP_DOCX_PATH)
    meth_paras = read_docx_paragraphs(METHODOLOGY_DOCX_PATH)

    for tab_name, cfg in TOPIC_DOCS.items():
        sop_excerpt = extract_docx_section(
            sop_paras, cfg["sop_marker"], cfg.get("sop_end_marker")
        )
        meth_excerpt = extract_docx_section(
            meth_paras, cfg["meth_marker"], cfg.get("meth_end_marker")
        )
        assert len(sop_excerpt) >= 2, f"Empty SOP excerpt for {tab_name}"
        assert len(meth_excerpt) >= 1, f"Empty Methodology excerpt for {tab_name}"


def test_methodology_contains_native_omml_equations() -> None:
    m_ns = "http://schemas.openxmlformats.org/officeDocument/2006/math"
    with zipfile.ZipFile(METHODOLOGY_DOCX_PATH, "r") as zf:
        xml_bytes = zf.read("word/document.xml")

    root = ET.fromstring(xml_bytes)
    omath_elems = root.findall(f".//{{{m_ns}}}oMath")
    omath_para_elems = root.findall(f".//{{{m_ns}}}oMathPara")
    assert len(omath_elems) >= 18, f"Expected >= 18 native <m:oMath> equations, got {len(omath_elems)}"
    assert len(omath_para_elems) >= 18, (
        f"Expected >= 18 <m:oMathPara> blocks, got {len(omath_para_elems)}"
    )

    for mt in root.findall(f".//{{{m_ns}}}t"):
        if mt.text:
            assert not _RAW_LATEX_RE.search(mt.text), (
                f"Raw LaTeX backslash leaked into OMML run: {mt.text}"
            )

    all_text = "\n".join(_all_docx_strings(METHODOLOGY_DOCX_PATH))
    assert "BloomPix v1.1.1" in all_text
    assert "BloomPix v1.1.1" in "\n".join(_all_docx_strings(SOP_DOCX_PATH))

    expected_terms = [
        "Geom_Bloom_Index",
        "PSD_Beta",
        "T_lo_used",
        "T_hi_used",
        "T_onset_C",
        "T_peak_C",
        "T_endset_C",
        "Delta_T_C",
        "FWHM_C",
        "Delta_H_J_g",
        "High_Melt_gt34C_pct",
        "baseline_overshoot_pct",
        "is_bimodal",
        "qc_flag",
        "Pearson r",
        "Spearman",
    ]
    for term in expected_terms:
        assert term in all_text, f"Expected term '{term}' missing from Methodology.docx tables/text"

    # Verify the DSC summary table appears BEFORE the Section 5 DSC OMML equations in document order
    w_ns = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    body = root.find(f"{{{w_ns}}}body")
    assert body is not None
    body_children = list(body)
    dsc_tbl_idx = next(
        (
            idx
            for idx, el in enumerate(body_children)
            if el.tag == f"{{{w_ns}}}tbl"
            and "T_onset_C" in "".join(t.text or "" for t in el.findall(f".//{{{w_ns}}}t"))
        ),
        None,
    )
    dsc_eq_idx = next(
        (
            idx
            for idx, el in enumerate(body_children)
            if el.tag == f"{{{w_ns}}}p"
            and el.find(f".//{{{m_ns}}}oMath") is not None
            and "Overshoot" in "".join(t.text or "" for t in el.findall(f".//{{{m_ns}}}t"))
        ),
        None,
    )
    assert dsc_tbl_idx is not None and dsc_eq_idx is not None
    assert dsc_tbl_idx < dsc_eq_idx, "DSC summary table must appear before Section 5 DSC OMML equations"
