"""Generate publication-grade docs/Methodology.docx (with native editable OMML equations) and docs/SOP.docx."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, Union

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml import parse_xml
from docx.oxml.ns import nsdecls
from docx.shared import Inches, Pt, RGBColor
from lxml import etree

NAVY = RGBColor(0x1B, 0x36, 0x5D)
TEAL = RGBColor(0x2B, 0x6C, 0x7A)
SLATE = RGBColor(0x47, 0x55, 0x69)
DARK = RGBColor(0x1E, 0x29, 0x3B)

NAVY_HEX = "1B365D"
LIGHT_BG_HEX = "F2F6FA"
ROW_ALT_HEX = "F8FAFC"
BORDER_HEX = "CBD5E1"

M_NS = "http://schemas.openxmlformats.org/officeDocument/2006/math"
W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
XML_NS = "http://www.w3.org/XML/1998/namespace"

etree.register_namespace("m", M_NS)
etree.register_namespace("w", W_NS)

OMMLNode = etree._Element
MathArg = Union[OMMLNode, Iterable[OMMLNode], str]


def _m(tag: str, **attrib: str) -> OMMLNode:
    return etree.Element(f"{{{M_NS}}}{tag}", **attrib)


def _w(tag: str, **attrib: str) -> OMMLNode:
    return etree.Element(f"{{{W_NS}}}{tag}", **attrib)


def _append_nodes(parent: OMMLNode, arg: MathArg) -> None:
    if isinstance(arg, str):
        parent.append(m_run(arg))
    elif isinstance(arg, etree._Element):
        parent.append(arg)
    else:
        for item in arg:
            _append_nodes(parent, item)


def _w_rpr_math(bold: bool = False) -> OMMLNode:
    w_rpr = _w("rPr")
    r_fonts = _w("rFonts")
    r_fonts.set(f"{{{W_NS}}}ascii", "Cambria Math")
    r_fonts.set(f"{{{W_NS}}}hAnsi", "Cambria Math")
    r_fonts.set(f"{{{W_NS}}}cs", "Cambria Math")
    w_rpr.append(r_fonts)
    if bold:
        w_rpr.append(_w("b"))
    color = _w("color")
    color.set(f"{{{W_NS}}}val", NAVY_HEX)
    w_rpr.append(color)
    sz = _w("sz")
    sz.set(f"{{{W_NS}}}val", "22")
    w_rpr.append(sz)
    sz_cs = _w("szCs")
    sz_cs.set(f"{{{W_NS}}}val", "22")
    w_rpr.append(sz_cs)
    return w_rpr


def m_run(text: str, italic: bool = True, bold: bool = False) -> OMMLNode:
    """Create a native OMML math run <m:r> with Cambria Math typography."""
    mr = _m("r")
    if not italic:
        mrpr = _m("rPr")
        mrpr.append(_m("nor"))
        mr.append(mrpr)
    elif bold:
        mrpr = _m("rPr")
        sty = _m("sty")
        sty.set(f"{{{M_NS}}}val", "bi")
        mrpr.append(sty)
        mr.append(mrpr)

    mr.append(_w_rpr_math(bold=bold))
    mt = _m("t")
    mt.set(f"{{{XML_NS}}}space", "preserve")
    mt.text = text
    mr.append(mt)
    return mr


def m_op(text: str, bold: bool = False) -> OMMLNode:
    """Create an upright operator/function/number/punctuation OMML run."""
    return m_run(text, italic=False, bold=bold)


def m_var(text: str, bold: bool = False) -> OMMLNode:
    """Create an italicized variable/Greek symbol OMML run."""
    return m_run(text, italic=True, bold=bold)


def m_frac(num: MathArg, den: MathArg) -> OMMLNode:
    """Create a native stacked OMML fraction <m:f>."""
    f = _m("f")
    fpr = _m("fPr")
    ftype = _m("type")
    ftype.set(f"{{{M_NS}}}val", "bar")
    fpr.append(ftype)
    f.append(fpr)

    m_num = _m("num")
    _append_nodes(m_num, num)
    m_den = _m("den")
    _append_nodes(m_den, den)
    f.append(m_num)
    f.append(m_den)
    return f


def m_rad(expr: MathArg, deg: MathArg | None = None) -> OMMLNode:
    """Create a native OMML radical <m:rad> (square root when deg is None)."""
    rad = _m("rad")
    rpr = _m("radPr")
    if deg is None:
        dh = _m("degHide")
        dh.set(f"{{{M_NS}}}val", "1")
        rpr.append(dh)
    rad.append(rpr)

    m_deg = _m("deg")
    if deg is not None:
        _append_nodes(m_deg, deg)
    rad.append(m_deg)

    m_e = _m("e")
    _append_nodes(m_e, expr)
    rad.append(m_e)
    return rad


def m_sub(base: MathArg, sub: MathArg) -> OMMLNode:
    """Create a native OMML subscript <m:sSub>."""
    el = _m("sSub")
    el.append(_m("sSubPr"))
    me = _m("e")
    _append_nodes(me, base)
    msub = _m("sub")
    _append_nodes(msub, sub)
    el.append(me)
    el.append(msub)
    return el


def m_sup(base: MathArg, sup: MathArg) -> OMMLNode:
    """Create a native OMML superscript <m:sSup>."""
    el = _m("sSup")
    el.append(_m("sSupPr"))
    me = _m("e")
    _append_nodes(me, base)
    msup = _m("sup")
    _append_nodes(msup, sup)
    el.append(me)
    el.append(msup)
    return el


def m_subsup(base: MathArg, sub: MathArg, sup: MathArg) -> OMMLNode:
    """Create a native OMML subscript+superscript <m:sSubSup>."""
    el = _m("sSubSup")
    el.append(_m("sSubSupPr"))
    me = _m("e")
    _append_nodes(me, base)
    msub = _m("sub")
    _append_nodes(msub, sub)
    msup = _m("sup")
    _append_nodes(msup, sup)
    el.append(me)
    el.append(msub)
    el.append(msup)
    return el


def m_delim(expr: MathArg, beg: str = "(", end: str = ")") -> OMMLNode:
    """Create auto-sizing OMML delimiters <m:d> (parentheses, brackets, abs bars)."""
    d = _m("d")
    dpr = _m("dPr")
    b = _m("begChr")
    b.set(f"{{{M_NS}}}val", beg)
    e = _m("endChr")
    e.set(f"{{{M_NS}}}val", end)
    dpr.append(b)
    dpr.append(e)
    d.append(dpr)

    me = _m("e")
    _append_nodes(me, expr)
    d.append(me)
    return d


def m_nary(
    chr_sym: str,
    lower: MathArg | None,
    upper: MathArg | None,
    expr: MathArg,
    lim_loc: str = "undOvr",
) -> OMMLNode:
    """Create a native OMML n-ary operator <m:nary> (summation ∑ or integral ∫)."""
    nary = _m("nary")
    npr = _m("naryPr")
    ch = _m("chr")
    ch.set(f"{{{M_NS}}}val", chr_sym)
    npr.append(ch)
    ll = _m("limLoc")
    ll.set(f"{{{M_NS}}}val", lim_loc)
    npr.append(ll)
    if lower is None:
        sh = _m("subHide")
        sh.set(f"{{{M_NS}}}val", "1")
        npr.append(sh)
    if upper is None:
        uh = _m("supHide")
        uh.set(f"{{{M_NS}}}val", "1")
        npr.append(uh)
    nary.append(npr)

    msub = _m("sub")
    if lower is not None:
        _append_nodes(msub, lower)
    nary.append(msub)

    msup = _m("sup")
    if upper is not None:
        _append_nodes(msup, upper)
    nary.append(msup)

    me = _m("e")
    _append_nodes(me, expr)
    nary.append(me)
    return nary


def m_matrix(rows: list[list[MathArg]]) -> OMMLNode:
    """Create a bracketed OMML matrix <m:d><m:e><m:m>...</m:m></m:e></m:d>."""
    n_cols = max((len(r) for r in rows), default=1)
    m_el = _m("m")
    mpr = _m("mPr")
    mcs = _m("mcs")
    mc = _m("mc")
    mcpr = _m("mcPr")
    cnt = _m("count")
    cnt.set(f"{{{M_NS}}}val", str(n_cols))
    jc = _m("mcJc")
    jc.set(f"{{{M_NS}}}val", "center")
    mcpr.append(cnt)
    mcpr.append(jc)
    mc.append(mcpr)
    mcs.append(mc)
    mpr.append(mcs)
    m_el.append(mpr)

    for row in rows:
        mr = _m("mr")
        for cell in row:
            me = _m("e")
            _append_nodes(me, cell)
            mr.append(me)
        m_el.append(mr)
    return m_delim(m_el, beg="[", end="]")


def m_lim_low(base: MathArg, lim: MathArg) -> OMMLNode:
    """Create an OMML lower-limit operator <m:limLow> (e.g., arg max over an interval)."""
    el = _m("limLow")
    el.append(_m("limLowPr"))
    me = _m("e")
    _append_nodes(me, base)
    mlim = _m("lim")
    _append_nodes(mlim, lim)
    el.append(me)
    el.append(mlim)
    return el


def m_acc(expr: MathArg, chr_sym: str = "\u0304") -> OMMLNode:
    """Create an OMML accent <m:acc> (default combining overbar for sample means)."""
    el = _m("acc")
    apr = _m("accPr")
    ch = _m("chr")
    ch.set(f"{{{M_NS}}}val", chr_sym)
    apr.append(ch)
    el.append(apr)
    me = _m("e")
    _append_nodes(me, expr)
    el.append(me)
    return el


def m_eval_at(expr: MathArg, sub_expr: MathArg) -> OMMLNode:
    """Create a derivative evaluation bar with subscripted evaluation point."""
    return m_sub(m_delim(expr, beg="", end="|"), sub_expr)


def add_omml_equation(doc: Document, *nodes: MathArg) -> None:
    """Insert a centered, shaded native Word OMML display equation paragraph."""
    p = doc.add_paragraph()
    p.paragraph_format.left_indent = Inches(0.25)
    p.paragraph_format.right_indent = Inches(0.25)
    p.paragraph_format.space_before = Pt(5)
    p.paragraph_format.space_after = Pt(4)
    p.paragraph_format.keep_with_next = True

    pPr = p._p.get_or_add_pPr()
    shd = parse_xml(f'<w:shd {nsdecls("w")} w:fill="{LIGHT_BG_HEX}"/>')
    pBdr = parse_xml(
        f'<w:pBdr {nsdecls("w")}>'
        f'<w:left w:val="single" w:sz="18" w:space="8" w:color="{NAVY_HEX}"/>'
        f'<w:top w:val="single" w:sz="4" w:space="4" w:color="{BORDER_HEX}"/>'
        f'<w:bottom w:val="single" w:sz="4" w:space="4" w:color="{BORDER_HEX}"/>'
        f'<w:right w:val="single" w:sz="4" w:space="8" w:color="{BORDER_HEX}"/>'
        f'</w:pBdr>'
    )
    pPr.append(shd)
    pPr.append(pBdr)

    omath_para = _m("oMathPara")
    omath_para_pr = _m("oMathParaPr")
    jc = _m("jc")
    jc.set(f"{{{M_NS}}}val", "center")
    omath_para_pr.append(jc)
    omath_para.append(omath_para_pr)

    omath = _m("oMath")
    for node in nodes:
        _append_nodes(omath, node)
    omath_para.append(omath)
    p._p.append(omath_para)


def add_where_block(doc: Document, definitions: list[tuple[str, str]]) -> None:
    """Insert an unbulleted academic nomenclature ('Where') block after an equation."""
    if not definitions:
        return

    p_lead = doc.add_paragraph()
    p_lead.paragraph_format.left_indent = Inches(0)
    p_lead.paragraph_format.space_before = Pt(2)
    p_lead.paragraph_format.space_after = Pt(2)
    p_lead.paragraph_format.keep_with_next = True
    r_lead = p_lead.add_run("Where")
    r_lead.font.name = "Calibri"
    r_lead.font.size = Pt(10)
    r_lead.font.color.rgb = DARK

    last_idx = len(definitions) - 1
    for idx, (symbol, description) in enumerate(definitions):
        p = doc.add_paragraph()
        p.paragraph_format.left_indent = Inches(0.25)
        p.paragraph_format.space_before = Pt(0)
        p.paragraph_format.space_after = Pt(6) if idx == last_idx else Pt(2)
        p.paragraph_format.line_spacing = 1.12

        r_sym = p.add_run(symbol)
        r_sym.bold = True
        r_sym.font.name = "Cambria Math"
        r_sym.font.size = Pt(10)
        r_sym.font.color.rgb = NAVY

        r_desc = p.add_run(f" — {description}")
        r_desc.bold = False
        r_desc.font.name = "Calibri"
        r_desc.font.size = Pt(10)
        r_desc.font.color.rgb = DARK


def _init_doc(title: str, subtitle: str) -> Document:
    doc = Document()
    for section in doc.sections:
        section.top_margin = Inches(0.85)
        section.bottom_margin = Inches(0.85)
        section.left_margin = Inches(0.9)
        section.right_margin = Inches(0.9)

    normal = doc.styles["Normal"]
    normal.font.name = "Calibri"
    normal.font.size = Pt(10.5)
    normal.font.color.rgb = DARK

    p_title = doc.add_paragraph()
    p_title.paragraph_format.space_before = Pt(0)
    p_title.paragraph_format.space_after = Pt(4)
    r_t = p_title.add_run(title)
    r_t.bold = True
    r_t.font.name = "Calibri"
    r_t.font.size = Pt(20)
    r_t.font.color.rgb = NAVY

    p_sub = doc.add_paragraph()
    p_sub.paragraph_format.space_before = Pt(0)
    p_sub.paragraph_format.space_after = Pt(14)
    r_s = p_sub.add_run(subtitle)
    r_s.italic = True
    r_s.font.name = "Calibri"
    r_s.font.size = Pt(11)
    r_s.font.color.rgb = TEAL
    return doc


def _add_h1(doc: Document, text: str) -> None:
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(14)
    p.paragraph_format.space_after = Pt(6)
    p.paragraph_format.keep_with_next = True
    r = p.add_run(text)
    r.bold = True
    r.font.name = "Calibri"
    r.font.size = Pt(14)
    r.font.color.rgb = NAVY

    pPr = p._p.get_or_add_pPr()
    pBdr = parse_xml(
        f'<w:pBdr {nsdecls("w")}><w:bottom w:val="single" w:sz="6" w:space="3" w:color="{NAVY_HEX}"/></w:pBdr>'
    )
    pPr.append(pBdr)


def _add_h2(doc: Document, text: str) -> None:
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(10)
    p.paragraph_format.space_after = Pt(4)
    p.paragraph_format.keep_with_next = True
    r = p.add_run(text)
    r.bold = True
    r.font.name = "Calibri"
    r.font.size = Pt(11.5)
    r.font.color.rgb = TEAL


def _add_body(doc: Document, text: str) -> None:
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(2)
    p.paragraph_format.space_after = Pt(5)
    p.paragraph_format.line_spacing = 1.15
    r = p.add_run(text)
    r.font.name = "Calibri"
    r.font.size = Pt(10.5)
    r.font.color.rgb = DARK


def _add_bullet(doc: Document, lead: str, text: str) -> None:
    p = doc.add_paragraph(style="List Bullet")
    p.paragraph_format.space_before = Pt(1)
    p.paragraph_format.space_after = Pt(3)
    p.paragraph_format.line_spacing = 1.15
    r1 = p.add_run(lead)
    r1.bold = True
    r1.font.name = "Calibri"
    r1.font.size = Pt(10.5)
    r1.font.color.rgb = NAVY
    r2 = p.add_run(text)
    r2.font.name = "Calibri"
    r2.font.size = Pt(10.5)
    r2.font.color.rgb = DARK


def _set_cell_shading(cell, fill_hex: str) -> None:
    tcPr = cell._tc.get_or_add_tcPr()
    shd = parse_xml(f'<w:shd {nsdecls("w")} w:fill="{fill_hex}"/>')
    tcPr.append(shd)


def _set_table_borders(table) -> None:
    tblPr = table._tbl.tblPr
    borders = parse_xml(
        f'<w:tblBorders {nsdecls("w")}>'
        f'<w:top w:val="single" w:sz="6" w:space="0" w:color="{NAVY_HEX}"/>'
        f'<w:bottom w:val="single" w:sz="6" w:space="0" w:color="{NAVY_HEX}"/>'
        f'<w:insideH w:val="single" w:sz="4" w:space="0" w:color="{BORDER_HEX}"/>'
        f'<w:left w:val="none"/><w:right w:val="none"/><w:insideV w:val="none"/>'
        f'</w:tblBorders>'
    )
    tblPr.append(borders)


def _add_table(doc: Document, headers: list[str], rows: list[list[str]]) -> None:
    tbl = doc.add_table(rows=1 + len(rows), cols=len(headers))
    tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
    _set_table_borders(tbl)

    hdr_cells = tbl.rows[0].cells
    for idx, text in enumerate(headers):
        _set_cell_shading(hdr_cells[idx], NAVY_HEX)
        p = hdr_cells[idx].paragraphs[0]
        p.paragraph_format.space_before = Pt(3)
        p.paragraph_format.space_after = Pt(3)
        r = p.add_run(text)
        r.bold = True
        r.font.name = "Calibri"
        r.font.size = Pt(9.5)
        r.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)

    for r_idx, row_vals in enumerate(rows):
        cells = tbl.rows[r_idx + 1].cells
        bg = ROW_ALT_HEX if r_idx % 2 == 1 else "FFFFFF"
        for c_idx, val in enumerate(row_vals):
            _set_cell_shading(cells[c_idx], bg)
            p = cells[c_idx].paragraphs[0]
            p.paragraph_format.space_before = Pt(2.5)
            p.paragraph_format.space_after = Pt(2.5)
            r = p.add_run(val)
            r.font.name = "Calibri"
            r.font.size = Pt(9.5)
            r.font.color.rgb = DARK

    spacer = doc.add_paragraph()
    spacer.paragraph_format.space_before = Pt(0)
    spacer.paragraph_format.space_after = Pt(4)


def build_methodology_docx(out_path: Path) -> None:
    doc = _init_doc(
        "BloomPix v1.1.2 — Scientific Methodology & Mathematical Reference",
        "Publication-Grade SEM Fat-Bloom Metrology, Brightness/Contrast-Invariant Roughness, Kinetic Modeling & DSC",
    )

    # Section 1
    _add_h1(doc, "1. General Overview & Physical Basis (SEM as Pseudo-AFM)")
    _add_body(
        doc,
        "Chocolate fat bloom manifests on tempered cocoa-butter surfaces as polymorphic recrystallization "
        "(Form V → Form VI / β_VI), producing needle-, blade-, and rosette-shaped lipid crystals that protrude "
        "above the smooth tempered matrix. In Everhart–Thornley Secondary Electron (ETD SE) Scanning Electron "
        "Microscopy (SEM), local pixel intensity increases strongly with surface slope and micro-edge curvature "
        "(edge effect). When properly anchored to the detector noise floor and calibrated to physical specimen "
        "coordinates (µm), SE micrographs provide a high-throughput quantitative proxy for Atomic Force "
        "Microscopy (AFM) surface roughness descriptors (Sq amplitude and Sdq root-mean-square gradient).",
    )
    _add_body(
        doc,
        "Every Thermo Fisher / FEI Quattro S TIFF micrograph stores exact scan geometry inside private TIFF Tag "
        "34682 (INI text). BloomPix parses PixelWidth (Δx in µm/px), HFW (µm), ResolutionX, ResolutionY, HV (kV), "
        "WD (mm), Detector, and detector Contrast/Brightness directly from Tag 34682, and strictly crops the "
        "instrument metadata banner (arr[:ResolutionY, :ResolutionX]) before computing any intensity, spectral, or "
        "roughness statistic. For non-FEI microscopes or PNG/JPG exports lacking Tag 34682, an automatic bottom-banner "
        "detector isolates the databar and flags uncalibrated images until manual µm/px calibration is supplied.",
    )
    add_omml_equation(
        doc,
        m_sub(m_var("u"), m_op("raster")),
        m_op(" = "),
        m_frac([m_op("Δ"), m_var("x")], m_rad(m_op("12"))),
        m_op("   [µm]"),
    )
    add_where_block(
        doc,
        [
            ("u_raster", "fundamental single-pixel uniform raster quantization uncertainty [µm]"),
            ("Δx", "calibrated physical pixel pitch (PixelWidth) [µm/px]"),
            ("√12", "standard deviation divisor of a uniform rectangular quantization distribution [dimensionless]"),
        ],
    )

    # Section 2
    _add_h1(doc, "2. Preprocessing, Detector Noise Estimation & Brightness/Contrast Invariance")
    _add_body(
        doc,
        "Naive global Z-normalization (subtracting mean and dividing by total image standard deviation) or "
        "histogram equalization destroys quantitative bloom comparison: on a smooth control surface, total variance "
        "is dominated by detector shot noise, so Z-normalization artificially inflates noise to unit amplitude and "
        "makes smooth chocolate appear as rough as heavily bloomed chocolate.",
    )
    _add_body(
        doc,
        "Instead, BloomPix anchors every amplitude and slope metric to the high-frequency electronic/shot noise "
        "floor σ_noise estimated directly from each image using the Immerkaer (1996) 3×3 zero-mean Laplacian "
        "operator K_Im and a robust Median Absolute Deviation (MAD) estimator (excluding outer 1-px borders and "
        "any masked boundaries):",
    )
    add_omml_equation(
        doc,
        m_sub(m_var("K"), m_op("Im")),
        m_op(" = "),
        m_matrix(
            [
                [m_op("1"), m_op("−2"), m_op("1")],
                [m_op("−2"), m_op("4"), m_op("−2")],
                [m_op("1"), m_op("−2"), m_op("1")],
            ]
        ),
    )
    add_where_block(
        doc,
        [
            ("K_Im", "Immerkaer (1996) 3×3 zero-mean Laplacian noise-estimation convolution kernel [dimensionless]"),
        ],
    )
    add_omml_equation(
        doc,
        m_sub(m_var("σ"), m_op("noise")),
        m_op(" = "),
        m_op("max"),
        m_delim(
            [
                m_frac(
                    [
                        m_frac(
                            [
                                m_op("median"),
                                m_delim(
                                    [
                                        m_delim(
                                            [
                                                m_var("I"),
                                                m_op(" * "),
                                                m_sub(m_var("K"), m_op("Im")),
                                            ],
                                            beg="|",
                                            end="|",
                                        )
                                    ]
                                ),
                            ],
                            m_op("0.6745"),
                        )
                    ],
                    m_op("6"),
                ),
                m_op(", "),
                m_sup(m_op("10"), m_op("−9")),
            ]
        ),
    )
    add_where_block(
        doc,
        [
            ("σ_noise", "estimated high-frequency detector shot and electronic noise standard deviation [intensity units]"),
            ("I", "raw databar-cropped SEM grayscale intensity image [intensity units]"),
            ("*", "2D discrete spatial convolution operator"),
            ("0.6745", "Gaussian Median Absolute Deviation (MAD) to standard deviation scaling constant [dimensionless]"),
            ("6", "L2 norm (√36) of the Immerkaer kernel K_Im [dimensionless]"),
            ("10⁻⁹", "numerical stability floor preventing division by zero on constant synthetic images [intensity units]"),
        ],
    )
    _add_body(
        doc,
        "Affine Invariance Proof: Under manual SEM brightness/contrast adjustment, the zero-sum kernel eliminates "
        "additive offset identically (b * K_Im = 0) and scales linearly with contrast gain. Because macro "
        "illumination tilt is removed by Gaussian background subtraction and all physical relief metrics are divided "
        "by detector noise, both gain and offset cancel identically:",
    )
    add_omml_equation(
        doc,
        m_var("I"),
        m_op("′ = "),
        m_var("a"),
        m_op(" ⋅ "),
        m_var("I"),
        m_op(" + "),
        m_var("b"),
        m_op("   ⟹   "),
        m_sub(m_op("σ′"), m_op("noise")),
        m_op(" = "),
        m_var("a"),
        m_op(" ⋅ "),
        m_sub(m_var("σ"), m_op("noise")),
    )
    add_where_block(
        doc,
        [
            ("I′", "SEM intensity image after manual linear brightness/contrast adjustment [intensity units]"),
            ("I", "original unadjusted databar-cropped SEM intensity image [intensity units]"),
            ("a", "manual SEM contrast gain factor (a > 0) [dimensionless]"),
            ("b", "manual SEM brightness offset [intensity units]"),
            ("σ′_noise", "estimated detector noise standard deviation of the adjusted image I′ [intensity units]"),
            ("σ_noise", "estimated detector noise standard deviation of the original image I [intensity units]"),
        ],
    )
    add_omml_equation(
        doc,
        m_sub(m_var("I"), m_op("flat")),
        m_delim([m_var("x"), m_op(", "), m_var("y")]),
        m_op(" = "),
        m_var("I"),
        m_delim([m_var("x"), m_op(", "), m_var("y")]),
        m_op(" − "),
        m_sub(m_var("G"), m_sub(m_var("σ"), m_op("bg"))),
        m_delim([m_var("I")]),
        m_op(",    "),
        m_sub(m_var("I"), m_op("topo")),
        m_delim([m_var("x"), m_op(", "), m_var("y")]),
        m_op(" = "),
        m_sub(m_var("G"), m_sub(m_var("σ"), m_op("topo"))),
        m_delim([m_sub(m_var("I"), m_op("flat"))]),
    )
    add_where_block(
        doc,
        [
            ("I_flat(x, y)", "background-flattened SEM intensity at pixel coordinates (x, y) with macro charging/tilt removed [intensity units]"),
            ("I(x, y)", "raw databar-cropped SEM intensity at pixel coordinates (x, y) [intensity units]"),
            ("G_σ_bg", "macro background Gaussian smoothing operator with σ_bg = 0.12 × max(H, W) [px]"),
            ("I_topo(x, y)", "gently denoised topographic SEM intensity field used for relief, slope, and ridge evaluation [intensity units]"),
            ("G_σ_topo", "denoising Gaussian filter with σ_topo = max(1.2 px, 0.16 µm / Δx) suppressing sub-pixel detector noise [px]"),
        ],
    )
    _add_body(
        doc,
        "Display enhancement (1st–99th percentile contrast stretching to [0, 1]) is strictly isolated for visual "
        "rendering and is never passed into any measurement function.",
    )

    # Section 3
    _add_h1(doc, "3. Surface Roughness, Isotropic Gaussian Pseudo-AFM & Crystal Morphology Metrics")
    _add_body(
        doc,
        "All spatial filter scales are defined in physical micrometers (µm) and scaled dynamically via pixel pitch "
        "Δx = µm/px so 50 µm (2500×) and 200 µm (650×) magnifications remain physically consistent. All summary "
        "statistics are evaluated strictly over valid unmasked pixels.",
    )

    _add_h2(doc, "3.1 Relief Amplitude & Smooth Isotropic Gaussian Pseudo-AFM")
    add_omml_equation(
        doc,
        m_sub(m_op("TRNR"), m_op("Relief")),
        m_op(" = "),
        m_frac(
            [m_op("std"), m_delim([m_sub(m_var("I"), m_op("topo"))])],
            m_sub(m_var("σ"), m_op("noise")),
        ),
    )
    add_where_block(
        doc,
        [
            ("TRNR_Relief", "Topographic Relief-to-Noise Ratio, global amplitude proxy for AFM Sq roughness [dimensionless]"),
            ("std(I_topo)", "standard deviation of denoised topographic intensity I_topo over valid unmasked pixels [intensity units]"),
            ("σ_noise", "Immerkaer detector noise standard deviation [intensity units]"),
        ],
    )
    add_omml_equation(
        doc,
        m_sub(m_var("σ"), m_op("loc")),
        m_op(" = "),
        m_op("clip"),
        m_delim(
            [
                m_frac([m_op("1.0 "), m_op("µm")], [m_op("Δ"), m_var("x")]),
                m_op(",  "),
                m_op("4.0"),
                m_op(",  "),
                m_frac([m_op("min"), m_delim([m_var("H"), m_op(", "), m_var("W")])], m_op("16")),
            ]
        ),
    )
    add_where_block(
        doc,
        [
            ("σ_loc", "isotropic Gaussian smoothing standard deviation for the Pseudo-AFM local roughness map [px]"),
            ("1.0 µm", "fixed physical isotropic Pseudo-AFM smoothing radius [µm]"),
            ("Δx", "calibrated physical pixel pitch [µm/px]"),
            ("H, W", "cropped SEM micrograph height and width [px]"),
        ],
    )
    add_omml_equation(
        doc,
        m_op("LocTRNR"),
        m_delim([m_var("x"), m_op(", "), m_var("y")]),
        m_op(" = "),
        m_frac(
            m_rad(
                [
                    m_op("max"),
                    m_delim(
                        [
                            m_sub(m_var("G"), m_sub(m_var("σ"), m_op("loc"))),
                            m_delim([m_subsup(m_var("I"), m_op("topo"), m_op("2"))]),
                            m_op(" − "),
                            m_sup(
                                m_delim(
                                    [
                                        m_sub(m_var("G"), m_sub(m_var("σ"), m_op("loc"))),
                                        m_delim([m_sub(m_var("I"), m_op("topo"))]),
                                    ],
                                    beg="[",
                                    end="]",
                                ),
                                m_op("2"),
                            ),
                            m_op(",  "),
                            m_op("0"),
                        ]
                    ),
                ]
            ),
            m_sub(m_var("σ"), m_op("noise")),
        ),
    )
    add_where_block(
        doc,
        [
            ("LocTRNR(x, y)", "local Pseudo-AFM roughness value at pixel (x, y) [dimensionless]"),
            ("G_σ_loc", "isotropic Gaussian spatial averaging operator with kernel radius σ_loc [px]"),
            ("I_topo", "denoised topographic SEM intensity image [intensity units]"),
            ("σ_noise", "Immerkaer detector noise standard deviation [intensity units]"),
        ],
    )
    add_omml_equation(
        doc,
        m_sub(m_op("Bloom_Coverage"), m_op("%")),
        m_op(" = "),
        m_op("100 × "),
        m_op("mean"),
        m_delim(
            [
                m_op("LocTRNR"),
                m_delim([m_var("x"), m_op(", "), m_var("y")]),
                m_op(" > "),
                m_sub(m_var("T"), m_op("ctrl,95")),
            ]
        ),
        m_op("   [%]"),
    )
    add_where_block(
        doc,
        [
            ("Bloom_Coverage_%", "percentage of valid unmasked chocolate surface area classified as bloomed [%]"),
            ("LocTRNR(x, y)", "local Pseudo-AFM roughness value at pixel (x, y) [dimensionless]"),
            ("T_ctrl,95", "95th percentile of LocTRNR across all valid pixels of Week 0 control scans for the active magnification scale [dimensionless]"),
        ],
    )
    _add_body(
        doc,
        "Using an isotropic Gaussian spatial kernel (≈ 9.3 px at 50 µm and 4.0 px at 200 µm) eliminates square "
        "boxcar directional ringing and produces smooth Pseudo-AFM topography maps while anchoring fresh tempered "
        "chocolate to ≈ 5.0% baseline coverage.",
    )

    _add_h2(doc, "3.2 Mesoscale Bandpass, Slope, Ridge & Structure Tensor Descriptors")
    add_omml_equation(
        doc,
        m_op("Meso_SNR"),
        m_op(" = "),
        m_frac(
            [
                m_op("std"),
                m_delim(
                    [
                        m_sub(m_var("G"), m_sub(m_var("σ"), m_op("small"))),
                        m_delim([m_sub(m_var("I"), m_op("flat"))]),
                        m_op(" − "),
                        m_sub(m_var("G"), m_sub(m_var("σ"), m_op("large"))),
                        m_delim([m_sub(m_var("I"), m_op("flat"))]),
                    ]
                ),
            ],
            m_sub(m_var("σ"), m_op("noise")),
        ),
    )
    add_where_block(
        doc,
        [
            ("Meso_SNR", "mesoscale Difference-of-Gaussians (DoG) crystal-cluster relief-to-noise ratio [dimensionless]"),
            ("G_σ_small", "fine-scale Gaussian operator with σ_small = max(1.5 px, 0.27 µm / Δx) [px]"),
            ("G_σ_large", "coarse-scale Gaussian operator with σ_large = max(10.0 px, 2.7 µm / Δx) [px]"),
            ("I_flat", "background-flattened SEM intensity image [intensity units]"),
            ("σ_noise", "Immerkaer detector noise standard deviation [intensity units]"),
        ],
    )
    add_omml_equation(
        doc,
        m_op("Grad_SNR"),
        m_op(" = "),
        m_frac(
            m_rad(
                [
                    m_op("mean"),
                    m_delim(
                        [
                            m_subsup(m_var("G"), m_var("x"), m_op("2")),
                            m_op(" + "),
                            m_subsup(m_var("G"), m_var("y"), m_op("2")),
                        ]
                    ),
                ]
            ),
            m_sub(m_var("σ"), m_op("noise")),
        ),
    )
    add_where_block(
        doc,
        [
            ("Grad_SNR", "noise-normalized root-mean-square topographic gradient, proxy for AFM Sdq slope [dimensionless]"),
            ("G_x, G_y", "horizontal and vertical Scharr spatial derivatives of I_topo [intensity units/px]"),
            ("σ_noise", "Immerkaer detector noise standard deviation [intensity units]"),
        ],
    )
    add_omml_equation(
        doc,
        m_op("Blade_Index"),
        m_op(" = "),
        m_op("mean"),
        m_delim(
            [
                m_op("Sato"),
                m_delim(
                    [
                        m_frac(
                            [
                                m_sub(m_var("I"), m_op("topo")),
                                m_op(" − "),
                                m_op("mean"),
                                m_delim([m_sub(m_var("I"), m_op("topo"))]),
                            ],
                            m_sub(m_var("σ"), m_op("noise")),
                        ),
                        m_op("; "),
                        m_sub(m_var("σ"), m_op("1")),
                        m_op(", "),
                        m_sub(m_var("σ"), m_op("2")),
                        m_op(", "),
                        m_sub(m_var("σ"), m_op("3")),
                    ]
                ),
            ]
        ),
    )
    add_where_block(
        doc,
        [
            ("Blade_Index", "mean multiscale ridge response quantifying bright protruding fat-bloom crystal needles and blades [dimensionless]"),
            ("Sato(·)", "multiscale Sato Hessian tubeness/ridge filter for bright linear structures [dimensionless]"),
            ("σ_1, σ_2, σ_3", "physical ridge scales corresponding to 0.16, 0.32, and 0.54 µm (clamped in pixels to max(1.2 px, 0.16/Δx), max(2.2 px, 0.32/Δx), and max(3.5 px, 0.54/Δx)) [px]"),
            ("I_topo", "denoised topographic SEM intensity image [intensity units]"),
            ("σ_noise", "Immerkaer detector noise standard deviation [intensity units]"),
        ],
    )
    add_omml_equation(
        doc,
        m_op("Anisotropy_Coh"),
        m_op(" = "),
        m_op("mean"),
        m_delim(
            [
                m_frac(
                    m_rad(
                        [
                            m_sup(
                                m_delim([m_sub(m_var("J"), m_var("xx")), m_op(" − "), m_sub(m_var("J"), m_var("yy"))]),
                                m_op("2"),
                            ),
                            m_op(" + 4"),
                            m_sup(m_sub(m_var("J"), m_var("xy")), m_op("2")),
                        ]
                    ),
                    [
                        m_sub(m_var("J"), m_var("xx")),
                        m_op(" + "),
                        m_sub(m_var("J"), m_var("yy")),
                    ],
                )
            ]
        ),
    )
    add_where_block(
        doc,
        [
            ("Anisotropy_Coh", "noise-independent mean Structure Tensor coherency measuring directional crystal blade alignment [0–1, dimensionless]"),
            ("J_xx, J_yy, J_xy", "components of the Gaussian-smoothed Structure Tensor computed on noise-normalized topography with σ_st = max(2.5 px, 0.38 µm / Δx) (denominator guarded by max(J_xx + J_yy, 10⁻¹²))"),
        ],
    )

    _add_h2(doc, "3.3 2D FFT Radial PSD, Spatial Correlation Length & Composite Bloom Index (CBI)")
    add_omml_equation(
        doc,
        m_sub(m_var("f"), m_op("µm⁻¹")),
        m_op(" = "),
        m_frac(
            m_sub(m_var("f"), m_op("px")),
            [m_sub(m_var("N"), m_op("ref")), m_op(" ⋅ Δ"), m_var("x")],
        ),
        m_op(",    "),
        m_op("PSD_logSNR"),
        m_op(" = "),
        m_sub(m_op("log"), m_op("10")),
        m_delim(
            [
                m_frac(
                    [m_op("mean"), m_delim([m_op("PSD"), m_delim([m_sub(m_var("f"), m_op("struct"))], beg="[", end="]")])],
                    [m_op("mean"), m_delim([m_op("PSD"), m_delim([m_sub(m_var("f"), m_op("noise"))], beg="[", end="]")])],
                )
            ]
        ),
    )
    add_where_block(
        doc,
        [
            ("f_µm⁻¹", "calibrated physical radial spatial frequency [µm⁻¹]"),
            ("f_px", "radial 2D FFT spatial frequency bin index [cycles/window]"),
            ("N_ref", "2D FFT window dimension [px]"),
            ("Δx", "calibrated physical pixel pitch [µm/px]"),
            ("PSD_logSNR", "base-10 logarithmic ratio of structural to noise radial spectral power [log₁₀, dimensionless]"),
            ("PSD[f_struct]", "azimuthally averaged radial power spectral density across the mid-frequency structural band"),
            ("PSD[f_noise]", "azimuthally averaged radial power spectral density across the high-frequency detector noise band"),
        ],
    )
    add_omml_equation(
        doc,
        m_sub(m_op("log"), m_op("10")),
        m_op("PSD"),
        m_delim([m_var("f")]),
        m_op(" = −"),
        m_var("β"),
        m_op(" ⋅ "),
        m_sub(m_op("log"), m_op("10")),
        m_delim([m_var("f")]),
        m_op(" + "),
        m_var("c"),
        m_op(",    "),
        m_var("f"),
        m_op(" ∈ [5, 0.35 ⋅ "),
        m_sub(m_var("r"), m_op("max")),
        m_op("] ⋅ Δ"),
        m_var("f"),
    )
    add_where_block(
        doc,
        [
            ("PSD(f)", "azimuthally averaged 2D radial power spectral density at spatial frequency f"),
            ("f", "calibrated physical radial spatial frequency [µm⁻¹]"),
            ("β", "mid-band power-law spectral decay slope (PSD_Beta) characterizing surface scaling [dimensionless]"),
            ("c", "ordinary least-squares log-log regression intercept [dimensionless]"),
            ("r_max, Δf", "maximum radial Nyquist bin index [px] and physical frequency bin spacing Δf = 1 / (N_ref · Δx) [µm⁻¹]"),
        ],
    )
    add_omml_equation(
        doc,
        m_sub(m_var("L"), m_op("corr")),
        m_op(" = "),
        m_sub(m_var("r"), m_op("1/e")),
        m_op(" ⋅ Δ"),
        m_var("x"),
        m_op("   [µm]"),
    )
    add_where_block(
        doc,
        [
            ("L_corr", "characteristic spatial correlation length (Corr_Len_um) of crystal domains [µm]"),
            ("r_1/e", "radial lag where the normalized 2D autocorrelation function decays to 1/e ≈ 0.368 [px]"),
            ("Δx", "calibrated physical pixel pitch [µm/px]"),
        ],
    )
    add_omml_equation(
        doc,
        m_op("CBI"),
        m_op(" = "),
        m_frac(m_op("1"), m_op("8")),
        m_nary(
            "∑",
            [m_var("m"), m_op("=1")],
            m_op("8"),
            [
                m_op("max"),
                m_delim(
                    [
                        m_frac(
                            [m_sub(m_var("x"), m_var("m")), m_op(" − "), m_sub(m_var("μ"), [m_var("m"), m_op(",ctrl")])],
                            [m_sub(m_var("P"), m_op("95,m")), m_op(" − "), m_sub(m_var("μ"), [m_var("m"), m_op(",ctrl")])],
                        ),
                        m_op(" × 100,  −20"),
                    ]
                ),
            ],
        ),
    )
    add_where_block(
        doc,
        [
            ("CBI", "Composite Bloom Index anchored to ≈ 0 for Week 0 controls and uncapped above 100 for severe late-stage blooming [pts]"),
            ("m", "index over the 8 core monotonic bloom metrics (TRNR_Relief, LocTRNR_Med, Meso_SNR, Grad_SNR, Blade_Index, Anisotropy_Coh, PSD_Struct_logSNR, Corr_Len_um)"),
            ("x_m", "measured image value of metric m"),
            ("μ_m,ctrl", "Week 0 control mean value of metric m for the active magnification scale"),
            ("P_95,m", "95th percentile upper normalization anchor of metric m across all valid non-HV-mismatched scans"),
        ],
    )
    add_omml_equation(
        doc,
        m_op("Geom_Bloom_Index"),
        m_op(" = "),
        m_frac(m_op("1"), m_op("3")),
        m_nary(
            "∑",
            [m_var("g"), m_op("=1")],
            m_op("3"),
            [
                m_op("max"),
                m_delim(
                    [
                        m_frac(
                            [m_sub(m_var("x"), m_var("g")), m_op(" − "), m_sub(m_var("μ"), [m_var("g"), m_op(",ctrl")])],
                            [m_sub(m_var("P"), m_op("95,g")), m_op(" − "), m_sub(m_var("μ"), [m_var("g"), m_op(",ctrl")])],
                        ),
                        m_op(" × 100,  −20"),
                    ]
                ),
            ],
        ),
    )
    add_where_block(
        doc,
        [
            ("Geom_Bloom_Index", "HV-resilient geometric/spectral bloom index serving as a noise-free cross-check against CBI [pts]"),
            ("g", "index over the 3 noise-free geometric/spectral metrics (Anisotropy_Coh, Corr_Len_um, PSD_Beta)"),
            ("x_g", "measured image value of geometric metric g"),
            ("μ_g,ctrl", "Week 0 control mean value of metric g for the active magnification scale"),
            ("P_95,g", "95th percentile upper normalization anchor of metric g across all valid non-HV-mismatched scans"),
        ],
    )

    _add_table(
        doc,
        ["Metric", "Units", "Physical Interpretation", "Bloom Trend"],
        [
            ["TRNR_Relief", "—", "Global topographic relief amplitude / detector noise (Sq proxy)", "Increases"],
            ["LocTRNR_Med / P90", "—", "Median and 90th percentile of Gaussian Pseudo-AFM map (σ = 1.0 µm)", "Increases"],
            ["Bloom_Coverage_%", "%", "Surface fraction exceeding Week 0 control 95th percentile", "5% → 90%+"],
            ["Meso_SNR", "—", "Mesoscale (0.27–2.7 µm) DoG crystal-cluster relief / noise", "Increases"],
            ["Grad_SNR", "—", "Denoised Scharr RMS slope / noise (Sdq proxy)", "Increases"],
            ["Blade_Index", "—", "Multiscale Sato Hessian ridge response to crystal needles", "Increases"],
            ["Anisotropy_Coh", "0–1", "Structure Tensor directional coherency of crystal blades", "Increases"],
            ["PSD_Struct_logSNR", "log₁₀", "2D FFT structural-to-noise radial power ratio", "Increases"],
            ["PSD_Beta", "—", "Mid-band radial PSD power-law decay exponent β", "Struct.-dep."],
            ["Corr_Len_um", "µm", "Characteristic spatial domain length (2D ACF 1/e decay)", "Increases"],
            ["CBI", "pts", "Composite Bloom Index across 8 monotonic metrics (Control ≈ 0)", "0 → 100+"],
            ["Geom_Bloom_Index", "pts", "HV-resilient mean normalized score across geometric/spectral subset (Anisotropy_Coh, Corr_Len_um, PSD_Beta)", "0 → 100+"],
        ],
    )

    # Section 4
    _add_h1(doc, "4. Kinetic Modeling, Statistical Ranking, PCA & HV Consistency Audit")
    _add_body(
        doc,
        "When a study provides shared Week 0 controls (data/control/control_*), BloomPix expands those baseline "
        "replicates to every treatment lacking its own Week 0 scans and aggregates Mean, SD, and SEM = SD / √n per "
        "(treatment, week). Sigmoidal bloom progression is modeled using a bounded 4-parameter logistic function "
        "fitted via multi-start nonlinear least squares (scipy.optimize.curve_fit):",
    )
    add_omml_equation(
        doc,
        m_var("y"),
        m_delim([m_var("t")]),
        m_op(" = "),
        m_sub(m_var("y"), m_op("0")),
        m_op(" + "),
        m_frac(
            [m_sub(m_var("y"), m_op("max")), m_op(" − "), m_sub(m_var("y"), m_op("0"))],
            [
                m_op("1 + "),
                m_op("exp"),
                m_delim([m_op("−"), m_var("k"), m_delim([m_var("t"), m_op(" − "), m_sub(m_var("t"), m_op("1/2"))])]),
            ],
        ),
        m_op(",    "),
        m_sub(m_var("t"), m_op("lag")),
        m_op(" = "),
        m_op("max"),
        m_delim([m_op("0,  "), m_sub(m_var("t"), m_op("1/2")), m_op(" − "), m_frac(m_op("2.197"), m_var("k"))]),
    )
    add_where_block(
        doc,
        [
            ("y(t)", "modeled bloom metric value at storage time t [metric units]"),
            ("t", "storage duration [weeks]"),
            ("y_0", "lower baseline asymptote corresponding to fresh tempered chocolate [metric units]"),
            ("y_max", "upper saturation plateau asymptote of mature fat bloom [metric units]"),
            ("k", "logistic growth rate constant [weeks⁻¹]"),
            ("t_1/2", "inflection / half-maximal bloom time where y(t_1/2) = (y_0 + y_max) / 2 [weeks]"),
            ("t_lag", "analytical 10%-rise bloom induction lag time [weeks]"),
            ("2.197", "exact logistic 10%-amplitude crossing factor ln(9) ≈ 2.197 [dimensionless]"),
        ],
    )
    add_omml_equation(
        doc,
        m_sub(m_op("AUC"), m_op("norm")),
        m_op(" = "),
        m_frac(m_op("1"), [m_sub(m_var("t"), m_op("max")), m_op(" − "), m_sub(m_var("t"), m_op("min"))]),
        m_nary(
            "∫",
            m_sub(m_var("t"), m_op("min")),
            m_sub(m_var("t"), m_op("max")),
            [m_var("y"), m_delim([m_var("t")]), m_op(" "), m_var("dt")],
        ),
    )
    add_where_block(
        doc,
        [
            ("AUC_norm", "time-normalized area under the kinetic progression curve used for objective treatment ranking [metric units]"),
            ("t_min, t_max", "first and last fitted storage timepoints [weeks]"),
            ("y(t)", "kinetic trajectory of the selected bloom metric as a function of storage week t [metric units]"),
        ],
    )
    _add_body(
        doc,
        "Trajectory Classification & Ranking Rules: (1) If CBI rise (max − y₀) < 20.0 (or max Bloom Coverage < 15%), "
        "the treatment is classified as 'Suppressed / No Bloom Onset' with t_lag = None; (2) A sigmoidal fit is "
        "accepted ('Fitted') only when R² ≥ 0.50 and k < 4.95; (3) Otherwise it is labeled 'Mild / Non-Sigmoidal "
        "Drift', reporting t_lag only when CBI ≥ 25.0 (or Coverage ≥ 15%) is sustained across ≥ 2 consecutive "
        "non-HV-mismatched weeks. Treatments are ranked objectively by lowest AUC_norm (Rank #1 = strongest bloom "
        "suppression).",
    )
    _add_body(
        doc,
        "HV Consistency Audit: Scans whose accelerating voltage deviates from the dataset mode by |HV − HV_mode| > "
        "0.25 kV (e.g., 10 kV scans among a 5 kV time series) are flagged as HV_Mismatch. Higher beam voltage alters "
        "electron penetration depth and subsurface scattering SNR, producing artificial step shifts in TRNR and CBI. "
        "By default, BloomPix excludes HV_Mismatch weeks from kinetic fits, PCA, hypothesis tests, and SEM×DSC "
        "correlations while plotting them as hollow diamond markers for full transparency.",
    )
    _add_body(
        doc,
        "Post-Induction Statistics & PCA: For weeks ≥ Min_Week (default 8), treatments are compared via One-Way "
        "ANOVA (F, p), Kruskal–Wallis (H, p), and pairwise Welch t-tests & Mann–Whitney U tests. Simultaneously, "
        "2D PCA (StandardScaler over 9 invariant metrics) maps surface trajectories from smooth control to bloomed "
        "crystal morphology.",
    )

    # Section 5
    _add_h1(doc, "5. Optional DSC Thermal Analysis & SEM×DSC Correlation Standard")
    _add_body(
        doc,
        "BloomPix parses raw TA Instruments Discovery DSC tab-delimited .txt thermograms directly (as well as "
        "pre-computed CSV/Excel tables). Duplicate rounded temperatures are averaged before sorting to ensure "
        "derivative stability, and aborted/incomplete runs lacking either baseline window are flagged as "
        "'Incomplete / Aborted Run' without fabricating numbers.",
    )
    _add_body(
        doc,
        "Smart Auto-Baseline & Realistic QC: Rather than relying on brittle fixed windows, BloomPix computes the "
        "90th-percentile heat-flow reference HF_ref inside [21.6, 23.0] °C (strictly after the 20.7–21.5 °C "
        "equilibration transient), retains only 0.6 °C sliding windows inside [21.6, 24.2] °C whose median remains "
        "within 0.006 W/g of HF_ref (preventing jumps onto post-drop shoulders), and chooses the flattest window "
        "(min |dHF/dT|) as the left anchor (T_lo, HF_lo). The right anchor (T_hi, HF_hi) is chosen inside "
        "[38.0, 45.0] °C via a 1.5 °C sliding window minimizing slope and residual noise. Automatic QC sets "
        "'Review Baseline' only for genuine issues (baseline overshoot > 5.0%, T_onset < T_lo + 0.05 °C, ΔH ≤ 1.0 J/g, "
        "or NaN onset); bimodal melting (≥ 2 peaks ≥ 2.0 °C apart, prominence ≥ 15%) is reported purely as "
        "informational metadata, and valid manual overrides resolve to 'OK (Manual)'.",
    )

    _add_h2(doc, "5.1 Summary Table of All DSC & Correlation Metrics (\"What is What\")")
    _add_table(
        doc,
        ["Parameter / Metric", "Units", "Physical & Statistical Interpretation"],
        [
            ["T_lo_used / T_hi_used", "°C", "Automatically detected pre-melting ([21.6, 24.2] °C) and post-melting ([38.0, 45.0] °C) linear baseline anchor temperatures (or manual override values)."],
            ["T_onset_C", "°C", "Extrapolated melting onset temperature (ASTM E794 steepest leading-edge tangent intercept with baseline); indicates initial crystal destabilization / early-melting polymorphs."],
            ["T_peak_C", "°C", "Peak maximum melting temperature of the endothermic transition; reflects the dominant cocoa-butter polymorph (β_V ≈ 32–34 °C, β_VI > 34 °C, softened/migrated fat < 30 °C)."],
            ["T_endset_C", "°C", "Extrapolated melting completion temperature (ASTM E794 steepest trailing-edge tangent intercept with baseline)."],
            ["Delta_T_C", "°C", "Total melting range width (T_endset − T_onset); increases with polymorphic heterogeneity and mixed crystal sizes."],
            ["FWHM_C", "°C", "Full Width at Half Maximum of the endothermic peak; robust measure of phase-transition broadening during fat bloom."],
            ["Delta_H_J_g", "J/g", "Specific melting enthalpy obtained by integrating endothermic heat flow over time; measures overall crystalline fat content / crystal lattice integrity."],
            ["High_Melt_gt34C_pct", "%", "High-melting enthalpy fraction at T ≥ T_cutoff (default 34.0 °C); quantitative proxy for high-melting β_VI polymorph formation."],
            ["baseline_overshoot_pct", "%", "Percentage of points in [T_lo, T_hi] where the curve exceeds the baseline by > 0.004 W/g; automatic baseline QC check."],
            ["is_bimodal", "True/False", "Informational flag indicating ≥ 2 distinct endothermic peaks (≥ 2.0 °C separation, prominence ≥ 15%); indicates multi-polymorph melting (not a QC error)."],
            ["qc_flag", "OK / OK (Manual) / Review Baseline", "Automated baseline quality status separating valid auto/manual baselines from curves needing baseline inspection."],
            ["Pearson r", "−1 to +1", "Linear correlation coefficient between matched SEM and DSC weekly means (reported with two-sided p_pearson)."],
            ["Spearman ρ", "−1 to +1", "Rank-order monotonic correlation coefficient resilient to nonlinear bloom progression and outliers (reported with two-sided p_spearman)."],
        ],
    )

    _add_h2(doc, "5.2 Complete Mathematical Formulations (DSC & SEM×DSC Correlation)")
    # 1. Linear Baseline Construction
    add_omml_equation(
        doc,
        m_sub(m_op("HF"), m_op("base")),
        m_delim([m_var("T")]),
        m_op(" = "),
        m_sub(m_op("HF"), m_op("lo")),
        m_op(" + "),
        m_frac(
            [m_sub(m_op("HF"), m_op("hi")), m_op(" − "), m_sub(m_op("HF"), m_op("lo"))],
            [m_sub(m_var("T"), m_op("hi")), m_op(" − "), m_sub(m_var("T"), m_op("lo"))],
        ),
        m_op(" ⋅ "),
        m_delim([m_var("T"), m_op(" − "), m_sub(m_var("T"), m_op("lo"))]),
    )
    add_where_block(
        doc,
        [
            ("HF_base(T)", "linearly interpolated thermal baseline heat flow at temperature T [W/g]"),
            ("T", "sample temperature [°C]"),
            ("(T_lo, HF_lo), (T_hi, HF_hi)", "automatically detected or manually overridden pre-melting and post-melting baseline anchor coordinates [°C, W/g]"),
        ],
    )
    # 2. Positive Endothermic Signal
    add_omml_equation(
        doc,
        m_op("endo"),
        m_delim([m_var("T")]),
        m_op(" = "),
        m_sub(m_op("HF"), m_op("base")),
        m_delim([m_var("T")]),
        m_op(" − "),
        m_op("HF"),
        m_delim([m_var("T")]),
        m_op("   [W/g]"),
    )
    add_where_block(
        doc,
        [
            ("endo(T)", "positive endothermic melting heat-flow signal above the linear baseline [W/g]"),
            ("HF_base(T)", "linearly interpolated baseline heat flow at temperature T [W/g]"),
            ("HF(T)", "measured normalized DSC heat flow (endothermic down convention) [W/g]"),
        ],
    )
    # 3. Melting Peak Temperature
    add_omml_equation(
        doc,
        m_sub(m_var("T"), m_op("peak")),
        m_op(" = "),
        m_lim_low(
            m_op("arg max"),
            [m_var("T"), m_op(" ∈ ["), m_sub(m_var("T"), m_op("lo")), m_op(", "), m_sub(m_var("T"), m_op("hi")), m_op("]")],
        ),
        m_op(" "),
        m_sub(m_op("endo"), m_op("smooth")),
        m_delim([m_var("T")]),
        m_op("   [°C]"),
    )
    add_where_block(
        doc,
        [
            ("T_peak", "peak maximum melting temperature of the endothermic transition [°C]"),
            ("endo_smooth(T)", "Gaussian-smoothed endothermic signal (σ = 6 grid points) on the 1000-point uniform temperature grid inside [T_lo, T_hi] [W/g]"),
        ],
    )
    # 4. Extrapolated Onset & Endset Temperatures (ASTM E794)
    add_omml_equation(
        doc,
        m_sub(m_var("T"), m_op("onset")),
        m_op(" = "),
        m_subsup(m_var("T"), m_op("lead"), m_op("*")),
        m_op(" − "),
        m_frac(
            [m_sub(m_op("endo"), m_op("smooth")), m_delim([m_subsup(m_var("T"), m_op("lead"), m_op("*"))])],
            m_eval_at(
                m_frac([m_var("d"), m_op(" "), m_sub(m_op("endo"), m_op("smooth"))], [m_var("dT")]),
                m_subsup(m_var("T"), m_op("lead"), m_op("*")),
            ),
        ),
        m_op("   [°C]"),
    )
    add_where_block(
        doc,
        [
            ("T_onset", "ASTM E794 extrapolated melting onset temperature [°C]"),
            ("T*_lead", "temperature of maximum rising slope on the leading peak edge within 20%–80% of peak height [°C]"),
            ("d endo_smooth / dT", "first temperature derivative of the smoothed endothermic signal [W/(g·°C)]"),
        ],
    )
    add_omml_equation(
        doc,
        m_sub(m_var("T"), m_op("endset")),
        m_op(" = "),
        m_subsup(m_var("T"), m_op("trail"), m_op("*")),
        m_op(" − "),
        m_frac(
            [m_sub(m_op("endo"), m_op("smooth")), m_delim([m_subsup(m_var("T"), m_op("trail"), m_op("*"))])],
            m_eval_at(
                m_frac([m_var("d"), m_op(" "), m_sub(m_op("endo"), m_op("smooth"))], [m_var("dT")]),
                m_subsup(m_var("T"), m_op("trail"), m_op("*")),
            ),
        ),
        m_op("   [°C]"),
    )
    add_where_block(
        doc,
        [
            ("T_endset", "ASTM E794 extrapolated melting completion temperature [°C]"),
            ("T*_trail", "temperature of steepest falling slope on the trailing peak edge within 20%–80% of peak height [°C]"),
            ("d endo_smooth / dT", "first temperature derivative of the smoothed endothermic signal [W/(g·°C)]"),
        ],
    )
    # 5. Melting Range Width & FWHM
    add_omml_equation(
        doc,
        m_op("Δ"),
        m_var("T"),
        m_op(" = "),
        m_sub(m_var("T"), m_op("endset")),
        m_op(" − "),
        m_sub(m_var("T"), m_op("onset")),
        m_op(",    "),
        m_op("FWHM"),
        m_op(" = "),
        m_sub(m_var("T"), m_op("right,0.5")),
        m_op(" − "),
        m_sub(m_var("T"), m_op("left,0.5")),
        m_op("   [°C]"),
    )
    add_where_block(
        doc,
        [
            ("ΔT", "total extrapolated melting range width [°C]"),
            ("FWHM", "Full Width at Half Maximum of the endothermic melting peak [°C]"),
            ("T_left,0.5, T_right,0.5", "leading and trailing temperatures where endo_smooth(T) crosses 50% of peak height [°C]"),
        ],
    )
    # 6. Specific Melting Enthalpy (t = time_min * 60 s) & High-Melting Fraction
    add_omml_equation(
        doc,
        m_op("Δ"),
        m_var("H"),
        m_op(" = "),
        m_nary(
            "∫",
            m_sub(m_var("t"), m_op("lo")),
            m_sub(m_var("t"), m_op("hi")),
            [
                m_op("max"),
                m_delim(
                    [
                        m_sub(m_op("HF"), m_op("base")),
                        m_delim([m_var("t")]),
                        m_op(" − "),
                        m_op("HF"),
                        m_delim([m_var("t")]),
                        m_op(",  0"),
                    ]
                ),
                m_op(" "),
                m_var("dt"),
            ],
        ),
        m_op("  [J/g],    "),
        m_sub(m_var("F"), m_op(">34°C")),
        m_op(" = "),
        m_frac(
            m_sub([m_op("Δ"), m_var("H")], m_op("T ≥ 34°C")),
            [m_op("Δ"), m_var("H")],
        ),
        m_op(" × 100%"),
    )
    add_where_block(
        doc,
        [
            ("ΔH", "total specific melting enthalpy integrated over time (W/g × s = J/g) [J/g]"),
            ("t_lo, t_hi", "elapsed timestamps corresponding to T_lo and T_hi, where t = time_min × 60 [s]"),
            ("F_>34°C", "high-melting enthalpy fraction above cutoff (default 34.0 °C) [%]"),
            ("ΔH_T≥34°C", "partial specific melting enthalpy integrated for T ≥ 34.0 °C [J/g]"),
        ],
    )
    # 7. Automatic Baseline Overshoot QC Criterion
    add_omml_equation(
        doc,
        m_sub(m_op("Overshoot"), m_op("%")),
        m_op(" = "),
        m_frac(m_op("100"), m_var("N")),
        m_nary(
            "∑",
            [m_var("i"), m_op("=1")],
            m_var("N"),
            [
                m_op("𝕀"),
                m_delim(
                    [
                        m_op("HF"),
                        m_delim([m_sub(m_var("T"), m_var("i"))]),
                        m_op(" > "),
                        m_sub(m_op("HF"), m_op("base")),
                        m_delim([m_sub(m_var("T"), m_var("i"))]),
                        m_op(" + 0.004"),
                    ]
                ),
            ],
        ),
        m_op("   [%]"),
    )
    add_where_block(
        doc,
        [
            ("Overshoot_%", "percentage of thermogram samples inside [T_lo, T_hi] exceeding the linear baseline beyond noise tolerance [%]"),
            ("N", "number of temperature points inside [T_lo, T_hi] [dimensionless]"),
            ("𝕀(·)", "indicator function equal to 1 when the condition holds and 0 otherwise [dimensionless]"),
            ("0.004 W/g", "detector noise tolerance margin above the linear baseline [W/g]"),
        ],
    )
    # 8. Pearson r and Spearman rho
    add_omml_equation(
        doc,
        m_var("r"),
        m_op(" = "),
        m_frac(
            [
                m_nary(
                    "∑",
                    [m_var("i"), m_op("=1")],
                    m_var("n"),
                    [
                        m_delim([m_sub(m_var("x"), m_var("i")), m_op(" − "), m_acc(m_var("x"))]),
                        m_delim([m_sub(m_var("y"), m_var("i")), m_op(" − "), m_acc(m_var("y"))]),
                    ],
                )
            ],
            [
                m_rad(
                    m_nary(
                        "∑",
                        [m_var("i"), m_op("=1")],
                        m_var("n"),
                        [m_sup(m_delim([m_sub(m_var("x"), m_var("i")), m_op(" − "), m_acc(m_var("x"))]), m_op("2"))],
                    )
                ),
                m_rad(
                    m_nary(
                        "∑",
                        [m_var("i"), m_op("=1")],
                        m_var("n"),
                        [m_sup(m_delim([m_sub(m_var("y"), m_var("i")), m_op(" − "), m_acc(m_var("y"))]), m_op("2"))],
                    )
                ),
            ],
        ),
    )
    add_where_block(
        doc,
        [
            ("r", "Pearson product-moment linear correlation coefficient [−1 to +1, dimensionless]"),
            ("x_i, y_i", "matched weekly mean SEM metric and DSC parameter for pair i"),
            ("x̄, ȳ", "sample means of the matched SEM and DSC vectors"),
            ("n", "number of matched (treatment, week) pairs (evaluated for n ≥ 3) [dimensionless]"),
        ],
    )
    add_omml_equation(
        doc,
        m_var("ρ"),
        m_op(" = 1 − "),
        m_frac(
            [
                m_op("6 "),
                m_nary(
                    "∑",
                    [m_var("i"), m_op("=1")],
                    m_var("n"),
                    [m_subsup(m_var("d"), m_var("i"), m_op("2"))],
                ),
            ],
            [m_var("n"), m_delim([m_sup(m_var("n"), m_op("2")), m_op(" − 1")])],
        ),
    )
    add_where_block(
        doc,
        [
            ("ρ", "Spearman rank-order monotonic correlation coefficient (tie-adjusted via scipy.stats.spearmanr when ties occur) [−1 to +1, dimensionless]"),
            ("d_i", "rank difference between x_i and y_i for matched pair i [dimensionless]"),
            ("n", "number of matched (treatment, week) pairs (evaluated for n ≥ 3) [dimensionless]"),
        ],
    )
    _add_body(
        doc,
        "For SEM × DSC correlation, replicate parameters are aggregated per (treatment, week), inner-joined with "
        "SEM metrics (Pooled or Per-Treatment Within-Group Aging, excluding HV-mismatched weeks per sidebar policy), "
        "and evaluated for pairs with n ≥ 3 observations; scipy.stats.spearmanr applies exact tie-adjusted rank "
        "correlation whenever tied ranks occur.",
    )
    _add_body(
        doc,
        "Reproducibility Guarantee: Every export bundle archives settings.json (build version, active scale, "
        "AnalysisConfig, pseudo_afm_gaussian_sigma_um = 1.0 µm, HV exclusions), analysis_report.md, image-level "
        "and kinetic CSV tables, optional DSC replicate/summary/correlation tables, and all 300-DPI PNG figures "
        "in a single ZIP.",
    )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(out_path)


def build_sop_docx(out_path: Path) -> None:
    doc = _init_doc(
        "BloomPix v1.1.2 — Standard Operating Procedure (SOP)",
        "Laboratory & Workstation Guide for SEM Chocolate Fat-Bloom & DSC Analysis (5-Tab Workflow)",
    )

    # Section 1
    _add_h1(doc, "1. Installation & Launching (macOS & Windows Portable)")
    _add_h2(doc, "1.1 Expected Dataset Directory Layout")
    _add_body(
        doc,
        "Place raw SEM micrographs inside timepoint subfolders under data/ (case-insensitive extensions: .tif, "
        ".tiff, .png, .jpg, .jpeg). Treatment codes and week counts are discovered automatically without "
        "hardcoded names:",
    )
    _add_bullet(doc, "data/control/ — ", "Week 0 baseline micrographs (shared control_* files or per-treatment *W0_* files).")
    _add_bullet(doc, "data/1/ ... data/N/ — ", "Numeric storage week folders (e.g., 1, 2, ..., 16) containing treatment micrographs.")
    _add_bullet(doc, "Hidden files — ", "macOS resource forks (._*) and .DS_Store files are automatically ignored.")

    _add_h2(doc, "1.2 Launching on macOS & Windows Portable")
    _add_bullet(
        doc,
        "macOS: ",
        "Double-click bloompix_run.command (or run ./bloompix_run.command in Terminal). On first launch it creates "
        "./venv, installs requirements.txt, and opens BloomPix in your browser.",
    )
    _add_bullet(
        doc,
        "Windows Portable: ",
        "Double-click BloomPix_Start.bat. It prioritizes bundled python_embed\\python.exe (falling back to venv, "
        ".venv, or system Python), performs a safe offline-tolerant status check if Git is present, and launches "
        "Streamlit via \"%PYTHON_EXE%\" -m streamlit run app.py. Desktop shortcut BloomPix.lnk with assets\\bloompix.ico "
        "is created automatically on launch.",
    )

    _add_h2(doc, "1.3 Magnification & HV Discipline")
    _add_body(
        doc,
        "Use 50 µm HFW (~2500×) as the primary quantitative scale for crystal-needle and Pseudo-AFM analysis, and "
        "200 µm HFW (~650×) as the macro cross-validation scale. Always select one scale at a time in the left "
        "sidebar—BloomPix strictly prevents mixing magnifications in the same kinetic curve.",
    )

    # Section 2
    _add_h1(doc, "2. Step-by-Step Operational Workflow (All 5 Tabs)")

    _add_h2(doc, "2.1 Tab 1 — 1. Data & Metadata")
    _add_bullet(doc, "1. Scan dataset: ", "Verify the Dataset Root Directory (default: data) and click 🔍 Scan Dataset (auto-scans on startup if data/ is populated).")
    _add_bullet(doc, "2. Check coverage: ", "Inspect the KPI cards and compact Replicate Coverage Matrix (Week × Treatment) for the active scale.")
    _add_bullet(doc, "3. Audit HV & calibration: ", "Review the HV & Calibration Audit table; toggle 'Show only HV-mismatched files' to inspect 10 kV outliers among 5 kV scans.")
    _add_bullet(doc, "4. Override or exclude: ", "Edit any mislabeled treatment/week or check excluded=True on ruined micrographs, then click Save Overrides to metadata_override.csv.")

    _add_h2(doc, "2.2 Tab 2 — 2. Roughness & Pseudo-AFM")
    _add_bullet(doc, "1. Run batch analysis: ", "Click 🚀 Run Surface Roughness Analysis ({active_scale}) to compute all 11 invariant metrics and CBI across the active scale.")
    _add_bullet(doc, "2. Inspect Single Treatment (All Weeks): ", "Select Treatment, Replicate, and Heatmap Type (Pseudo-AFM Local TRNR or Sato Crystal Blade Response), then click 🖼️ Generate All-Weeks Heatmaps & PSD.")
    _add_bullet(doc, "3. Export high-res maps & PSD: ", "Download the Combined All-Weeks Grid (300 DPI PNG), Individual High-Res Week Maps (ZIP), and 2D FFT Radial PSD Data (CSV, µm⁻¹).")
    _add_bullet(doc, "4. Compare Two Treatments: ", "Switch to Compare Two Treatments to inspect side-by-side SEM + shared-scale heatmaps and overlaid 2D FFT PSD curves at any week.")

    _add_h2(doc, "2.3 Tab 3 — 3. Kinetics & Comparison")
    _add_bullet(doc, "1. Configure HV policy: ", "Verify sidebar Global HV Policy (default: exclude HV-mismatched weeks from fits while displaying them as hollow diamonds).")
    _add_bullet(doc, "2. Evaluate kinetics: ", "Select the Kinetic Metric (default: Composite Bloom Index), inspect the progression plot, and click Download Displayed Kinetic Data (CSV).")
    _add_bullet(doc, "3. Review ranking & heatmap: ", "Check the Treatment Ranking table (Rank #1 = lowest AUC_norm = best bloom suppression) and download the Heatmap Matrix (CSV).")
    _add_bullet(doc, "4. PCA & hypothesis tests: ", "Inspect the 2D Morphology PCA trajectory and adjust Statistical Comparison Min Week (default: 8) to review ANOVA, Kruskal–Wallis, and pairwise p-values.")

    _add_h2(doc, "2.4 Tab 4 — 4. DSC Correlation")
    _add_bullet(doc, "1. Raw TA Instruments DSC Folder (.txt): ", "Place .txt thermograms in data/DSC/ (or DSC/) named <treatment>W<week>r<rep>.txt (and controlr<rep>.txt), set High-Melt Cutoff (default 34.0 °C), and click 🔥 Scan & Analyze Raw DSC Folder—pre-melting and post-melting baselines are detected automatically.")
    _add_bullet(doc, "2. Baseline QC & Manual Overrides: ", "Check Baseline QC OK vs Needs Review (flagged only for overshoot > 5%, T_onset < T_lo + 0.05 °C, or ΔH ≤ 1.0 J/g; bimodal peaks are purely informational). Use Apply Override & Recompute for immediate feedback (resolved files become OK (Manual)).")
    _add_bullet(doc, "3. Thermograms, Evolution & All-Samples Table: ", "Inspect baseline anchor markers in Thermogram QA Inspector, review parameter evolution vs. storage time, and view or download the All Samples — DSC Thermodynamic Parameters table (Weekly Means ± SD or Individual Replicates) directly below as CSV.")
    _add_bullet(doc, "4. Correlate with SEM (Pooled or Per-Treatment): ", "Choose All Treatments (Pooled) or Per-Treatment (Within-Group Aging) while respecting the global sidebar HV-exclusion policy, and inspect Pearson r / Spearman ρ tables, heatmaps, and labeled scatter plots.")

    _add_h2(doc, "2.5 Tab 5 — 5. Export & Report")
    _add_bullet(doc, "1. Preview audit files: ", "Review analysis_report.md and settings.json under Section 1 before generating the bundle.")
    _add_bullet(doc, "2. Configure archive scope: ", "Select Heatmap & PSD Replicate Scope (Rep 1 recommended, Rep 2, or All Replicates), verify Statistical Comparison Min Week (applied to all 8 kinetic metrics), and optionally check 'Include individual per-week 300-DPI heatmaps'.")
    _add_bullet(doc, "3. Build Complete Publication Archive: ", "Click 📦 Build Complete Publication Archive ({active_scale}) to automatically generate 300-DPI All-Weeks Pseudo-AFM Local TRNR grids, Sato Crystal Blade Response grids, 2D FFT Radial PSD plots + CSVs, and per-treatment tables for every discovered treatment, plus kinetic progression plots, Treatment × Week heatmaps, ranking tables, and ANOVA/Kruskal–Wallis statistics for all 8 kinetic metrics and 2D PCA.")
    _add_bullet(doc, "4. Download ZIP: ", "Verify the PNG/CSV manifest summary and click ⬇️ Download Complete Publication Archive (ZIP) (or use the Quick Session Export expander for already-rendered figures only).")

    # Section 3
    _add_h1(doc, "3. Troubleshooting & 8-Step Quick-Start Checklist")
    _add_table(
        doc,
        ["Symptom / Question", "Root Cause", "Recommended Action"],
        [
            ["Week 5–6 marked HV_Mismatch", "Scans acquired at 10 kV instead of dominant 5 kV.", "Keep 'Exclude HV-mismatched weeks from fits' enabled; confirm stability via Geom_Bloom_Index."],
            ["Calibration source = 'uncalibrated'", "Non-FEI TIFF/PNG lacks TIFF Tag 34682.", "Supply manual um_per_px in data/metadata_override.csv and re-scan."],
            ["Treatment classified 'Suppressed'", "CBI increase < 20 pts across storage.", "Normal behavior for bloom-resistant formulations (e.g., CNF); no false t_lag is extrapolated."],
            ["Empty DSC correlation table", "Mismatched treatment/week names or < 3 pairs.", "Check treatment/week naming or use CSV Template in Tab 4 so keys match Tab 1."],
            ["Need all weeks for a publication figure", "Individual week PNGs needed separately.", "Use 'Download Individual High-Res Week Maps (ZIP)' in Tab 2."],
        ],
    )

    _add_table(
        doc,
        ["Step", "Action", "Expected Outcome"],
        [
            ["1", "Place micrographs in data/control/ and data/1/..N/", "Clean study-agnostic folder tree"],
            ["2", "Launch via bloompix_run.command or BloomPix_Start.bat", "App opens in browser at localhost:8501"],
            ["3", "Select active scale (50um or 200um) in Sidebar", "Single magnification isolated cleanly"],
            ["4", "Verify coverage & HV Audit on Tab 1", "10 kV outliers flagged; ruined frames excluded"],
            ["5", "Run Batch Roughness & All-Weeks Inspector on Tab 2", "Gaussian Pseudo-AFM maps & PSD CSV ready"],
            ["6", "Inspect Kinetics, Ranking, PCA & ANOVA on Tab 3", "Objective ranking (#1 = best suppression)"],
            ["7", "Scan data/DSC/ & export All-Samples DSC CSV on Tab 4", "Auto-baseline QC passed; Pooled/Per-Treatment correlations ready"],
            ["8", "Build & download Complete Publication Archive (ZIP) on Tab 5", "All treatments & all 8 metrics (300-DPI PNGs, CSVs, JSON, report) saved"],
        ],
    )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(out_path)


if __name__ == "__main__":
    root = Path(__file__).resolve().parent.parent
    build_methodology_docx(root / "docs" / "Methodology.docx")
    build_sop_docx(root / "docs" / "SOP.docx")
    print("Generated docs/Methodology.docx (with native OMML equations) and docs/SOP.docx successfully.")
