# -*- coding: utf-8 -*-
"""Hermes system state & architecture — full management-style Word report.

v2: charts, per-component detail tables, corrected performance figures
(23 positions / +176$ net — the earlier '34 trades' was deal count, not
positions), technical appendix with every live threshold.
"""
import json
from docx import Document
from docx.shared import Pt, Mm, RGBColor, Emu
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.section import WD_SECTION
from docx.oxml.ns import qn
from docx.oxml import OxmlElement

# ── palette ──────────────────────────────────────────────────────────────
NAVY = RGBColor(0x1F, 0x38, 0x64)
BLUE = RGBColor(0x2E, 0x74, 0xB5)
STEEL = RGBColor(0x44, 0x54, 0x6A)
GRAY = RGBColor(0x59, 0x59, 0x59)
LGRAY = RGBColor(0x8A, 0x8A, 0x8A)
DARK = RGBColor(0x26, 0x26, 0x26)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
GREEN_T = RGBColor(0x00, 0x61, 0x00); GREEN_F = "D5EDD8"
AMBER_T = RGBColor(0x9C, 0x65, 0x00); AMBER_F = "FFF2CC"
RED_T = RGBColor(0x9C, 0x00, 0x06); RED_F = "F8D7DA"
HDR_F = "1F3864"; HDR2_F = "2E74B5"; ZEBRA = "F2F5FA"; PANEL = "EEF2F8"
FONT = "Tahoma"
MONO = "Consolas"
PAGE_W_MM = 210; MARGIN_MM = 16
CONTENT_MM = PAGE_W_MM - 2 * MARGIN_MM

GREEN_K = ('GREEN', 'STABLE', 'ACTIVE', 'OK', 'NORMAL', 'SYNCED', 'READY',
           'OFF', 'LOW', 'PASS', 'HEALTHY', 'VERIFIED', 'COMPLETE')
AMBER_K = ('AMBER', 'MEDIUM', 'GATED', 'QUEUED', 'BACKLOG', 'WATCH',
           'PARTIAL', 'PENDING', 'CAUTION', 'MONITOR')


def _rf(run, name=FONT):
    run.font.name = name
    rPr = run._r.get_or_add_rPr()
    rf = rPr.find(qn('w:rFonts'))
    if rf is None:
        rf = OxmlElement('w:rFonts')
        rPr.insert(0, rf)
    for a in ('w:ascii', 'w:hAnsi', 'w:cs', 'w:eastAsia'):
        rf.set(qn(a), name)
    szcs = OxmlElement('w:szCs')
    szcs.set(qn('w:val'), str(int((run.font.size or Pt(11)).pt * 2)))
    rPr.append(szcs)


def R(p, text, size=10.5, bold=False, color=DARK, italic=False, font=FONT):
    r = p.add_run(text)
    r.font.size = Pt(size)
    r.bold = bold
    r.italic = italic
    r.font.color.rgb = color
    _rf(r, font)
    return r


def rtl(p, align=WD_ALIGN_PARAGRAPH.RIGHT):
    pPr = p._p.get_or_add_pPr()
    b = OxmlElement('w:bidi')
    b.set(qn('w:val'), '1')
    pPr.append(b)
    p.alignment = align
    return p


def para(doc, text, size=10.5, bold=False, color=DARK, space_after=6,
         align=WD_ALIGN_PARAGRAPH.JUSTIFY, italic=False, font=FONT):
    p = rtl(doc.add_paragraph(), align)
    p.paragraph_format.space_after = Pt(space_after)
    R(p, text, size=size, bold=bold, color=color, italic=italic, font=font)
    return p


def rich(doc, parts, space_after=6, align=WD_ALIGN_PARAGRAPH.JUSTIFY):
    """parts = [(text, {kwargs}), ...] in one paragraph."""
    p = rtl(doc.add_paragraph(), align)
    p.paragraph_format.space_after = Pt(space_after)
    for text, kw in parts:
        R(p, text, **kw)
    return p


def shade(el_pr, fill):
    shd = OxmlElement('w:shd')
    shd.set(qn('w:val'), 'clear')
    shd.set(qn('w:color'), 'auto')
    shd.set(qn('w:fill'), fill)
    el_pr.append(shd)


def cell_shade(cell, fill):
    shade(cell._tc.get_or_add_tcPr(), fill)


def cell_margins(cell, top=60, bottom=60, left=90, right=90):
    tcPr = cell._tc.get_or_add_tcPr()
    mar = OxmlElement('w:tcMar')
    for tag, val in (('top', top), ('bottom', bottom),
                     ('start', left), ('end', right)):
        e = OxmlElement(f'w:{tag}')
        e.set(qn('w:w'), str(val))
        e.set(qn('w:type'), 'dxa')
        mar.append(e)
    tcPr.append(mar)


