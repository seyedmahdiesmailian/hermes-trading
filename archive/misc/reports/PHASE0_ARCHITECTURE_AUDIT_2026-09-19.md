# فاز صفر — گزارش معماری و وضعیت فعلی Hermes Trading

تاریخ بررسی: ۲۰۲۶-۰۹-۱۹
برنچ بررسی‌شده: `arena/01a0bb28-hermes-trading` (HEAD = `d378c4b`)
روش: خواندن تک‌به‌تک فایل‌های اجرایی، موتورها، بریج، سرویس‌ها، اسناد و state روی دیسک.
هیچ حدسی زده نشده. هر ادعایی منبع فایلی دارد.
هیچ تغییری در منطق ترید در این فاز اعمال نشده است.

> این گزارش از روی **checkout گیت** نوشته شده، نه از روی سرور زنده لینوکس/ویندوز.
> اعداد حساب، پوزیشن باز و سلامت بریج زنده در این sandbox قابل استعلام نیستند.
> state داخل `data/` مربوط به آخرین سینک ریپو است (آخرین پلن: ۲۰۲۶-۰۹-۱۰).

---

## ۰. قرارداد کاری این جلسه

- روی `master` هیچ کامیت/پوشی انجام نمی‌شود.
- کار فقط روی برنچ جلسهٔ Arena یعنی `arena/01a0bb28-hermes-trading` است.
  این برنچ از `arena/01a0b01d-hermes-trading` منشعب شده؛ جلسه به همین نام قفل است.
- هر تغییر کد در همین برنچ کامیت می‌شود.
- تغییر بزرگ بعدی فقط بعد از تأیید شما اجرا می‌شود.

---

## ۱. معماری فعلی سیستم

### ۱.۱ ایدهٔ اصلی (از قبل پیاده شده)

دو ماشین، دو نقش. مغز روی لینوکس فکر می‌کند؛ ویندوز فقط بازوی اجرا است.

```
┌─────────────────────────────────────────────────────────────┐
│  Linux  (مغز)  /home/ai/hermes-trading                      │
│                                                             │
│  hermes_master.py      کرون هر ۱۵ دقیقه                     │
│    └─ hermes_runtime.cycle()                                │
│         اسکن بازار → پلن → گیت → ورود خودکار                │
│                                                             │
│  position_daemon.py    systemd هر ۵ ثانیه                   │
│         مدیریت پوزیشن باز: SL / BE / trail / TP / news_lock │
│                                                             │
│  signal_daemon.py      systemd long-poll                    │
│         سیگنال تلگرام → پارس → ارزیابی → اجرا یا رد         │
│                                                             │
│  dashboard_bot.py      پنل مانیتورینگ تلگرام                │
│  bridge_health_monitor کرون هر ۵ دقیقه                      │
│  offsite_backup        کرون روزانه                          │
│  git_sync / autopilot  کرون                                 │
└───────────────────────────┬─────────────────────────────────┘
                            │ HTTP :5050  Bearer token
                            │ LAN  192.168.10.18 → 192.168.10.51
┌───────────────────────────┴─────────────────────────────────┐
│  Windows VM  (بازوی اجرا)                                   │
│  MetaTrader 5 + C:\Temp\bridge.py                           │
│  سورس canonical در گیت: scripts/mt5_http_server_v2.py       │
│  فقط: tick / OHLC / account / order / modify / close        │
│  هیچ منطق تریدی روی ویندوز نیست                             │
└─────────────────────────────────────────────────────────────┘
```

این دقیقاً همان معماری هدفی است که شما توصیف کردید: لینوکس = مغز، ویندوز = MT5 + بروکر.

### ۱.۲ دو پروژهٔ مستقل داخل یک ریپو

| پروژه | ورودی | تصمیم | اجرا |
|---|---|---|---|
| ۱. تریدر اسکنر | کندل M5/M15/H1/H4 از بریج | SMC + کلاسیک → پلن → تریگر M5 | `auto_executor` → `bridge.send_order` |
| ۲. listener سیگنال | گروه تلگرام (`TELEGRAM_SIGNAL_GROUP`) | ۸ چک + گیت مشترک executor | همان executor + LIMIT pending |

هر دو مسیر در نهایت از **یک گلوگاه** رد می‌شوند: `engines/auto_executor.evaluate_proposal` و `execute_trade`. این نقطه قوت معماری است.

