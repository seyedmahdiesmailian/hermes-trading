# -*- coding: utf-8 -*-
"""Build the management-style Word report for Hermes system state."""
from docx import Document
from docx.shared import Pt, Mm, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml.ns import qn
from docx.oxml import OxmlElement

NAVY = RGBColor(0x1F, 0x38, 0x64)
BLUE = RGBColor(0x2E, 0x74, 0xB5)
GRAY = RGBColor(0x59, 0x59, 0x59)
DARK = RGBColor(0x26, 0x26, 0x26)
GREEN_T = RGBColor(0x00, 0x61, 0x00); GREEN_F = "C6EFCE"
AMBER_T = RGBColor(0x9C, 0x65, 0x00); AMBER_F = "FFEB9C"
RED_T = RGBColor(0x9C, 0x00, 0x06); RED_F = "FFC7CE"
HDR_F = "1F3864"; ZEBRA = "F2F5FA"
FONT = "Tahoma"

def _rf(run, name=FONT):
    run.font.name = name
    rPr = run._r.get_or_add_rPr()
    rf = rPr.find(qn('w:rFonts'))
    if rf is None:
        rf = OxmlElement('w:rFonts'); rPr.insert(0, rf)
    for a in ('w:ascii', 'w:hAnsi', 'w:cs', 'w:eastAsia'):
        rf.set(qn(a), name)
    szcs = OxmlElement('w:szCs')
    szcs.set(qn('w:val'), str(int((run.font.size or Pt(11)).pt * 2)))
    rPr.append(szcs)

def R(p, text, size=10.5, bold=False, color=DARK, italic=False):
    r = p.add_run(text); r.font.size = Pt(size); r.bold = bold
    r.italic = italic; r.font.color.rgb = color; _rf(r)
    return r

def rtl(p, align=WD_ALIGN_PARAGRAPH.RIGHT):
    pPr = p._p.get_or_add_pPr()
    b = OxmlElement('w:bidi'); b.set(qn('w:val'), '1'); pPr.append(b)
    p.alignment = align
    return p

def para(doc, text, size=10.5, bold=False, color=DARK, space_after=6,
         align=WD_ALIGN_PARAGRAPH.JUSTIFY):
    p = rtl(doc.add_paragraph(), align)
    p.paragraph_format.space_after = Pt(space_after)
    R(p, text, size=size, bold=bold, color=color)
    return p

def heading(doc, text, level=1):
    p = doc.add_heading('', level=level)
    rtl(p, WD_ALIGN_PARAGRAPH.RIGHT)
    sizes = {1: 15, 2: 12.5, 3: 11}
    R(p, text, size=sizes.get(level, 11), bold=True,
      color=NAVY if level == 1 else BLUE)
    p.paragraph_format.space_before = Pt(14 if level == 1 else 10)
    p.paragraph_format.space_after = Pt(6)
    return p

def shade(cell, fill):
    tcPr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement('w:shd'); shd.set(qn('w:val'), 'clear')
    shd.set(qn('w:color'), 'auto'); shd.set(qn('w:fill'), fill)
    tcPr.append(shd)

def cell_text(cell, text, size=9.5, bold=False, color=DARK,
              align=WD_ALIGN_PARAGRAPH.RIGHT):
    cell.text = ''
    p = rtl(cell.paragraphs[0], align)
    p.paragraph_format.space_after = Pt(2)
    p.paragraph_format.space_before = Pt(2)
    R(p, str(text), size=size, bold=bold, color=color)

