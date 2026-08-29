#!/usr/bin/env python3
"""Generate the full infrastructure status report (Persian, RTL) as .docx."""
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

from docx import Document
from docx.shared import Pt, Cm, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml.ns import qn
from docx.oxml import OxmlElement

IRT = timezone(timedelta(hours=3, minutes=30))
OUT = Path("/home/ai/hermes-trading/reports/Hermes_Trading_Infrastructure_Report.docx")
OUT.parent.mkdir(exist_ok=True)

DARK = RGBColor(0x1F, 0x2A, 0x44)
ACCENT = RGBColor(0xC9, 0x9A, 0x3C)   # gold
GREEN = RGBColor(0x2E, 0x7D, 0x32)
RED = RGBColor(0xB3, 0x26, 0x1E)
GRAY = RGBColor(0x66, 0x66, 0x66)

doc = Document()

# page setup
for sec in doc.sections:
    sec.top_margin = Cm(2); sec.bottom_margin = Cm(2)
    sec.left_margin = Cm(2.2); sec.right_margin = Cm(2.2)

# base style
style = doc.styles["Normal"]
style.font.name = "Vazirmatn"
style.font.size = Pt(11)
rpr = style.element.get_or_add_rPr()
rf = rpr.find(qn('w:rFonts'))
if rf is None:
    rf = OxmlElement('w:rFonts'); rpr.append(rf)
rf.set(qn('w:cs'), 'Vazirmatn')
rf.set(qn('w:ascii'), 'Vazirmatn')
rf.set(qn('w:hAnsi'), 'Vazirmatn')


def rtl_p(text="", size=11, bold=False, color=None, align="right", space_after=6, space_before=0):
    p = doc.add_paragraph()
    p.alignment = {"right": WD_ALIGN_PARAGRAPH.RIGHT,
                   "center": WD_ALIGN_PARAGRAPH.CENTER,
                   "left": WD_ALIGN_PARAGRAPH.LEFT}[align]
    pf = p.paragraph_format
    pf.space_after = Pt(space_after); pf.space_before = Pt(space_before)
    # RTL paragraph
    pPr = p._p.get_or_add_pPr()
    bidi = OxmlElement('w:bidi'); bidi.set(qn('w:val'), '1'); pPr.append(bidi)
    if text:
        r = p.add_run(text)
        r.font.size = Pt(size); r.bold = bold
        if color: r.font.color.rgb = color
        r.font.name = "Vazirmatn"
        rr = r._r.get_or_add_rPr()
        cs = rr.find(qn('w:rtl'))
        if cs is None:
            cs = OxmlElement('w:rtl'); rr.append(cs)
    return p


def heading(text, level=1):
    sizes = {0: 22, 1: 15, 2: 13}
    p = rtl_p(text, size=sizes[level], bold=True,
              color=DARK if level else ACCENT, space_before=14 if level else 0, space_after=8)
    if level == 1:
        pPr = p._p.get_or_add_pPr()
        pbdr = OxmlElement('w:pBdr')
        b = OxmlElement('w:bottom')
        b.set(qn('w:val'), 'single'); b.set(qn('w:sz'), '6')
        b.set(qn('w:space'), '2'); b.set(qn('w:color'), 'C99A3C')
        pbdr.append(b); pPr.append(pbdr)
    return p


def table(headers, rows, widths=None):
    t = doc.add_table(rows=1 + len(rows), cols=len(headers))
    t.style = "Light Grid Accent 1"
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    # RTL table
    tblPr = t._tbl.tblPr
    bidi = OxmlElement('w:bidiVisual'); tblPr.append(bidi)
    for i, h in enumerate(headers):
        c = t.rows[0].cells[i]
        c.text = ""
        p = c.paragraphs[0]; p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        r = p.add_run(h); r.bold = True; r.font.size = Pt(10); r.font.name = "Vazirmatn"
    for ri, row in enumerate(rows):
        for ci, val in enumerate(row):
            c = t.rows[ri + 1].cells[ci]
            c.text = ""
            p = c.paragraphs[0]; p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
            r = p.add_run(str(val)); r.font.size = Pt(10); r.font.name = "Vazirmatn"
    doc.add_paragraph().paragraph_format.space_after = Pt(2)
    return t


def bullets(items):
    for it in items:
        rtl_p("•  " + it, size=10.5, space_after=3)


