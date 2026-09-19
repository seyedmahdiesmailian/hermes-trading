# فاز صفر — بررسی `origin/master` (منبع حقیقت زنده)

تاریخ: ۲۰۲۶-۰۹-۱۹
منبع: `origin/master` = `2fedb95` (b79e3)
روش: `git archive origin/master` → خواندن فایل‌به‌فایل. روی master هیچ کامیت/مرج/پوشی نشده.

> گزارش‌های قبلی همین جلسه (`PHASE0_ARCHITECTURE_AUDIT` و `PHASE0_DEEP_AUDIT`)
> روی برنچ موازی فیکس ۱۷ سپتامبر (`d378c4b`) نوشته شده بودند، **نه روی master**.
> حرف‌های آنجا دربارهٔ «بریج canonical با auth در scripts/»، «C1»، «requirements.txt نیست»
> برای master **کهنه/غلط** است. این سند آن‌ها را باطل می‌کند.

تأییدهای اپراتور که هنوز معتبرند: حساب **دمو**؛ فورواردر می‌تواند از مسیر اجرایی جدا بماند؛ **هیچ چیز داخل master نرود**.

---

## ۰. سه کامیت تازهٔ شما روی master که قبلاً ندیده بودم

| SHA | عنوان | چه آورد |
|---|---|---|
| `783c7d3` b79e | pull live Windows bridge + ops واقعی + فورواردر | `windows_bridge/`، ۹ یونیت systemd، `crontab.root.txt`، `forwarder/` |
| `7fd97aa` b79e2 | leftover bridge + CI فورواردر | `restart_bridge.py`، workflow |
| `2fedb95` b79e3 | `requirements.txt` + تعمیر `setup.sh` | قفل وابستگی + بوت‌استرپ سالم |

این سه مورد دقیقاً چند حفرهٔ گزارش ۱۷ سپتامبر را روی **مشاهده‌پذیری** بسته‌اند، نه لزوماً روی رفتار زنده.

---

## ۱. معماری فعلی master (آنچه واقعاً در ریپو است)

دو ماشین، دو نقش — مطابق هدف شما:

```
Linux 192.168.10.18                         Windows 192.168.10.51
/home/ai/hermes-trading                     C:\Temp\bridge.py   ← LIVE
                                            (آینه در windows_bridge/bridge.py)

مغز:
  hermes_master.py     کرون زنده: هر ۵ دقیقه (crontab.root.txt)
                       داکیومنت/timer: هر ۱۵ دقیقه  ← تضاد
  position_daemon      systemd هر ۵ ثانیه
  signal_daemon        systemd long-poll
  dashboard_bot        پنل تلگرام
  hermes-forwarder     Telethon — اجرا از ~/projects/... نه از forwarder/ ریپو
  hermes-gateway       بیرون ریپو (/home/ai/.hermes)
  hermes-webui         بیرون ریپو پورت 9119
  omniroute            بیرون ریپو
```

دو پروژهٔ جدا داخل همین ریپو:

1. اسکنر: `hermes_master` → `hermes_runtime.cycle` → SMC+کلاسیک → پلن → گیت → `bridge.send_order`
2. سیگنال: فورواردر ۷ کانال → یک گروه → `signal_daemon` → parser → scorer → همان `evaluate_proposal`

گلوگاه واحد اجرا هنوز `engines/auto_executor.py` است.

---

## ۲. نقشهٔ پوشه‌ها روی master (بعد از b79e)

```
hermes_master.py / hermes_runtime.py / position_daemon.py / signal_daemon.py
cli.py  bridge_client.py  env_loader.py  setup.sh  requirements.txt   ← جدید
engines/          ۳۵ ماژول منطق
notifier/         تلگرام + داشبورد
ops/systemd/      ۹ یونیت واقعی (قبلاً ۳)
ops/cron/         crontab.backup.txt (۱۵د) + crontab.root.txt (۵د)  ← جدید
forwarder/        سورس Telethon (آینه؛ اجرا هنوز بیرون است)         ← جدید
windows_bridge/   آینهٔ C:\Temp شامل bridge.py زنده                  ← جدید
scripts/          cron، deploy (هنوز download→patch)، آزمایشگاه
tests/            hermetic
data/             state (در گیت هست، خلاف README)
legacy_*          بایگانی
```