def make_table(doc, headers, rows, widths=None, rag_col=None,
               mono_cols=()):
    t = doc.add_table(rows=1, cols=len(headers))
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    t.style = 'Table Grid'
    tblPr = t._tbl.tblPr
    bv = OxmlElement('w:bidiVisual'); tblPr.append(bv)
    lay = OxmlElement('w:tblLayout'); lay.set(qn('w:type'), 'fixed')
    tblPr.append(lay)
    for i, h in enumerate(headers):
        c = t.rows[0].cells[i]
        cell_text(c, h, size=9.5, bold=True, color=RGBColor(0xFF, 0xFF, 0xFF),
                  align=WD_ALIGN_PARAGRAPH.CENTER)
        shade(c, HDR_F)
    for ri, row in enumerate(rows):
        cells = t.add_row().cells
        for ci, val in enumerate(row):
            al = WD_ALIGN_PARAGRAPH.CENTER if (ci in mono_cols or ci == rag_col) \
                else WD_ALIGN_PARAGRAPH.RIGHT
            cell_text(cells[ci], val, align=al)
            if ri % 2 == 1:
                shade(cells[ci], ZEBRA)
            if rag_col is not None and ci == rag_col:
                v = str(val)
                if any(k in v for k in ('GREEN', 'STABLE', 'active', 'ACTIVE',
                                        'OK', 'normal', 'synced', 'ready',
                                        'OFF', 'IN PROGRESS', 'SCHEDULED',
                                        'LOW')):
                    shade(cells[ci], GREEN_F)
                elif any(k in v for k in ('AMBER', 'MEDIUM', 'GATED',
                                          'QUEUED', 'BACKLOG', 'WATCH')):
                    shade(cells[ci], AMBER_F)
                else:
                    shade(cells[ci], RED_F)
    if widths:
        for row in t.rows:
            for i, w in enumerate(widths):
                row.cells[i].width = Mm(w)
    doc.add_paragraph().paragraph_format.space_after = Pt(2)
    return t

def field(par, instr, placeholder=''):
    r = par.add_run(); f1 = OxmlElement('w:fldChar')
    f1.set(qn('w:fldCharType'), 'begin'); r._r.append(f1)
    r2 = par.add_run(); it = OxmlElement('w:instrText')
    it.set(qn('xml:space'), 'preserve'); it.text = instr
    r2._r.append(it)
    r3 = par.add_run(); f2 = OxmlElement('w:fldChar')
    f2.set(qn('w:fldCharType'), 'separate'); r3._r.append(f2)
    r4 = par.add_run(placeholder)
    r5 = par.add_run(); f3 = OxmlElement('w:fldChar')
    f3.set(qn('w:fldCharType'), 'end'); r5._r.append(f3)
    for rr in (r, r2, r3, r4, r5):
        _rf(rr)

def bullets(doc, items, size=10.5):
    for it in items:
        p = rtl(doc.add_paragraph())
        p.paragraph_format.space_after = Pt(3)
        pPr = p._p.get_or_add_pPr()
        nb = OxmlElement('w:numPr')
        il = OxmlElement('w:ilvl'); il.set(qn('w:val'), '0')
        ui = OxmlElement('w:numId'); ui.set(qn('w:val'), '1')
        nb.append(il); nb.append(ui); pPr.append(nb)
        R(p, it, size=size)

doc = Document()
# page + base styles
sec = doc.sections[0]
sec.page_width, sec.page_height = Mm(210), Mm(297)
for m in ('top_margin', 'bottom_margin'):
    setattr(sec, m, Mm(18))
for m in ('left_margin', 'right_margin'):
    setattr(sec, m, Mm(16))

st = doc.styles['Normal']
st.font.name = FONT; st.font.size = Pt(10.5); st.font.color.rgb = DARK
st.element.rPr.rFonts.set(qn('w:cs'), FONT)

# header / footer
hp = rtl(sec.header.paragraphs[0], WD_ALIGN_PARAGRAPH.CENTER)
R(hp, 'گزارش وضعیت و معماری سیستم Hermes — داخلی/محرمانه', size=8, color=GRAY)
fp = rtl(sec.footer.paragraphs[0], WD_ALIGN_PARAGRAPH.CENTER)
R(fp, 'HMT-1405-06-13 · ', size=8, color=GRAY)
field(fp, 'PAGE', '1')
R(fp, ' از ', size=8, color=GRAY)
field(fp, 'NUMPAGES', '1')

