# گزارش فاز صفر — بررسی کامل و دقیق سیستم فعلی
**تاریخ:** ۱۲۰۵/۰۷/۲۵ (2026-10-15)
**بررسی‌کننده:** Hermes Agent (مدل: hermes-claude)
**روش:** بررسی فایل‌به‌فایل، اجرای زنده، بررسی دیتابیس، بررسی سرویس‌ها و لاگ‌ها — **بدون هیچ تغییری در کد**
**برanches:** `arena/01a0bb32-hermes-trading` (درگیر تغییرات نشده — این گزارش صرفاً خواندنی است)

---

## ۰. خلاصه اجرایی (یک نگاه)

سیستم شما در حال حاضر **دو معماری موازی** دارد:
1. **V2 (در حال اجرا):** Clean Architecture — `cron_master.py` → `brain/` هر ۵ دقیقه.
2. **V1 (شکسته/بایگانی):** `legacy_v1/engines/` — کد اصلی شما که موتور تصمیم‌گیری و اجرای واقعی در آن بود.

**مشکل اصلی:** در تاریخ ۸ اکتبر ۲۰۲۶ یک مهاجرت ناقص انجام شد. کد V1 به `legacy_v1/` منتقل شد، اما **مسیرهای import داخل آن اصلاح نشدند**. نتیجه: `hermes_runtime.py` و `hermes_master.py` و `position_daemon.py` (که موتور اجرای واقعی V1 بودند) اکنون **قابل import شدن نیستند** (خطای `No module named 'engines'`).

**وضعیت امروز سیستم:**
- 🟢 زنده و در حال اجرا (۸ سرویس)
- 🟢 بریج MT5 سالم، حساب $۴٬۹۳۲، پوزیشن بازی نیست
- 🟢 ۲۰۰ سیگنال تلگرام پارس و پردازش شده‌اند
- 🟢 یادگیری: ۶۲ ترید در ژورنال، وین‌ریت **۶۶.۱٪**
- 🔴 **هیچ تریدی از V2 اجرا نشده** — V2 تصمیم می‌گیرد اما دست اجرا ندارد
- 🔴 **сетка امنیتی V1 الان در مسیر اجرا نیست** (گیت‌های fail-closed که با آن‌ها ۶۶٪ وین‌ریت داشتید)
- 🔴 استراتژی‌های V2 در بک‌تست همگی **سودده نیستند** (ML Heuristic بهترین: ۲۷.۹٪ WR، ۶۸ ترید، return −۰.۶۰٪)

---

## ۱. دیاگرام ارتباط اجزا (واقعیت روی دیسک)

