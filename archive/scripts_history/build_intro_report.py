# -*- coding: utf-8 -*-
"""Hermes — clean project introduction report (v2).

Center of gravity: the AUTONOMOUS TRADER — what it is, how one trading
cycle flows (data -> plan -> gate -> execute -> manage/learn), what makes
it safe, what it reports. The Telegram-signal feature is one short
subsection, not the story. Written for a reader with zero prior context;
no incident chronology, no scattered fragments.

b64/b66: no literal hosts or repo paths — everything derived at runtime.
"""
import os
import subprocess
import sys
from pathlib import Path

from docx import Document
from docx.shared import Pt, Mm, RGBColor
from docx.oxml.ns import qn
from docx.oxml import OxmlElement

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_REPO))
from report_lib import *   # noqa: E402,F401,F403

CH = '/tmp'
OUT = str(_REPO / 'reports' / 'Hermes_Project_Introduction_v2_1405-06-13.docx')


def _local_ip() -> str:
    """This machine's own LAN address, via the default route (no literal)."""
    try:
        out = subprocess.run(['hostname', '-I'], capture_output=True,
                             text=True, timeout=5).stdout
        return out.split()[0] if out.split() else 'this host'
    except Exception:
        return 'this host'


def _win_ip() -> str:
    try:
        import bridge_client
        return str(bridge_client.WIN_IP)
    except Exception:
        return 'execution host'


LAN_IP = _local_ip()
WIN = _win_ip()

# ── document scaffold (A4, margins, Normal style, header/footer) ──
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

hp = rtl(sec.header.paragraphs[0], WD_ALIGN_PARAGRAPH.CENTER)
R(hp, 'Hermes — گزارش معرفی پروژه', size=8, color=GRAY)
pPr = sec.header.paragraphs[0]._p.get_or_add_pPr()
pbdr = OxmlElement('w:pBdr')
bt = OxmlElement('w:bottom')
bt.set(qn('w:val'), 'single'); bt.set(qn('w:sz'), '6')
bt.set(qn('w:space'), '2'); bt.set(qn('w:color'), 'BFC9D9')
pbdr.append(bt); pPr.append(pbdr)

fp = rtl(sec.footer.paragraphs[0], WD_ALIGN_PARAGRAPH.CENTER)
R(fp, 'Hermes Introduction · ', size=8, color=LGRAY)
field(fp, 'PAGE', '1')
R(fp, ' از ', size=8, color=LGRAY)
field(fp, 'NUMPAGES', '1')

# ══════════════════════════════════ COVER ══════════════════════════════
for _ in range(5):
    doc.add_paragraph()
p = rtl(doc.add_paragraph(), WD_ALIGN_PARAGRAPH.CENTER)
R(p, 'Hermes', size=46, bold=True, color=NAVY)
p = rtl(doc.add_paragraph(), WD_ALIGN_PARAGRAPH.CENTER)
R(p, 'ربات تریدر خودکار طلا', size=20, bold=True, color=BLUE)
p = rtl(doc.add_paragraph(), WD_ALIGN_PARAGRAPH.CENTER)
R(p, 'معرفی کامل پروژه — معماری، قابلیت‌ها و مسیر پیش‌رو', size=12,
  color=LGRAY)
doc.add_paragraph()
p = rtl(doc.add_paragraph(), WD_ALIGN_PARAGRAPH.CENTER)
R(p, 'نسخهٔ معرفی · ۱۴۰۵/۰۶/۱۳', size=11, color=LGRAY)
page_break(doc)

# ══════════════════════════════════ TOC ════════════════════════════════
heading(doc, 'فهرست مطالب', level=1)
ptoc = rtl(doc.add_paragraph())
field(ptoc, r'TOC \o "1-2" \h \z \u', 'راست‌کلیک ← Update Field')
para(doc, 'پس از باز کردن سند در Word: راست‌کلیک روی فهرست ← Update Field '
          'تا شمارهٔ صفحه‌ها ساخته شود.', size=9, color=LGRAY)
page_break(doc)