# ───────────────────────── cover
for _ in range(4):
    doc.add_paragraph()
p = rtl(doc.add_paragraph(), WD_ALIGN_PARAGRAPH.CENTER)
R(p, 'گزارش وضعیت و معماری سیستم', size=26, bold=True, color=NAVY)
p = rtl(doc.add_paragraph(), WD_ALIGN_PARAGRAPH.CENTER)
R(p, 'زیرساخت تریدینگ Hermes', size=16, bold=True, color=BLUE)
p = rtl(doc.add_paragraph(), WD_ALIGN_PARAGRAPH.CENTER)
R(p, 'مغز لینوکسی · بازوی اجرای MT5 · مسیر سیگنال تلگرام', size=11, color=GRAY)
doc.add_paragraph()
make_table(doc, ['Field', 'Value'], [
    ['Report ID', 'HMT-1405-06-13'],
    ['Date', 'جمعه ۱۳ شهریور ۱۴۰۵ — ۲۰۲۶-09-04، ساعت ۱۹:۴۰ UTC'],
    ['Prepared by', 'Hermes (خودکار) — داده‌ها زنده از دیسک و بروکر'],
    ['Approved by', 'سید مهدی اسماعیلیان'],
    ['Version', '1.0'],
    ['Classification', 'داخلی — محرمانه'],
    ['Scope', 'کل زیرساخت: سرویس‌ها، کد، ریسک، عملکرد، ریسک‌ها'],
], widths=[45, 105], mono_cols=())
doc.add_page_break()

# ───────────────────────── TOC
heading(doc, 'فهرست مطالب', 1)
p = doc.add_paragraph()
field(p, r'TOC \o "1-2" \h \z \u',
      'برای ساخت فهرست: راست‌کلیک ← Update Field')
para(doc, 'در Word روی متن بالا راست‌کلیک و Update Field را بزنید تا فهرست '
          'با شماره صفحه ساخته شود.', size=8.5, color=GRAY)
doc.add_page_break()

# ───────────────────────── 1 executive summary
heading(doc, '۱. خلاصه مدیریتی', 1)
para(doc, 'سیستم تریدینگ Hermes در وضعیت پایدار و کاملاً خودکار در حال '
          'اجراست. هر شش سرویس فعال‌اند، پل ارتباطی با متاتریدر سالم است، '
          '۷۲۵ تست روی کلون تمیز کد پاس می‌شوند و هیچ پوزیشن بازی یا '
          'خطای فعالی وجود ندارد. حساب نمایشی با موجودی ۵٬۱۸۶ دلار، '
          '۳۴ ترید بسته‌شده و سود خالص ۱۹۶+ دلار در ۱۲ روز اخیر است.')
para(doc, 'یک یافتهٔ کلیدی در این دورهٔ گزارش‌گیری تأیید شد: مسیر سیگنال '
          'تلگرام از زمان راه‌اندازی تاکنون صفر ترید اجرا کرده است (۲۲ '
          'رویداد پردازش‌شده، همه رد). تصمیم مدیریت (گزینهٔ الف) بر این '
          'است که تا جمع‌آوری حدود ۱۰۰ ترید زندهٔ جدید، هیچ پارامتری در '
          'گیت انتخاب تغییر نکند. این تصمیم در دفتر تصمیمات (بخش ۸) ثبت '
          'شده است.', bold=False)