def cell_text(cell, text, size=9.5, bold=False, color=DARK,
              align=WD_ALIGN_PARAGRAPH.RIGHT, font=FONT, valign='center'):
    cell.text = ''
    p = rtl(cell.paragraphs[0], align)
    p.paragraph_format.space_after = Pt(1)
    p.paragraph_format.space_before = Pt(1)
    R(p, str(text), size=size, bold=bold, color=color, font=font)
    tcPr = cell._tc.get_or_add_tcPr()
    va = OxmlElement('w:vAlign')
    va.set(qn('w:val'), valign)
    tcPr.append(va)


def borders(cell, edges=('top', 'bottom', 'left', 'right'), sz=4,
            color="BFC9D9", val="single"):
    tcPr = cell._tc.get_or_add_tcPr()
    tb = tcPr.find(qn('w:tcBorders'))
    if tb is None:
        tb = OxmlElement('w:tcBorders')
        tcPr.append(tb)
    for e in edges:
        el = OxmlElement(f'w:{e}')
        el.set(qn('w:val'), val)
        el.set(qn('w:sz'), str(sz))
        el.set(qn('w:color'), color)
        tb.append(el)


def no_borders(t):
    tblPr = t._tbl.tblPr
    b = OxmlElement('w:tblBorders')
    for e in ('top', 'left', 'bottom', 'right', 'insideH', 'insideV'):
        el = OxmlElement(f'w:{e}')
        el.set(qn('w:val'), 'none')
        el.set(qn('w:sz'), '0')
        b.append(el)
    tblPr.append(b)


def heading(doc, text, level=1, num=None):
    p = doc.add_heading('', level=level)
    rtl(p, WD_ALIGN_PARAGRAPH.RIGHT)
    if level == 1:
        # navy bar behind the heading
        pPr = p._p.get_or_add_pPr()
        pbdr = OxmlElement('w:pBdr')
        top = OxmlElement('w:top')
        top.set(qn('w:val'), 'single'); top.set(qn('w:sz'), '18')
        top.set(qn('w:space'), '4'); top.set(qn('w:color'), '1F3864')
        pbdr.append(top)
        pPr.append(pbdr)
        shade(pPr, PANEL)
        R(p, text, size=14.5, bold=True, color=NAVY)
        p.paragraph_format.space_before = Pt(16)
        p.paragraph_format.space_after = Pt(8)
    elif level == 2:
        R(p, text, size=12, bold=True, color=BLUE)
        p.paragraph_format.space_before = Pt(11)
        p.paragraph_format.space_after = Pt(4)
    else:
        R(p, text, size=10.5, bold=True, color=STEEL)
        p.paragraph_format.space_before = Pt(8)
        p.paragraph_format.space_after = Pt(3)
    return p


def make_table(doc, headers, rows, widths=None, rag_col=None, mono_cols=(),
               center_cols=(), header_fill=HDR_F, font_size=9.5,
               zebra=True, first_col_bold=False, row_fills=None):
    t = doc.add_table(rows=1, cols=len(headers))
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    t.autofit = False
    tblPr = t._tbl.tblPr
    tblPr.append(OxmlElement('w:bidiVisual'))
    lay = OxmlElement('w:tblLayout')
    lay.set(qn('w:type'), 'fixed')
    tblPr.append(lay)
    for i, h in enumerate(headers):
        c = t.rows[0].cells[i]
        cell_text(c, h, size=font_size, bold=True, color=WHITE,
                  align=WD_ALIGN_PARAGRAPH.CENTER)
        cell_shade(c, header_fill)
        cell_margins(c)
    for ri, row in enumerate(rows):
        cells = t.add_row().cells
        for ci, val in enumerate(row):
            if ci in mono_cols or ci in center_cols:
                al = WD_ALIGN_PARAGRAPH.CENTER
            else:
                al = WD_ALIGN_PARAGRAPH.RIGHT
            fnt = MONO if ci in mono_cols else FONT
            cell_text(cells[ci], val, size=font_size, align=al, font=fnt,
                      bold=(first_col_bold and ci == 0))
            cell_margins(cells[ci])
            if zebra and ri % 2 == 1:
                cell_shade(cells[ci], ZEBRA)
            if row_fills and row_fills[ri]:
                cell_shade(cells[ci], row_fills[ri])
            if rag_col is not None and ci == rag_col:
                v = str(val).upper()
                if any(k in v for k in GREEN_K):
                    cell_shade(cells[ci], GREEN_F)
                    cells[ci].paragraphs[0].runs[0].font.color.rgb = GREEN_T
                    cells[ci].paragraphs[0].runs[0].bold = True
                elif any(k in v for k in AMBER_K):
                    cell_shade(cells[ci], AMBER_F)
                    cells[ci].paragraphs[0].runs[0].font.color.rgb = AMBER_T
                    cells[ci].paragraphs[0].runs[0].bold = True
                else:
                    cell_shade(cells[ci], RED_F)
                    cells[ci].paragraphs[0].runs[0].font.color.rgb = RED_T
                    cells[ci].paragraphs[0].runs[0].bold = True
    if widths:
        for row in t.rows:
            for i, w in enumerate(widths):
                row.cells[i].width = Mm(w)
    sp = doc.add_paragraph()
    sp.paragraph_format.space_after = Pt(3)
    R(sp, '', size=4)
    return t