README هنوز `forwarder/` و `windows_bridge/` و `requirements.txt` را در بلوک ساختار نیاورده.

---

## ۳. فایل‌به‌فایل — اجزای جدید و حیاتی

### ۳.۱ `windows_bridge/bridge.py` — دستِ واقعی اجرا

این فایل زندهٔ `:5050` است (pythonw + waitress، ۸ thread).

دارد: account / positions / tick / ohlc / order / close / modify / partial / history/deals / pending / cancel / health.

یافته‌های تأییدشده از خود فایل:

| مورد | واقعیت کد |
|---|---|
| Auth | `@app.before_request` Bearer |
| اگر توکن خالی باشد | `if _BRIDGE_TOKEN and ...` → **auth خاموش می‌شود (fail-open)** |
| مقایسهٔ توکن | `!=` رشته، نه `hmac.compare_digest` |
| `/health` | **balance حساب را برمی‌گرداند** (نشتی) |
| پوزیشن `type` | `int` (0/1) نه `"BUY"`/`"SELL"` — runtime هر دو شکل را می‌فهمد |
| استارت بدون توکن | بوت می‌شود |
| `scripts/mt5_http_server_v2.py` | **بدون auth**، Flask `app.run`، **اجرا نمی‌شود** |

`windows_bridge/mt5_http_server_v2.py` و `scripts/mt5_http_server_v2.py` رفرنس قدیمی‌اند. README خود پوشه این را گفته.

`_deploy_bridge.py` روی master هنوز: **دانلود زنده → patch رشته‌ای → آپلود**. روی VM تازه مرحلهٔ ۱ fail می‌شود. DR گام ۵ DEPLOY.md با این اسکریپت روی باکس خالی کار نمی‌کند؛ باید `windows_bridge/bridge.py` را مستقیم پوش کرد — این مسیر هنوز اسکریپت نشده.

`bridge_watchdog.bat`: health روی localhost؛ اگر fail → kill همهٔ `pythonw.exe` → استارت مجدد. درشت است (هر pythonw دیگر روی آن باکس هم می‌میرد).

### ۳.۲ `forwarder/main.py` — منبع سیگنال

Telethon userbot: چند کانال → یک گروه، با prefix نام کانال، ویرایش/حذف، watchdog اتصال هر ۱۲۰ث، catch-up پیش‌فرض خاموش (سیگنال کهنه بدتر از بی‌سیگنال).

- رازها در ریپو نیستند (`config.json` / session). `config.example.json` دو کانال نمونه دارد.
- سرویس واقعی: `WorkingDirectory=/home/ai/projects/forwarder-telegram-dockerized` — **نه** `forwarder/` داخل این ریپو. آینه برای خواندن است، نه مسیر اجرا.
- داشبورد `_services()` هنوز forwarder را چک نمی‌کند (فقط signal/position/gateway/dashboard).

### ۳.۳ `ops/` — آنچه واقعاً روی ماشین است

۹ یونیت:

| یونیت | داخل این ریپو اجرا می‌شود؟ |
|---|---|
| hermes-position / signal / dashboard | بله |
| hermes-trading.service + timer ۱۵د | بله (کرون موازی هم هست) |
| hermes-forwarder | خیر — مسیر `~/projects/...` |
| hermes-gateway / webui / omniroute | خیر — `/home/ai/.hermes` و `omniroute` |

کرون زنده (`crontab.root.txt`):

- `hermes_cron.sh` **هر ۵ دقیقه**
- health هر ۵د، autopilot ساعتی، digest 02:00، weekly جمعه، backup 23:45، git_sync هر ۱۵د
- backup با پایتون venv ایجنت: `/home/ai/.hermes/hermes-agent/venv/bin/python3`