heading(doc, 'شاخص‌های کلیدی (KPI)', 2)
make_table(doc, ['KPI', 'Value', 'RAG'], [
    ['وضعیت کلی سیستم', 'STABLE — no action required', 'GREEN'],
    ['سرویس‌های فعال', '6 / 6 active — 0 failed units', 'GREEN'],
    ['پوزیشن باز', '0 open', 'GREEN'],
    ['موجودی حساب (دمو)', '$5,186.04', 'GREEN'],
    ['تریدهای زنده (۱۲ روز)', '34 trades — net +$196', 'GREEN'],
    ['بازده نرمال‌شده (0.01 lot)', '+$54 ≈ $4.5 / day', 'AMBER'],
    ['مسیر سیگنال تلگرام', '22 events — 0 executed', 'AMBER'],
    ['کیفیت کد', '725 tests OK · clean checkout · 128s', 'GREEN'],
    ['Kill Switch', 'OFF — 0 consecutive losses', 'GREEN'],
], widths=[52, 68, 28], rag_col=2)
para(doc, 'تفسیر یک‌خطی: ماشین درست می‌چرخد؛ تنها سؤال باز، کیفیت '
          'ورودیِ مسیر سیگنال است نه سلامت اجرا.', size=9.5, color=GRAY)

# ───────────────────────── 2 status board
heading(doc, '۲. داشبورد وضعیت اجزا', 1)
make_table(doc, ['Component', 'Status', 'Detail'], [
    ['hermes-signal', 'active', 'خوانش سیگنال از گروه، پارس، گیت، اطلاع‌رسانی'],
    ['hermes-position', 'active', 'مدیریت پوزیشن هر ۵ ثانیه (SL/BE/trail/TP)'],
    ['تریدر اسکنر (hermes_master)', 'active (cron 15m)', 'کرون هر ۱۵ دقیقه — اسکن، پلن، ورود'],
    ['hermes-forwarder', 'active', 'فوروارد زندهٔ ۷ کانال به یک گروه'],
    ['hermes-dashboard', 'active', 'پنل مانیتورینگ'],
    ['hermes-gateway', 'active', 'پل تلگرام/هرمس'],
    ['VM ویندوز + بریج MT5', 'OK', 'پینگ 0.57ms · Bridge health سالم'],
    ['دیسک سرور', 'normal', '۳۲٪ مصرف — 44G آزاد'],
    ['پایگاه‌داده هرمس', 'ok', 'integrity_check=ok — 266MB'],
    ['گیت‌هاب', 'synced', 'HEAD = origin/master — استمپ تأیید فعال'],
    ['تقویم اقتصادی', 'ready', 'پیش‌نیاز بلاک خبری (fail-closed)'],
], widths=[48, 22, 78], rag_col=1)

# ───────────────────────── 3 architecture
heading(doc, '۳. معماری سیستم', 1)
para(doc, 'معماری دو-میزبانه است و تفکیک مسئولیت آن عمدی: تمام منطق '
          'تصمیم‌گیری روی لینوکس اجرا می‌شود و ویندوز صرفاً بازوی اجرای '
          'متاتریدر است. دلیل این طراحی، فروپاشی نسخهٔ قبلی روی ویندوز '
          'است؛ در معماری فعلی خرابی ویندوز فقط اجرا را متوقف می‌کند، '
          'نه تحلیل را.')
make_table(doc, ['Layer', 'Host', 'Responsibility'], [
    ['مغز / تصمیم', 'Ubuntu — 192.168.10.18',
     'پارس سیگنال، تحلیل، گیت‌های ریسک، مدیریت پوزیشن'],
    ['اجرا', 'Windows VM — 192.168.10.51',
     'MetaTrader 5 (session 1) — فقط ثبت/ویرایش/بستن سفارش'],
    ['پل ارتباطی', 'HTTP :5050 (Bearer)',
     'قیمت، کندل M5 (۲۰٬۰۰۰ عدد)، پوزیشن، دیل، حساب'],
    ['مدل هوش مصنوعی', 'omniroute (localhost:20128)',
     'ارائهٔ مدل برای autopilot و تحلیل‌ها'],
    ['اطلاع‌رسانی', 'Telegram gateway + forwarder',
     'گزارش‌ها، SKIP، هشدارها، فوروارد کانال‌ها'],
    ['کد و نسخه', 'git — seyedmahdi…/hermes-trading',
     'سینک خودکار ۱۵ دقیقه — فقط HEAD تأییدشده push می‌شود'],
], widths=[30, 48, 70])
heading(doc, 'زنجیرهٔ داده (Data Flow)', 2)
bullets(doc, [
    'کانال‌های تلگرام ← forwarder ← گروه سیگنال ← hermes-signal ← پارسر '
    '← گیت امتیازی ← بریج ← MT5',
    'MT5 ← بریج (قیمت/کندل) ← اسکنر (تحلیل کلاسیک + SMC/ICT) ← پلن ← '
    'گیت ریسک ← بریج ← MT5',
    'هر دو مسیر: مدیریت پوزیشن (hermes-position) + لاگ + گزارش تلگرام',
    'بازخورد: تریدهای بسته → DEFCON/kill-switch → تعدیل ریسک چرخهٔ بعد',
])

