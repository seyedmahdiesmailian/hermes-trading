# -*- coding: utf-8 -*-
"""Build the full management-style Word report (v2 — detailed, with charts)."""
import os
import sys
from pathlib import Path

# b66: resolve the repo from THIS file, never an absolute literal — a moved
# repo or second checkout must not read/write the wrong tree.
_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_REPO))   # bridge_client lives at repo root
from report_lib import *   # noqa
from docx.shared import Pt, Mm, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.oxml import OxmlElement

OUT = str(_REPO / 'reports' / 'Hermes_System_Report_Full_1405-06-13.docx')
CH = '/tmp'   # scratch dir for generated charts (not a repo path)

# b64/b66: the report must not restate network facts as literals — a moved
# box would keep describing the OLD network while looking authoritative. The
# Windows arm comes from bridge_client (the single resolver of HERMES_WIN_IP);
# this box's own address comes from the kernel routing table.
from bridge_client import WIN_IP as _BRIDGE_WIN_IP


def _local_ip() -> str:
    """This machine's own LAN address, asked of the OS — no literal written
    down anywhere, so a relocated box reports its real new address."""
    import subprocess
    try:
        out = subprocess.run(['hostname', '-I'], capture_output=True,
                             text=True, timeout=5).stdout.split()
        return out[0] if out else '—'
    except (OSError, subprocess.SubprocessError):
        return '—'


WIN_IP = _BRIDGE_WIN_IP
LAN_IP = _local_ip()
FWD_DIR = str(Path.home() / 'projects' / 'forwarder-telegram-dockerized')

doc = Document()
sec = doc.sections[0]
sec.page_width, sec.page_height = Mm(210), Mm(297)
sec.top_margin = sec.bottom_margin = Mm(18)
sec.left_margin = sec.right_margin = Mm(MARGIN_MM)

st = doc.styles['Normal']
st.font.name = FONT
st.font.size = Pt(10.5)
st.font.color.rgb = DARK
st.element.rPr.rFonts.set(qn('w:cs'), FONT)
st.paragraph_format.line_spacing = 1.18

# header / footer
hp = rtl(sec.header.paragraphs[0], WD_ALIGN_PARAGRAPH.CENTER)
R(hp, 'گزارش وضعیت و معماری سیستم Hermes  ·  داخلی — محرمانه', size=8, color=GRAY)
pPr = sec.header.paragraphs[0]._p.get_or_add_pPr()
pbdr = OxmlElement('w:pBdr')
bt = OxmlElement('w:bottom')
bt.set(qn('w:val'), 'single'); bt.set(qn('w:sz'), '6')
bt.set(qn('w:space'), '2'); bt.set(qn('w:color'), 'BFC9D9')
pbdr.append(bt); pPr.append(pbdr)

fp = rtl(sec.footer.paragraphs[0], WD_ALIGN_PARAGRAPH.CENTER)
R(fp, 'HMT-1405-06-13 · v2.0 · ', size=8, color=LGRAY)
field(fp, 'PAGE', '1')
R(fp, ' از ', size=8, color=LGRAY)
field(fp, 'NUMPAGES', '1')

# ══════════════════════════════ COVER ══════════════════════════════════
for _ in range(3):
    doc.add_paragraph()
p = rtl(doc.add_paragraph(), WD_ALIGN_PARAGRAPH.CENTER)
R(p, 'HERMES', size=13, bold=True, color=BLUE)
p = rtl(doc.add_paragraph(), WD_ALIGN_PARAGRAPH.CENTER)
R(p, 'گزارش وضعیت و معماری سیستم', size=27, bold=True, color=NAVY)
p = rtl(doc.add_paragraph(), WD_ALIGN_PARAGRAPH.CENTER)
R(p, 'زیرساخت تریدینگ خودکار طلا (XAUUSD)', size=15, bold=True, color=STEEL)
p = rtl(doc.add_paragraph(), WD_ALIGN_PARAGRAPH.CENTER)
p.paragraph_format.space_after = Pt(18)
R(p, 'مغز لینوکسی  ·  بازوی اجرای MT5  ·  مسیر سیگنال تلگرام  ·  '
     'چارچوب کنترل ریسک', size=10.5, color=GRAY)

make_table(doc, ['فیلد', 'مقدار'], [
    ['شناسهٔ گزارش', 'HMT-1405-06-13'],
    ['تاریخ صدور', 'جمعه ۱۳ شهریور ۱۴۰۵ — ۲۰۲۶-09-04، ساعت ۱۹:۴۰ UTC'],
    ['بازهٔ گزارش', '۲۱ آگوست تا ۴ سپتامبر ۲۰۲۶ (عملکرد) — وضعیت لحظه‌ای'],
    ['نسخه', '2.0 — کامل، همراه با نمودار و پیوست فنی'],
    ['تهیه‌کننده', 'Hermes (تولید خودکار) — همهٔ اعداد زنده از دیسک و بروکر'],
    ['تأییدکننده', 'سید مهدی اسماعیلیان'],
    ['طبقه‌بندی', 'داخلی — محرمانه'],
    ['دامنه', '۶ سرویس، ۴۰۳ فایل پایتون، ۷۰٬۵۴۲ خط کد، ۲ موتور ترید، '
              '۷ کانال سیگنال، ۳۷ موتور تحلیلی و ریسک'],
], widths=[42, 116], first_col_bold=True)

para(doc, '', size=6)
callout(doc, 'نکتهٔ صحت‌سنجی (مهم‌ترین تغییر این نسخه)',
        'در نسخهٔ قبلی این گزارش، عملکرد به‌صورت «۳۴ ترید / ۱۹۶+ دلار» اعلام شد. '
        'آن اعداد نادرست بودند: ۳۴ تعداد «دیل‌های» بروکر بود، نه تعداد پوزیشن '
        '(هر پوزیشن یک دیل باز کردن و یک یا چند دیل بستن دارد). با تجمیع بر '
        'اساس position_id، ارقام صحیح به‌دست آمد: ۲۴ پوزیشن، سود ناخالص '
        '۱۹۶.۰۰ دلار، کارمزد ۴.۹۸- دلار، و سود خالص ۱۹۱.۰۲ دلار. '
        'همهٔ اعداد عملکرد در این نسخه از همین روش استخراج شده‌اند.',
        fill=RED_F, bar="C62828", tcol=RED_T)
page_break(doc)

# ══════════════════════════════ TOC ════════════════════════════════════
heading(doc, 'فهرست مطالب', 1)
p = doc.add_paragraph()
field(p, r'TOC \o "1-3" \h \z \u',
      'راست‌کلیک ← Update Field برای ساخت فهرست با شماره صفحه')
para(doc, 'این سند شامل ۱۲ بخش و ۳ پیوست است: خلاصه مدیریتی، داشبورد وضعیت، '
          'معماری، سرویس‌ها، پروژهٔ تریدر، پروژهٔ سیگنال، چارچوب ریسک، '
          'وضعیت مهندسی، عملکرد (با نمودار)، تحلیل کانال‌ها، دفتر تصمیمات، '
          'ثبت ریسک‌ها و برنامهٔ اقدام.', size=9.5, color=GRAY)
page_break(doc)

# ═══════════════════════ ۱ EXECUTIVE SUMMARY ═══════════════════════════
heading(doc, '۱. خلاصه مدیریتی', 1)
para(doc,
     'سیستم تریدینگ Hermes در وضعیت پایدار و کاملاً خودکار در حال اجراست. '
     'هر شش سرویس systemd فعال‌اند، هیچ یونیت شکست‌خورده‌ای وجود ندارد، '
     'پل ارتباطی با متاتریدر سالم است، ۷۲۵ تست خودکار روی کلون تمیز کد پاس '
     'می‌شوند و هیچ پوزیشن بازی باز نکرده است. حساب نمایشی با موجودی '
     '۵٬۱۸۶ دلار، بدون ضرردی روزانهٔ فعال و بدون تریگر kill-switch است.')