```
┌──────────────────────────────────────────────────────────────────────┐
│                       لینوکس 192.168.10.18                            │
│                    /home/ai/hermes-trading                            │
│                                                                       │
│  ┌─── کرون (هر ۵ دقیقه) ────────────────────────────────────────┐    │
│  │  scripts/hermes_cron.sh → entry_points/cron_master.py        │    │
│  │     → DIContainer → AutonomousTradingUseCase                 │    │
│  │        → MarketAnalyzer (SMC + Classic strategies)           │    │
│  │        → DecisionEngine (۵ فاکتور وزن‌دار)                    │    │
│  │        → JSONRepository.save_plan ← ✅ تا همین‌جا             │    │
│  │        ❌ اجرای معامله وجود ندارد                              │    │
│  └───────────────────────────────────────────────────────────────┘    │
│                                                                       │
│  ┌─── سرویس‌های systemd ────────────────────────────────────────┐     │
│  │  hermes-signal-v2    : signal_file_watcher.py (هر ۱۰ث)      │     │
│  │       → 200 سیگنال پارس شد → ❌ بدون اجرای معامله            │     │
│  │  hermes-position-v2  : daemon_position.py (هر ۲ث)           │     │
│  │       → JSON خالی → ۷ روز silence (پوزیشنی برای مدیریت نیست) │     │
│  │  hermes-dashboard    : scripts/dashboard_bot.py (پنل تلگرام) │     │
│  │  hermes-command-bot  : scripts/command_bot.py (دستورات)      │     │
│  │  hermes-forwarder    : Telethon — ۷ کانال → data/signals/    │     │
│  │       (مسیر اجرا: ~/projects/forwarder-... خارج ریپو)        │     │
│  │  hermes-gateway      : پیام‌رسانی (خارج ریپو)                │     │
│  │  hermes-webui        : داشبورد وب پورت 9119                 │     │
│  │  hermes-telegram-listener : telethon long-poll (dead سرویس)  │     │
│  └───────────────────────────────────────────────────────────────┘    │
│                                                                       │
│  ┌─── V1 شکسته (بایگانی شده) ──────────────────────────────────┐     │
│  │  hermes_runtime.py / hermes_master.py / position_daemon.py   │     │
│  │  signal_daemon.py / cli.py / bridge_client.py                │     │
│  │  notifier/telegram.py / notifier/dashboards.py               │     │
│  │     ❌ import engines → ModuleNotFoundError                  │     │
│  │     (۴۰+ فایل: ۱۴٬۴۰۴۶ LOC کل ریپو، ۱۵٬۱۹۸ LOC legacy)        │     │
│  └───────────────────────────────────────────────────────────────┘    │
└───────────────────────────────┬───────────────────────────────────────┘
                                │ HTTP REST :5050 + Bearer
                                │ (متن_plain در LAN)
┌───────────────────────────────▼───────────────────────────────────────┐
│                  ویندوز 192.168.10.51                                 │
│   C:\Temp\bridge.py (فلask + waitress، ۸ ترد)                        │
│      MT5 → CapitalxtendLLC-MU (دمو)                                  │
│      اکانت: 10382667                                                 │
└───────────────────────────────────────────────────────────────────────┘
```

### جریان سیگنال (طبق متن شما: پروژه دوم)
```
۷ کانال تلگرام → forwarder (Telethon) → data/signals/signals_log.json
  → signal_file_watcher (هر ۱۰ث) → SignalProcessingUseCase
      → MarketAnalyzer.analyze (تحلیل مستقل)
      → DecisionEngine.evaluate_signal_entry
          فاکتورها: کیفیت سیگنال / هماهنگی جهت / RR / کیفیت تحلیل ما / ریسک / تایمینگ
      → نتیجه: ACCEPT (trade_ready) یا REJECT
      ✅ ۲۰۰ سیگنال پردازش شد
      ❌ هیچ‌گاه به place_order نرسید ( execution port وجود ندارد)
```

---

## ۲. معماری فعلی سیستم

### ۲.۱ لایه‌های V2 (در حال اجرا)

| لایه | فایل‌ها | وضعیت | نقاط قوت |
|------|---------|--------|-----------|
| **Domain** | `brain/domain/` — entities, value_objects, services, repositories | ✅ کامل | استقلال از فریم‌ورک، تست‌پذیری |
| **Application** | `brain/application/use_cases/` — ۳ یوزکیس | ✅ کامل | تفکیک واضح جریان‌ها |
| **Adapters** | `adapters/gateways/mt5/`, `data/` | ⚠️ ناقص | دروازه‌های تمیز |
| **Infrastructure** | `infrastructure/` — DI, config, cache, pool | ✅ کامل | DIContainer خوب |
| **Entry Points** | `entry_points/` — ۴ نقطه ورود | ✅ فعال | — |

### ۲.۲ مغز تصمimگیری V2

`DecisionEngine.evaluate_entry` با ۵ فاکتور وزن‌دار:
1. کیفیت تحلیل (۳۰٪)
2. ریسک قابل‌قبول (۳۰٪)
3. شرایط بازار (۲۰٪)
4. الگوهای یادگرفته‌شده (۱۰٪)
5. تایمینگ (۱۰٪)

خروجی: `ENTER_TRADE / WAIT / REJECT` + `action_params` (نقش ورود، SL، TP، حجم).

### ۲.۳ نقاط ضعف معماری فعلی