# ══════════════════ 1. WHO IS HERMES ══════════════════
heading(doc, '۱ — Hermes چیست؟', level=1)
rich(doc, [
    ('Hermes یک ', {}),
    ('ربات تریدر کاملاً خودکار', {'bold': True}),
    (' برای بازار طلا (XAUUSD) است. نرم‌افزاری که مثل یک تریدر حرفه‌ای کار '
     'می‌کند: بازار را می‌خواند، پیش از هر ورود روی کاغذ می‌آورد که چرا، '
     'کجا، با چه حد ضرری و با چه توجیهی وارد می‌شود؛ سپس بدون هیچ دخالت '
     'انسانی معامله را باز و مدیریت می‌کند و در پایان هر هفته خودش '
     'کارنامه‌اش را می‌نویسد.', {}),
])
para(doc, 'مهم‌ترین ویژگی‌اش را در یک جمله می‌توان خلاصه کرد:', space_after=4)
callout(doc, 'هیچ انسانی در چرخهٔ ترید کلیک نمی‌کند.',
        'سیستم ۲۴ ساعته و ۷ روز هفته روی یک سرور داخلی اجرا می‌شود. تصمیم '
        'انسانی فقط در سطح سیاست‌گذاری کلان است (مثلاً تغییر سقف ریسک روزانه)، '
        'نه در ورود و خروج به معاملات.')
para(doc, 'Hermes دو «شخصیت» دارد که شخصیت اول، داستان اصلی است:',
     space_after=4)
bullets(doc, [
    'تریدر مستقل (قلب پروژه) — خودش تحلیل می‌کند، خودش پلن می‌نویسد، '
    'خودش معامله می‌کند. بخش‌های ۲ تا ۵ همین را روایت می‌کنند.',
    'شکارچی سیگنال (قابلیت جانبی) — می‌تواند سیگنال‌های تلگرامی را هم '
    'بخواند و از همان فیلترهای امنیتی تریدر رد کند. بخش ۶.',
])

# ══════════════════ 2. WHY ══════════════════
heading(doc, '۲ — چه دردی را درمان می‌کند؟', level=1)
para(doc, 'آمار صنعت یک‌شکل است: اکثر تریدرهای انسانی ضرر می‌کنند — نه به '
          'خاطر نداشتن دانش، به خاطر ساختار ذهن انسان. Hermes دقیقاً همان '
          'نقاط ضعف را با ماشین پر می‌کند:')
make_table(doc,
           ['نقطهٔ ضعف انسانی', 'پاسخ Hermes'],
           [
               ('احساسات: ترس، طمع، انتقام از بازار',
                'ربات هرگز نمی‌ترسد و طمع نمی‌کند؛ فقط قوانین از پیش '
                'نوشته را اجرا می‌کند'),
               ('خستگی و حواس‌پرتی',
                '۲۴/۷ بیدار است؛ هر ۱۵ دقیقه یک چرخهٔ کامل تصمیم‌گیری'),
               ('ورود بدون حد ضرر، ریسک بی‌قاعده',
                'بدون SL هیچ تریدی باز نمی‌شود — این قانون در کد نوشته '
                'شده، نه توصیه'),
               ('فراموشی و نبودِ حساب‌وکتاب',
                'هر تصمیم در ژورنال مکتوب می‌شود؛ گزارش هفتگی خودکار با '
                'اعداد واقعی بروکر'),
               ('تحلیل یک‌بُعدی',
                'تحلیل دوگانهٔ کلاسیک + SMC/ICT با رأی‌گیری هم‌زمان سه '
                'تایم‌فریم'),
           ],
           widths=[55, 100])

# ══════════════════ 3. ONE CYCLE — THE FLOWCHART ══════════════════
heading(doc, '۳ — یک چرخهٔ ترید، از داده تا درس', level=1)
para(doc, 'کل سیستم حول یک حلقهٔ تکرارشونده می‌چرخد: هر ۱۵ دقیقه، بدون '
          'استثنا، پنج مرحلهٔ زیر اجرا می‌شود. این نقشه، مهم‌ترین تصویر '
          'کل پروژه است:')
picture(doc, f'{CH}/chart_flow.png', width_mm=178,
        caption='شکل ۱ — فلوچارت چرخهٔ خودکار تریدر Hermes: داده ← پلن ← '
                'گیت امنیتی ← اجرا ← مدیریت و یادگیری')
page_break(doc)

heading(doc, 'مرحلهٔ ۱ — داده: بازار را می‌خواند', level=2)
para(doc, 'تریدر از طریق یک «پل» امن به متاتریدر وصل است و سه نوع داده '
          'می‌گیرد: کندل‌های پنج‌دقیقه، یک‌ساعته و چهارساعتهٔ طلا؛ قیمت '
          'زنده و اسپرد لحظه‌ای؛ و وضعیت حساب (موجودی، پوزیشن‌های باز، '
          'معاملات بسته). بدون دادهٔ تازه هیچ تصمیمی گرفته نمی‌شود — اگر '
          'پل قطع باشد، سیستم وارد حالت امن می‌شود و ترید جدیدی نمی‌زند.')