### ۱.۳ جریان تصمیم پروژهٔ ۱ (اسکنر)

```
bridge.get_rates(M5/M15/H1/H4)
        │
        ▼
engines.context.build_plan_context     ← ATR، بایز چندتایم‌فریم، زون، رژیم
        │
        ▼
engines.smc.smc_analyse                ← OB / FVG / sweep / BOS-CHoCH / PD / killzone
        │
        ▼
engines.smc.merge_smc_with_classic
engines.plan.apply_smc_merge           ← range-kill + stale-at-birth
        │
        ▼
engines.orchestrator.build_plan_from_context
        │  ذخیره: data/xau_plan/current_plan.json
        ▼
evaluate_monitor_cycle                 ← زون + ۳ کلوز M5 هم‌جهت (b187)
        │
        ▼
گیت‌ها (همه fail-closed):
  kill_switch → account_policy → daily_loss → daily_trades
  → open_positions=1 → geometry → RR≥1.5 → grade≥B
  → DEFCON → cooldown → news blackout → market_hours → spread
  → sizing  (base از policy، سقف ۲٪)
        │
        ▼
bridge.send_order  (اگر DRY_RUN=false)
        │
        ▼
position_daemon هر ۵ ثانیه:
  TP ladder / breakeven / trail / news_lock / time_exit
```

### ۱.۴ جریان تصمیم پروژهٔ ۲ (سیگنال تلگرام)

```
Telegram getUpdates (گروه سیگنال)
        │  تازگی ≤ ۱۰ دقیقه
        │  فیلتر نماد غیرطلا روی متن خام
        ▼
engines.signal_parser.parse_signal     ← side/entry/SL/TP/نردبان/قیمت مخفف
        │
        ▼
engines.signal_decision.evaluate_signal
  ۱. نماد باید XAUUSD باشد
  ۲. کیفیت/اطمینان پارسر
  ۳. جهت معتبر
  ۴. هم‌جهتی با بایز پلن هرمس
  ۵. RR
  ۶. سیاست حساب (locked/defensive/recovery)
  ۷. بلاک خبری HARD (تقویم در دسترس نباشد = معامله نیست)
  ۸. هشدارهای پارسر
  آستانه اجرا: امتیاز ≥ ۶ از ۱۰  و  SL موجود
        │
        ▼
همان evaluate_proposal + execute_trade
  اگر قیمت هنوز به ورود نرسیده → LIMIT pending (b70)
  اگر از ورود گذشته → رد (stale)
```

سیستم **کورکورانه سیگنال اجرا نمی‌کند**. این بخش از هدف نهایی شما از قبل پیاده شده است.

---

## ۲. نقشهٔ ارتباط اجزا (فایل به فایل)

```
cli.py ──────────────────────────► hermes_master.main
setup.sh / ops/systemd / ops/cron

hermes_master.py
  ├─ BridgeClient.health
  ├─ engines.cooldown.ensure_startup_cooldown
  ├─ hermes_runtime.cycle  ─────────────────────────┐
  ├─ engines.learning.run_learning_cycle            │
  └─ notifier.telegram (send_telegram / send_ops)   │
                                                    │
hermes_runtime.py  ◄────────────────────────────────┘
  ├─ engines.context.build_plan_context
  ├─ engines.smc.smc_analyse + merge_smc_with_classic
  ├─ engines.plan.apply_smc_merge / setup_grade / stale_at_birth
  ├─ engines.orchestrator (plan / monitor / sizing / M5 confirm)
  ├─ engines.trade_management (ladder / BE / trail)
  ├─ engines.risk (policy + performance_state)
  ├─ engines.storage (plan / journal / risk_ledger)
  ├─ engines.macro_filter + economic_calendar
  ├─ engines.legacy_guards (news_lock / time_exit)
  ├─ engines.auto_executor
  ├─ engines.kill_switch
  └─ engines.broker_clock (کالیبراسیون ساعت بروکر از watchdog)

position_daemon.py
  ├─ engines.trade_management
  ├─ engines.plan.setup_grade          ← یک تعریف مشترک با runtime
  ├─ engines.legacy_guards
  ├─ engines.auto_executor.evaluate_management_action
  └─ engines.broker_clock.save_offset

signal_daemon.py
  └─ engines.signal_listener.run_signal_check
        ├─ signal_parser
        ├─ signal_decision
        ├─ signal_pending
        ├─ kill_switch + risk.assess_account_policy
        ├─ macro_filter (fail-closed)
        └─ auto_executor.evaluate_proposal + execute_trade

bridge_client.py  ──HTTP Bearer──►  Windows :5050
                                      scripts/mt5_http_server_v2.py
                                      (Flask + waitress + MetaTrader5)

notifier/
  telegram.py     ربات ترید vs ربات ops (b37)
  dashboards.py   پنل‌های HTML تلگرام

scripts/ (عملیاتی، نه آزمایشگاه)
  hermes_cron.sh, bridge_health_monitor.py, offsite_backup.py
  git_sync.sh, verify_head.sh, verify_chain.py
  _deploy_bridge.py, mt5_http_server_v2.py
  autopilot.sh, dashboard_bot.py, weekly_report.py
```

