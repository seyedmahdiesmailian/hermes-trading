import {
  Document, Packer, Paragraph, TextRun, HeadingLevel,
  Table, TableCell, TableRow, WidthType, AlignmentType, ShadingType,
  BorderStyle, PageBreak, Header, Footer, PageNumber,
} from "docx";
import { writeFileSync } from "fs";

// ── Styling helpers ──

const accent = "1F4A3B";  // dark green
const accent2 = "2E7D32"; // lighter green
const bgGreen = "E8F5E9";
const bgRed = "FFEBEE";
const bgGray = "F5F5F5";
const textDark = "212121";

function heading(text, level = 1) {
  return new Paragraph({
    heading: HeadingLevel[`HEADING_${level}`],
    spacing: { before: level === 1 ? 400 : 280, after: 120 },
    children: [new TextRun({ text, bold: true, color: accent, size: level === 1 ? 44 : level === 2 ? 36 : 30 })],
  });
}

function para(text, options = {}) {
  return new Paragraph({
    spacing: { after: options.spacing ?? 80 },
    children: [new TextRun({ text, size: options.size ?? 22, font: options.font ?? "B Nazanin", color: textDark, ...(options.bold ? { bold: true } : {}) })],
  });
}

function rtlPara(text, options = {}) {
  return new Paragraph({
    spacing: { after: 80 },
    alignment: AlignmentType.RIGHT,
    children: [new TextRun({ text: "◄ " + text, size: options.size ?? 22, font: "B Nazanin", color: textDark, rightToLeft: true })],
  });
}

function cell(text, options = {}) {
  return new TableCell({
    width: options.width ? { size: options.width, type: WidthType.DXA } : undefined,
    shading: options.shading ? { fill: options.shading, type: ShadingType.CLEAR } : undefined,
    children: [new Paragraph({
      alignment: options.center ? AlignmentType.CENTER : AlignmentType.RIGHT,
      spacing: { before: 40, after: 40 },
      children: [new TextRun({ text, size: 20, font: "B Nazanin", bold: options.header || false, color: options.header ? "FFFFFF" : textDark, rightToLeft: true })],
    })],
  });
}

function headerRow(...labels) {
  return new TableRow({
    tableHeader: true,
    children: labels.map(l => cell(l, { header: true, width: 10000 / labels.length, shading: accent, center: true })),
  });
}

function dataRow(...cells) {
  return new TableRow({
    children: cells.map(c => cell(c, { width: 10000 / cells.length })),
  });
}

// ── Document ──