| مشکل | شواهد دقیق | درجه |
|------|-------------|-------|
| **بدون لایه اجرا** | `place_order` در `MT5Gateway` تعریف شده اما **هیچ‌جا صدا زده نمی‌شود** — همه‌جا کامنت `# Would execute ... via execution port` | 🔴 حیاتی |
| **مدیریت پوزیشن کور** | `PositionManagementUseCase` پوزیشن‌ها را از `data/positions/*.json` می‌خواند (خالی) نه از MT5 → ۷ روز silence | 🔴 حیاتی |
| **یادگیری صفر** | `LearningEngine` الگوها را استخراج می‌کند اما `match_patterns` هیچ‌گاه فراخوانی نمی‌شود (decision engine از آن استفاده می‌کند ولی `learning_repo` ثبت نمی‌کند) | 🔴 حیاتی |
| **دو منبع داده** | `trade_journal` (۶۲ ردیف) vs `signals` (۰ ردیف) vs `plans` (۱ ردیف) — همگام‌سازی وجود ندارد | 🟠 متوسط |
| **دیتابیس بدون مصرف‌کننده زنده** | `data/hermes.db` (۱۲ جدول) اما V2 به JSONRepository وصل است — DB فقط توسط tests و migration استفاده می‌شود | 🟠 متوسط |
| **زبان یادگیری فانتزی** | `learning_engine.py` خالی است از منطق real — فقط dataclass; `match_patterns` و `extract_patterns` stub | 🔴 حیاتی |

---

## ۳. تکنولوژی‌های استفاده‌شده

| دسته | تکنولوژی | نقش |
|------|----------|------|
| زبان | Python 3.14.7 (`.venv`) | همه سیستم |
| متاتریدر | MetaTrader5 (ویندوز) + Flask Bridge :5050 | دست اجرا |
| ارتباط | HTTP REST + Bearer، ConnectionPool، rate-limit ۱۲۰/دقیقه | لینوکس ↔ ویندوز |
| تلگرام | Bot API + Telethon userbot (forwarder) | سیگنال + نوتیف |
| ذخیره‌سازی | JSON/CSV اتمیک + SQLite (hermes.db) | state |
| سرویس | systemd --user (۸ فعال) + cron (۵د) | اجرای پیوسته |
| تحلیل | SMC, Classic TA, ML Heuristic, Hybrid | استراتژی‌ها |
| تست | pytest (۶۱ از ۱۸۹ فایل) | — |
| زیرساخت | DI Container, Cache, ConnectionPool | — |

---

## ۴. وضعیت پروژه — بخش‌های تکمیل‌شده vs ناقص

### ✅ تکمیل‌شده

1. **لینوکس = مغز، ویندوز = دست** — جداسازی ماشین‌ها مطابق هدف
2. **بریج MT5 زنده و سالم** (`/health` → `{"balance":4932.0,"ok":true}`) با ۱۳ اندپوینت: account, positions, tick, ohlc, order, close, modify, partial, history/deals, pending, cancel, health
3. **پارس سیگنال چندزبانه** (EN/FA/AR/Emoji) — ۲۰۰ سیگنال واقعی پارس شد
4. **معماری تمیز V2** — Domain/Application/Adapters/Infrastructure
5. ** flagged اجزای V2** (طبق README_V2): Domain ۱۰۰٪، Application ۱۰۰٪، Adapters ۸۰٪، Infrastructure ۸۰٪
6. **پیشرفت‌های امنیتی:** bridge auth Bearer، fail-closed gates (در V1), idempotency keys برای order
7. **	memory های عملیاتی:** backup روزانه، git_sync ۱۵د، health monitor، autopilot
8. **داشبورد تلگرام + command bot + webui**
9. **پلن‌گذاری اتوماتیک** (V2 هر ۵ دقیقه پلن می‌سازد — `data/plans/current_plan.json`)

### ❌ ناقص