### ۲.۱ چیزهایی که **بیرون** از این ریپو هستند

| سرویس | محل | نقش | در ریپو؟ |
|---|---|---|---|
| hermes-forwarder | `/home/ai/projects/forwarder-telegram-dockerized` | ۷ کانال سیگنال → یک گروه | خیر |
| hermes-gateway | روی سرور زنده | پل تلگرام/هرمس | خیر |
| omniroute | localhost:20128 | provider مدل | خیر |

یعنی Disaster Recovery سی‌دقیقه‌ایِ `docs/DEPLOY.md` **فقط مغز + بریج + سه سرویس systemd** را پوشش می‌دهد، نه منبع سیگنال.

---

## ۳. تکنولوژی‌ها

| لایه | تکنولوژی |
|---|---|
| زبان مغز | Python 3.11+ (stdlib + requests / dotenv / pandas / numpy / python-telegram-bot) |
| اجرای بروکر | MetaTrader 5 روی ویندوز |
| پل لینوکس↔ویندوز | HTTP REST روی LAN، پورت ۵۰۵۰، Bearer token، waitress |
| استقرار بریج | WinRM (`pywinrm` / `requests_ntlm`) از لینوکس به ویندوز |
| اعلان | Telegram Bot API (دو ربات: ترید و ops) |
| زمان‌بندی | cron کاربر لینوکس + systemd --user |
| persistence | JSON اتمیک + CSV (ژورنال، execution_log، risk_ledger) — بدون دیتابیس |
| تست | `unittest` hermetic (~۱۴۱ فایل تست) |
| بک‌تست | `engines/backtest.py` + `backtest_real.py` با parity قیف لایو |
| تقویم خبری | ForexFactory + Investing.com، کش دیسک، fail-closed |
| یادگیری | rule-based از ژورنال (سفت‌کردن RR/grade/risk) — **نه مدل ML** |

نکته مهم: هیچ `requirements.txt` / `pyproject.toml` وجود ندارد. وابستگی‌ها فقط در `setup.sh` و `docs/DEPLOY.md` آمده‌اند.

---

## ۴. وضعیت فعلی پروژه (از روی دیسک این checkout)

| مورد | مقدار | منبع |
|---|---|---|
| HEAD | `d378c4b` fix merge regime key + re-measurement | git |
| برنچ جلسه | `arena/01a0bb28-hermes-trading` | git |
| فایل پایتون (بدون legacy) | ۴۰۱ | find |
| engines | ۳۴ ماژول / ۹۸۵۱ خط | wc |
| تست | ۱۴۱ فایل `test_*.py` | ls |
| اسکریپت | ۲۱۳ | ls |
| آخرین verify_head | **BROKEN** در ۲۰۲۶-۰۹-۱۸T11:28Z، ۱۷۶۵ تست | `data/ops/head_verified.json` |
| پلن جاری | `xau-2dd9fd56` بایز **bearish** سشن london، ساخته ۲۰۲۶-۰۹-۱۰، منقضی ۲۰۲۶-۰۹-۱۱ | `data/xau_plan/current_plan.json` |
| Kill switch | halted=false، last_check ۲۰۲۶-۰۹-۱۰ | `data/kill_switch_state.json` |
| Learning | min_rr=1.5، min_grade=B، risk_mult=1.0، آخرین آپدیت ۲۰۲۶-۰۸-۲۹ | `data/xau_plan/learning_state.json` |
| لاگ سیگنال | ۵۲ رویداد: skip=۴۷، review=۳، execute=۲ | `data/signals/signals_log.json` |
| DRY_RUN پیش‌فرض | `true` (ایمن) | `.env.example` |