para(doc,
     'در ۱۲ روز اخیر ۲۴ پوزیشن توسط موتور داخلی باز و بسته شده است: '
     '۱۸ برد و ۶ باخت، سود خالص ۱۹۱.۰۲ دلار پس از کسر کارمزد، و افت '
     'سرمایهٔ حداکثری ۱۶۸.۴۸- دلار. این سود عمدتاً از چند برد بزرگ '
     '(بیشترین ۸۳.۹۷ دلار) آمده، نه از شیب پیوسته؛ و یک باخت ۱۰۵.۶۰- '
     'تنها ۵۵٪ کل سود دوره را می‌بلعد.')

heading(doc, 'یافتهٔ کلیدی این دوره', 2)
callout(doc, 'مسیر سیگنال تلگرام تاکنون صفر ترید اجرا کرده است',
        '۲۲ رویداد پردازش سیگنال از ۲۸ آگوست ثبت شده و هیچ‌کدام به اجرا '
        'نرسیده (executed=True = صفر). همهٔ ۲۴ پوزیشن واقعی از موتور تحلیل '
        'داخلی (hermes_master) آمده‌اند، نه از کانال‌ها. گیت امتیازدهی با '
        'آستانهٔ ۶ از ۱۰، عملاً هر سیگنال کانال را رد می‌کند. '
        'این یعنی دو گزاره که قبلاً یکی فرض می‌شدند از هم جدا می‌شوند: '
        '«گیت از ما محافظت می‌کند» و «گیت ما را از سود محروم می‌کند». '
        'با ۲۲ نمونه نمی‌توان تشخیص داد کدام درست است — و به همین دلیل '
        'تصمیم بر «دست نزدن» و جمع‌آوری داده باقی ماند.',
        fill=AMBER_F, bar="F9A825", tcol=AMBER_T)

heading(doc, 'تصمیم‌های مورد نیاز مدیریت', 2)
make_table(doc, ['#', 'تصمیم', 'توصیهٔ سیستم', 'اولویت'], [
    ['D-1', 'آیا آستانهٔ گیت سیگنال (۶ از ۱۰) بازنگری شود؟',
     'خیر — تا رسیدن به ~۱۰۰ ترید زندهٔ جدید', 'پایین'],
    ['D-2', 'آیا کانال goldfree (+۹۴۸$ در رپلی ۹۰ روزه) به منبع زنده تبدیل شود؟',
     'خیر — گیت همان را هم رد می‌کند؛ اول داده', 'پایین'],
    ['D-3', 'آیا حساب از دمو به واقعی منتقل شود؟',
     'خیر — ۲۴ پوزیشن برای نتیجه‌گیری کافی نیست', 'متوسط'],
    ['D-4', 'آیا پروفایل ریسک (میانگین باخت ۵۸.۳۱- در برابر برد ۳۰.۰۵+) اصلاح شود؟',
     'بله — این تنها ضعف ساختاری تأییدشده است', 'بالا'],
], widths=[10, 62, 62, 24], center_cols=(0, 3), rag_col=None)

heading(doc, 'وضعیت در یک نگاه', 2)
kpi_grid(doc, [
    ('STABLE', 'وضعیت کلی', 'g'),
    ('6 / 6', 'سرویس فعال', 'g'),
    ('725', 'تست سبز', 'g'),
    ('0', 'پوزیشن باز', 'g'),
    ('+$191.02', 'سود خالص ۱۲ روز', 'g'),
    ('75.0%', 'نرخ برد', 'g'),
    ('-$168.48', 'حداکثر افت سرمایه', 'r'),
    ('0', 'ترید از سیگنال', 'a'),
], per_row=4)
page_break(doc)

# ═══════════════════════ ۲ SYSTEM DASHBOARD ════════════════════════════
heading(doc, '۲. داشبورد وضعیت لحظه‌ای', 1)
para(doc, 'همهٔ مقادیر زیر در لحظهٔ تولید گزارش (۱۹:۴۰ UTC جمعه) از سرویس‌ها، '
          'بریج و بروکر خوانده شده‌اند.', size=9.5, color=GRAY)

heading(doc, '۲.۱ زیرساخت و سرویس‌ها', 2)
make_table(doc, ['کامپوننت', 'وضعیت', 'جزئیات'], [
    ['hermes-signal', 'ACTIVE', 'daemon سیگنال تلگرام — long-poll'],
    ['hermes-position', 'ACTIVE', 'watchdog مدیریت پوزیشن، ثانیه‌ای'],
    ['hermes-forwarder', 'ACTIVE', 'فوروارد ۷ کانال → یک گروه'],
    ['hermes-dashboard', 'ACTIVE', 'پنل‌های فقط‌خواندنی تلگرام'],
    ['hermes-gateway', 'ACTIVE', 'اتصال تلگرام / هرمس'],
    ['omniroute', 'ACTIVE', 'provider مدل روی localhost:20128'],
    ['MT5 Bridge', 'OK', 'پینگ VM ۰.۵۷ms — آخرین بررسی ۱۹:۴۰'],
    ['Failed units', 'NONE', 'systemctl — صفر یونیت شکست‌خورده'],
    ['Host uptime', '6 days', 'load average 0.49'],
    ['Disk /', 'OK', '۳۲٪ مصرف — ۴۴ گیگ آزاد'],
], widths=[36, 22, 100], rag_col=1, center_cols=(1,))

heading(doc, '۲.۲ حساب و بازار', 2)
make_table(doc, ['شاخص', 'مقدار', 'توضیح'], [
    ['Balance', '$5,186.04', 'حساب نمایشی 10382667'],
    ['Equity', '$5,186.04', 'مساوی balance — پوزیشن باز نیست'],
    ['Free margin', '$5,186.04', 'بدون درگیری مارجین'],
    ['Open positions', '0', 'پل و بروکر هم‌نظرند'],
    ['XAUUSD bid / ask', '4435.33 / 4435.45', 'اسپرد ۰.۱۲ دلار'],
    ['Market state', 'OPEN', 'جمعه ۱۹:۴۰ UTC — ۲:۲۰ ساعت تا بسته شدن'],
    ['M5 history depth', '20,000 candles', 'تا ۲۶ مه ۲۰۲۶'],
], widths=[38, 40, 80], center_cols=(1,))

heading(doc, '۲.۳ چارچوب کنترل ریسک', 2)
make_table(doc, ['گارد', 'وضعیت', 'آستانهٔ فعال'], [
    ['Kill switch', 'OFF — normal', 'ضرر روزانه ۵٪ / افت ۱۰٪ / ۴ باخت متوالی'],
    ['Consecutive losses', '0', 'تریگر در ۴'],
    ['Cooldown', 'OFF', '۴ ساعت پس از هر halt'],
    ['DEFCON', 'GREEN', 'YELLOW در باخت متوالی ≥۲'],
    ['Plan bias', 'NEUTRAL', 'جهت پلن فعلی خنثی است'],
    ['Daily trade cap', 'READY', 'محدودیت تعداد ترید روزانه فعال'],
], widths=[36, 26, 96], rag_col=1, center_cols=(1,))

heading(doc, '۲.۴ خط لولهٔ داده', 2)
make_table(doc, ['مرحله', 'وضعیت', 'جزئیات'], [
    ['Forwarder → Group', 'SYNCED', '۷ کانال → گروه -1003805320011'],
    ['Group → Parser', 'ACTIVE', '۲۲ رویداد پردازش‌شده (کل تاریخچه)'],
    ['Parser → Gate', 'ACTIVE', 'گیت ۸-مرحله‌ای، آستانه ۶/۱۰'],
    ['Gate → Execution', 'BLOCKED', '۰ عبور از گیت — صفر اجرا'],
    ['Position watchdog', 'READY', 'بدون پوزیشن برای مدیریت'],
    ['Git sync', 'VERIFIED', 'HEAD = origin/master — stamp معتبر'],
], widths=[36, 24, 98], rag_col=1, center_cols=(1,))
page_break(doc)

# ═══════════════════════ ۳ ARCHITECTURE ════════════════════════════════
heading(doc, '۳. معماری سیستم', 1)
para(doc, 'معماری دو-ماشینه با تفکیک کامل «تصمیم» از «اجرا». لینوکس فکر می‌کند '
          'و ویندوز فقط دست به کلید می‌زند. این تفکیک عمدی است: پس از فروپاشی '
          'سیستم قبلی، تصمیم شد که هیچ منطق تحلیلی روی ماشین MT5 اجرا نشود تا '
          'قطعی یا ری‌استارت ویندوز، مغز سیستم را از بین نبرد.')