1. **لایه اجرای معامله** 🔴 — V2 هیچ‌گاه order نمی‌فرستد (`put_order` -وصل نیست)
2. **مدیریت پوزیشن** 🔴 — JSON خالی می‌خواند، نه MT5 را
3. **یادگیری** 🔴 — استخراج الگو stub است؛ nothing is learned
4. **fundamental analysis** — فقط blackout تقویم، نه تفسیر
5. **بک‌تستprofitable** 🔴 — همه ۵ استراتژی منفی (بهترین: −۰.۶۰٪، ۲۷.۹٪ WR)
6. **یک نماد (XAUUSD)، یک حساب**
7. **سرویس‌های的死:** hermes-telegram-listener (inactive dead), hermes-signal (dead), hermes-position (dead)
8. **لاگ‌های ناقص:** hermes-position-v2 از ۸ اکتبر هیچ خروجی ندارد (JSON خالی → loop بدون log)
9. **legacy paths شکسته** — `No module named 'engines'` در ۴۰+ فایل، ۱۷ تست collection error

---

## ۵. مشکلات موجود (شواهد دقیق)

### 🔴 بحرانی

**۵.۱. سیستم بدون دست اجراست (Critical)**
- **شاهد:** `grep -rn 'place_order' brain/ adapters/ entry_points/` → خالی
- **شاهد:** `autonomous_trading.py` خط ۱۳۱: `# Would execute trade here via execution port`
- **شاهد:** آخرین ترید واقعی در `data/hermes.db.trades`: `entry_time = 2026-10-08` (قبل از انتقال V2)
- **نتیجه:** سیستم شما الان فقط "فکر می‌کند" — هیچ معامله‌ای نمی‌زند

**۵.۲. گیت‌های ایمنی V1 در مسیر اجرا نیستند**
- موتورImpl اصلی شما `legacy_v1/engines/auto_executor.py` (۷۱۴ خط) با ۱۰+ fail-closed gate بود
- الان `import` نمی‌شود → تمام آن منطق بی‌اثر است
- وین‌ریت ۶۶.۱٪ شما (۶۲ ترید) حاصل همان گیت‌ها بود

**۵.۳. یادگیری صفر است**
- `LearningEngine.match_patterns` و `extract_patterns` stub هستند
- `learning_adjustments` table: **۰ ردیف** در DB
- `learning state` در V2 اصلاً--------- وصل نیست

**۵.۴. استراتژی‌ها سودده نیستند**
| استراتژی | Return | WR | ترید |
|---|---|---|---|
| ML Heuristic | −۰.۶۰٪ | ۲۷.۹٪ | ۶۸ |
| Standalone ML | −۱.۰۸٪ | ۲۸.۸٪ | ۶۶ |
| V1 SMC | −۲.۳۰٪ | ۱۵.۴٪ | ۱۳ |
| Hybrid ML-SMC | −۱.۵۱٪ | ۲۳.۱٪ | ۲۶ |
| Comprehensive | −۱.۸۸٪ | ۳۲.۶٪ | ۴۳ |

**۵.۵. position daemon کور است**
- `daemon_position.py` از `data/positions/*.json` می‌خواند (خالی)
- در نتیجه `ManagePositionRequest` → success + 0 positions → loop بدون خروجی
- حتی اگر تریدی باز شد، **مدیریت نمی‌شود** (SL/TP/BE/trail)

### 🟠 متوسط

**۵.۶. bridge auth fail-open**
- `bridge.py`: `if _BRIDGE_TOKEN and ...` — توکن خالی = همه APIها باز
- مقایسه `!=` رشته‌ای است نه `hmac.compare_digest`
- `/health` موجودی حساب را نشت می‌دهد

**۵.۷. HTTP plain در LAN**
- همه ترافیک بین لینوکس و ویندوز `http://` است
- یک اسکنر پورت در LAN مالک توکن‌ها و order API است

**۵.۸. کرون ۵د vs مستندات ۱۵د**
- `crontab`: هر ۵ دقیقه
- README، DEPLOY، `ops/cron/crontab.backup.txt`: ۱۵ دقیقه
- سه منبع، دو عدد

**۵.۹. تست‌ها half-broken**
- ۶۱ از ۱۸۹ فایل تست (*حدود ۲۰۴۲ تست*)
- ۱۷ collection error (`No module named 'engines'`)
- آنهایی که اجرا می‌شوند: ۱۲۴ PASSED (تست‌های brain/ + legacy adapters)

