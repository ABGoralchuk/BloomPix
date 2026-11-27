"""Unit tests for Stage 5 documentation integrity, Unicode math compliance, and sidebar help."""

from __future__ import annotations

import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from docx import Document

from core.version import APP_VERSION
from scripts import build_windows_portable
from ui.help_docs import (
    METHODOLOGY_DOCX_PATH,
    METHODOLOGY_MD_PATH,
    SOP_DOCX_PATH,
    SOP_MD_PATH,
    TOPIC_DOCS,
    extract_docx_section,
    load_md_sections,
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


def test_app_version_is_1_1_2() -> None:
    assert APP_VERSION == "1.1.2"


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
    assert "BloomPix v1.1.2" in all_text
    assert "BloomPix v1.1.2" in "\n".join(_all_docx_strings(SOP_DOCX_PATH))

    expected_terms = [
        "Geom_Bloom_Index",
        "PSD_Beta",
        "T_lo_used",
        "T_hi_used",
        "T_onset_C",
        "T_peak_C",
        "FWHM_C",
        "Delta_H_J_g",
        "baseline_overshoot_pct",
        "is_bimodal",
        "qc_flag",
        "Pearson r",
        "Spearman",
    ]
    for term in expected_terms:
        assert term in all_text, f"Expected term '{term}' missing from Methodology.docx tables/text"

    for removed_term in ("T_endset_C", "Delta_T_C", "High_Melt_gt34C_pct"):
        assert removed_term not in all_text, (
            f"Removed DSC term '{removed_term}' should not appear in Methodology.docx"
        )

    sop_text = "\n".join(_all_docx_strings(SOP_DOCX_PATH))
    for removed_sop in ("High-Melt Cutoff", "T_endset"):
        assert removed_sop not in sop_text, (
            f"Removed DSC term '{removed_sop}' should not appear in SOP.docx"
        )

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


def test_every_omml_equation_followed_by_unbulleted_where_block() -> None:
    m_ns = "http://schemas.openxmlformats.org/officeDocument/2006/math"
    w_ns = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    with zipfile.ZipFile(METHODOLOGY_DOCX_PATH, "r") as zf:
        xml_bytes = zf.read("word/document.xml")

    root = ET.fromstring(xml_bytes)
    body = root.find(f"{{{w_ns}}}body")
    assert body is not None
    children = list(body)

    def _p_text(el: ET.Element) -> str:
        return "".join(t.text or "" for t in el.findall(f".//{{{w_ns}}}t")).strip()

    eq_indices = [
        idx
        for idx, el in enumerate(children)
        if el.tag == f"{{{w_ns}}}p" and el.find(f".//{{{m_ns}}}oMathPara") is not None
    ]
    where_indices = [
        idx
        for idx, el in enumerate(children)
        if el.tag == f"{{{w_ns}}}p" and _p_text(el) == "Where"
    ]

    assert len(eq_indices) == 29, f"Expected 29 OMML equations, found {len(eq_indices)}"
    assert len(where_indices) == len(eq_indices), (
        f"Mismatch between OMML equations ({len(eq_indices)}) and 'Where' blocks ({len(where_indices)})"
    )

    for eq_idx in eq_indices:
        assert eq_idx + 2 < len(children), f"Equation at index {eq_idx} missing following 'Where' block"
        lead_el = children[eq_idx + 1]
        assert lead_el.tag == f"{{{w_ns}}}p"
        assert _p_text(lead_el) == "Where", (
            f"Paragraph right after equation {eq_idx} must be 'Where', got '{_p_text(lead_el)}'"
        )

        # Verify every unbulleted nomenclature item in this Where block
        j = eq_idx + 2
        item_count = 0
        while j < len(children) and children[j].tag == f"{{{w_ns}}}p":
            el = children[j]
            txt = _p_text(el)
            pPr = el.find(f"{{{w_ns}}}pPr")
            ind = pPr.find(f"{{{w_ns}}}ind") if pPr is not None else None
            has_left_ind = ind is not None and (
                ind.get(f"{{{w_ns}}}left") is not None
            )
            if not (" — " in txt and has_left_ind):
                break
            numPr = pPr.find(f"{{{w_ns}}}numPr") if pPr is not None else None
            assert numPr is None, f"Where item must not use numbered/bulleted XML list: {txt}"
            assert not txt.startswith(("•", "- ")), f"Where item must not start with bullet character: {txt}"
            assert not _RAW_LATEX_RE.search(txt), f"Raw LaTeX backslash in Where item: {txt}"
            item_count += 1
            j += 1

        assert item_count >= 1, f"Where block after equation {eq_idx} has zero variable definitions"


def test_quick_md_files_exist_parse_and_match_tabs() -> None:
    expected_tabs = [
        "1. Data & Metadata",
        "2. Roughness & Pseudo-AFM",
        "3. Kinetics & Comparison",
        "4. DSC Correlation",
        "5. Export & Report",
    ]
    assert SOP_MD_PATH.exists() and SOP_MD_PATH.stat().st_size > 0
    assert METHODOLOGY_MD_PATH.exists() and METHODOLOGY_MD_PATH.stat().st_size > 0

    sop_sections = load_md_sections(str(SOP_MD_PATH))
    meth_sections = load_md_sections(str(METHODOLOGY_MD_PATH))

    assert list(sop_sections.keys()) == expected_tabs
    assert list(meth_sections.keys()) == expected_tabs

    for tab_name in expected_tabs:
        assert len(sop_sections[tab_name]) >= 80, f"SOP section too short for {tab_name}"
        assert len(meth_sections[tab_name]) >= 80, f"Methodology section too short for {tab_name}"

    for tab_name in expected_tabs[:4]:
        assert "$$" in meth_sections[tab_name], f"Expected display LaTeX in {tab_name}"

    meth_full = "\n".join(meth_sections.values())
    required_identifiers = [
        "34682",
        r"u_{\text{raster}}",
        "HV_Mismatch",
        r"\sigma_{\text{noise}}",
        "TRNR",
        "LocTRNR",
        "Bloom_Coverage",
        "Meso_SNR",
        "Grad_SNR",
        "Blade_Index",
        "Anisotropy_Coh",
        "PSD_logSNR",
        "PSD_Beta",
        r"L_{\text{corr}}",
        "CBI",
        "Geom_Bloom_Index",
        r"t_{\text{lag}}",
        "AUC",
        "Suppressed",
        "Mild / Non-Sigmoidal Drift",
        "PCA",
        "Kruskal",
        r"HF_{\text{base}}",
        r"T_{\text{peak}}",
        r"T_{\text{onset}}",
        "FWHM",
        r"\Delta H",
        "Overshoot",
        "settings.json",
        "analysis_report.md",
    ]
    for ident in required_identifiers:
        assert ident in meth_full, f"Missing identifier '{ident}' in Methodology_quick.md"

    sop_full = "\n".join(sop_sections.values())
    for forbidden in (r"T_{\text{endset}}", "High_Melt", "High-Melt Cutoff", "F_{>34"):
        assert forbidden not in meth_full, f"Removed identifier '{forbidden}' still in Methodology_quick.md"
        assert forbidden not in sop_full, f"Removed identifier '{forbidden}' still in SOP_quick.md"


def test_quick_md_files_have_zero_orphan_where_lines() -> None:
    orphan_where_re = re.compile(r"^\s*(?:[*_#>\-\s]*)?where\b[:\s]*$", re.IGNORECASE)
    starts_with_where_re = re.compile(r"^\s*(?:[*_#>\-\s]*)?where\b", re.IGNORECASE)

    for md_path in (SOP_MD_PATH, METHODOLOGY_MD_PATH):
        for lineno, line in enumerate(md_path.read_text(encoding="utf-8").splitlines(), start=1):
            assert not orphan_where_re.match(line), (
                f"Orphan 'Where' line found in {md_path.name}:{lineno}: {line}"
            )
            assert not starts_with_where_re.match(line), (
                f"Line starts with 'Where' in {md_path.name}:{lineno}: {line}"
            )


def test_windows_portable_packager_includes_docs_dir(tmp_path: Path) -> None:
    project_root = Path(__file__).resolve().parent.parent
    staged = build_windows_portable._stage_project_files(project_root, tmp_path)
    for expected_rel in (
        "docs/SOP_quick.md",
        "docs/Methodology_quick.md",
        "docs/SOP.docx",
        "docs/Methodology.docx",
    ):
        assert expected_rel in staged, f"Missing '{expected_rel}' in staged portable files"
        assert (tmp_path / expected_rel).is_file()
