#!/usr/bin/env python3
"""Honest backtest report v2 (Persian, RTL) with charts."""
import json
from pathlib import Path

from docx import Document
from docx.shared import Pt, Cm, RGBColor, Inches
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.oxml import OxmlElement

DARK = RGBColor(0x1F, 0x2A, 0x44)
ACCENT = RGBColor(0xC9, 0x9A, 0x3C)
GRAY = RGBColor(0x66, 0x66, 0x66)
GREEN = RGBColor(0x2E, 0x7D, 0x32)
RED = RGBColor(0xB3, 0x26, 0x1E)

OUT = Path("/home/ai/hermes-trading/reports/Backtest_Report.docx")
results = json.load(open("/home/ai/hermes-trading/data/backtest/sweep_results_v2.json"))
by_label = {r["label"].split(":")[0]: r for r in results}

doc = Document()
for sec in doc.sections:
    sec.top_margin = Cm(2); sec.bottom_margin = Cm(2)
    sec.left_margin = Cm(2.2); sec.right_margin = Cm(2.2)

style = doc.styles["Normal"]
style.font.size = Pt(11)
rpr = style.element.get_or_add_rPr()
rf = rpr.find(qn('w:rFonts'))
if rf is None:
    rf = OxmlElement('w:rFonts'); rpr.append(rf)
for attr in ('w:cs', 'w:ascii', 'w:hAnsi'):
    rf.set(qn(attr), 'Vazirmatn')


def rtl_p(text="", size=11, bold=False, color=None, align="right", space_after=6, space_before=0):
    p = doc.add_paragraph()
    p.alignment = {"right": WD_ALIGN_PARAGRAPH.RIGHT, "center": WD_ALIGN_PARAGRAPH.CENTER,
                   "left": WD_ALIGN_PARAGRAPH.LEFT}[align]
    pf = p.paragraph_format
    pf.space_after = Pt(space_after); pf.space_before = Pt(space_before)
    pPr = p._p.get_or_add_pPr()
    bidi = OxmlElement('w:bidi'); bidi.set(qn('w:val'), '1'); pPr.append(bidi)
    if text:
        r = p.add_run(text)
        r.font.size = Pt(size); r.bold = bold
        if color: r.font.color.rgb = color
        rr = r._r.get_or_add_rPr()
        if rr.find(qn('w:rtl')) is None:
            rr.append(OxmlElement('w:rtl'))
    return p


def heading(text, level=1):
    sizes = {0: 22, 1: 15, 2: 12.5}
    p = rtl_p(text, size=sizes[level], bold=True,
              color=DARK if level else ACCENT, space_before=14 if level else 0, space_after=8)
    if level == 1:
        pPr = p._p.get_or_add_pPr()
        pbdr = OxmlElement('w:pBdr'); b = OxmlElement('w:bottom')
        b.set(qn('w:val'), 'single'); b.set(qn('w:sz'), '6'); b.set(qn('w:space'), '2'); b.set(qn('w:color'), 'C99A3C')
        pbdr.append(b); pPr.append(pbdr)
    return p


def table(headers, rows, fontsize=10):
    t = doc.add_table(rows=1 + len(rows), cols=len(headers))
    t.style = "Light Grid Accent 1"
    tblPr = t._tbl.tblPr
    tblPr.append(OxmlElement('w:bidiVisual'))
    for i, h in enumerate(headers):
        c = t.rows[0].cells[i]; c.text = ""
        p = c.paragraphs[0]; p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        r = p.add_run(h); r.bold = True; r.font.size = Pt(fontsize)
    for ri, row in enumerate(rows):
        for ci, val in enumerate(row):
            c = t.rows[ri + 1].cells[ci]; c.text = ""
            p = c.paragraphs[0]; p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            r = p.add_run(str(val)); r.font.size = Pt(fontsize)
    doc.add_paragraph().paragraph_format.space_after = Pt(2)
    return t


# ═══ COVER ═══
for _ in range(4):
    doc.add_paragraph()
rtl_p("گزارش بک‌تست XAUUSD — نسخه ۲ (واقع‌گرایانه)", size=24, bold=True, color=DARK, align="center", space_after=10)
rtl_p("اسپرد مدل‌شده + BE از کندل بعدی + ۸۰۰۰ کندل داده واقعی", size=13, color=GRAY, align="center", space_after=30)
rtl_p("XAUUSD M15 • 1500 تا 8000 کندل • ~6 هفته تا 4 ماه داده • اسپرد 0.20", size=11, color=ACCENT, align="center", space_after=40)
rtl_p("تهیه‌شده توسط: Hermes Agent — اوت 2026", size=11, color=GRAY, align="center")
doc.add_page_break()