# ═══════════════ COVER ═══════════════
for _ in range(4):
    doc.add_paragraph()
rtl_p("گزارش وضعیت زیرساخت معاملاتی Hermes", size=26, bold=True, color=DARK, align="center", space_after=10)
rtl_p("معماری، اجزا، و نحوه‌ی کارکرد سیستم", size=14, color=GRAY, align="center", space_after=30)
rtl_p("XAUUSD • CapitalXtend • Linux Brain + Windows Execution", size=11, color=ACCENT, align="center", space_after=40)
rtl_p(f"تاریخ تهیه: {datetime.now(IRT).strftime('%Y/%m/%d - %H:%M')} به وقت تهران", size=11, color=GRAY, align="center")
rtl_p("تهیه‌شده توسط: Hermes Agent", size=11, color=GRAY, align="center")
doc.add_page_break()

# ═══════════════ 1. EXEC SUMMARY ═══════════════
heading("۱. خلاصه‌ی مدیریتی", 1)
rtl_p("سیستم معاملاتی خودکار طلا (XAUUSD) با معماری «مغز لینوکس + بازوی ویندوز» طراحی شده است. "
      "تمام تصمیم‌گیری‌ها روی سرور لینوکس انجام می‌شود و ویندوز سرور فقط و فقط نقش اجرای دستور در MT5 را دارد. "
      "هیچ کدی بدون عبور از ۱۳ گیت ایمنی دستور خرید/فروش نمی‌فرستد.", size=11)
bullets([
    "مغز تصمیم: Ubuntu 24 — پایتون، ~۶۱۰۰ خط کد، ۲۳ ماژول موتور، ۳۷ تست خودکار",
    "بازوی اجرا: Windows Server VM — MT5 + HTTP Bridge با احراز هویت توکنی",
    "حساب: CapitalXtend (login 10382667) — بالانس فعلی ~$5,070",
    "قانون طلایی: هیچ تریدی بدون عبور از همه گیت‌ها اجرا نمی‌شود؛ کنترل نهایی با کاربر",
    "یادگیری تطبیقی: سیستم از ژورنال معاملات خودش پارامترها را سفت/شل می‌کند",
])

# ═══════════════ 2. ARCHITECTURE ═══════════════
heading("۲. معماری کلی", 1)
rtl_p("جریان داده و کنترل:", size=11, bold=True)
table(
    ["لایه", "محل اجرا", "وظیفه"],
    [
        ["داده بازار", "MT5 (ویندوز)", "کندل‌ها، تیک، اکانت، پوزیشن‌ها — از طریق API متاتریدر"],
        ["پل ارتباطی", "ویندوز — پورت 5050", "bridge.py (Flask) — فقط با Bearer Token و فقط از IP لینوکس"],
        ["مغز تحلیل", "لینوکس — هر ۱۵ دقیقه", "تحلیل Classic + SMC/ICT، ساخت پلن، ارزیابی مانیتور"],
        ["گیت ایمنی", "لینوکس", "۱۳ چک قبل از هر دستور (ریسک، DEFCON، خبر، رنج، RR و...)"],
        ["اجرا", "لینوکس → ویندوز", "ارسال دستور سفارش به بریج؛ تایید retcode بروکر"],
        ["مدیریت پوزیشن", "لینوکس — هر ثانیه", "position_daemon: BE، پارتیال، تریل، time-exit، news-lock"],
        ["سیگنال تلگرام", "لینوکس — بلادرنگ", "signal_daemon: خواندن کانال، پارس، تصمیم، اجرا"],
        ["گزارش‌دهی", "لینوکس", "گزارش هر سایکل به تلگرام + لاگ کامل + ژورنال"],
    ],
)
rtl_p("اصل طراحی: لینوکس هیچ‌وقت MT5 را مستقیم لمس نمی‌کند و ویندوز هیچ‌وقت تصمیم نمی‌گیرد. "
      "اگر ویندوز قطع شود، لینوکس فقط گزارش می‌دهد؛ اگر لینوکس قطع شود، دیمون‌های ویندوزی کاری انجام نمی‌دهند.", size=10.5, color=GRAY)