# ───────────────────────── 4 two projects
heading(doc, '۴. دو پروژهٔ معاملاتی', 1)
make_table(doc, ['Project', 'Input', 'Mechanism', 'Current Output'], [
    ['تریدر اسکنر (خودکفا)', 'کندل/قیمت XAUUSD',
     'تحلیل دوگانهٔ Classic + SMC/ICT → پلن → گیت → ورود خودکار',
     '۳۴ ترید · $196+ · وین‌ریت ۷۹٪'],
    ['شنوندهٔ سیگنال', 'گروه تلگرام (۷ کانال)',
     'تازگی ≤۱۰دقیقه ← فیلتر نماد ← پارس ← گیت ۸-چکه (≥۶/۱۰)',
     '۲۲ رویداد · ۰ اجرا (همه رد)'],
], widths=[30, 30, 60, 28])
para(doc, 'نکتهٔ معماری مهم: فورواردر هر ۷ کانال را در یک گروه می‌ریزد و '
          'شنونده همان گروه را می‌خواند؛ یعنی همهٔ کانال‌ها از قبل ورودی '
          'هستند و فیلترکنندهٔ واقعی، گیت است — نه نبودِ اتصال.',
     size=9.5, color=GRAY)

# ───────────────────────── 5 controls
heading(doc, '۵. چارچوب کنترل ریسک', 1)
para(doc, 'هیچ‌یک از گیت‌ها در این دوره شل نشده‌اند. جدول، خطِ دفاعی '
          'سیستم را نشان می‌دهد:')
make_table(doc, ['Control', 'Value / Rule', 'Source'], [
    ['ریسک هر ترید', '۲٪ موجودی (ضریب تطبیقی ≤ 1.0)', 'auto_executor'],
    ['حداقل نسبت R/R', '1.5', 'auto_executor'],
    ['پذیرش سیگنال', 'امتیاز ≥ ۶ از ۱۰ (۸ چک)', 'signal_decision'],
    ['حد ضرر', 'بدون SL → رد قطعی', 'همهٔ مسیرها'],
    ['اخبار/ماکرو', 'HARD BLOCK — تقویم ناموجود = معامله نیست', 'b30'],
    ['ساعات بازار', 'Sun 23:00 – Fri 22:00 UTC', 'market_hours'],
    ['DEFCON', 'GREEN/YELLOW/RED از بازخورد تریدهای بسته', 'defcon'],
    ['Kill Switch', 'توقف خودکار روی ضررهای متوالی', 'kill_switch'],
    ['Cooldown', 'استراحت اجباری بعد از هر ترید', 'cooldown'],
    ['تازگی سیگنال', 'قدیمی‌تر از ۱۰ دقیقه → نادیده', 'signal_listener'],
    ['نماد', 'غیرطلا → رد (زنده + replay مشترک)', 'b74g'],
], widths=[34, 76, 38])
heading(doc, 'حلقهٔ ایمنی سه‌لایهٔ کد', 2)
bullets(doc, [
    'verify_head.sh — سوئیت کامل روی کلون تمیز detached از HEAD',
    'git_sync.sh — از push کردن HEAD تأییدنشده خودداری می‌کند',
    'head_verify.py — ابتدای هر اجرای autopilot، استمپ گمشده را ترمیم '
    'می‌کند',
])