کرون مرجع قدیمی (`crontab.backup.txt`) هنوز ۱۵ دقیقه است. README و DEPLOY هم ۱۵د. **سه منبع، دو عدد.**

`setup.sh` فقط ۳ سرویس کاربر را enable می‌کند (position/signal/dashboard)، نه ۹ تا. crontab را از `crontab.root.txt` می‌گذارد.

### ۳.۴ `requirements.txt`

وجود دارد (ادعای قبلی «نیست» برای master غلط است). runtime: requests, dotenv, pywinrm, ntlm, pandas, numpy, telegram-bot, flask, waitress, telethon, qrcode, python-docx, matplotlib. MetaTrader5 عمداً لینوکس نیست.

---

## ۴. موتور مغز روی master (engines) — وضعیت نسبت به هدف شما

منطق ترید روی master با آنچه قبلاً خواندم از `d378c4b` در **هسته** یکی است:

- کلاسیک چندتایم‌فریم + SMC (OB/FVG/sweep/BOS/PD/killzone)
- ادغام + پلن + تریگر ۳ کلوز M5 + گیت fail-closed + sizing
- سیگنال: پارس → ۸ چک → همان executor
- مدیریت: نردبان/BE/trail + news_lock/time_exit روی watchdog

تفاوت‌های مهم master نسبت به برنچ فیکس ۱۷ سپتامبر (که روی master **نیستند**):

| مورد | master `2fedb95` |
|---|---|
| `merge_smc_with_classic` رژیم | `classic_context.get("regime", "range")` — کلید بالای ctx **وجود ندارد**؛ رژیم همیشه `"range"` → confidence کلاسیک همیشه نصف |
| `storage.load_*` | هنوز از `ensure_xau_plan_dirs` می‌گذرد → mkdir روی مسیر خواندن |
| `position_daemon` مدیریت | `if not DRY_RUN and plan:` — بدون پلن **کل** مدیریت (حتی گاردها) خاموشِ بی‌صدا |
| بکاپ offsite | HTTP روی `0.0.0.0` **بدون توکن** (`.env` در آرشیو) |
| verify_head استمپ | BROKEN در ۲۰۲۶-۰۹-۱۰، sha `18cc1ea`، ۱۷۰۶ تست |

b210 (daily_pnl گراس) روی master هم باز است.

---

## ۵. تکنولوژی‌ها (master)

Python 3.11+ · MetaTrader5 روی ویندوز · HTTP REST :5050 waitress · WinRM/NTLM · Telegram Bot API + Telethon userbot · systemd --user · cron · JSON/CSV اتمیک · unittest hermetic · بدون دیتابیس · بدون مدل ML

---

## ۶. بخش تکمیل‌شده / ناقص نسبت به متن شما

تکمیل‌شده روی master:

- لینوکس = مغز، ویندوز = دست
- تحلیل تکنیکال XAUUSD + SMC
- گیت ریسک ورود fail-closed، یک پوزیشن، RR≥1.5، خبر، ساعت بازار
- اجرای خودکار اسکنر
- سیگنال کور اجرا نمی‌شود (امتیاز + گیت مشترک)
- آینهٔ بریج زنده و فورواردر و ops در گیت (b79e) — مشاهده‌پذیری
- `requirements.txt`

ناقص نسبت به هدف «تریدر حرفه‌ای که یاد می‌گیرد»:

- فاندامنتال = فقط blackout تقویم، نه تفسیر
- یادگیری rule-based و practically روی پروفایل وین‌ریت‌بالا/payoff-پایین ساکت
- یک نماد، یک حساب
- مسیر سیگنال practically صفر اجرا (ژورنال بدون `plan_id=signal`)
- مدل AI وجود ندارد

---

## ۷. مشکلات تأییدشده **روی master** (حدس نیست)

