"""Unit tests for Stage 5 documentation integrity, Unicode math compliance, and sidebar help."""

from __future__ import annotations

import re
from pathlib import Path

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
    r"\\(?:frac|sqrt|mu|sigma|beta|rho|pm|le|ge|times|text|cdot|sum|int|approx|ln|log)\b"
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


def test_app_version_is_1_0_0() -> None:
    assert APP_VERSION == "1.0.0"


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