این checkout **سرور زنده نیست**. پلن ۹ روزهٔ منقضی یعنی state سینک‌شده کهنه است، نه لزوماً اینکه سیستم زنده خوابیده.

---

## ۵. بخش‌های تکمیل‌شده

این‌ها واقعاً وجود دارند و در مسیر live صدا زده می‌شوند (نه کد مرده):

### مغز و تحلیل
- تحلیل کلاسیک چندتایم‌فریم (M5 ورود، H1/H4 بایز، M15 فقط رأی تحلیلی)
- موتور SMC/ICT: Order Block، FVG، Liquidity Sweep، BOS/CHoCH، Premium/Discount، Killzone، Breaker، Rejection، OTE، Silver Bullet
- ادغام SMC با کلاسیک + veto «stale at birth»
- پلن با زون ورود، invalidation، نردبان TP، reassessment هر ۵ دقیقه، انقضا ۱۲ ساعت
- تریگر ورود: لمس زون **به‌علاوه** ۳ کلوز متوالی M5 هم‌جهت با بایز (ضد انتخاب نامساعد)

### ریسک و ایمنی
- ریسک پایه طبق موجودی (۱٪ / ۱.۵٪ / ۲٪) با سقف ۲٪
- حداقل RR ۱.۵، حداکثر ۱ پوزیشن، حداکثر ۵ ترید در روز، سقف ضرر روزانه ۵٪
- Kill switch (ضرر روزانه / دراودان ۱۰٪ / ۴ ضرر متوالی / مارجین)
- DEFCON GREEN/YELLOW/RED از تاریخچهٔ بسته‌شده
- Cooldown بعد از استارت و بعد از ترید
- قفل خبر ۳۰ دقیقه قبل/بعد رویداد USD (fail-closed)
- ساعت بازار XAUUSD (یکشنبه ۲۳:۰۰ تا جمعه ۲۲:۰۰ UTC)
- گیت اسپرد ورود (پیش‌فرض ۰.۶۰ دلار)
- DRY_RUN پیش‌فرض true
- یادگیری فقط می‌تواند گیت را **سفت** کند، هرگز شل نمی‌کند

### اجرا و مدیریت
- اجرای خودکار بدون تأیید انسانی
- مدیریت ۵ ثانیه‌ای: partial TP، breakeven، trail، بستن زودهنگام
- news_lock و time_exit روی watchdog (نه فقط روی کرون ۱۵ دقیقه‌ای)
- اگر watchdog بمیرد، runtime هر ۱۵ دقیقه fallback مدیریت می‌کند
- اگر kill switch فعال باشد ولی watchdog مرده باشد، مدیریت حفاظتی همچنان کار می‌کند (b207)
- اگر پلن نباشد، گاردهای مستقل از پلن (news_lock/time_exit) همچنان فعال می‌مانند و ops باخبر می‌شود (C1)

### سیگنال تلگرام
- پارسر با پشتیبانی قیمت مخفف، نردبان TP، ایموجی، فارسی/انگلیسی
- رد نماد غیرطلا روی متن خام
- مقایسه با بایز هرمس
- همان گیت‌های ریسک مسیر پلن
- LIMIT اگر قیمت هنوز به ورود نرسیده

### زیرساخت
- بریج canonical داخل گیت، با Bearer auth و waitress (فیکس ۱۷ سپتامبر)
- deploy از روی فایل گیت، نه patch زنده
- مسیر state از `engines.paths` در زمان فراخوانی (تست‌ها production را خراب نمی‌کنند)
- نوشتن JSON اتمیک (tmp + replace)
- بکاپ روزانه به ویندوز، سینک گیت‌هاب، health monitor
- سوئیت تست بزرگ با قرارداد «هر باگ → یک تست رگرسیون»

---

## ۶. بخش‌های ناقص نسبت به هدف نهایی شما

هدف شما: «تریدر حرفه‌ای که تحلیل می‌کند، تصمیم می‌گیرد، ریسک را مدیریت می‌کند، اجرا می‌کند و از گذشته یاد می‌گیرد.»