# ───────────────────────── 6 engineering
heading(doc, '۶. وضعیت مهندسی', 1)
make_table(doc, ['Metric', 'Value'], [
    ['HEAD', 'c32f4e8 — هم‌ارز origin/master (push شده)'],
    ['Commits', '152 (+1 گزارش حاضر)'],
    ['Python files', '403'],
    ['Lines of code', '70,542'],
    ['Tests', '725 سبز روی clean-checkout (128 ثانیه) · 58 فایل تست'],
    ['engines modules', '34 ماژول — 7,882 خط'],
    ['Scripts', '123 — 13,538 خط (آزمایشگاه/بک‌تست/replay)'],
    ['Live data', '1,529 فایل · 45MB — پلن‌ها، replay، لاگ سیگنال'],
    ['Logs', '58 فایل · 1.7MB'],
    ['Services', '6 systemd user — همه enabled (ماندگار پس از ریبوت)'],
], widths=[42, 106])

# ───────────────────────── 7 performance
heading(doc, '۷. عملکرد و شواهد', 1)
heading(doc, '۷.۱ عملکرد زندهٔ سیستم (بروکر، ۲۱ آگوست – ۳ سپتامبر)', 2)
make_table(doc, ['Metric', 'Value', 'Note'], [
    ['Trades closed', '34 in 12 days', 'حجم نمونه برای داوری کم است'],
    ['Net P&L', '$196+ (lot 0.01–0.16)', 'قابل‌قیاس مستقیم با replay نیست'],
    ['Normalized to 0.01 lot', '+$54 ≈ $4.5 / day', 'در حد نیمی از goldfree'],
    ['MaxDD', '-$167', 'قابل قبول برای دمو'],
    ['Win rate', '79%', 'برد +$20 / ضرر -$50 → پروفایل شکننده'],
], widths=[38, 56, 54])
heading(doc, '۷.۲ نتیجهٔ replay ۹۰ روزهٔ ۷ کانال (۰.۰۱ لات، TP1، بدون اسپرد)', 2)
make_table(doc, ['Channel', 'Legs', 'Net P&L', 'MaxDD', 'Win%', 'Verdict'], [
    ['goldfree', '349', '+$948', '-$59', '82', 'تنها کانال ارزشمند'],
    ['gtmo', '63', '+$106', '-$14', '68', 'کوچک ولی تمیز'],
    ['radin', '667', '+$595', '-$486', '53', 'لبه فقط در فروش'],
    ['goldsystem', '37', '+$23', '-$22', '57', 'حاشیهٔ ناچیز'],
    ['otsfx', '6', '+$19', '-$36', '33', '۶۹٪ جفت‌ارز، نه طلا'],
    ['gtmofx (پولی)', '115', '-$84', '-$102', '76', 'رد'],
    ['olivex', '47', '-$244', '-$244', '15', 'رد — بدترین'],
], widths=[26, 14, 20, 20, 14, 54], mono_cols=(1, 2, 3, 4))
para(doc, 'با اسپرد 0.5 دلار: radin به ~+$262 و نسبت بازده/ریسک منفی '
          'می‌رسد؛ goldfree همچنان ~+$774 است.', size=9.5, color=GRAY)
heading(doc, '۷.۳ یافتهٔ اصلی دوره: صفر-اجرا در مسیر سیگنال', 2)
para(doc, 'در کل پنجرهٔ رصد (۲۸ آگوست تا امروز)، گیت سیگنال ۲۲ رویداد را '
          'پردازش و همه را رد کرده است. در دنیای واقعی هنوز نمونه‌ای از '
          '«گیت، سیگنال خوب را پذیرفت» نداریم؛ شواهد پذیرش/رد فعلاً فقط '
          'از replay است. با ۲۲ رویداد نمی‌توان میان «گیت محافظ ماست» و '
          '«گیت کور است» تمایز گذاشت — و همین، دلیل منطقی تصمیم '
          '«دست‌نزدن تا ۱۰۰ ترید زنده» است.')