# ═══ 1. v1 vs v2 ═══
heading("۱. نسخه ۱ چه ایرادی داشت؟ (صادقانه)", 1)
rtl_p("بعد از تحویل نسخه ۱، سه ایراد واقعی در موتور پیدا کردم و همه اصلاح شدند:", size=11)
table(["ایراد نسخه ۱", "اثر روی آمار", "فیکس نسخه ۲"],
      [
          ["اسپرد/کارمزد مدل نشده بود", "هر ترید 0.2$ جعلی گران‌تر — اسکرچ‌ها «رایگان» به‌نظر می‌رسیدند", "اسپرد 0.20 در هر رفت‌وبرگشت کسر می‌شود"],
          ["BE-move همان کندلی که 0.5R می‌خورد اعمال می‌شد", "اسکرچ‌های جعلی: کندلی که هم سود می‌خورد هم برمی‌گشت، صفر بسته می‌شد", "BE از کندل بعدی اعمال می‌شود (مثل لایو)"],
          ["داده کم: 1500 کندل (~۲ هفته)", "آمار غیرقابل‌اتکا", "تا 8000 کندل (~۴ ماه) تست شد"],
      ])

# ═══ 2. headline numbers ═══
h = by_label["H"]
g = by_label["G"]
heading("۲. نتیجه اصلی — مسیر کامل لایو (با SMC) روی 8000 کندل", 1)
table(["پیکربندی", "ترید", "برد", "باخت", "اسکرچ", "وین‌ریت", "PnL خالص"],
      [
          ["G: RR1.5 + BE0.5", g["trades"], g["wins"], g["losses"], g["scratches"],
           f"{g['win_rate']*100:.0f}%", f"{g['net_pnl']:+.1f}$"],
          ["H: همان + پارتیال 50٪", h["trades"], h["wins"], h["losses"], h["scratches"],
           f"{h['win_rate']*100:.0f}%", f"{h['net_pnl']:+.1f}$"],
      ])

rtl_p("خوانش:", bold=True, space_before=8)
for line in [
    "این اعداد با نسخه قبلی (31 ترید، +215$) زمین تا آسمان فرق دارد — و این‌بار درست است. دلیل: در بک‌تست قبلی، ترکیب Classic+SMC (که در لایو بایاس نهایی را می‌سازد) هرگز صدا زده نمی‌شد. با اضافه شدن SMC، فیلترها بسیار سخت‌گیرتر شدند.",
    "قیف واقعی روی 2900 کندل: 678 بار بایاس خنثی، 1299 بار عدم‌الاینمنت، 740 بار قیمت بیرون زون — فقط 157 فرصت در-زون که با قانون تک‌پوزیشن و RR به 7 ترید در ~4 ماه رسید (~1.6 ترید در ماه).",
    "وین‌ریت 71٪ روی 7 نمونه تقریباً بی‌معنی است. این بک‌تست دیگر ابزار بهینه‌سازی پارامتر نیست؛ فقط ابزار بازبینی مسیر تصمیم است.",
    "پارتیال همچنان مثبت بود (+41.7 در برابر +30.3) اما با این حجم نمونه، تصادفی هم می‌تواند باشد.",
]:
    rtl_p("•  " + line, size=10.5, space_after=3)

# ═══ 3. charts ═══
heading("۳. نمودارها", 1)
doc.add_picture("/home/ai/hermes-trading/reports/backtest_charts.png", width=Inches(6.4))
rtl_p("وین‌ریت خام در برابر مؤثر (سبز)، PnL خالص بعد از اسپرد، تعداد ترید، منحنی سرمایه", size=9, color=GRAY, align="center")

# ═══ 4. trade detail ═══
heading("۴. ریز معاملات سناریو H (پیشنهادی)", 1)
detail = []
for t in h["trade_log"]:
    detail.append([t["side"], t["session"], t["exit_reason"].upper(), f"{t['pnl']:+.2f}"])
table(["جهت", "سشن", "خروج", "PnL ($)"], detail, fontsize=8.5)

# ═══ 5. honest limits ═══
heading("۵. محدودیت‌ها — چطور این آمار را نباید خواند", 1)
for line in [
    "بک‌تست از کندل‌های M15 استفاده می‌کند، نه تیک. داخل هر کندل ترتیب SL/TP حدس محافظه‌کارانه است، نه قطعی.",
    "سیگنال‌سازِ بک‌تست نسخه ساده‌شده منطق لایو است (SMC کامل، DEFCON، کوول‌داون و خبر در آن نیست) — لایو می‌تواند بهتر یا بدتر باشد.",
    "ورود در بک‌تست روی close همان کندل است؛ در لایو چند ثانیه تأخیر و اسلیپیج ممکن است.",
    "31 ترید هنوز نمونه آماری بزرگی نیست؛ جهت روند کافی است نه نتیجه قطعی.",
    "پارامترها روی همین داده بهینه شدند — خطر overfitting واقعی است. راه‌حل: چند هفته فوروارد-تست لایو با همین پارامترها قبل از افزایش ریسک.",
]:
    rtl_p("•  " + line, size=10.5, space_after=3)

rtl_p("", space_after=14)
rtl_p("— پایان گزارش —", size=10, color=GRAY, align="center")
doc.save(OUT)
print("saved:", OUT)