### 🔴 دستِ اجرا دو نسخه است و DR هنوز از نسخهٔ غلط deploy می‌کند
زنده = `windows_bridge/bridge.py` (auth شرطی). رفرنس = `scripts/mt5_http_server_v2.py` (باز، بدون توکن). `_deploy_bridge.py` از زنده دانلود می‌کند؛ VM تازه می‌میرد. اگر کسی v2 را بالا بیاورد، API سفارش بدون رمز روی LAN است.

### 🔴 Auth زنده fail-open است
توکن خالی = همهٔ `/api/order|close|modify` باز. `/health` موجودی را لو می‌دهد.

### 🔴 مدیریت بدون پلن = خاموشی کامل
`if not DRY_RUN and plan:` — فایل پلن خراب = بدون TP/BE/trail **و بدون** news_lock/time_exit، بدون هشدار ops.

### 🔴 بکاپ حاوی `.env` روی HTTP بدون auth
پنجرهٔ کوتاه، LAN؛ هر اسکنر پورت در آن لحظه مالک توکن‌هاست.

### 🔴 verify_head از ۱۰ سپتامبر BROKEN
زنجیرهٔ push-gate fail-open روی استمپ کهنه.

### 🟠 رژیم merge همیشه range
مصرف‌کنندهٔ دیگر (`apply_smc_merge`) کلید درست `quality.regime` را می‌خواند. دو تعریف.

### 🟠 کرون ۵د vs داکیومنت/timer ۱۵د
رفتار زنده ۵ دقیقه است (`crontab.root.txt`).

### 🟠 داشبورد ۴ سرویس می‌بیند از ۹
forwarder/omniroute/webui خارج از دید «همه چیز سبز».

### 🟠 فورواردر در ریپو است، اجرا از مسیر دیگر
drift بین آینه و پروسهٔ زنده ممکن است.

### 🟡 mkdir روی read، chat-id هاردکد، git_sync به origin/master

اقتصاد ژورنال (همان data روی هر دو درخت): ۳۴ پوزیشن، نت حدود −۱۰۲$، وین ۶۵٪، میانگین برد +۳۰ / ضرر −۶۳. این روی master هم صادق است چون data یکی است.

---

## ۸. آیا معماری برای ربات حرفه‌ای مناسب است؟

**اسکلت: بله — و با b79e مشاهده‌پذیرتر شده.** لینوکس/ویندوز، گلوگاه واحد، fail-closed ورود، آینهٔ بریج/فورواردر/ops.

**محصول نهایی: هنوز نه.** خروج economically ضعیف، یادگیری payoff را نمی‌بیند، دستِ اجرا دو فایل است، چند گیت ایمنی روی مسیر مدیریت fail-open می‌مانند.

اتصال MT5: **همین Bridge زنده را نگه دارید** (`windows_bridge/bridge.py`)، آن را منبع canonical کنید، v2 را صریحاً «اجرا نشو» علامت بزنید، deploy را git→Windows یک‌طرفه کنید. EA/WebSocket برای این توپولوژی لازم نیست.

بازطراحی نکنید: جداسازی ماشین‌ها، گلوگاه executor، یک پوزیشن، fail-closed ورود.

اولویت تعمیر (پیشنهاد، اجرا با تأیید، **فقط روی برنچ جلسه**):

1. Auth زنده fail-closed + health بدون balance
2. deploy از `windows_bridge/bridge.py` بدون دانلود زنده
3. مدیریت بدون پلن → حداقل گاردها + هشدار
4. توکن روی بکاپ HTTP
5. یک عدد برای تناوب کرون (۵ یا ۱۵) در هر سه جا
6. داشبورد ۹ سرویس
7. b210 / رژیم merge — با اندازه‌گیری

---

## ۹. آنچه انجام شد / نشد

شد: خواندن `origin/master@2fedb95` فایل‌به‌فایل، از جمله هر فایل جدید b79e.

نشد: مرج به master، پوش به master، تغییر منطق ترید، شل‌کردن گیت.

برنچ جلسه فقط همین گزارش را می‌گیرد.

---

تا بگویید کدام مورد از لیست بالا را روی `arena/01a0bb28-hermes-trading` اجرا کنم، کدی عوض نمی‌شود.