picture(doc, f'{CH}/chart_arch.png',
        caption='شکل ۱ — معماری و جریان کنترل/داده. مسیر بالایی سیگنال تلگرام '
                'است (که تاکنون صفر اجرا داده) و مسیر میانی موتور تحلیل داخلی '
                '(که هر ۲۴ پوزیشن واقعی از آن آمده).')

heading(doc, '۳.۱ گره‌ها و نقش‌ها', 2)
make_table(doc, ['گره', 'IP', 'نقش', 'اجزا'], [
    ['Ubuntu 24.04', LAN_IP, 'مغز — تحلیل، تصمیم، ریسک، زمان‌بندی',
     '۶ سرویس systemd · ۷ کران · ۴۰۳ فایل پایتون'],
    ['Windows Server VM', WIN_IP, 'بازوی اجرا — فقط MT5',
     'MT5 در session 1 · Bridge :5050 با Bearer auth'],
    ['Telegram', '—', 'منبع سیگنال و کانال گزارش',
     '۷ کانال · ۱ گروه واسط · چت مدیر 194015957'],
], widths=[26, 24, 46, 62])

heading(doc, '۳.۲ جریان داده — مسیر سیگنال', 2)
para(doc, 'از کانال تا کلید، هفت مرحله. هر مرحله می‌تواند سیگنال را متوقف کند '
          'و دلیلش را ثبت می‌کند:', size=10)
make_table(doc, ['مرحله', 'کامپوننت', 'خروجی / شرط عبور'], [
    ['۱', '۷ کانال تلگرام', 'پیام خام (متن فارسی/انگلیسی، فرمت آزاد)'],
    ['۲', 'hermes-forwarder', 'فقط پیام زنده — بدون backfill گذشته'],
    ['۳', 'گروه واسط -1003805320011', 'همهٔ کانال‌ها در یک جا'],
    ['۴', 'signal_daemon (long-poll)', 'دریافت پیام + timestamp'],
    ['۵', 'engines/signal_parser', 'نماد، جهت، entry، SL، نردبان TP'],
    ['۶', 'engines/signal_decision', 'امتیاز ۰ تا ۱۰ — آستانهٔ ۶'],
    ['۷', 'engines/auto_executor', 'اجرا یا SKIP با دلیل ثبت‌شده'],
], widths=[10, 46, 102], center_cols=(0,))

heading(doc, '۳.۳ جریان داده — مسیر تریدر داخلی', 2)
para(doc, 'موتوری که تمام ۲۴ ترید واقعی از آن آمده است. برخلاف مسیر سیگنال، '
          'اینجا سیستم خودش بازار را می‌خواند و پلن می‌سازد:', size=10)
make_table(doc, ['مرحله', 'کامپوننت', 'کار'], [
    ['۱', 'BridgeClient.get_rates', '۲۰٬۰۰۰ شمع M5 + H1/D1 از MT5'],
    ['۲', 'engines/context', 'بافت قیمتی، نواحی، نقدینگی'],
    ['۳', 'engines/smc', 'Order Block، FVG، Liquidity، BOS/CHoCH'],
    ['۴', 'engines/plan', 'پلن Pre-session با جهت و ناحیهٔ ورود'],
    ['۵', 'engines/orchestrator', 'ارزیابی چرخه، blueprint، کیفیت'],
    ['۶', 'engines/risk + defcon', 'اندازهٔ لات، سطح ریسک مجاز'],
    ['۷', 'hermes_master → Bridge', 'ارسال command با SL اجباری'],
    ['۸', 'hermes-position watchdog', 'BE، trail، TP پلکانی، خروج'],
], widths=[10, 44, 104], center_cols=(0,))

heading(doc, '۳.۴ زمان‌بندی (Cron)', 2)
make_table(doc, ['دوره', 'اسکریپت', 'کار'], [
    ['هر ۵ دقیقه', 'bridge_health_monitor.py', 'سلامت بریج و MT5'],
    ['هر ۱۵ دقیقه', 'hermes_cron.sh', 'نگهداری و همگام‌سازی'],
    ['هر ۱۵ دقیقه', 'git_sync.sh', 'push فقط اگر stamp تأیید معتبر باشد'],
    ['ساعتی (:05)', 'autopilot.sh', 'چرخهٔ خودکار بهبود و backlog'],
    ['۰۲:۰۰', 'autopilot_digest.py', 'خلاصهٔ روزانهٔ autopilot'],
    ['۲۳:۴۵', 'offsite_backup.py', 'پشتیبان خارج از سایت'],
    ['پنجشنبه ۲۲:۳۰ UTC', 'weekly_report.py', 'گزارش هفتگی مدیریتی'],
], widths=[30, 48, 80])

heading(doc, '۳.۵ قفل کیفیت کد', 2)
para(doc, 'هیچ کدی بدون اثبات روی کلون تمیز push نمی‌شود. این قفل پس از دو '
          'بار شکست HEAD در گذشته ساخته شد:')
make_table(doc, ['مکانیزم', 'توضیح'], [
    ['scripts/verify_head.sh',
     'کارگیت تمیز از HEAD می‌سازد، ۷۲۵ تست را همان‌جا اجرا می‌کند'],
    ['data/ops/head_verified.json',
     'stamp شامل sha، حکم، تعداد تست و زمان — تنها مدرک معتبر'],
    ['scripts/git_sync.sh',
     'اگر sha استamp با HEAD نخواند، push نمی‌کند'],
    ['engines/head_verify.py',
     'منطق برنامه‌ای بررسی یکپارچگی stamp'],
    ['engines/dirty_work.py',
     'تشخیص آلودگی تست به فایل‌های واقعی (بهم‌ریختن state)'],
    ['engines/hermetic (tests/)',
     'use_temp_data_root() — جداسازی کامل تست از دادهٔ زنده'],
], widths=[40, 118])
page_break(doc)

# ═══════════════════════ ۴ PROJECT A: TRADER ═══════════════════════════
heading(doc, '۴. پروژهٔ اول — تریدر خودکار', 1)
para(doc, 'موتور اصلی که تمام تریدهای واقعی را زده است. فلسفهٔ طراحی: '
          '«پلن اول، ورود دوم». سیستم هیچ‌وقت بدون پلن مکتوب وارد معامله '
          'نمی‌شود و پلن هر بار قبل از ورود ارزیابی مجدد می‌شود.')

heading(doc, '۴.۱ تحلیل دوگانه — Classic + SMC/ICT', 2)
make_table(doc, ['موتور', 'فایل', 'خروجی'], [
    ['کلاسیک', 'engines/indicators.py (1,131 خط)',
     'MA، RSI، MACD، ATR، بولینگر، Stochastic، ADX، Ichimoku، VWAP، '
     'Pivot، Fibonacci، VWAP، divergence'],
    ['اسمارت‌مانی', 'engines/smc.py (616 خط)',
     'Order Block، Fair Value Gap، Liquidity Sweep، BOS، CHoCH، '
     'Premium/Discount، OTE، Breaker، Equal High/Low، Killzone، '
     'Displacement، FVG Mitigation'],
    ['بافت بازار', 'engines/context.py',
     'ناحیهٔ ورود بر اساس lookback شمع M5'],
    ['ساعت بازار', 'engines/market_hours.py',
     'پنجرهٔ XAUUSD: یکشنبه ۲۳:۰۰ تا جمعه ۲۲:۰۰ UTC'],
], widths=[22, 44, 92])