# ═══════════════ 3. CYCLE ═══════════════
heading("۳. چرخه‌ی کار — یک سایکل کامل (هر ۱۵ دقیقه)", 1)
table(
    ["#", "فاز", "چه اتفاقی می‌افتد"],
    [
        ["1", "سلامت بریج", "پینگ /health با توکن؛ اگر ویندوز down باشد → هشدار و توقف امن"],
        ["2", "گرفتن داده", "اکانت، تیک XAUUSD، پوزیشن‌های باز، کندل‌های M5/M15/H1/H4/D1/W1"],
        ["3", "مسیریابی", "build_plan / monitor / reassess — بر اساس انقضای پلن و وضعیت بازار"],
        ["4", "تحلیل دوگانه", "Classic (regime/bias/value zone) + SMC (OB/FVG/OTE/POI/Killzone + 8 مفهوم پیشرفته) → ادغام"],
        ["5", "پلن معاملاتی", "side/entry/SL/TP با هندسه معتبر؛ re-anchor به قیمت زنده؛ اعتبار ۴ ساعته"],
        ["6", "مانیتور", "آیا قیمت به zone رسید؟ proposal ساخته می‌شود"],
        ["7", "گیت‌ها", "۱۳ چک ایمنی روی proposal (بخش ۴)"],
        ["8", "اجرا", "سفارش با سایز ریسک‌محور → بریج → MT5 → retcode → ثبت در execution_log"],
        ["9", "مدیریت", "دیمون ثانیه‌ای: BE در 0.5R، پارتیال در TP1، تریل، news-lock، time-exit"],
        ["10", "یادگیری", "ژورنال تریدهای بسته + تحلیل → تنظیم خودکار پارامترها"],
        ["11", "گزارش", "خلاصه‌ی فارسی به تلگرام (چه کرد، چرا کرد، چه دیدی دارد)"],
    ],
)

# ═══════════════ 4. SAFETY GATES ═══════════════
heading("۴. گیت‌های ایمنی — هیچ تریدی بدون این‌ها رد نمی‌شود", 1)
table(
    ["گیت", "قانون", "منبع"],
    [
        ["۱. اعتبار پلن", "پلن منقضی/مسدود → اجرا نمی‌شود", "جدید"],
        ["۲. مجوز ریسک", "risk budget ≤ ۲٪ بالانس در حالت عادی", "جدید"],
        ["۳. رنج مارکت", "regime=range → فقط limit، بدون market", "جدید"],
        ["۴. محدودیت روزانه", "حداکثر ترید/روز + ضرر روزانه", "جدید"],
        ["۵. سقف پوزیشن", "حداکثر ۱ پوزیشن باز", "جدید"],
        ["۵.۵ هندسه", "SELL: TP<entry<SL — وگرنه رد", "جدید"],
        ["۵.۶ حداقل RR", "ریسک/ریوارد ≥ ۱.۵ (بک‌تست‌شده)", "بک‌تست"],
        ["۶. گرید ستاپ", "حداقل B (تقاطع OB/FVG + روند ≥ ۸)", "بک‌تست"],
        ["۶.۵ یادگیری", "آستانه‌های سفت‌ترِ خودکار از ژورنال", "یادگیری"],
        ["۶.۶ DEFCON", "GREEN کامل / YELLOW نصف ریسک / RED ورود ممنوع", "مهاجرت قدیم"],
        ["۶.۷ کول‌داون", "۱۵ دقیقه بعد باز شدن بازار + ۵ دقیقه بعد ریستارت", "مهاجرت قدیم"],
        ["۷. فیلتر خبر", "بلک‌اوت ۳۰ دقیقه اطراف خبر قرمز USD", "جدید"],
        ["۸. بازار باز", "تعطیل/ویک‌اند → retcode 10018 رد می‌شود", "جدید"],
        ["۹. Kill Switch", "ضرر روزانه ۵٪ / افت دارایی ۱۰٪ / ۴ ضرر متوالی → توقف کامل ۴ ساعته", "جدید"],
    ],
)
rtl_p("اولویت مدیریت پوزیشن (مهاجرت از سیستم قدیمی): news_lock (۱) > time_exit (۲) > partial_tp (۳) > trail (۴) > breakeven (۵). "
      "قانون طلایی قدیمی هم حفظ شد: اگر خروج‌های مدیریتی به‌طور مزمن ضرر بدهند، runnerها کلاً خاموش می‌شوند.", size=10.5, color=GRAY)