**۵.۱۰. داشبورد ۴ از ۹ سرویس را می‌بیند**
- forwarder/omniroute/webui خارج از دید "همه چیز سبز"

**۵.۱۱. drift فورواردر**
- سورس در `forwarder/` repo، اجرا از `~/projects/forwarder-telegram-dockerized`
- همگام‌سازی بین آینه و پروسه زنده وجود ندارد

### 🟡 خفیف

- `mkdir` روی مسیر خواندن (storage)
- chat-id hardcoded در جاهایی
- `git_sync.sh` push به origin/master مستقیم
- پورت RCypress: `notifier/telegram.py` به `engines.config` import می‌کند (شکسته)

---

## ۶. اقتصاد ژورنال (واقعیت آماری)

از `trade_journal` در `data/hermes.db`:
- **۶۲ ترید** (همه از V1، قبل از ۸ اکتبر)
- **وین‌ریت: ۶۶.۱٪** (۴۱ برد)
- **نت: −۱۵.۵۲ دلار**
- آخرین ترید: ۸ اکتبر (تاریخ مهاجرت)

> **توجه:** وین‌ریت ۶۶٪ اما نت منفی — یعنی میانگین برد کوچک‌تر از میانگین ضرر است. طبق ممیزی قبلی: میانگین برد +۳۰ / ضرر −۶۳. این الگو (high WR, negative net) نشان می‌دهد یادگیری V1 payoff را نمی‌دید — فقط وین‌ریت.

---

## ۷. پاسخ به سوالات معماری (طبق متن شما)

### ۷.۱. آیا معماری فعلی مناسب ساخت ربات ترید حرفه‌ای است؟

**اسکلت V2: بله.** لایه‌بندی درست، DI 잘Done، تفکیک واضح، استراتژی‌ها قابل افزودن.

**محصول نهایی: نه.** سه perder اساسی:
1. **لایه اجرا وجود ندارد** — تصمیم به order ختم نمی‌شود
2. **یادگیری stub است** — هیچ یادگیری اتفاق نمی‌افتد
3. **استراتژی‌ها edge ندارند** — همه منفی در بک‌تست

### ۷.۲. قابلیت توسعه، مقیاس‌پذیری، امنیت

| محور | ارزیابی | دلیل |
|------|---------|------|
| **توسعه‌پذیری** | ✅ خوب | تفکیک لایه‌ها، interface-based strategies، DI |
| **مقیاس‌پذیری** | ⚠️ محدود به یک نماد | همه‌چیز XAUUSD hardcoded؛ `get_open_positions` از فایل JSON نه از MT5 |
| **امنیت** | ⚠️ نیاز به تقویت | bridge auth fail-open، HTTP plain، `/health` نشتی، توکن در plain text |
| **اتصال به MT5** | ✅ مناسب | Bridge HTTP + Bearer برای این توپولوژی بهترین انتخاب است (نه EA، نه WebSocket) |

### ۷.۳. چه بخش‌هایی باید بازطراحی شوند؟

**بازطراحی نکنید:** جداسازی ماشین‌ها، گلوگاه executor، یک پوزیشن، fail-closed ورود.

**بازطراحی کنید (اولویت با ترتیب):**
1. **لایه اجرا** — connection بین DecisionEngine و MT5Gateway place_order
2. **مدیریت پوزیشن** — خواندن مستقیم از MT5 (نه JSON)
3. **یادگیری** — استخراج وloy实景 الگوها از trade_journal واقعی
4. **ذخیره‌سازی** — migration کامل به SQLite (مPOSIX dual-write)

### ۷.۴. چه تکنولوژی‌ها/سرویس‌هایی باید اضافه شوند؟

1. **Execution Port/Repository** در domain layer + Adapter برای `place_order`
2. **Tick streaming / WebSocket** بین بریج و لینوکس (هر ۲ث polling ضعیف است)
3. **TLS/HTTPS** برای ترافیک LAN (یا حداقل token rotation + hmac.compare_digest)
4. **OANDA/Alpha Vantage or دیگر data feeds** برای validation متقابل
5. **Backtest engine واقعی** روی داده‌های archived (الان `backtest_*.py` در root هستند)
6. **Alerting/observability** — Prometheus/Grafana یا حداقل better structured logging