heading(doc, 'مرحلهٔ ۲ — پلن: قبل از ترید، روی کاغذ می‌آورد', level=2)
para(doc, 'قلب فلسفهٔ Hermes همین‌جاست: «Plan-First» — اول یک سند پلن '
          'مکتوب ساخته و روی دیسک ذخیره می‌شود، بعد سراغ ترید می‌رویم. '
          'پلن شامل این‌هاست:')
bullets(doc, [
    'جهت بازار (Bias) — رأی‌گیری هم‌زمان از سه تایم‌فریم M5/H1/H4؛ اگر '
    'جهت‌ها هم‌راستا نباشند، سوژهٔ قوی نداریم',
    'ناحیهٔ ورود — قیمت در تخفیف است یا پرمیوم؟ ناحیهٔ ارزش معاملاتی '
    '(Value Zone) کجاست؟',
    'تحلیل دوگانه — سبک کلاسیک روند و سطوح را می‌خواند، سبک SMC/ICT '
    'نقدینگی، اوردر بلاک و شکاف‌های قیمتی (FVG) را؛ خروجی یک عدد '
    'اطمینان است',
    'نقشهٔ راه ترید — قیمت ورود، حد ضرر، سه سطح سود و اندازهٔ پوزیشن '
    'بر اساس ریسک ثابت درصدی از سرمایه',
])
para(doc, 'پلن هر ۵ دقیقه بازبینی می‌شود؛ اگر بازار عوض شود پلن هم عوض '
          'می‌شود — ولی هیچ تریدی بدون پلنِ معتبر باز نمی‌شود.')

heading(doc, 'مرحلهٔ ۳ — گیت: ده لایهٔ امنیتی پیش از هر کلیک', level=2)
para(doc, 'حتی اگر پلن بگوید «بخر»، تریدر اجازهٔ ورود ندارد مگر از همهٔ '
          'قفل‌های زیر رد شود. قفل‌ها مستقل‌اند و حالت پیش‌فرض همه «ترید '
          'نکن» است (Fail-closed) — یعنی خرابی هر قفل، ورود را می‌بندد، '
          'نه باز:')
make_table(doc,
           ['قفل', 'به زبان ساده'],
           [
               ('حد ضرر اجباری', 'بدون SL مشخص، سفارش اصلاً ارسال نمی‌شود'),
               ('نسبت سود به ریسک (RR)', 'اگر پتانسیل سود نسبت به حد ضرر '
                'به آستانه نرسد، رد — «این قمار است نه ترید»'),
               ('Kill Switch', 'ضرر روزانه یا سری باخت‌های متوالی از سقف '
                'بگذرد → تریدر آن روز خاموش می‌شود'),
               ('DEFCON', 'سطح خطر بازار مثل سطح هشدار امنیتی؛ در وضعیت '
                'قرمز فقط نظارت، بدون ورود'),
               ('News Blackout', 'دور اخبار مهم (نرخ بهره، CPI…) ورود جدید '
                'ممنوع؛ اسپرد و نوسان غیرقابل‌اعتماد می‌شوند'),
               ('سقف اسپرد', 'فاصلهٔ خرید/فروش که از حد عادی بگذرد، ورود '
                'متوقف'),
               ('Cooldown', 'بعد از هر ترید بسته‌شده، استراحت اجباری برای '
                'جلوگیری از ترید انتقامی'),
               ('سقف پوزیشن و ریسک', 'حداکثر تعداد پوزیشن باز و مجموع '
                'ریسک هم‌زمان محدود'),
               ('ساعت بازار', 'خارج از سشن‌های فعال طلا، ورود جدید ندارد'),
               ('امتیاز ستاپ', 'کیفیت فرصت نمره می‌گیرد (۰ تا ۱۰)؛ زیر '
                'آستانه با ثبت دلیل رد می‌شود'),
           ],
           widths=[48, 107])