# ═══════════════ 5. MODULES ═══════════════
heading("۵. نقشه‌ی ماژول‌ها", 1)
rtl_p("موتور تحلیل:", size=11, bold=True, space_after=2)
table(
    ["ماژول", "کار"],
    [
        ["engines/context.py", "تحلیل Classic: bias، regime، value zone، ATR"],
        ["engines/smc.py", "SMC/ICT: OB، FVG، Liquidity Sweep، Premium/Discount، Killzone، POI Grading + ۸ مفهوم پیشرفته (Breaker، OTE، Power-of-3، Silver Bullet...)"],
        ["engines/plan.py", "ساخت پلن + re-anchor هندسه به قیمت زنده"],
        ["engines/orchestrator.py", "سایزینگ پوزیشن ریسک‌محور"],
        ["engines/macro_snapshot.py", "DXY، سیلور، SPX، حجم تیک، موقعیت H4/D1/W1"],
        ["engines/economic_calendar.py", "تقویم خبری + بلک‌اوت"],
    ],
)
rtl_p("اجرا و ایمنی:", size=11, bold=True, space_after=2)
table(
    ["ماژول", "کار"],
    [
        ["engines/auto_executor.py", "مغز تصمیم اجرا — ۱۳ گیت + ساخت command"],
        ["engines/risk.py", "بودجه ریسک، رژیم اکانت، performance state"],
        ["engines/kill_switch.py", "توقف فاجعه‌بار + کول‌داون ۴ ساعته"],
        ["engines/defcon.py", "حلقه بازخورد تریدهای بسته (مهاجرت قدیم)"],
        ["engines/cooldown.py", "کول‌داون پس‌از-بازگشایی/ریستارت (مهاجرت قدیم)"],
        ["engines/legacy_guards.py", "time_exit ۳۶ ساعته + news_lock (مهاجرت قدیم)"],
        ["engines/trade_management.py", "BE / partial / trail / scale-in / close-early"],
        ["engines/learning.py", "ژورنال → تحلیل → تنظیم خودکار پارامتر"],
        ["engines/storage.py", "مانتژ پلن/تاریخچه/لاگ‌ها"],
    ],
)
rtl_p("نودهای اجرایی:", size=11, bold=True, space_after=2)
table(
    ["نود", "زمان‌بندی", "کار"],
    [
        ["hermes_master.py", "کرون هر ۱۵ دقیقه", "سایکل کامل + گزارش تلگرام"],
        ["position_daemon.py", "سرویس systemd — ثانیه‌ای", "مدیریت پوزیشن‌های باز"],
        ["signal_daemon.py", "سرویس systemd — بلادرنگ", "سیگنال‌های کانال تلگرام"],
        ["bridge_health_monitor", "کرون هر ۵ دقیقه", "پینگ بریج + ریستارت خودکار"],
        ["bridge.py (ویندوز)", "schtasks + watchdog", "اجرای MT5 — فقط با توکن"],
    ],
)

# ═══════════════ 6. LEARNING ═══════════════
heading("۶. سیستم یادگیری تطبیقی", 1)
rtl_p("هر سایکل، تریدهای بسته‌ی MT5 به ژورنال محلی اضافه می‌شود. وقتی نمونه‌ها به ۱۵ رسید، "
      "وین‌ریت و سود میانگین محاسبه شده و پارامترها تنظیم می‌شوند:", size=11)
bullets([
    "۱۵ ضرر متوالی → حداقل RR بالا می‌رود (تا ۲.۵)، گرید حداقل A، ریسک تا ۳۰٪ کاهش",
    "۱۵ سود متوالی → ریسک آرام آزاد می‌شود (هرگز بالای سقف ۲٪)",
    "عملکرد ضعیف SELL → آستانه RR مخصوص Sells بالا می‌رود",
    "اصل ایمنی: یادگیری فقط می‌تواند سخت‌گیرتر کند یا ریسک را در clamp کاهش دهد — هرگز قوانین بنیادی را شل نمی‌کند",
])