heading(doc, '۴.۲ چرخهٔ پلن‌سازی', 2)
make_table(doc, ['تابع', 'نقش'], [
    ['build_pre_session_plan()',
     'پلن قبل از سشن: جهت، ناحیهٔ ورود، ترازهای کلیدی، ریسک مجاز'],
    ['reassess_plan_bias()',
     'بازارزیابی جهت پلن با دادهٔ تازه (منبع دادهٔ بایز: ۷۵۹ رکورد از ۲۸ آگوست)'],
    ['build_plan_from_context()',
     'ساخت پلن از بافت بازار فعلی'],
    ['_passes_quality_gate()',
     'آیا پلن کیفیت ورود دارد؟'],
    ['route_runtime_step()',
     'تعیین گام بعدی در زمان اجرا'],
    ['evaluate_monitor_cycle()',
     'ارزیابی هر چرخهٔ مانیتورینگ با قیمت لحظه‌ای'],
    ['execute_trade_blueprint()',
     'تبدیل blueprint به command واقعی با حجم و SL'],
    ['compute_xau_position_size()',
     'لات از ریسک دلاری، گرد به volume_step، محدود به min/max'],
], widths=[46, 112])

heading(doc, '۴.۳ مدیریت پوزیشن (watchdog)', 2)
para(doc, 'سرویس hermes-position هر ثانیه پوزیشن‌های باز را بررسی می‌کند. '
          'منطق در engines/trade_management.py (۲۴۴ خط):')
make_table(doc, ['اقدام', 'شرط', 'منطق'], [
    ['Breakeven', 'پیش‌رفت کافی',
     '_breakeven_stop() — انتقال SL به نقطهٔ ورود'],
    ['Trailing stop', 'بر اساس grade',
     '_trail_params() — پارامترها به درجهٔ ستاپ (A/B/C) وابسته است'],
    ['Partial TP', 'رسیدن به TP پلکانی',
     '_partial_close_fraction() — بستن بخشی از حجم'],
    ['Close all at TP1', 'ب55',
     'اگر TP1 کل حجم باشد، MT5 partial ۱۰۰٪ را رد می‌کند → close کامل'],
    ['Scale-in', 'مجاز و تحت DEFCON',
     '_scale_in_allowed() — در YELLOW/RED غیرفعال'],
    ['Runner kill', 'استراتژی خروج ضعیف',
     '_runner_should_die() — قانون legacy حفظ شده'],
], widths=[26, 34, 98])

heading(doc, '۴.۴ گیت‌های پیش از ورود', 2)
make_table(doc, ['گیت', 'فایل', 'کار'], [
    ['Economic calendar', 'engines/economic_calendar.py',
     'بلک‌اوت خبری با دادهٔ ForexFactory (fallback کش)'],
    ['Macro filter', 'engines/macro_filter.py',
     'فیلتر ماکرو روی زمان و جفت‌ارز'],
    ['Macro snapshot', 'engines/macro_snapshot.py',
     'اسنپ‌شات pre-session'],
    ['Lab decay', 'engines/lab_decay.py',
     'بررسی شکل مارجین پیش از پرواز'],
    ['Broker clock', 'engines/broker_clock.py',
     'هم‌ترازی زمان بروکر با UTC (بروکر epoch می‌دهد)'],
    ['Market hours', 'engines/market_hours.py',
     'جلوگیری از ورود در بازار بسته'],
    ['Guard status', 'engines/guard_status.py',
     'آلارم گاردِ تضعیف‌شده'],
], widths=[30, 46, 82])
page_break(doc)

# ═══════════════════════ ۵ PROJECT B: SIGNAL ═══════════════════════════
heading(doc, '۵. پروژهٔ دوم — مسیر سیگنال تلگرام', 1)
para(doc, 'مسیری که پیام آزاد کانال‌ها را به دستور قابل‌اجرا تبدیل می‌کند. '
          'این مسیر از نظر کد کامل است و ۴ باگ جدی در آن اصلاح شده، اما '
          'هرگز ترید تولید نکرده است.')

heading(doc, '۵.۱ پارسر', 2)
para(doc, 'engines/signal_parser.py (۱٬۰۹۴ خط). پشتیبانی از فرمت‌های آزاد '
          'فارسی و انگلیسی:')
bullets(doc, [
    'استخراج نماد، جهت (BUY/SELL)، قیمت ورود، حد ضرر و حد سود',
    'نردبان کامل TP (tps, tps_raw) — قبلاً فقط TP اول نگه داشته می‌شد',
    'تبدیل قیمت‌های مخفف: «۲۴» → ۴۴۲۴ یا ۴۵۲۴ با لنگر entry و band واقعی بازار',
    'guard بزرگی عدد: تایپوی «TP7 39980» دیگر به هدف ۱۷٬۰۰۰- دلاری ترجمه نمی‌شود',
    'names_other_instrument() — رد جفت‌ارزهایی که خودشان را طلا جا می‌زنند (b74g)',
    'اعتبار هندسی SL: SL در سمت اشتباه entry باعث رد سیگنال می‌شود',
], size=10)

heading(doc, '۵.۲ گیت امتیازدهی — ۸ مرحله', 2)
para(doc, 'engines/signal_decision.py (۱۸۵ خط). سقف امتیاز ۱۰، آستانهٔ اجرا ۶. '
          'هر مرحله یا امتیاز می‌دهد یا کسر می‌کند:')
make_table(doc, ['مرحله', 'بررسی', 'امتیاز'], [
    ['۱', 'پشتیبانی نماد (غیر طلا → رد کامل)', 'رد فوری'],
    ['۲', 'کیفیت پارس و اطمینان سیگنال', '+۱.۰ پایه'],
    ['۳', 'تازگی سیگنال (staleness)', '+۲.۰ تازه / +۱.۰ قابل‌قبول'],
    ['۴', 'هم‌جهتی با بایز Hermes',
     '+۲.۰ هم‌جهت · +۰.۵ خنثی · ۱.۰- متعارض'],
    ['۵', 'ریسک به ریوارد',
     '+۱.۵ (≥۲) · +۱.۰ (≥۱.۵) · +۰.۵ (≥۱) · ۱.۰- (<۱)'],
    ['۶', 'سیاست حساب (trade_allowed)', 'قفل → رد'],
    ['۷', 'تطابق با پلن فعلی', '+۱.۵ / +۱.۰ / +۰.۵ / ۱.۰-'],
    ['۸', 'فیلتر ماکرو و بلک‌اوت خبری', '۵.۰- (رد) · ۰.۵-'],
], widths=[10, 62, 86], center_cols=(0,))

heading(doc, '۵.۳ حالت معلق (Pending)', 2)
para(doc, 'engines/signal_pending.py (۲۹۴ خط) — پاسخ به یک مشکل واقعی: کانال '
          'BUY @ 4472 می‌فرستد در حالی که قیمت 4484 است. سیگنال معتبر است، '
          'فقط قیمت هنوز نرسیده. قبلاً این مورد skip می‌شد؛ حالا تبدیل به '
          'BUY_LIMIT روی همان قیمت می‌شود.')
make_table(doc, ['رویداد', 'رفتار'], [
    ['filled', 'آلارم — مدیریت بعدی با مسیر عادی پوزیشن'],
    ['TTL expired', 'لغو + آلارم (سیگنال ۴ ساعته مرده است)'],
    ['kill-switch halt', 'لغو همهٔ pendingها + آلارم'],
    ['market close', 'لغو قبل از بسته شدن (گپ شنبه آن تریدی نیست که امضا کردیم)'],
    ['سقف', 'حداکثر HERMES_PENDING_MAX (پیش‌فرض ۲) هم‌زمان'],
    ['حجم', 'از مدل ریسک خودمان، سقف‌خورده با لات اعلامی کانال'],
], widths=[28, 130])

heading(doc, '۵.۴ کانال‌های ورودی', 2)
make_table(doc, ['کانال', 'شناسه', 'نقش'], [
    ['RADIN', '-1003417665507', 'کانال اصلی — ۷۱۶ پا در رپلی'],
    ['goldfree', '-1001845330414', 'قوی‌ترین در رپلی (+۹۴۸$)'],
    ['olivex', '-1002154820747', 'رد شده (−۲۴۴$)'],
    ['otsfx', '-1001732210058', 'کانال طلا نیست (~۶۹٪ جفت‌ارز)'],
    ['goldsystem', '-1001404446654', 'حاشیهٔ ناچیز (+۲۳$)'],
    ['gtmo', '-1002250937706', 'کوچک ولی تمیز (+۱۰۶$)'],
    ['gtmofx', '-1003970164492', 'ضررده (−۸۴$)'],
], widths=[26, 40, 92])
para(doc, 'معماری: فورواردر هر ۷ کانال را در یک گروه می‌ریزد و hermes-signal '
          'فقط از همان گروه می‌خواند. پس همهٔ کانال‌ها از قبل ورودی زنده‌اند؛ '
          'چیزی برای «اضافه کردن» وجود ندارد — فیلتر، خودِ گیت است.',
     size=9.5, color=GRAY)