heading(doc, 'مرحلهٔ ۴ — اجرا: ارسال سفارش به بروکر', level=2)
para(doc, 'از این نقطه به بعد همه‌چیز ماشینی و در کسری از ثانیه است: '
          'سفارش با ورودی، حد ضرر و سه حد سود به MT5 ارسال می‌شود؛ شمارهٔ '
          'پوزیشن ثبت، پیام تلگرامی «ترید باز شد» می‌رود و پلن به حالت '
          '«در حال اجرا» می‌رود. اندازهٔ پوزیشن حدس نیست: از فرمول ریسک '
          'ثابت می‌آید — درصد مشخصی از سرمایه در هر ترید در معرض خطر، '
          'فارغ از میزان اطمینان.')

heading(doc, 'مرحلهٔ ۵ — مدیریت، خروج، یادگیری', level=2)
para(doc, 'بزرگ‌ترین تفاوت تریدر آماتور و حرفه‌ای اینجاست: بعد از ورود چه '
          'می‌شود. Hermes پوزیشن باز را رها نمی‌کند:')
bullets(doc, [
    'Breakeven خودکار — وقتی سود به حد مشخصی رسید، حد ضرر روی قیمت ورود '
    'می‌نشیند؛ از آن لحظه ترید ریسک‌فری شده',
    'Trailing — حد ضرر آرام‌آرام قیمت را دنبال می‌کند تا سودِ در جریان '
    'فرار نکند',
    'خروج پله‌ای — بخشی از پوزیشن در TP1 بسته و سود قطعی می‌شود؛ '
    'باقی‌مانده برای TP2 و TP3 باز می‌ماند',
    'خروج زمانی و قفل خبری — ترید بی‌حرکت یا خبر نزدیک، خروج با احتیاط '
    'را به‌دنبال دارد',
    'ژورنال و یادگیری — هر پوزیشن با شناسه، کمیسیون و سود خالص ثبت '
    'می‌شود؛ پنجشنبه‌ها گزارش هفتگی خودکار با وین‌ریت، Drawdown و اعداد '
    'واقعی بروکر ساخته می‌شود',
])

# ══════════════════ 4. ARCHITECTURE ══════════════════
heading(doc, '۴ — معماری فنی در یک نگاه', level=1)
para(doc, 'سیستم روی دو ماشین ساده ساخته شده؛ هیچ سرویس ابری یا هزینهٔ '
          'اشتراکی ندارد:')
make_table(doc,
           ['نقش', 'میزبان', 'مسئولیت'],
           [
               ('مغز', f'Ubuntu Linux — {LAN_IP}',
                'تحلیل، پلن، گیت‌ها، مدیریت، ژورنال، گزارش‌ها — همهٔ '
                'منطق در Python'),
               ('بازوی اجرا', f'Windows Server — {WIN}',
                'فقط متاتریدر ۵؛ هیچ تصمیمی نمی‌گیرد'),
               ('پل ارتباطی', 'HTTP + Bearer Token',
                'خواندن داده و ارسال سفارش بین مغز و بازو'),
           ],
           widths=[26, 52, 77])
para(doc, 'این جداسازی عمدی است: حتی اگر مغز از کار بیفتد، هیچ سفارش '
          'تصادفی به بروکر نمی‌رود؛ و MT5 فقط مجری دستوراتی است که از ده '
          'لایهٔ گیت رد شده‌اند.')
picture(doc, f'{CH}/chart_arch.png', width_mm=178,
        caption='شکل ۲ — نقشهٔ اجزا: مغز لینوکسی، پل HTTP، بازوی '
                'ویندوزی/MT5 و کانال‌های تلگرامی')

# ══════════════════ 5. TRANSPARENCY ══════════════════
heading(doc, '۵ — شفافیت: هرچه می‌کند، گزارش می‌دهد', level=1)
para(doc, 'مالک سیستم هیچ‌وقت نباید حدس بزند ربات چه کرده:', space_after=4)
bullets(doc, [
    'لحظه‌ای — هر رویداد مهم (باز/بسته شدن ترید، رد سیگنال با دلیل، فعال '
    'شدن Kill Switch) روی تلگرام',
    'روزانه — خلاصهٔ وضعیت حساب و پوزیشن‌ها',
    'هفتگی — گزارش مدیرتی با اعداد تصالح‌شده با بروکر (شمارش پوزیشن، نه '
    'ردیف خام)',
    'سند کامل — گزارش‌های Word با نمودار منحنی سرمایه و قیف تصمیمات',
])

# ══════════════════ 6. SIGNAL FEATURE ══════════════════
heading(doc, '۶ — قابلیت جانبی: شکار سیگنال تلگرام', level=1)
para(doc, 'علاوه بر تریدر مستقل، Hermes می‌تواند کانال‌های سیگنال تلگرام را '
          'هم بخواند — اما نه به‌عنوان فرمان، به‌عنوان سوژه:')