| قابلیت هدف | وضعیت واقعی |
|---|---|
| تحلیل تکنیکال | کامل برای XAUUSD (کلاسیک + SMC) |
| تحلیل فاندامنتال | فقط تقویم اقتصادی + snapshot ماکرو (DXY/بازدهی/نقره/SPX) برای **گزارش**. گیت تصمیم فقط blackout خبر است، نه تفسیر فاندامنتال |
| مدیریت سرمایه | sizing درصدی موجود است؛ بدون پورتفولیو چندنمادی، بدون Kelly، بدون همبستگی جفت‌ها |
| مدیریت ریسک | لایهٔ ورود قوی؛ لایهٔ مدیریت (DEFCON روی trail) عمداً سیم‌کشی نشده |
| اجرای هوشمند | کامل روی یک نماد، یک پوزیشن |
| یادگیری از گذشته | rule-based سفت‌کردن پارامتر؛ **مدل ML/RL وجود ندارد**. learning از ۲۰۲۶-۰۸-۲۹ تغییر نکرده |
| چند نماد / چند بروکر | فقط XAUUSD، یک بریج، یک حساب |
| اتصال تلگرام | پیاده شده؛ اما فورواردر بیرون ریپو است و مسیر سیگنال practically تقریباً اجرا نمی‌شود |
| هوش مصنوعی به‌معنای مدل زبانی/پیش‌بینی | وجود ندارد. «مغز» الگوریتم rule-based است |

---

## ۷. مشکلات موجود (فقط موارد تأییدشده از کد/دیسک)

سطح‌بندی: 🔴 باید قبل از هر استراتژی جدید بسته شود · 🟠 بدهی واقعی · 🟡 بهداشتی

### 🔴 زنجیرهٔ خودتأییدی قطع است
`data/ops/head_verified.json` آخرین بار ۲۰۲۶-۰۹-۱۸ با `verdict=BROKEN` و ۱۷۶۵ تست استمپ شده. یعنی `verify_head.sh` آخرین اجرای موفق سبز ندارد. ادعاهای قدیمی «۷۲۵/۱۷۰۰ تست سبز» منقضی‌اند.

### 🔴 daily_pnl گیت‌های پولی gross است (b210، هنوز باز)
`engines/risk.compute_performance_state` فقط `profit` را جمع می‌کند. کمیسیون و سواپ (~۲.۷٪ ضرر در نمونهٔ ۷روزه) دیده نمی‌شود. Kill switch، DEFCON و رژیم حساب کمی **شل‌تر از واقعیت حساب** تصمیم می‌گیرند. فیکس پشت دیوار ۵۰ دقیقه‌ای re-pin لجرهای b88/b89 گیر کرده.

### 🟠 مسیر سیگنال practically مرده است
۵۲ رویداد لاگ‌شده، ۲ verdict=execute، بقیه skip. گزارش ۴ سپتامبر هم صفر اجرای زنده از کانال را ثبت کرده بود. بدون فورواردر داخل ریپو و بدون مانیتورینگ آن، پنل ops می‌تواند سبز باشد در حالی که منبع سیگنال مرده است.

### 🟠 سرویس‌های جانبی در ریپو نیستند
forwarder / gateway / omniroute. DR ناقص. `ops/systemd` فقط ۳ یونیت دارد (position / signal / dashboard).

### 🟠 بدون قفل وابستگی
`pip3 install` بدون pin نسخه. روی Ubuntu 24 با PEP 668 ممکن است fail شود (`setup.sh` خطا را می‌بلعد).

### 🟠 HTTP خام روی LAN
بریج و بکاپ روی HTTP بدون TLS. طراحی پذیرفته‌شدهٔ شبکهٔ داخلی، ولی sniff = کنترل ترید / سرقت `.env`.

### 🟠 DEFCON روی مدیریت پوزیشن سیم نیست
عمدی: YELLOW اگر روی trail اعمال شود، runner را به بستن کامل تبدیل می‌کند (سیاست خروج تست‌نشده). فقط روی ورود اثر دارد.