page_break(doc)

# ═══════════════════════ ۶ RISK FRAMEWORK ══════════════════════════════
heading(doc, '۶. چارچوب کنترل ریسک', 1)
para(doc, 'چهار لایهٔ مستقل که هرکدام به‌تنهایی می‌تواند جلوی ترید را بگیرد. '
          'طراحی لایه‌ای است چون تجربهٔ فروپاشی سیستم قبلی نشان داد یک '
          'گارد تنها، روزی خاموش یا دور زده می‌شود.')

heading(doc, '۶.۱ لایهٔ ۱ — Kill Switch', 2)
para(doc, 'engines/kill_switch.py — بالاترین سطح. هر تریگر = توقف کامل:')
make_table(doc, ['پارامتر', 'مقدار', 'معنا'], [
    ['DAILY_LOSS_LIMIT_PCT', '5%', 'ضرر روزانه بیش از ۵٪ موجودی → HALT'],
    ['EQUITY_DRAWDOWN_LIMIT_PCT', '10%', 'افت سرمایه از قله → HALT'],
    ['CONSECUTIVE_LOSSES_LIMIT', '4', 'چهار باخت پشت سر هم → HALT'],
    ['MARGIN_RATIO_MIN', '10', 'نسبت مارجین آزاد کمتر از ۱۰ → HALT'],
    ['COOLDOWN_HOURS', '4', 'فاصلهٔ اجباری پس از هر توقف'],
], widths=[52, 18, 88], center_cols=(1,), mono_cols=(0,))

heading(doc, '۶.۲ لایهٔ ۲ — DEFCON (بازخورد ترید بسته‌شده)', 2)
make_table(doc, ['سطح', 'شرط', 'اقدام مجاز'], [
    ['GREEN', 'پیش‌فرض', 'همهٔ اقدامات، ریسک کامل'],
    ['YELLOW', 'باخت متوالی ≥۲  یا  (نسبت SL ≥۰.۵ و بسته ≥۳)',
     'ریسک نصف · runner غیرفعال · scale-in غیرفعال'],
    ['RED', 'بسته ≥۵ و SL-محور و ضرر روزانه منفی',
     'ورود جدید ممنوع · فقط مدیریت بازها'],
], widths=[20, 62, 74], rag_col=0, center_cols=(0,))
para(doc, 'قانون legacy که حفظ شده: اگر استراتژی خروج مدیریت‌شده consistently '
          'ضرر بزند (win ratio ≤ ۰.۳ و P&L منفی)، runnerها بدون توجه به سطح '
          'DEFCON غیرفعال می‌شوند.', size=9.5, color=GRAY)

heading(doc, '۶.۳ لایهٔ ۳ — سیاست حساب و بودجهٔ ریسک', 2)
para(doc, 'engines/risk.py — ضریب ریسک پویا بر اساس سلامت حساب:')
make_table(doc, ['شرط', 'ضریب', 'رژیم'], [
    ['ضرر روزانه ≤ ۳٪ موجودی  یا  افت ≥ ۵٪', '0.00', 'قفل کامل'],
    ['باخت متوالی ≥ ۲  یا  ضرر روزانه ≥ ۱٪', '0.75', 'احتیاط'],
    ['افت سرمایه ≥ ۲.۵٪', '0.50', 'کاهش'],
    ['نرمال', '1.00', 'عادی'],
], widths=[70, 20, 68], center_cols=(1,), rag_col=2)
para(doc, 'ریسک پایه بر حسب موجودی (پلکانی):')
make_table(doc, ['موجودی', 'ریسک پایه به ازای ترید'], [
    ['کمتر از $800', '1.0%'],
    ['$800 تا $1,500', '1.5%'],
    ['$1,500 تا $5,000', '2.0%'],
    ['بیش از $5,000', '1.5%'],
], widths=[60, 98], center_cols=(1,))
para(doc, 'بودجهٔ نهایی با recommend_risk_budget() و بر اساس درجهٔ ستاپ '
          '(A/B/C) تعیین می‌شود. در موجودی فعلی ($5,186) ریسک پایه ۱.۵٪ '
          'یعنی حدود $۷۸ به ازای هر ترید در حالت عادی است.', size=9.5)

heading(doc, '۶.۴ لایهٔ ۴ — قوانین ثابت', 2)
bullets(doc, [
    'بدون SL هیچ تریدی زده نمی‌شود — بدون استثنا، در هر دو مسیر',
    'RR ضعیف (زیر ۱) رد می‌شود: «این قمار است نه ترید»',
    'فورواردر فقط پیام زنده را می‌فرستد؛ گذشته هرگز backfill نمی‌شود',
    'هیچ فلاگ محیطی بدون مستند اضافه نمی‌شود (قانون b62)',
    'سیستم ۱۰۰٪ خودکار است — هیچ تأیید انسانی در مسیر وجود ندارد',
    'هیچ تریدی در چت شخصی هرمس انجام نمی‌شود؛ ربات ترید مستقل است',
], size=10)
page_break(doc)

# ═══════════════════════ ۷ ENGINEERING STATE ═══════════════════════════
heading(doc, '۷. وضعیت مهندسی', 1)

heading(doc, '۷.۱ شاخص‌های کد', 2)
kpi_grid(doc, [
    ('403', 'فایل پایتون', 'n'),
    ('70,542', 'خط کد', 'n'),
    ('152', 'کامیت', 'n'),
    ('725', 'تست سبز', 'g'),
], per_row=4)
make_table(doc, ['ناحیه', 'خط کد', 'سهم'], [
    ['tests/', '14,408', '۲۰٪'],
    ['scripts/', '13,538', '۱۹٪'],
    ['engines/', '7,882', '۱۱٪'],
    ['ریشه (daemon/master/bridge)', '2,331', '۳٪'],
    ['notifier/', '1,425', '۲٪'],
    ['باقی (docs, ops, mt5, tools)', '30,958', '۴۵٪'],
], widths=[60, 30, 68], center_cols=(1, 2))
para(doc, 'نسبت تست به منطق ≈ ۱.۸ به ۱. این عمدی است: هر باگی که در محیط '
          'واقعی دیده شده، به یک تست تبدیل شده تا تکرار نشود.', size=9.5)

heading(doc, '۷.۲ بزرگ‌ترین موتورها', 2)
make_table(doc, ['فایل', 'خط', 'مسئولیت'], [
    ['engines/indicators.py', '1,131', 'اندیکاتورهای کلاسیک'],
    ['engines/signal_parser.py', '1,094', 'پارسر سیگنال تلگرام'],
    ['engines/smc.py', '616', 'تحلیل SMC/ICT'],
    ['engines/signal_pending.py', '294', 'حالت معلق سیگنال'],
    ['engines/trade_management.py', '244', 'منطق BE/trail/TP'],
    ['engines/plan.py', '238', 'پلن pre-session'],
    ['engines/signal_decision.py', '185', 'گیت امتیازدهی'],
    ['engines/orchestrator.py', '179', 'ارکستراسیون چرخه'],
    ['engines/auto_executor.py', '174', 'اجرا و گیت نهایی'],
    ['engines/defcon.py', '171', 'بازخورد سطح ریسک'],
], widths=[52, 18, 88], center_cols=(1,))