bullets(doc, [
    'پیام کانال‌ها به یک گروه مرکزی فوروارد می‌شود؛ پارسر فارسی/انگلیسی '
    'متن را به ساختار استاندارد (جهت، ورود، SL، TPها) تبدیل می‌کند',
    'هر سیگنال وارد همان گیت ده‌لایهٔ تریدر می‌شود؛ اگر RR یا امتیاز '
    'کیفیت نگیرد، با دلیل ثبت و رد می‌شود',
    'سیگنال قدیمی/بی‌تایم هرگز اجرا نمی‌شود — فقط پیام‌های زنده',
    '۷ کانال در بازهٔ ۹۰ روزه روی دادهٔ واقعی قیمت شبیه‌سازی شدند تا '
    'کیفیت هر کانال پیش از هر اعتماد سنجیده شود',
])
callout(doc, '«سیگنال بی‌تایم بدتر از بی‌سیگنال است».',
        'تاریخچهٔ کانال‌ها ابزار داوری است، نه مجوز اجرا. تصمیم نهایی همیشه '
        'با گیت‌های تریدر است، نه با نویسندهٔ سیگنال.',
        fill=PANEL, bar='2E74B5', tcol=NAVY)

# ══════════════════ 7. STATUS & ROADMAP ══════════════════
heading(doc, '۷ — وضعیت امروز و مسیر پیش‌رو', level=1)
para(doc, 'صداقت بخشی از طراحی است. امروز:', space_after=4)
bullets(doc, [
    'سیستم روی حساب نمایشی (Demo) با سرمایهٔ شبیه‌سازی در حال اجراست',
    'در دو هفتهٔ نخست، ۲۴ پوزیشن با سود خالص مثبت بسته شده — این نمونهٔ '
    'کوچک است، نه ادعای سوددهی',
    'تصمیم سیاستی: تا انباشته‌شدن حدود ۱۰۰ ترید زنده، هیچ پارامتری شل یا '
    'سخت نمی‌شود؛ داوری با داده، نه با حس',
])
para(doc, 'مسیر پیش‌رو:', space_after=4)
bullets(doc, [
    'کسب سابقهٔ آماری کافی روی Demo (حدود ۱۰۰ ترید)',
    'بررسی ورود به حساب واقعی با ریسک حداقلی، در صورت تأیید آمار',
    'گسترش تدریجی به نمادها و تایم‌فریم‌های بیشتر، با همان چارچوب گیت',
])

# ══════════════════ 8. GLOSSARY ══════════════════
heading(doc, '۸ — واژه‌نامهٔ سریع', level=1)
make_table(doc,
           ['اصطلاح', 'معنی ساده'],
           [
               ('XAUUSD', 'نماد جهانی طلا در برابر دلار'),
               ('SL / TP', 'حد ضرر / حد سود'),
               ('RR', 'نسبت سودِ محتمل به ریسک؛ زیر آستانه = قمار'),
               ('Lot', 'اندازهٔ پوزیشن (هر ۰.۰۱ لات طلا تقریباً ۱ دلار به '
                'ازای هر دلار حرکت)'),
               ('Drawdown', 'بیشترین افت سرمایه از قله'),
               ('SMC / ICT', 'سبک‌های نوین تحلیل بر پایهٔ نقدینگی و ردپای '
                'نهادهای بزرگ'),
               ('FVG / Order Block', 'شکاف قیمتی / ناحیهٔ سفارشات نهادی'),
               ('DEFCON', 'سطح هشدار بازار؛ قرمز = فقط نظارت'),
               ('Kill Switch', 'قطع خودکار ترید بعد از ضرر سقف‌دار'),
               ('Fail-closed', 'در خطا یا ابهام، حالت پیش‌فرض «انجام نده»'),
               ('Demo / Real', 'حساب نمایشی با پول مجازی / حساب واقعی'),
               ('MT5', 'پلتفرم متاتریدر ۵ — پنل بروکر'),
           ],
           widths=[42, 113])

doc.add_paragraph()
p = rtl(doc.add_paragraph(), WD_ALIGN_PARAGRAPH.CENTER)
R(p, '— پایان —', size=9, color=LGRAY)

# ── fontTable: declare Tahoma/Consolas ──
import zipfile, shutil
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