def kpi_grid(doc, items, per_row=4, fill=PANEL):
    """items = [(value, label, tone)] — tone in ('g','a','r','n')."""
    TONE = {'g': GREEN_F, 'a': AMBER_F, 'r': RED_F, 'n': fill}
    TC = {'g': GREEN_T, 'a': AMBER_T, 'r': RED_T, 'n': NAVY}
    for i in range(0, len(items), per_row):
        chunk = items[i:i + per_row]
        t = doc.add_table(rows=2, cols=per_row)
        t.alignment = WD_TABLE_ALIGNMENT.CENTER
        t.autofit = False
        no_borders(t)
        for j in range(per_row):
            if j < len(chunk):
                val, lab, tone = chunk[j]
                for row, txt, sz, bold, col in (
                        (0, val, 15, True, TC[tone]),
                        (1, lab, 8, False, GRAY)):
                    c = t.cell(row, j)
                    cell_text(c, txt, size=sz, bold=bold, color=col,
                              align=WD_ALIGN_PARAGRAPH.CENTER)
                    cell_shade(c, TONE[tone])
                    cell_margins(c, top=70, bottom=70)
                    c.width = Mm(CONTENT_MM / per_row - 1)
        sp = doc.add_paragraph()
        sp.paragraph_format.space_after = Pt(4)
        R(sp, '', size=4)


def callout(doc, title, body, fill=AMBER_F, bar="F9A825", tcol=AMBER_T):
    t = doc.add_table(rows=1, cols=1)
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    t.autofit = False
    no_borders(t)
    c = t.cell(0, 0)
    c.width = Mm(CONTENT_MM)
    cell_shade(c, fill)
    borders(c, edges=('right',), sz=24, color=bar[:6] if len(bar) == 7 else bar)
    cell_margins(c, top=110, bottom=110, left=140, right=140)
    c.text = ''
    p = rtl(c.paragraphs[0], WD_ALIGN_PARAGRAPH.RIGHT)
    p.paragraph_format.space_after = Pt(2)
    R(p, title, size=10.5, bold=True, color=tcol)
    p2 = rtl(c.add_paragraph(), WD_ALIGN_PARAGRAPH.JUSTIFY)
    R(p2, body, size=9.5, color=DARK)
    sp = doc.add_paragraph()
    sp.paragraph_format.space_after = Pt(6)
    R(sp, '', size=4)
    return t


def bullets(doc, items, size=10, space=3, bold_lead=True):
    for it in items:
        p = rtl(doc.add_paragraph())
        p.paragraph_format.space_after = Pt(space)
        pPr = p._p.get_or_add_pPr()
        nb = OxmlElement('w:numPr')
        il = OxmlElement('w:ilvl'); il.set(qn('w:val'), '0')
        ui = OxmlElement('w:numId'); ui.set(qn('w:val'), '1')
        nb.append(il); nb.append(ui)
        pPr.append(nb)
        if bold_lead and ' — ' in it:
            head, tail = it.split(' — ', 1)
            R(p, head + ' — ', size=size, bold=True, color=NAVY)
            R(p, tail, size=size)
        else:
            R(p, it, size=size)


def field(par, instr, placeholder=''):
    r = par.add_run()
    f1 = OxmlElement('w:fldChar'); f1.set(qn('w:fldCharType'), 'begin')
    r._r.append(f1)
    r2 = par.add_run()
    it = OxmlElement('w:instrText')
    it.set(qn('xml:space'), 'preserve')
    it.text = instr
    r2._r.append(it)
    r3 = par.add_run()
    f2 = OxmlElement('w:fldChar'); f2.set(qn('w:fldCharType'), 'separate')
    r3._r.append(f2)
    r4 = par.add_run(placeholder)
    r5 = par.add_run()
    f3 = OxmlElement('w:fldChar'); f3.set(qn('w:fldCharType'), 'end')
    r5._r.append(f3)
    for rr in (r, r2, r3, r4, r5):
        _rf(rr)


def picture(doc, path, width_mm=CONTENT_MM, caption=None):
    p = rtl(doc.add_paragraph(), WD_ALIGN_PARAGRAPH.CENTER)
    p.paragraph_format.space_before = Pt(4)
    p.paragraph_format.space_after = Pt(2)
    p.add_run().add_picture(path, width=Mm(width_mm))
    if caption:
        cp = rtl(doc.add_paragraph(), WD_ALIGN_PARAGRAPH.CENTER)
        cp.paragraph_format.space_after = Pt(10)
        R(cp, caption, size=8.5, italic=True, color=GRAY)


def page_break(doc):
    doc.add_paragraph().add_run().add_break(WD_BREAK.PAGE)


def fa(n):
    """Latin digits -> Persian digits."""
    return ''.join('۰۱۲۳۴۵۶۷۸۹'[int(ch)] if ch.isdigit() else ch for ch in str(n))