# ───────────────────────── 8 decision log
heading(doc, '۸. دفتر تصمیمات', 1)
make_table(doc, ['Date', 'Decision', 'Rationale / Evidence'], [
    ['۱۳ شهریور ۱۴۰۵', 'گزینهٔ الف: بدون تغییر گیت/RR/ورودی/لاگ سایه‌ای',
     'شواهد زنده ناکافی (۲۲ رویداد)؛ بازبینی پس از ~۱۰۰ ترید زنده'],
    ['۱۲ شهریور', 'b74g — فیلتر نماد در شنوندهٔ زنده (مشترک با replay)',
     'رویداد BUY XAUUSD @ 1655.8 = نشت جفت‌ارز؛ سیستم را سخت‌تر می‌کند'],
    ['۱۱ شهریور', 'گیت RR روی TP1 باقی می‌ماند؛ شل‌کردن برای نردبان ممنوع',
     'replay ۹۰ روزه: رد زیرمجموعه ۱۲۱-$ ضرر بوده'],
    ['۸ شهریور', 'فوروارد فقط زنده — بک‌فیل تاریخچه ممنوع',
     '«سیگنال بی‌تایم بدتر از بی‌سیگنال»'],
    ['۳۱ مرداد', 'حذف کامل ورودی/تأیید انسانی از مسیر ترید',
     'دستور نهایی مدیریت: سیستم ۱۰۰٪ خودکار'],
    ['۳۱ مرداد', 'بلاک خبری از جریمه به HARD BLOCK تبدیل شد (b30)',
     'سیگنال ۷.۵ می‌توانست وسط FOMC اجرا شود'],
], widths=[24, 60, 64])

# ───────────────────────── 9 risks
heading(doc, '۹. ثبت ریسک‌ها', 1)
make_table(doc, ['ID', 'Risk', 'Severity', 'Response'], [
    ['R1', 'صفر-اجرا در مسیر سیگنال — ارزش کانال‌ها (goldfree +$948) '
     'عملاً دریافت نمی‌شود', 'HIGH',
     'جمع‌آوری دادهٔ زنده تا ~۱۰۰ ترید؛ بازبینی گیت با مدرک، نه بک‌تست'],
    ['R2', 'پروفایل شکنندهٔ سود: ضرر میانگین ۲.۵× برد میانگین', 'HIGH',
     'پایش هفتگی؛ تغییر سیاست خروج فقط با شواهد'],
    ['R3', 'اسپرد در replay لحاظ نشده — اعداد خوش‌بینانه', 'MEDIUM',
     'حساسیت اسپرد محاسبه شد؛ نتیجه تغییر نکرد'],
    ['R4', 'بایز تاریخی فقط از ۲۸ آگوست — replay کامل گیت ممکن نیست',
     'MEDIUM', 'لاگ بایز فعال است؛ با گذر زمان پر می‌شود'],
    ['R5', 'پنجرهٔ ۱۲ روزهٔ زنده برای هر ادعای برتری', 'MEDIUM',
     'گزارش هفتگی پنجشنبه؛ داوری در ۴-۶ هفته'],
    ['R6', 'لاگ autopilot_cron.log از ۲ سپتامبر بی‌محتوا (خطاهای '
     'تاریخی گمراه‌کننده)', 'LOW', 'فایل فیکس شده؛ پاک‌سازی لاگ در '
     'نوبت autopilot'],
    ['R7', 'دو هشدار npm در hermes doctor (ابزار مرورگر)', 'LOW',
     'بی‌ربط به مسیر ترید؛ اولویت پایین'],
], widths=[12, 62, 16, 58], rag_col=2)