const doc = new Document({
  styles: {
    default: { document: { run: { font: "B Nazanin", size: 22 } } },
  },
  sections: [{
    properties: { page: { size: { width: 12240, height: 15840 } } },
    headers: {
      default: new Header({
        children: [new Paragraph({
          alignment: AlignmentType.CENTER,
          children: [
            new TextRun({ text: "Hermes Trading System — XAUUSD", size: 16, color: "888888", italics: true }),
          ],
        })],
      }),
    },
    footers: {
      default: new Footer({
        children: [new Paragraph({
          alignment: AlignmentType.CENTER,
          children: [
            new TextRun({ text: "صفحه ", size: 16, color: "888888" }),
            new TextRun({ children: [PageNumber.CURRENT], size: 16, color: "888888" }),
          ],
        })],
      }),
    },
    children: [

      // ═══════ COVER ═══════
      new Paragraph({ spacing: { before: 3000 } }),
      new Paragraph({
        alignment: AlignmentType.CENTER,
        children: [new TextRun({ text: "سیستم معاملات خودکار طلا", size: 56, bold: true, color: accent, font: "B Titr" })],
      }),
      new Paragraph({ spacing: { before: 200 } }),
      new Paragraph({
        alignment: AlignmentType.CENTER,
        children: [new TextRun({ text: "XAUUSD · SMC/ICT/RTM · MetaTrader 5", size: 32, color: accent2, font: "B Nazanin" })],
      }),
      new Paragraph({ spacing: { before: 600 } }),
      new Paragraph({
        alignment: AlignmentType.CENTER,
        children: [new TextRun({ text: "━━━━━━━━━━━━━━━━━", size: 24, color: "CCCCCC" })],
      }),
      new Paragraph({ spacing: { before: 400 } }),
      new Paragraph({
        alignment: AlignmentType.CENTER,
        children: [new TextRun({ text: "گزارش معماری سیستم — ۲۰ مرداد ۱۴۰۵", size: 28, color: textDark, font: "B Nazanin" })],
      }),
      new Paragraph({
        alignment: AlignmentType.CENTER,
        children: [new TextRun({ text: "حساب دمو · بالانس ۱,۳۳۸ دلار · ۲۰۴ تست تأییدشده", size: 24, color: "888888", font: "B Nazanin" })],
      }),

      // ── PAGE BREAK ──
      new Paragraph({ children: [new PageBreak()] }),

      // ═══════ TABLE OF CONTENTS ═══════
      heading("فهرست مطالب", 1),
      para("۱. نمای کلی سیستم", { bold: true }),
      para("۲. جریان اصلی کار (Pipeline)", { bold: true }),
      para("۳. تحلیل تکنیکال — موتور SMC/ICT", { bold: true }),
      para("۴. معماری فایلها", { bold: true }),
      para("۵. مدیریت ریسک و سرمایه", { bold: true }),
      para("۶. اجرای معامله", { bold: true }),
      para("۷. پایش و بازنگری (Monitor & Reassess)", { bold: true }),
      para("۸. وضعیت فعلی و برنامه آینده", { bold: true }),

      new Paragraph({ children: [new PageBreak()] }),

      // ═══════ SECTION 1: OVERVIEW ═══════
      heading("۱. نمای کلی سیستم", 1),

      rtlPara("این سیستم یک تریدر تمام‌خودکار برای طلا (XAUUSD) است که روی حساب دمو متاتریدر ۵ اجرا می‌شود. مغز اصلی تحلیل آن SMC (Smart Money Concepts) و ICT (Inner Circle Trader) است که همراه با تحلیل تکنیکال کلاسیک، تصمیم‌گیری می‌کند."),

      heading("اجزای اصلی", 2),
      rtlPara("🔹 Cron Scheduler — هر ۱۵ دقیقه سیستم را بیدار می‌کند"),
      rtlPara("🔹 Runtime Engine — دریافت داده از MT5، تحلیل، تصمیم‌گیری و اجرا"),
      rtlPara("🔹 Classic Analysis — تشخیص بایاس، نواحی ارزش، ATR و رژیم بازار"),
      rtlPara("🔹 SMC Engine — ۱۷ مفهوم اسمارت مانی: Order Block، FVG، نقدینگی، ساختار، Breaker و ..."),
      rtlPara("🔹 Merge Engine — ترکیب تحلیل کلاسیک و SMC به یک تصمیم واحد"),
      rtlPara("🔹 Risk Manager — محاسبه لات، حد ضرر، حد سود و محافظت از حساب"),
      rtlPara("🔹 Execution Layer — ارسال مستقیم سفارش به متاتریدر از طریق Python API"),

      heading("مشخصات فنی", 2),
      new Table({
        width: { size: 10000, type: WidthType.DXA },
        rows: [
          dataRow("XAUUSD", "نماد معاملاتی"),
          dataRow("M15 · H1 · H4", "تایم‌فریم‌های تحلیل"),
          dataRow("حساب دمو (Capitalxtend)", "بروکر"),
          dataRow("۱,۳۳۸ دلار", "بالانس حساب"),
          dataRow("هر ۱۵ دقیقه", "فرکانس اجرا"),
          dataRow("۲۰۴ تست (همه سبز)", "پوشش تست"),
          dataRow("۱۷ مفهوم", "موتور SMC/ICT"),
        ],
      }),

      new Paragraph({ children: [new PageBreak()] }),

      // ═══════ SECTION 2: PIPELINE ═══════
      heading("۲. جریان اصلی کار (Pipeline)", 1),

      rtlPara("سیستم هر ۱۵ دقیقه توسط Cron اجرا می‌شود و مراحل زیر را به ترتیب طی می‌کند:"),

      heading("مرحله ۱ — جمع‌آوری داده", 2),
      rtlPara("داده‌های OHLC تایم‌فریم‌های M15 (۲۰۰ کندل)، H1 (۵۰ کندل) و H4 (۳۰ کندل) مستقیماً از MetaTrader 5 دریافت می‌شود."),

      heading("مرحله ۲ — تشخیص Session", 2),
      rtlPara("سیستم تشخیص می‌دهد الان در کدام سشن معاملاتی هستیم: آسیا (۱-۶ صبح UTC)، لندن (۷-۹ صبح UTC)، نیویورک (۱۲-۵ عصر UTC)، یا خارج از ساعات اصلی."),

      heading("مرحله ۳ — تحلیل کلاسیک", 2),
      rtlPara("نواحی ارزش (Value Zone) محاسبه می‌شود. بایاس بازار (صعودی/نزولی/خنثی) با سه تایم‌فریم تعیین می‌شود. ATR و رژیم بازار (روند/رنج/بریک‌اوت) مشخص می‌شود."),

      heading("مرحله ۴ — تحلیل SMC (مغز اصلی)", 2),
      rtlPara("داده‌های M15 وارد موتور SMC می‌شود. ۱۷ مفهوم تحلیل می‌شوند: Order Block تشخیص داده می‌شود، Fair Value Gap محاسبه می‌شود، جاروب نقدینگی (Liquidity Sweep) بررسی می‌شود، ساختار بازار (BOS/CHoCH) تعیین می‌شود، ناحیه Premium/Discount فیبوناچی محاسبه می‌شود، وزن Killzone زمانی اعمال می‌شود، و نهایتاً یک POI Grade (A/B/C) به منطقه مورد نظر اختصاص داده می‌شود."),

      heading("مرحله ۵ — Merge (ترکیب)", 2),
      rtlPara("نتیجه تحلیل کلاسیک و SMC با هم ترکیب می‌شوند. وقتی کلاسیک خنثی باشد، وزن SMC غالب است (۶۰٪). وقتی توافق کامل باشد، confidence بالاتر می‌رود. نتیجه نهایی: یک بایاس واحد (صعودی/نزولی/خنثی) با عدد confidence مشخص."),

      heading("مرحله ۶ — ساخت Plan", 2),
      rtlPara("بر اساس بایاس ترکیبی و confidence، یک Plan معاملاتی ساخته می‌شود. این Plan شامل: تصمیم (wait / enter_plan / execute)، حد ضرر (SL)، حد سود (TP)، حجم معامله (lot)، و قیمت ورود است."),

      heading("مرحله ۷ — بررسی ریسک", 2),
      rtlPara("قبل از اجرا، ریسک حساب بررسی می‌شود: آیا مارجین کافی داریم؟ آیا loss streak اخیر زیاده؟ حساب در چه وضعیتی است (DEFCON)؟"),
      rtlPara("فرمول: free_margin ÷ (risk_usd + margin_required) باید ≥ ۱.۵ باشد. همچنین risk_multiplier تطبیقی بر اساس performance اخیر اعمال می‌شود (الان ۰.۷۵ = defensive)."),

      heading("مرحله ۸ — اجرا یا انتظار", 2),
      rtlPara("اگر Plan تصمیم execute داشته باشد و ریسک چک پاس شود، سفارش مستقیماً از طریق Python API به متاتریدر ارسال می‌شود. SL و TP همزمان تنظیم می‌شوند. اگر Plan تصمیم wait داشته باشد، هیچ اقدامی نمی‌شود و سیستم فقط پایش می‌کند."),

      heading("مرحله ۹ — پایش پوزیشن باز", 2),
      rtlPara("اگر پوزیشن بازی وجود داشته باشد، سیستم هر ۱۵ دقیقه آن را reassess می‌کند: آیا SL باید تریل شود؟ آیا باید partial close انجام شود؟ آیا پوزیشن باید بسته شود؟"),
      rtlPara("تصمیم‌ها بر اساس: فاصله از SL، فاصله از TP، سود فعلی، و سیگنال تحلیل جدید گرفته می‌شوند."),

      new Paragraph({ children: [new PageBreak()] }),

      // ═══════ SECTION 3: SMC ENGINE ═══════
      heading("۳. تحلیل تکنیکال — موتور SMC/ICT", 1),

      rtlPara("این موتور مغز اصلی تحلیل سیستم است. برخلاف تحلیل کلاسیک که صرفاً بر اساس میانگین قیمت و بایاس ساده کار می‌کند، SMC رفتار \"پول هوشمند\" (بانک‌ها و مؤسسات) را شبیه‌سازی می‌کند."),

      heading("لایه ۱ — مفاهیم پایه (۷ مفهوم)", 2),

      new Table({
        width: { size: 10000, type: WidthType.DXA },
        rows: [
          headerRow("توضیح", "مفهوم"),
          dataRow("آخرین کندل نزولی قبل از بریک‌اوت صعودی (یا برعکس). محدوده OB به عنوان حمایت/مقاومت عمل می‌کند.", "Order Block"),
          dataRow("شکاف قیمتی سه‌کندله. FVG صعودی = low کندل سوم > high کندل اول. ناحیه عدم تعادل.", "Fair Value Gap"),
          dataRow("شکستن سقف/کف قبلی و برگشت سریع. نشانه جمع‌آوری نقدینگی توسط مارکت میکر.", "Liquidity Sweep"),
          dataRow("BOS = شکست ساختار، CHoCH = تغییر کاراکتر. تشخیص روند و نقاط برگشت.", "Market Structure"),
          dataRow("محاسبه موقعیت قیمت روی فیبوناچی ۰ تا ۱. پایین ۰.۵ = Discount، بالای ۰.۵ = Premium.", "Premium/Discount"),
          dataRow("وزن‌دهی زمانی. سشن لندن و نیویورک وزن بالا، آسیا وزن متوسط، آخر هفته وزن صفر.", "Killzone Timing"),
          dataRow("نمره‌دهی به نقاط ورود (A=عالی, B=خوب, C=متوسط). بر اساس OB+FVG+Structure+Zone.", "POI Grading"),
        ],
      }),

      heading("لایه ۲ — مفاهیم پیشرفته (۸ مفهوم)", 2),

      new Table({
        width: { size: 10000, type: WidthType.DXA },
        rows: [
          headerRow("توضیح", "مفهوم"),
          dataRow("OB که price آن را شکسته. چرخش نقش: OB صعودی شکسته شده → مقاومت نزولی.", "Breaker Block"),
          dataRow("کندل پین‌بار با سایه بلند که OB را تست کرده و برگشته. تأیید ورود.", "Rejection Block"),
          dataRow("ناحیه ۶۲٪ تا ۷۹٪ فیبوناچی. بهترین ناحیه برای ورود در پولبک.", "OTE Zone"),
          dataRow("چرخه روزانه: Accumulation → Manipulation → Distribution.", "Power of Three"),
          dataRow("بریک‌اوت فیک + برگشت شدید. کلاهبرداری از تریدرهای خرد.", "Turtle Soup"),
          dataRow("پنجره زمانی ۱۰-۱۱ صبح و ۲-۳ بعدازظهر نیویورک. ستاپ ویژه ICT.", "Silver Bullet"),
          dataRow("محاسبه سقف/کف/میانه سشن و تشخیص جاروب شدن آنها.", "Session Liquidity"),
          dataRow("تشخیص کندل‌هایی با حجم معاملات غیرعادی (>۲.۵× میانگین).", "Volume Imbalance"),
        ],
      }),

      heading("نحوه ترکیب (Merge Logic)", 2),
      rtlPara("بایاس کلاسیک (از طریق bias_classify) و بایاس SMC (از طریق _derive_smc_bias) با هم ترکیب می‌شوند:"),
      rtlPara("✅ هر دو هم‌جهت → همان بایاس با confidence بالا"),
      rtlPara("✅ کلاسیک خنثی → SMC غالب می‌شود (وزن ۶۰٪ SMC)"),
      rtlPara("✅ تضاد (conflict) → کلاسیک غالب می‌شود (محافظه‌کارانه)"),
      rtlPara("Confidence نهایی = میانگین وزنی classic:smc با نسبت ۰.۴:۰.۶"),

      new Paragraph({ children: [new PageBreak()] }),

      // ═══════ SECTION 4: FILES ═══════
      heading("۴. معماری فایلها", 1),

      new Table({
        width: { size: 10000, type: WidthType.DXA },
        rows: [
          headerRow("وظیفه", "فایل", "خط"),
          dataRow("مغز اجرایی — pipeline اصلی", "mt5_xau_runtime.py", "۹۱۷"),
          dataRow("موتور SMC/ICT — ۱۷ تابع تحلیل", "mt5_xau_smc.py", "۸۲۲"),
          dataRow("تحلیل کلاسیک (bias, zones, ATR)", "mt5_xau_context.py", "۲۱۱"),
          dataRow("ساخت plan از merge result", "mt5_xau_plan.py", "۲۲۵"),
          dataRow("مدیریت پوزیشن باز (trailing, partial)", "mt5_xau_trade_management.py", "۱۷۵"),
          dataRow("Direct MT5 API (order_send)", "mt5_direct.py", "۳۷۹"),
          dataRow("حساب — ریسک و sizing", "mt5_account_risk.py", "۱۳۰"),
          dataRow("گزارش فارسی", "mt5_xau_report.py", "۲۱۹"),
          dataRow("ذخیره plan/state/history", "mt5_xau_storage.py", "۱۰۱"),
          dataRow("Orchestrator wrapper", "mt5_xau_orchestrator.py", "۱۳۰"),
          dataRow("موتور اصلی (legacy)", "mt5_engine.py", "۱۰۱۱"),
        ],
      }),

      heading("فایل‌های تست (۴۴ فایل، ۲۰۴ تست)", 2),
      rtlPara("تمامی ماژول‌ها به صورت TDD (تست قبل از کد) پیاده‌سازی شده‌اند. هر فایل تست پوشش کاملی برای سناریوهای موفق و لبه‌ای (edge case) فراهم می‌کند."),
      rtlPara("مهم‌ترین فایل تست: test_mt5_xau_smc.py با ۵۳ تست برای تمام ۱۷ مفهوم SMC."),

      new Paragraph({ children: [new PageBreak()] }),

      // ═══════ SECTION 5: RISK ═══════
      heading("۵. مدیریت ریسک و سرمایه", 1),

      heading("محاسبه حجم (Lot Sizing)", 2),
      rtlPara("حجم معامله بر اساس سه فاکتور محاسبه می‌شود:"),
      rtlPara("۱. درصد ریسک از بالانس (۱٪ = ۱۳.۳۸ دلار در شرایط عادی)"),
      rtlPara("۲. فاصله SL (حد ضرر) — بر اساس ATR و ساختار بازار"),
      rtlPara("۳. risk_multiplier تطبیقی — بر اساس performance اخیر"),

      heading("سطوح DEFCON", 2),
      new Table({
        width: { size: 10000, type: WidthType.DXA },
        rows: [
          headerRow("عملکرد", "شرط", "سطح"),
          dataRow("عادی (risk × ۱.۰)", "بدون محدودیت", "🟢 ۵"),
          dataRow("محتاط (risk × ۰.۷۵)", "loss_streak ≥ ۲", "🟡 ۴"),
          dataRow("دفاعی (risk × ۰.۵)", "loss_streak ≥ ۳", "🟠 ۳"),
          dataRow("فقط بستن (ورود ممنوع)", "loss_streak ≥ ۴", "🔴 ۲"),
          dataRow("توقف کامل", "drawdown > ۱۰٪", "⛔ ۱"),
        ],
      }),
      rtlPara("الان در سطح 🟠 دفاعی هستیم (loss_streak=۳, risk × ۰.۷۵)."),

      heading("محافظت مارجین", 2),
      rtlPara("قبل از هر معامله: free_margin ÷ (risk + margin) ≥ ۱.۵. اگر مارجین کافی نباشد، معامله لات کاهش می‌یابد یا کلاً لغو می‌شود."),

      new Paragraph({ children: [new PageBreak()] }),

      // ═══════ SECTION 6: EXECUTION ═══════
      heading("۶. اجرای معامله", 1),

      rtlPara("اجرا مستقیماً از طریق Python MetaTrader5 API انجام می‌شود — بدون فایل، بدون bridge، بدون EA."),

      heading("مراحل اجرا", 2),
      rtlPara("۱. دریافت تیک قیمت زنده از MT5"),
      rtlPara("۲. ساخت درخواست (order_send) با: نماد، جهت، حجم، SL، TP"),
      rtlPara("۳. بررسی اعتبار درخواست (order_check)"),
      rtlPara("۴. ارسال سفارش (order_send)"),
      rtlPara("۵. بازبینی نتیجه و ذخیره ticket number"),

      heading("مدیریت پوزیشن باز", 2),
      rtlPara("✅ Trailing Stop — با حرکت قیمت، SL به طور خودکار تنظیم می‌شود"),
      rtlPara("✅ Partial Close — بستن بخشی از پوزیشن برای قفل سود"),
      rtlPara("✅ Modify SL/TP — تنظیم مستقیم بدون بستن پوزیشن"),

      new Paragraph({ children: [new PageBreak()] }),

      // ═══════ SECTION 7: MONITOR ═══════
      heading("۷. پایش و بازنگری (Monitor & Reassess)", 1),

      rtlPara("وقتی پوزیشن باز است، سیستم هر ۱۵ دقیقه موارد زیر را بررسی می‌کند:"),

      new Table({
        width: { size: 10000, type: WidthType.DXA },
        rows: [
          headerRow("اقدام", "شرط"),
          dataRow("هیچ کاری", "قیمت بین SL و TP است و هنوز به نقطه reassess نرسیده"),
          dataRow("Reassess: بازنگری تحلیل", "تحلیل جدید سیگنال متفاوتی نشان می‌دهد یا قیمت از TP فاصله گرفته"),
          dataRow("Trail SL", "قیمت به اندازه کافی در سود حرکت کرده (مثلاً +۲۰ پیپ از ورود)"),
          dataRow("Partial Close (۵۰٪)", "قیمت به ۷۰٪ مسیر TP رسیده و برگشت نشان می‌دهد"),
          dataRow("Close All", "SL خورده، TP خورده، یا سیگنال قوی خلاف جهت"),
        ],
      }),

      heading("گزارش فارسی", 2),
      rtlPara("گزارش‌ها به صورت پیام فارسی ساده و مختصر ارسال می‌شوند. فرمت گزارش:"),
      rtlPara("📊 **گزارش روزانه** — خلاصه عملکرد، PnL، وضعیت حساب"),
      rtlPara("📋 **Plan** — بایاس، confidence، نواحی ورود/خروج، ریسک"),
      rtlPara("🔄 **Reassess** — وضعیت پوزیشن باز، اقدام توصیه‌شده"),
      rtlPara("⚠️ **هشدار** — فقط وقتی تغییری رخ دهد (silent on no-change)"),

      new Paragraph({ children: [new PageBreak()] }),

      // ═══════ SECTION 8: STATUS ═══════
      heading("۸. وضعیت فعلی و برنامه آینده", 1),

      heading("وضعیت امروز (شنبه ۱۹ مرداد — بازار بسته)", 2),
      new Table({
        width: { size: 10000, type: WidthType.DXA },
        rows: [
          headerRow("وضعیت", "بخش"),
          dataRow("۲۰۴ تست — همه سبز", "تست‌ها"),
          dataRow("۱۷ مفهوم کامل + merge", "موتور SMC"),
          dataRow("در حال اجرا با cron هر ۱۵ دقیقه", "Runtime"),
          dataRow("$۱,۳۳۸", "بالانس"),
          dataRow("بدون پوزیشن باز", "پوزیشن"),
          dataRow("منتظر دوشنبه ۲۰ مرداد — شروع لندن", "آمادگی"),
        ],
      }),

      heading("برنامه آینده", 2),
      rtlPara("🔹 دوشنبه ۲۰ مرداد — اولین روز معامله زنده با SMC کامل"),
      rtlPara("🔹 مانیتورینگ عملکرد و رفع باگ در روزهای اول"),
      rtlPara("🔹 اضافه کردن SMT Divergence (نیاز به داده DXY)"),
      rtlPara("🔹 اضافه کردن News Filter (تقویم اقتصادی)"),
      rtlPara("🔹 ساخت Backtest Engine برای بهینه‌سازی پارامترها"),
      rtlPara("🔹 انتقال به حساب Real پس از ۲ هفته performance مثبت"),

      // ═══════ SIGNATURE ═══════
      new Paragraph({ spacing: { before: 800 } }),
      new Paragraph({
        alignment: AlignmentType.CENTER,
        children: [new TextRun({ text: "━━━━━━━━━━━━━━━━━━━━━━━", size: 18, color: "CCCCCC" })],
      }),
      new Paragraph({
        alignment: AlignmentType.CENTER,
        children: [new TextRun({ text: "Hermes Agent — Nous Research", size: 20, color: "888888", italics: true })],
      }),

    ],
  }],
});

// ── Write ──
const buf = await Packer.toBuffer(doc);
writeFileSync("C:\\Users\\Administrator\\Desktop\\XAUUSD_Trading_System_Report.docx", buf);
console.log("✅ Report written to Desktop");