### 🟠 پروفایل سود شکننده (از گزارش زندهٔ ۴ سپتامبر — نیاز به به‌روزرسانی با دادهٔ زنده)
وین‌ریت بالا، میانگین ضرر بزرگ‌تر از میانگین برد. یک ضرر می‌تواند ده برد را ببرد. این را در این sandbox نمی‌توانم دوباره اندازه بگیرم.

### 🟡 state و data داخل گیت
`data/` (پلن‌ها، ژورنال، تاریخچهٔ کانال، بک‌تست‌ها) و `legacy_backup/` در ریپو هستند؛ خلاف ادعای README.

### 🟡 chat-id مالک هاردکد
`194015957` به‌عنوان default در چند فایل.

### 🟡 SMC پیشرفته بیشتر observatory است
Silver Bullet / POI grade / breaker / turtle soup در پلن stamp می‌شوند ولی **گیت ورود از آن‌ها مصرف نمی‌کند**. ورود از بایز ادغام‌شده + زون + تأیید M5 می‌آید.

### موارد قبلاً قرمز که در HEAD فعلی بسته‌اند
- بریج بدون auth → الان Bearer + waitress + امتناع از استارت بدون توکن
- merge رژیم از کلید اشتباه → فیکس در `d378c4b`؛ re-measure: روی ۱۵۹۴ پلن، صفر action flip
- mkdir روی مسیر خواندن storage → فیکس A1
- مدیریت بدون پلن خاموشِ بی‌صدا → C1: گاردها می‌مانند + هشدار ops
- newline لاگ تلگرام → فیکس A4
- Silver Bullet DST → فیکس با `America/New_York`

---

## ۸. آیا معماری فعلی برای ربات حرفه‌ای مناسب است؟

**بله، به‌عنوان اسکلت. خیر، به‌عنوان محصول نهایی هوش مصنوعی.**

### قابلیت توسعه
خوب. مرزها روشن‌اند: `engines/` منطق خالص، دایمون‌ها چسب، بریج بدون منطق. قرارداد «یک تعریف، چند مصرف‌کننده» بارها با خون به دست آمده (grade، ladder، paths، regime). افزودن استراتژی جدید باید از همین گلوگاه‌ها رد شود.

### مقیاس‌پذیری
برای **یک نماد طلا، یک حساب، یک پوزیشن** طراحی شده. افقی نیست:
- state فایل‌سیستمی (JSON/CSV) با چند پروسس که kill_switch را read-modify-write می‌کنند
- کرون ۱۵ دقیقه + دایمون ۵ ثانیه کافی است برای اسکالپ M5 طلا، نه برای ۲۰ نماد
- بریج تک‌پروسس روی ویندوز SPOF است

### امنیت
برای LAN خانگی/آفیس قابل قبول؛ برای اینترنت نه.
- Bearer روی HTTP خام
- توکن‌ها در `.env` (در گیت نیست — درست)
- بکاپ offsite قبلاً بدون auth روی `0.0.0.0` سرو می‌شد (باید در فاز بعد دوباره از روی کد فعلی تأیید شود)
- هیچ RBAC، هیچ audit امضاشده، هیچ جداسازی حساب دمو/ریل در کد (فقط DRY_RUN)

### اتصال به متاتریدر
همین الان بهترین شکل عملی برای این پروژه است:

| گزینه | وضعیت |
|---|---|
| HTTP Bridge + EA/اسکریپت پایتون MT5 (فعلی) | پیاده، تست‌شده، canonical در گیت |
| Expert Advisor اختصاصی MQ5 | وجود ندارد؛ پایتون `MetaTrader5` روی ویندوز معادل عملیاتی آن است |
| WebSocket | وجود ندارد؛ polling ۵ث/۱۵د برای طلا کافی است |
| ZeroMQ / named pipe | پیچیدگی بیشتر بدون سود واضح روی LAN |

پیشنهاد من برای فاز دو (فقط پیشنهاد، اجرا نمی‌شود تا تأیید کنید): **همین Bridge را نگه دارید**، آن را سخت‌تر کنید (TLS یا حداقل bind روی اینترفیس داخلی + firewall)، EA/اسکریپت را از گیت deploy کنید، و WebSocket را فقط اگر تأخیر ورود زیر ۱ ثانیه هدف شد اضافه کنید.