# ───────────────────────── 10 action plan
heading(doc, '۱۰. برنامهٔ اقدام', 1)
make_table(doc, ['Action', 'Owner', 'Timeline', 'Status'], [
    ['ادامهٔ اجرای بدون‌دست‌کاری و جمع‌آوری ترید زنده', 'سیستم',
     'مستمر', 'IN PROGRESS'],
    ['گزارش هفتگی مدیریت', 'سیستم', 'هر پنجشنبه ۱۷:۳۰ تهران', 'SCHEDULED'],
    ['بازبینی گیت سیگنال با ~۱۰۰ ترید زنده', 'مدیریت + سیستم',
     'رسیدن به آستانه', 'GATED'],
    ['پایش سلامت بریج/VM', 'سیستم', 'هر ۵ دقیقه', 'ACTIVE'],
    ['پاک‌سازی لاگ قدیمی autopilot', 'سیستم', 'چرخهٔ بعدی', 'QUEUED'],
    ['رسیدگی به هشدارهای npm', 'زیرساخت', 'اولویت پایین', 'BACKLOG'],
], widths=[58, 26, 38, 26], rag_col=3)

# ───────────────────────── 11 appendix
heading(doc, '۱۱. پیوست — نقشهٔ ارجاع', 1)
make_table(doc, ['Topic', 'Location'], [
    ['متن کامل همین گزارش (Markdown)', 'reports/SYSTEM_STATE_2026-09-04.md'],
    ['راه‌اندازی روی سرور تازه', 'docs/DEPLOY.md + setup.sh'],
    ['کارکرد autopilot', 'docs/AUTOPILOT.md · data/ops/autopilot_backlog.md'],
    ['منطق گیت سیگنال (۸ چک)', 'engines/signal_decision.py'],
    ['منطق گیت تریدر', 'engines/auto_executor.py'],
    ['پارسر سیگنال', 'engines/signal_parser.py'],
    ['تحلیل SMC/ICT', 'engines/smc.py'],
    ['پارامترهای ریسک', 'engines/risk.py · defcon.py · kill_switch.py'],
    ['خروجی replay کانال‌ها', 'data/radin/replay_*.csv'],
    ['تأیید HEAD', 'data/ops/head_verified.json · logs/verify_head.log'],
    ['گزارش هفتگی', 'scripts/weekly_report.py'],
], widths=[62, 86])
para(doc, 'پایان گزارش — تهیه‌شده به‌صورت خودکار توسط Hermes؛ '
          'همهٔ اعداد در زمان ۱۹:۴۰ UTC جمعه ۴ سپتامبر ۲۰۲۶ از '
          'بروکر/دیسک قرائت شده‌اند.', size=8.5, color=GRAY)

out = '/home/ai/hermes-trading/reports/Hermes_System_Report_1405-06-13.docx'
doc.save(out)

# Declare Tahoma in fontTable.xml so Word resolves it cleanly (incl. complex
# script face used for Persian).
import zipfile, shutil, os, re
tmp = out + '.tmp'
with zipfile.ZipFile(out) as zin:
    names = zin.namelist()
    ft = zin.read('word/fontTable.xml').decode('utf-8')
    with zipfile.ZipFile(tmp, 'w', zipfile.ZIP_DEFLATED) as zout:
        for n in names:
            data = zin.read(n)
            if n == 'word/fontTable.xml':
                if 'w:name="Tahoma"' not in ft:
                    decl = ('<w:font w:name="Tahoma">'
                            '<w:altName w:val="Microsoft Sans Serif"/>'
                            '<w:panose1 w:val="020B0604030504040204"/>'
                            '<w:charset w:val="00"/>'
                            '<w:family w:val="swiss"/>'
                            '<w:pitch w:val="variable"/></w:font>')
                    ft = ft.replace('</w:fonts>', decl + '</w:fonts>')
                data = ft.encode('utf-8')
            zout.writestr(n, data)
os.replace(tmp, out)
print('saved', out)