---

## ۸. پیشنهادهای اصلاحی (با تحلیل ریسک)

### پیشنهاد ۱:添加 لایه اجرا (Execution Repository) 🔴
- **مزیت:** سیستم واقعاً trade می‌زند، V2 از حالت تئوری خارج می‌شود
- **معایب/ریسک:** اگر گیت‌های ایمنی منتقل نشوند، ریسک پول واقعی (الان دمو است)
- **راهکار:** قبل از فعال‌سازی، gate fail-closed همه Behaviorsها به V2 منتقل شود
- **دوره:** ۳-۵ روز

### پیشنهاد ۲: انتقال gates از V1 به V2 🔴
- **مزیت:**With وین‌ریت ۶۶٪ واید شما محفوظ می‌ماند
- **معایب:** V1 شکسته‌ است — استخراج نیاز به بازخوانی ۷۱۴ خط auto_executor دارد
- **راهکار:** مطالعه `legacy_v1/engines/auto_executor.py` و نوشتن معادل V2
- **دوره:** ۵-۷ روز

### پیشنهاد ۳: مدیریت پوزیشن مستقیم از MT5 🔴
- **مزیت:** حتی اگر پوزیشن از راه دیگری باز شد، مدیریت می‌شود
- **معایب:** نیاز به polling هر ۲ ثانیه از bridge (load)
- **راهکار:** `get_open_positions` در JSONRepository → MT5Gateway
- **دوره:** ۱-۲ روز

### پیشنهاد ۴: فعال‌سازی real learning loop 🟠
- **مزیت:** fulfillment پروژه شما (یادگیری از داده‌ها)
- **معایب:** نیاز به داده کافی (۶۲ ترید کم است)
- **راهکار:** پیاده‌سازی `extract_patterns` + زنجیره یادگیری از trade_journal
- **دوره:** ۵-۱۰ روز

### پیشنهاد ۵: امنیت bridge 🟠
- **مزیت:** محافظت از order API در LAN
- **معایب:** نیاز به restart bridge روی ویندوز
- **راهکار:** fail-closed auth، `hmac.compare_digest`، health بدون balance
- **دوره:** ۱ روز

---

## ۹. سوالات من از شما (پاسخ لازم قبل از ادامه)

طبق قانون شما ("اگر متوجه نشدی، سوال بپرس"):

1. **هدف نهایی:** آیا می‌خواهید V1 بازیابی شود (restore backup) یا V2 ادامه یابد؟
   - (V1 وین‌ریت ۶۶٪ داشت؛ V2 هنوز هیچ تریدی نزده)
2. **داده‌های V1:** آیا backup ویندوز `C:\HermesBackups` شامل کد V1 یا state بیشتری است؟
3. **دمو vs واقعی:** حسابرسی‌های قبلی حساب را **دمو** اعلام کردند. تأیید می‌کنید؟
4. **اولویت:** ابتدا "سیستم trade زن کارآمد" یا "سیستم یادگیرنده هوشمند"؟
5. **محتوای کانال‌های سیگنال:** آیا ۲۰۰ سیگنال پارس‌شده نماینده استراتژی真实ی هستند که می‌خواهید validate شود؟

---

## ۱۰. خلاصه

**سیستم شما الان یک مغز بدون دست است.** تحلیل می‌کند، تصمیم می‌گیرد، پلن می‌سازد — اما هیچ‌گاه order نمی‌فرستد. وین‌ریت ۶۶٪ شما حاصل V1 بود که الان شکسته است.

**راهبرد پیشنهادی من:** V2 را به عنوان مسیر اصلی نگه دارید (معماری خوب است)، اما **三个 شرط**:
1. لایه اجرا اضافه شود (Execution Repository → MT5Gateway.place_order)
2. گیت‌های fail-closed V1 به V2 منتقل شود
3. یادگیری واقعی (نه stub) فعال شود

**تایید شما لازم است قبل از هر تغییری.**