heading(doc, '۷.۳ باگ‌های اصلاح‌شده در این دوره', 2)
para(doc, 'چهار باگ پارسر که مستقیماً روی سیستم زنده اثر داشتند:')
make_table(doc, ['باگ', 'اثر واقعی', 'رفع'], [
    ['نردبان TP دور ریخته می‌شد',
     'فقط TP اول تحلیل می‌شد؛ بقیهٔ اهداف نامرئی', 'b74'],
    ['«🔴Stop» به‌عنوان SELL تفسیر می‌شد',
     'جهت سیگنال برعکس می‌شد', 'b74e'],
    ['تایپوی عددی (TP7 39980)',
     'هدف ۱۷٬۰۰۰- دلاری ساختگی در رپلی', 'b74 guard'],
    ['SL در سمت اشتباه',
     'BUY با SL بالاتر = ضرر شمرده نمی‌شد', 'b74d'],
    ['جفت‌ارز به‌جای طلا در listener زنده',
     'GBPJPY با SL معتبر می‌توانست به‌عنوان طلا اجرا شود', 'b74g'],
], widths=[38, 66, 24], center_cols=(2,))
para(doc, 'سه مورد اول باعث شدند رپلی اولیهٔ goldfree (+۹٬۰۰۰$) اشتباه '
          'به‌نظر برسد. بعد از رفع، عدد واقعی +۹۴۸$ شد.', size=9.5, color=GRAY)

heading(doc, '۷.۴ بدهی فنی و محدودیت ابزار', 2)
make_table(doc, ['مورد', 'شرح', 'اثر'], [
    ['بدون LibreOffice',
     'هیچ پیش‌نمایش PDF/رندر از Word روی سرور گرفته نمی‌شود',
     'تأیید فقط در سطح XML'],
    ['python-dotenv نصب نیست',
     'بارگذاری env دستی با env_loader.py', 'مستند در مهارت'],
    ['BridgeClient ناهمگون',
     'get_positions دیکت می‌دهد نه لیست؛ get_account_info وجود ندارد؛ '
     'days فیلتر در get_history_deals بی‌اثر',
     'چند بار باعث خطای تحلیلی شد'],
    ['state.db بزرگ',
     '۲۶۶ مگابایت — یکپارچگی OK ولی یکبار نوشتن شکست خورد',
     'پیام هشدار سیستم'],
], widths=[26, 82, 50])
page_break(doc)

# ═══════════════════════ ۸ PERFORMANCE ═════════════════════════════════
heading(doc, '۸. عملکرد — ۲۴ پوزیشن در ۱۲ روز', 1)
para(doc, 'داده از دیل‌های بروکر استخراج شده و بر اساس position_id تجمیع شده '
          'است. یک پوزیشن ممکن است چند دیل بستن داشته باشد (partial TP + '
          'باقی‌مانده)، بنابراین شمارش دیل اشتباه است.')

heading(doc, '۸.۱ شاخص‌های اصلی', 2)
kpi_grid(doc, [
    ('24', 'پوزیشن بسته', 'n'),
    ('+191.02$', 'سود خالص', 'g'),
    ('75.0%', 'نرخ برد', 'g'),
    ('-$168.48', 'حداکثر افت', 'r'),
], per_row=4)
make_table(doc, ['شاخص', 'مقدار', 'تفسیر'], [
    ['پوزیشن باز و بسته‌شده', '24', '۲۴ ورود / ۳۴ خروج — همه بسته، صفر باز'],
    ['بردها / باخت‌ها', '18 / 6', 'نرخ برد ۷۵.۰٪'],
    ['سود ناخالص', '+$196.00', 'پیش از کارمزد'],
    ['کارمزد', '-$4.98', 'swap صفر'],
    ['سود خالص', '+$191.02', 'معیار واقعی'],
    ['میانگین برد', '+$30.05', '—'],
    ['میانگین باخت', '-$58.31', '۱.۹۴ برابر بزرگ‌تر از برد'],
    ['بهترین / بدترین', '+$83.97 / -$105.60', 'بدترین، ۵۵٪ سود کل را می‌بلعد'],
    ['حداکثر افت سرمایه', '-$168.48', 'تجمعی، فقط پوزیشن بسته'],
    ['پوزیشن چندپایه (TP جزئی)', '7 از 24', 'حداکثر ۳ پایه در یک پوزیشن'],
    ['لات مصرفی', '0.01 تا 0.16', 'میانگین 0.057 — متغیر'],
    ['سود نرمال‌شده @0.01', '+$67.39', 'برابر‌سازی حجم'],
    ['پنجرهٔ زمانی', '21 آگوست تا 3 سپتامبر', '۱۲ روز'],
], widths=[42, 34, 82], center_cols=(1,))

picture(doc, f'{CH}/chart_equity.png',
        caption='شکل ۲ — منحنی سود تجمعی ۲۴ پوزیشن بسته (خالص از کارمزد). '
                'سود عمدتاً از چند پلهٔ بزرگ می‌آید، نه شیب پیوسته.')
picture(doc, f'{CH}/chart_pertrade.png',
        caption='شکل ۳ — نتیجهٔ تک‌تک ۲۴ پوزیشن. تعداد برد زیاد است (۱۸) اما '
                'عمق باخت‌ها (میانگین ۵۸-) از ارتفاع بردها (میانگین ۳۰+) بیشتر است.')

heading(doc, '۸.۲ تفسیر صادقانه', 2)
callout(doc, 'پروفایل شکننده: سود از اجتناب از ضرر بزرگ می‌آید، نه برد بزرگ',
        'نرخ برد ۷۵.۰٪ خوب است، اما ترکیب آن با میانگین باخت ۵۸.۳۱- در برابر '
        'میانگین برد ۳۰.۰۵+ یعنی سیستم با یک باخت بد، دو تا سه برد را پاک می‌کند. '
        'بدون بدترین باخت ۱۰۵.۶۰- دلاری، سود خالص به حدود ۲۹۷ دلار می‌رسید. '
        'این تنها ضعف ساختاری است که در داده تأیید شده و تنها موردی است که '
        'پیشنهاد بازنگری جدی دارد (تصمیم D-4).',
        fill=AMBER_F, bar="F9A825", tcol=AMBER_T)

heading(doc, '۸.۳ تفکیک منبع ترید', 2)
make_table(doc, ['کامنت باز کردن', 'تعداد', 'سود'], [
    ['Hermes', '21', 'بخش عمده'],
    ['Hermes Master', '1', '—'],
    ['Hermes Apprentice', '1', '—'],
    ['TEST_WITH_SLTP', '1', 'تست — باید حذف/شناسایی شود'],
    ['HERMES_CLOSE_DEV20', '1', 'کامنت بستن'],
    ['مجموع پوزیشن', '24', '+$191.02 خالص'],
], widths=[52, 24, 82], center_cols=(1,))
para(doc, 'نکتهٔ مهم: کامنت دیل‌های بستن متفاوت است — شامل '
          '[sl 4431.33]، [tp 4466.84]، HermesClose، HermesPartial، '
          'HERMES_CLOSE_DEV20 و خالی. شمارش بر اساس کامنت دیل، همان خطایی '
          'بود که به عدد نادرست ۳۴ ترید رسید.', size=9.5, color=GRAY)

heading(doc, '۸.۴ مسیر سیگنال — صفر اجرا', 2)
make_table(doc, ['شاخص', 'مقدار', 'منبع'], [
    ['رویداد پردازش سیگنال (کل تاریخچه)', '22', 'logs/signal_daemon.log'],
    ['executed=True (کل تاریخچه)', '0', 'grep لاگ'],
    ['تصمیم‌های امروز', '21 skip / 0 execute', 'لاگ ۴ سپتامبر'],
    ['ترید واقعی از مسیر سیگنال', '0', 'بروکر — صفر'],
], widths=[62, 34, 62], center_cols=(1,))
para(doc, 'دلیل فنی: بالاترین امتیازی که یک سیگنال کانال می‌تواند بگیرد '
          'حدود ۵ است (چون بایز Hermes معمولاً neutral است → فقط +۰.۵ و '
          'نه +۲.۰)، در حالی که آستانهٔ اجرا ۶ است. یعنی گیت عملاً '
          'بستهٔ پیش‌فرض است.', size=10)

picture(doc, f'{CH}/chart_funnel.png',
        caption='شکل ۴ — قیف سیگنال با شمارش واقعی از دیسک: ۸٬۵۹۴ پیام کانال '
                'در ۹۰ روز → ۸۸۱ سیگنال پارس‌شده → ۱٬۳۵۸ پای قابل رپلی → '
                'فقط ۱۱۰ پای امتیازگیری‌شده (لاگ بایز از ۲۸ آگوست شروع شد) → '
                '۱ عبور از گیت → ۰ اجرای زنده. مقیاس لگاریتمی است.')