### چه چیزی باید بازطراحی شود
1. ورودی گیت‌های پولی باید net باشد (b210)
2. state چندپروسسی kill_switch/cooldown باید با فایل‌لاک یا یک writer واحد باشد
3. فورواردر و gateway باید وارد همین ریپو شوند یا حداقل یونیت و healthcheck داشته باشند
4. `requirements.txt` + نسخهٔ پایتون قفل شود
5. یادگیری از «سفت‌کردن سه عدد» به حلقهٔ اندازه‌گیری واقعی (expectancy per lane، per session) ارتقا یابد — هنوز ML لازم نیست
6. SMC observatory را یا به گیت وصل کنید بعد از اندازه‌گیری، یا از پلن حذف کنید تا توهم قابلیت ساخته نشود

### چه چیزی نباید بازطراحی شود
- جداسازی لینوکس/ویندوز
- گلوگاه واحد `evaluate_proposal`
- fail-closed بودن گیت‌های ورود
- hermetic tests + «هر باگ یک رگرسیون»
- DRY_RUN پیش‌فرض true
- یک پوزیشن در لحظه، تا وقتی expectancy پایدار نشده

---

## ۹. برنامهٔ ادامهٔ مسیر (پیشنهاد فازبندی، بدون اجرا)

منطبق با فازبندی خودتان، با واقعیت کد فعلی:

| فاز | هدف شما | واقعیت الان | کار باقی |
|---|---|---|---|
| **۰ شناخت** | گزارش | همین سند | تأیید شما |
| **۱ انتقال زیرساخت** | لینوکس = هسته | انجام شده | قفل وابستگی، DR فورواردر، verify_head سبز |
| **۲ ارتباط MT5** | پل حرفه‌ای | HTTP Bridge موجود و auth‌دار | TLS/bind، تست پاریتی زنده با بریج، حذف fork خارج گیت روی ویندوز |
| **۳ موتور تحلیل** | تکنیکال+فاندامنتال+ریسک+تصمیم | تکنیکال+ریسک ورود کامل؛ فاندامنتال نازک | b210، سیم اختیاری DEFCON روی مدیریت بعد از A/B، فاندامنتال واقعی |
| **۴ اجرای معاملات** | اجرای هوشمند | کامل برای ۱ نماد | فقط سخت‌کردن، نه بازنویسی |
| **۵ تلگرام** | تحلیل سیگنال نه اجرای کور | منطق هست، اجرا practically صفر | فورواردر داخل ریپو، علت‌یابی ۵۲ skip، آستانه را بدون شل‌کردن گیت‌ها بررسی کنید |
| **۶ بهینه‌سازی/بک‌تست/یادگیری** | ارتقا | آزمایشگاه بزرگ هست؛ یادگیری ضعیف | net PnL در گیت، expectancy per lane، سپس و فقط سپس مدل |

---

## ۱۰. آنچه در این فاز انجام دادم و آنچه نکردم

انجام شد:
- خواندن کل سطح اجرایی ریپو (root، engines، notifier، ops، docs، bridge، دایمون‌ها)
- تطبیق گزارش‌های قبلی (۴ و ۱۷ سپتامبر) با HEAD فعلی
- ثبت این سند

انجام نشد (عمدی، طبق قانون شما):
- هیچ تغییر منطق ترید
- هیچ شل‌کردن گیت
- هیچ اتصال به بروکر زنده
- هیچ بازطراحی

---

## ۱۱. سؤال‌هایی که قبل از فاز یک باید جواب بدهید

حدس نمی‌زنم. این‌ها را نمی‌دانم:

1. **حساب زنده الان دمو است یا ریل؟** `HERMES_DRY_RUN` روی سرور چیست؟
2. **فورواردر تلگرام باید وارد همین ریپو شود یا جدا بماند؟**
3. **اولویت بعدی شما کدام است؟**
   - الف) بستن بدهی ایمنی (verify_head + b210 + DR)
   - ب) علت‌یابی مسیر سیگنال (۵۲ skip)
   - ج) ارتقای موتور تحلیل (فاندامنتال / چندتایم‌فریم سخت‌تر)
   - د) چیز دیگر که شما می‌گویید
4. **آیا اجازه دارم سوئیت تست را در این sandbox اجرا کنم؟** (ممکن است روی snapshot کهنه fail شود؛ تغییری در گیت‌ها نمی‌دهد)

تا تأیید شما هیچ فاز اجرایی شروع نمی‌شود.