# ═══════════════ 7. SECURITY ═══════════════
heading("۷. امنیت", 1)
table(
    ["لایه", "وضعیت"],
    [
        ["احراز هویت بریج", "Bearer Token ۴۳ رقمی — درخواست بدون توکن = 401"],
        ["فایروال ویندوز", "پورت 5050 فقط از IP سرور لینوکس (قاعده Hermes MT5 Bridge)"],
        ["ذخیره توکن", "فقط در .env لینوکس و env متغیر ویندوز — خارج از ریپو"],
        ["دسترسی MT5", "فقط از طریق بریج؛ هیچ ترمینال/اسکریپت دیگری روی ویندوز ترید نمی‌زند"],
        ["تفکیک ربات", "ربات ترید (Account5000bot) کاملاً جدا از چت شخصی Hermes"],
        ["قانون کنترل", "دستور صریح کاربر برای ترید دستی؛ خودکار فقط در چارچوب گیت‌ها"],
    ],
)

# ═══════════════ 8. LEGACY MIGRATION ═══════════════
heading("۸. مهاجرت از سیستم قدیمی (بکاپ 20260813)", 1)
rtl_p("بکاپ کامل سیستم قبلی (۲۳۴۵ فایل) از دسکتاپ ویندوز استخراج و فایل‌به‌فایل مقایسه شد. "
      "شش قابلیت ارزشمندی که در بازسازی جا مانده بود، عیناً منتقل و تست شد:", size=11)
table(
    ["قابلیت", "ماژول جدید", "توضیح"],
    [
        ["DEFCON", "engines/defcon.py", "سطح‌بندی GREEN/YELLOW/RED با قوانین دقیق قدیمی + قطع runner وقتی مدیریت‌ها ضرر می‌دهند"],
        ["کول‌داون", "engines/cooldown.py", "ممنوعیت ورود ۱۵ دقیقه بعد بازگشایی هفتگی + ۵ دقیقه بعد ریستارت"],
        ["پری‌سشن ماکرو", "engines/macro_snapshot.py", "DXY/سیلور/SPX/حجم/زون‌های H4-D1-W1 در هر پلن"],
        ["time_exit", "engines/legacy_guards.py", "خروج پوزیشن کهنه (>۳۶ ساعت)"],
        ["news_lock", "engines/legacy_guards.py", "سفت‌کردن SL به ۰.۵ ATR نیم‌ساعت قبل خبر قرمز"],
        ["ژورنال غنی", "engines/learning.py", "اسنپ‌شات تصمیم + نتیجه + درس (نسخه خودکارِ قوی‌تر)"],
    ],
)
rtl_p("نکته: معماری قدیمی (کد خودش ترید می‌زد) بازنگشت — فقط دانش و گاردهایش منتقل شد. تصمیم‌گیر همچنان مغز لینوکس با گیت‌های جدید است.", size=10.5, color=GRAY)

# ═══════════════ 9. CURRENT STATUS ═══════════════
heading("۹. وضعیت لحظه‌ای", 1)
table(
    ["جزء", "وضعیت"],
    [
        ["سرور لینوکس (مغز)", "فعال — کرون هر ۱۵ دقیقه"],
        ["سرور ویندوز (MT5)", "فعال — HermesBridge + Watchdog: Ready"],
        ["بریج + احراز هویت", "سالم — health OK با توکن"],
        ["دیمون پوزیشن", "سرویس systemd فعال"],
        ["دیمون سیگنال", "سرویس systemd فعال"],
        ["تست‌ها", "37/37 سبز"],
        ["حساب", "بالانس ~$5,070 — بدون پوزیشن باز"],
        ["پلن فعلی", "XAUUSD bearish — breakout_continuation — سشن London"],
        ["بازار", "تعطیل آخر هفته — بازگشایی یکشنبه ۰۲:۳۰ بامداد تهران"],
    ],
)

# ═══════════════ 10. ROADMAP ═══════════════
heading("۱۰. باقی‌مانده و برنامه", 1)
bullets([
    "امتیازدهی اعتبار فرستنده سیگنال: ثبت نتیجه‌ی سیگنال‌های ردشده (فاز ۵ — بعد از جمع شدن داده واقعی)",
    "چند هفته عملکرد زنده با پارامترهای بک‌تست‌شده قبل از افزایش ریسک",
    "بازبینی hysteresis: سیستم قدیمی ۶ ضرر متوالی داشت — گاردهای جدید (DEFCON + kill switch + یادگیری) جلوی تکرارش را می‌گیرند",
])

rtl_p("", space_after=20)
rtl_p("— پایان گزارش —", size=10, color=GRAY, align="center")

doc.save(OUT)
print("saved:", OUT)