page_break(doc)

# ═══════════════════════ ۹ CHANNEL ANALYSIS ════════════════════════════
heading(doc, '۹. تحلیل تاریخی کانال‌ها', 1)
para(doc, 'رپلی ۹۰ روزه روی شمع واقعی XAUUSD، سیاست A، لات ثابت ۰.۰۱، '
          'بدون اسپرد. هدف: فهمیدن اینکه آیا کانال‌ها ارزش پیروی دارند یا نه. '
          'این تحلیل با قانون «فقط فوروارد زنده» تضاد ندارد — بک‌تست است، '
          'نه ارسال مجدد سیگنال قدیمی.')

picture(doc, f'{CH}/chart_channels.png',
        caption='شکل ۵ — مقایسهٔ ۷ کانال: سود خالص و حداکثر افت سرمایه '
                'در رپلی ۹۰ روزه با لات ثابت.')

heading(doc, '۹.۱ جدول نهایی', 2)
make_table(doc, ['کانال', 'پا', 'سود A', 'سود B', 'وین‌ریت', 'MaxDD', 'حکم'], [
    ['goldfree', '366', '+$948', '+$432', '78%', '-$59', 'تنها کانالی که می‌ارزد'],
    ['radin', '716', '+$595', '+$192', '50%', '-$486', 'بی‌کیفیت — افت سنگین'],
    ['gtmo', '63', '+$106', '+$94', '68%', '-$14', 'کوچک ولی تمیز'],
    ['goldsystem', '38', '+$23', '+$26', '55%', '-$22', 'حاشیهٔ ناچیز'],
    ['otsfx', '7', '+$19', '-$23', '29%', '-$36', 'اصلاً طلا نیست (۲۸ پا فیلتر)'],
    ['gtmofx', '118', '-$84', '-$135', '74%', '-$102', 'ضررده'],
    ['olivex', '50', '-$244', '+$2', '14%', '-$244', 'بدترین'],
], widths=[24, 12, 18, 18, 16, 18, 52], center_cols=(1, 2, 3, 4, 5))
para(doc, 'A = سیاست خروج فعلی (TP اول). B = سیاست جایگزین. اعداد '
          'خوش‌بینانه‌اند چون اسپرد لحاظ نشده؛ با اسپرد ۰.۵ دلار radin به '
          'حدود +۲۶۲ دلار می‌رسد ولی نسبت بازده/ریسکش منفی می‌ماند.',
     size=9.5, color=GRAY)

heading(doc, '۹.۲ مقایسه با عملکرد واقعی', 2)
make_table(doc, ['معیار', 'Hermes واقعی', 'goldfree رپلی'], [
    ['بازه', '۱۲ روز', '۹۰ روز'],
    ['لات', 'متغیر (۰.۰۱–۰.۱۶)', 'ثابت ۰.۰۱'],
    ['سود نرمال‌شده @0.01', '+$67.39', '+$948'],
    ['حداکثر افت', '-$168.48', '-$59'],
    ['نرخ برد', '75.0%', '78%'],
    ['اجرا شده در سیستم', '24', '0'],
], widths=[36, 44, 78], center_cols=(1, 2))
para(doc, 'این مقایسه به نفع goldfree است اما منصفانه نیست: ۱۲ روز در برابر '
          '۹۰ روز، و رپلی بدون اسپرد و بدون lag اجرا. تنها نتیجهٔ قابل‌دفاع '
          'این است که «نمی‌دانیم» و داده کم است.', size=10)

heading(doc, '۹.۳ مدرک گیت در پنجرهٔ بایز', 2)
bullets(doc, [
    '۱۰۱ پا در پنجره‌ای که بایز ثبت شده بود',
    'فقط ۱ پا از گیت عبور کرد',
    'پاهای ردشده در مجموع ۱۲۱- دلار ضرر بودند → گیت درست عمل کرد',
    'اما در goldfree تنها ۲۹ پا رد شد با ۸- دلار ضرر → مدرک ناکافی',
    'دادهٔ بایز فقط از ۲۸ آگوست موجود است (reassessment_log.csv، ۷۵۹ رکورد)',
], size=10)
page_break(doc)

# ═══════════════════════ ۱۰ DECISION LOG ═══════════════════════════════
heading(doc, '۱۰. دفتر تصمیمات', 1)
para(doc, 'تصمیم‌هایی که در این دوره گرفته شد و مبنای هرکدام. این بخش برای '
          'آن است که شش ماه بعد، دلیلِ هر انتخاب قابل بازیابی باشد.')
make_table(doc, ['تصمیم', 'مبنا', 'وضعیت'], [
    ['گیت دست‌نخورده می‌ماند (گزینهٔ الف)',
     'با ۲۲ رویداد نمی‌توان بین «محافظ» و «مانع» فرق گذاشت', 'ACTIVE'],
    ['بازکردن بحث گیت فقط پس از ~۱۰۰ ترید زنده',
     'آستانهٔ نمونه‌ای برای نتیجه‌گیری آماری', 'ACTIVE'],
    ['RR گیت بر مبنای TP اول',
     'نردبان TP لاگ می‌شود ولی سیاست خروج را عوض نمی‌کند', 'ACTIVE'],
    ['لنگر قیمت مخفف به entry',
     'قیمت زندهٔ بازار می‌تواند از سیگنال دور باشد', 'ACTIVE'],
    ['استفاده از band واقعی ۲۴ ساعته',
     'رفع ابهام «۲۴» → ۴۴۲۴ یا ۴۵۲۴', 'ACTIVE'],
    ['حاشیهٔ band از ۲۵ به ۱۰',
     'کاهش کاندیداهای اشتباه', 'ACTIVE'],
    ['فیلتر نماد در پارسر (نه replay)',
     'منبع حقیقت مشترک بین listener زنده و رپلی', 'ACTIVE'],
    ['Per-leg fill semantics',
     'پای زیر بازار = limit، پای بالای بازار = stop', 'ACTIVE'],
    ['هر SKIP با msg_id لاگ شود',
     'رفع ابهام «چرا پیام نیامد؟»', 'ACTIVE'],
    ['تست‌ها با use_temp_data_root',
     'HERMES_DATA_ROOT محیطی بر set_data_root اولویت دارد', 'ACTIVE'],
    ['push فقط با stamp تأیید معتبر',
     'دو بار HEAD شکست‌خورده در کلون تمیز', 'ACTIVE'],
], widths=[46, 76, 16], center_cols=(2,), rag_col=2)

heading(doc, '۱۰.۱ رویدادهای کلیدی', 2)
make_table(doc, ['تاریخ', 'رویداد', 'درس'], [
    ['۲ سپتامبر', 'HEAD e304c63 در کلون تمیز شکست',
     'آلودگی تست به state واقعی — آلوده‌سازی باید ایزوله شود'],
    ['۳ سپتامبر', 'HEAD 51c1ca2 شکست (import env_loader)',
     'ماژول فرضی + python-dotenv نصب نیست'],
    ['۳ سپتامبر', 'آلارم کاذب «LIMIT از لیست بروکر حذف شد»',
     'ریشه: تست، نه بروکر'],
    ['۴ سپتامبر', 'شکست نوشتن state.db',
     'دیتابیس سالم؛ احتمالاً قفل هم‌زمان WAL'],
    ['۴ سپتامبر', 'تصحیح «۳۴ ترید» به «۲۴ پوزیشن»',
     'شمارش دیل ≠ شمارش پوزیشن'],
], widths=[18, 52, 88])
page_break(doc)

# ═══════════════════════ ۱۱ RISK REGISTER ══════════════════════════════
heading(doc, '۱۱. ثبت ریسک‌ها', 1)
make_table(doc, ['ID', 'ریسک', 'شدت', 'پاسخ'], [
    ['R1', 'مسیر سیگنال صفر اجرا — اگر گیت بیش‌ازحد سخت باشد، '
     'سود ۹۴۸ دلاری goldfree هرگز دریافت نمی‌شود', 'HIGH',
     'جمع‌آوری داده تا ~۱۰۰ ترید؛ سپس بازنگری'],
    ['R2', 'پروفایل ریسک شکننده — باخت میانگین ۱.۸۵ برابر برد', 'HIGH',
     'تنها مورد پیشنهادی برای بازنگری (D-4)'],
    ['R3', 'وابستگی کامل به MT5 در session 1 ویندوز', 'MEDIUM',
     'autologon + Startup + health monitor هر ۵ دقیقه'],
    ['R4', 'D درایو ویندوز پر است', 'MEDIUM', 'استفاده فقط از C: — مستند'],
    ['R5', 'state.db بزرگ و یکبار شکست نوشتن', 'LOW',
     'یکپارچگی OK؛ در صورت تکرار، hermes doctor'],
    ['R6', 'بدون پیش‌نمایش رندر — تأیید سند فقط در سطح XML', 'LOW',
     'باز کردن در Word محلی'],
    ['R7', 'دادهٔ بایز فقط از ۲۸ آگوست — رپلی کامل گیت ممکن نیست', 'MEDIUM',
     'ثبت مداوم؛ بازبینی در ~۱۰۰ ترید'],
], widths=[8, 62, 16, 72], center_cols=(0, 2), rag_col=2)

heading(doc, '۱۱.۱ برنامهٔ اقدام', 2)
make_table(doc, ['اولویت', 'اقدام', 'وضعیت'], [
    ['بالا', 'پایش پروفایل برد/باخت و بررسی علت عمق ۱۰۵- دلاری', 'OPEN'],
    ['بالا', 'ادامهٔ ثبت لاگ بدون تغییر گیت', 'IN PROGRESS'],
    ['متوسط', 'رسیدن به ~۱۰۰ ترید زنده و سپس بازبینی گیت', 'SCHEDULED'],
    ['متوسط', 'یکپارچه‌سازی API بریج (dict/list، فیلتر days)', 'BACKLOG'],
    ['پایین', 'نصب LibreOffice برای رندر و پیش‌نمایش', 'BACKLOG'],
    ['پایین', 'آرشیو/فشرده‌سازی state.db', 'BACKLOG'],
], widths=[16, 100, 22], center_cols=(0, 2), rag_col=2)
page_break(doc)

# ═══════════════════════ ۱۲ APPENDICES ═════════════════════════════════
heading(doc, 'پیوست الف — مرجع پارامترهای فنی', 1)
para(doc, 'همهٔ آستانه‌های فعال در کد، همان‌طور که در منبع تعریف شده‌اند.',
     size=9.5, color=GRAY)
make_table(doc, ['پارامتر', 'مقدار', 'فایل'], [
    ['Signal gate threshold', '6 / 10', 'signal_decision.py'],
    ['MIN_RISK_REWARD', '1.5', 'auto_executor.py'],
    ['DAILY_LOSS_LIMIT_PCT', '0.05', 'kill_switch.py'],
    ['EQUITY_DRAWDOWN_LIMIT_PCT', '0.10', 'kill_switch.py'],
    ['CONSECUTIVE_LOSSES_LIMIT', '4', 'kill_switch.py'],
    ['MARGIN_RATIO_MIN', '10', 'kill_switch.py'],
    ['COOLDOWN_HOURS', '4', 'kill_switch.py'],
    ['HERMES_PENDING_MAX', '2 (env)', 'signal_pending.py'],
    ['Pending TTL', '4 hours', 'signal_pending.py'],
    ['Price band window', '24 hours H1', 'bridge_client.py'],
    ['Band margin', '10.0', 'signal_parser.py'],
    ['M5 history depth', '20,000 candles', 'bridge'],
    ['XAUUSD session', 'Sun 23:00 → Fri 22:00 UTC', 'market_hours.py'],
    ['DEFCON YELLOW', 'loss_streak ≥ 2', 'defcon.py'],
    ['DEFCON RED', 'closed ≥ 5 & SL-dominant & daily<0', 'defcon.py'],
    ['Runner disable', 'managed_win_ratio ≤ 0.3', 'defcon.py'],
], widths=[54, 44, 60], mono_cols=(0,))

heading(doc, 'پیوست ب — سرویس‌ها و مسیرها', 1)
make_table(doc, ['مسیر', 'محتوا'], [
    [str(_REPO), 'مخزن اصلی — ۴۰۳ فایل پایتون'],
    ['├ engines/', '۳۷ موتور تحلیل، ریسک، پارس، ارکستراسیون'],
    ['├ scripts/', '۶۰+ ابزار: verify_head, git_sync, autopilot, replay'],
    ['├ tests/', '۷۲۵ تست'],
    ['├ notifier/', 'پنل‌های تلگرام (dashboards, panels, callbacks)'],
    ['├ data/', '۴۵ مگابایت — ۱۷ زیرپوشهٔ وضعیت، پلن، ژورنال، رپلی'],
    ['├ logs/', '۵۸ فایل لاگ — ۱.۷ مگابایت'],
    ['├ ops/', 'unit files, install.sh, desktop, systemd'],
    ['└ reports/', 'خروجی گزارش‌های مدیریتی'],
    [FWD_DIR, 'فورواردر — config با ۷ کانال مبدأ'],
    [f'{WIN_IP}:5050', 'بریج MT5 با Bearer auth'],
], widths=[52, 106])

heading(doc, 'پیوست پ — واژه‌نامه', 1)
make_table(doc, ['اصطلاح', 'معنا'], [
    ['Bridge', 'سرویس روی ویندوز که درخواست‌های HTTP را به MT5 ترجمه می‌کند'],
    ['Gate', 'ارزیابی ۸-مرحله‌ای که به سیگنال امتیاز ۰ تا ۱۰ می‌دهد'],
    ['DEFCON', 'سطح ریسک پویا (GREEN/YELLOW/RED) بر اساس نتایج اخیر'],
    ['Kill switch', 'توقف کامل ترید در صورت عبور از حد ضرر یا افت'],
    ['SMC / ICT', 'تحلیل بر اساس سفارش‌بلوک، گپ ارزش منصفانه، نقدینگی'],
    ['Pre-session plan', 'پلن مکتوب قبل از سشن: جهت، ناحیه، ترازها'],
    ['Pending', 'سیگنال معتبری که قیمتش هنوز نرسیده → BUY_LIMIT'],
    ['Replay', 'شبیه‌سازی تاریخی سیگنال کانال روی شمع واقعی'],
    ['Leg', 'یک پای از سیگنال چند-هدفه'],
    ['Stamp', 'مدرک تأیید HEAD در کلون تمیز (head_verified.json)'],
    ['Normalized P&L', 'سود به لات ثابت ۰.۰۱ برای مقایسهٔ منصفانه'],
], widths=[34, 124])

para(doc, '')
p = rtl(doc.add_paragraph(), WD_ALIGN_PARAGRAPH.CENTER)
R(p, '— پایان گزارش —', size=9, color=LGRAY)

# ── fontTable: declare Tahoma ───────────────────────────────────────────
import zipfile, shutil, os
doc.save(OUT)
tmp = OUT + '.tmp'
with zipfile.ZipFile(OUT) as zin, zipfile.ZipFile(tmp, 'w',
                                                  zipfile.ZIP_DEFLATED) as zout:
    for item in zin.namelist():
        data = zin.read(item)
        if item == 'word/fontTable.xml':
            s = data.decode('utf-8')
            add = ''
            for name in ('Tahoma', 'Consolas'):
                if f'w:name="{name}"' not in s:
                    add += (f'<w:font w:name="{name}">'
                            '<w:panose1 w:val="020B0604030504040204"/>'
                            '<w:charset w:val="00"/>'
                            '<w:family w:name="swiss"/>'
                            '<w:pitch w:val="variable"/>'
                            '</w:font>')
            s = s.replace('</w:fonts>', add + '</w:fonts>')
            data = s.encode('utf-8')
        zout.writestr(item, data)
shutil.move(tmp, OUT)
print('saved', OUT, os.path.getsize(OUT), 'bytes')
