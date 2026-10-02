# گزارش تحلیل عمیق ساختار قبلی Hermes Trading

## وضعیت این مرحله

این مرحله فقط تحلیل، catalog و تست بود. هیچ تغییری روی سیستم اجرایی، Bridge، cron یا ترید واقعی اعمال نشد.

مسیر legacy نرمالشده برای مطالعه:

```text
/home/ai/hermes-trading/legacy_backup/normalized
```

فایلهای catalog:

```text
/home/ai/hermes-trading/legacy_backup/catalog/inventory.json
/home/ai/hermes-trading/legacy_backup/catalog/python_summary.json
/home/ai/hermes-trading/legacy_backup/catalog/high_value_python.json
/home/ai/hermes-trading/legacy_backup/catalog/deep_compare.json
```

---

## 1. هسته معماری قبلی چه بوده؟

ساختار قبلی یک سیستم Plan-First بوده، نه فقط سیگنال ساده.

جریان اصلی در فایل زیر است:

```text
scripts/mt5_xau_runtime.py
```

این فایل runtime اصلی قبلی است و این مراحل را انجام میدهد:

```text
1. دریافت داده M15/H1/H4 از MT5
2. ساخت context کلاسیک بازار
3. اجرای SMC/ICT/RTM
4. merge کردن SMC با context کلاسیک
5. ساخت plan جدید
6. ذخیره current_plan/runtime_state/performance_state
7. در چرخههای بعدی:
   - اگر plan منقضی شده: plan جدید
   - اگر زمان بازبینی رسیده: reassess
   - اگر plan فعال است: monitor
8. اگر position باز وجود دارد: manage position
9. اگر setup ورود فعال شده: sizing + execution
10. ثبت journal/log/setup profile
```

این یعنی معماری قبلی دنبال «هر بار سیگنال بزن» نبود؛ دنبال «پلن بساز، بعد پایش کن، بعد فقط اگر شرایط فعال شد ورود/مدیریت کن» بود.

---

## 2. مسیر دقیق Plan / Reassess / Monitor / Execute

### Plan

تابعهای اصلی:

```text
mt5_xau_runtime._build_live_plan()
mt5_xau_context.build_plan_context()
mt5_xau_smc.smc_analyse()
mt5_xau_smc.merge_smc_with_classic()
mt5_xau_orchestrator.build_plan_from_context()
```

ورودی لازم:

```text
M15: 80 کندل
H1: 80 کندل
H4: 80 کندل
session: asia/london/newyork
```

خروجی plan شامل اینهاست:

```json
{
  "plan_id": "xau-...",
  "symbol": "XAUUSD",
  "bias": "bullish|bearish|neutral",
  "session": "asia|london|newyork",
  "zones": {},
  "invalidation": 0,
  "targets": [],
  "execution": {},
  "quality": {},
  "created_at": "...",
  "expires_at": "...",
  "next_reassessment": "...",
  "context": {}
}
```

### Reassess

تابع مسیر:

```text
mt5_xau_orchestrator.route_runtime_step()
```

قانون:

```text
اگر plan نیست => plan
اگر expires_at گذشته => plan
اگر next_reassessment رسیده => reassess
وگرنه => monitor
```

زمانبندی بازبینی:

```text
Asia: تا 07:00
London: تا 13:00
NY: هر حدود 4 ساعت
Plan expiry: 12 ساعت
```

### Monitor

تابعها:

```text
mt5_xau_orchestrator.evaluate_monitor_cycle()
mt5_xau_plan.decide_execution_action()
mt5_xau_runtime._select_execution_decision()
```

رفتار:

- اگر bias خنثی یا regime رنج باشد: no_trade
- اگر bullish و breakout trigger زده شود: market_entry_now
- اگر bullish و قیمت زیر scale zone باشد: place_buy_limit
- اگر bearish و trigger یا zone مناسب باشد: معادل sell
- اگر quality gate پاس نشود: wait_for_trigger

### Execute

تابع اصلی قبلی:

```text
mt5_xau_orchestrator.execute_trade_blueprint()
```

این تابع command میسازد:

```text
open XAUUSD BUY|SELL LOT SL_POINTS TP_POINTS "Hermes plan"
```

و با runner میفرستد به:

```text
mt5_direct_runner.run_mt5_direct_command()
mt5_direct.py
```

نکته مهم: در معماری جدید این قسمت نباید مستقیم اجرا کند؛ باید تبدیل شود به proposal و approval gate.

---

## 3. SMC / ICT / RTM قبلی چقدر ارزشمند است؟

فایل:

```text
scripts/mt5_xau_smc.py
```

این یکی از ارزشمندترین بخشهای سیستم قبلی است.

قابلیتها:

- Order Blocks
- Fair Value Gaps
- Liquidity Sweep / Stop Hunt
- Market Structure: BOS / CHoCH / Range
- Premium / Discount
- Killzone timing
- POI grading
- Breaker Blocks
- Rejection Blocks
- OTE
- Power of Three
- Turtle Soup
- Silver Bullet
- Session Liquidity
- Volume Imbalance
- merge_smc_with_classic

این فایل مستقل از MetaTrader5 است؛ یعنی برای انتقال به لینوکس بسیار مناسب است.

تصمیم انتقال:

```text
KEEP / PORT DIRECTLY
```

ولی باید خروجی آن استاندارد شود و با decision schema جدید ادغام شود.

---

## 4. Context و Classic Analysis قبلی

فایل:

```text
scripts/mt5_xau_context.py
```

قابلیتها:

- value zone با percentile
- bias برای M15/H1/H4
- ATR ساده
- alignment بین تایمفریمها
- regime detection
- ساخت execution plan
- تعیین invalidation و targets

مهمترین قانونهای context:

```text
اگر bias خنثی یا trend ضعیف => range
اگر alignment یا higher TF همسو نباشد => range
اگر قیمت از value zone خارج شود => breakout_continuation
وگرنه pullback_continuation
```

تصمیم انتقال:

```text
KEEP / PORT DIRECTLY, سپس تقویت با SMC
```

---

## 5. Risk / DEFCON قبلی

دو فایل مهم:

```text
scripts/mt5_account_risk.py
scripts/mt5_xau_defcon.py
```

### mt5_account_risk.py

مستقل از MT5 است و قابل انتقال مستقیم است.

قوانین اصلی:

```text
Balance < 800     => base risk 1%
Balance < 1500    => base risk 1.5%
Balance < 5000    => base risk 2%
Balance >= 5000   => base risk 1.5%
```

قفلها:

```text
drawdown >= 5% یا daily loss >= 3% balance => locked
loss_streak >= 2 یا daily loss >= 1% balance => defensive
drawdown >= 2.5% => recovery
margin_ratio < 20 => locked
max_positions_allowed = 1
```

setup grade impact:

```text
A => 100% risk budget
B => 60%
C => 30%
```

### DEFCON

قوانین runtime:

```text
GREEN: full runner/scale-in/partial allowed
YELLOW: loss_streak >= 2 یا SL ratio بالا => runner و scale-in خاموش
RED: >=5 closed و SL dominant و daily_pnl منفی => no new entries
```

تصمیم انتقال:

```text
KEEP, ولی بخش snapshot_closed_deals باید از Bridge/history endpoint داده بگیرد نه import مستقیم MT5
```

---

## 6. Trade Management قبلی

فایل:

```text
scripts/mt5_xau_trade_management.py
```

این فایل مستقل از MT5 است و بسیار قابل انتقال است.

رفتار:

- TP1 خورده:
  - اگر setup قوی باشد: فقط 30% ببندد و runner نگه دارد
  - اگر setup ضعیف باشد: 70% ببندد
  - حالت معمول: 50%
- بعد از TP1:
  - SL به breakeven یا کمی سود منتقل شود
- بعد از TP2:
  - اگر structure خراب شد: close_runner
  - اگر سالم بود: trail_stop
- Scale-in فقط وقتی:
  - thesis معتبر باشد
  - structure خراب نباشد
  - exposure زیاد نباشد
  - RR باقیمانده کافی باشد
- اگر thesis قبل از target باطل شد:
  - close_trade_early

تصمیم انتقال:

```text
KEEP / PORT DIRECTLY
```

اما execution actions باید فقط به proposal تبدیل شوند مگر اینکه command صریح کاربر باشد.

---

## 7. Storage و Report قبلی

### Storage

فایل:

```text
scripts/mt5_xau_storage.py
```

قابلیتها:

- current_plan.json
- plan_history
- runtime_state.json
- performance_state.json
- execution_log.csv
- reassessment_log.csv
- pending_orders.json

مشکل:

مسیر پیشفرض ویندوزی است:

```text
C:\Users\Administrator\AppData\Local\hermes\trading\xau_plan
```

تصمیم انتقال:

```text
KEEP, ولی DEFAULT_BASE_DIR باید Linux-safe شود:
/home/ai/hermes-trading/data/xau_plan
```

### Report

فایل:

```text
scripts/mt5_xau_report.py
```

این فایل گزارش فارسی تمیز میسازد:

- پلن جدید
- بازبینی پلن
- پایش
- اجرای معامله
- مدیریت معامله

تصمیم انتقال:

```text
KEEP / PORT DIRECTLY
```

---

## 8. اجرای مستقیم MT5 قبلی

فایلها:

```text
scripts/mt5_direct.py
scripts/mt5_engine.py
scripts/mt5_xau_runtime.py
scripts/mt5_xau_defcon.py
```

اینها جاهایی هستند که مستقیم `MetaTrader5` import یا `order_send` دارند.

برای معماری جدید:

```text
DO NOT PORT DIRECT EXECUTION TO LINUX
```

چرا؟

- لینوکس MT5 ندارد.
- ویندوز باید فقط execution host بماند.
- هر order_send باید پشت Bridge و approval gate باشد.
- قوانین جدید کاربر: هیچ تریدی بدون دستور صریح /trade نباید اجرا شود.

پس از این فایلها فقط منطق قابل استخراج را میبریم، نه اجرای مستقیم.

---

## 9. تستهای legacy چه نشان دادند؟

برای صحت منطق مستقل از MT5 یک venv موقت ساختم و pytest نصب کردم. این تستها اجرا شدند:

```text
test_mt5_xau_context.py
test_mt5_xau_plan.py
test_mt5_xau_trade_management.py
test_mt5_account_risk.py
test_mt5_xau_quality_gates.py
```

نتیجه واقعی:

```text
29 passed in 0.19s
```

این یعنی بخشهای pure logic قبلی سالم و قابل اتکا هستند.

تست کامل همه فایلها فعلاً اجرا نشد چون بخشی از تستها به MetaTrader5/pytest environment کامل وابستهاند. ولی subset مهم logic پاس شد.

---

## 10. مقایسه با سیستم فعلی لینوکس

### فعلی لینوکس

```text
hermes_master.py
hermes_brain.py
hermes_analyzer.py
```

### مشکل فعلی

`hermes_analyzer.py` فقط یک نسخه سبک است:

- trend ساده
- ATR ساده
- FVG ساده
- confidence ساده
- DEFCON عددی ساده

در برابر legacy، خیلی ضعیفتر است.

### مشکل بزرگتر

`hermes_master.py` الان با command file میتواند `bridge.send_order()` را صدا بزند. البته DRY_RUN=True است، ولی implementation فعلی واقعاً قبل از check خشک/زنده، send_order را صدا میزند و بعد فقط `dry_run` را روی result میگذارد. این از نظر ایمنی باید اصلاح شود.

اصلاح ضروری در معماری جدید:

```text
اگر DRY_RUN=True باشد اصلاً نباید bridge.send_order فراخوانی شود.
```

---

## 11. چه چیزهایی از legacy منتقل شود؟

### انتقال مستقیم/تقریباً مستقیم

```text
mt5_xau_smc.py
mt5_xau_context.py
mt5_xau_plan.py
mt5_xau_orchestrator.py - فقط pure functions
mt5_xau_trade_management.py
mt5_account_risk.py
mt5_xau_report.py
mt5_xau_storage.py - با مسیر لینوکسی
```

### انتقال با adapter

```text
mt5_xau_runtime.py
```

این فایل باید به `hermes_runtime.py` جدید تبدیل شود:

- حذف import مستقیم MetaTrader5
- جایگزینی `_rows()` با BridgeClient.get_rates()
- جایگزینی mt5.account_info با BridgeClient.get_account()
- جایگزینی mt5.positions_get با BridgeClient.get_positions()
- جایگزینی history_deals_get با BridgeClient.get_history_deals()
- تبدیل execute به proposal/approval gate

### انتقال محدود/فقط ایدهها

```text
mt5_direct.py
mt5_engine.py
mt5_xau_defcon.py
```

از اینها:

- منطق validation
- filling mode handling
- close/partial/modify patterns
- retcode handling
- risk/news ideas

را میگیریم، اما کد اجرای مستقیم را وارد brain لینوکس نمیکنیم.

### منتقل نشود / legacy only

```text
هر چیزی که مستقیم order_send کند روی لینوکس
هر چیزی که auto-trade کند بدون approval
هر چیزی که path ویندوزی hardcoded دارد بدون adapter
هر چیزی که Hermes old cron/session/state db وابسته است
```

---

## 12. معماری پیشنهادی بازطراحی جدید

ساده، نه طلاکوبی:

```text
/home/ai/hermes-trading/
├── hermes_master.py              # فقط runner هر 15 دقیقه
├── bridge_client.py              # HTTP client به ویندوز
├── engines/
│   ├── smc.py                    # از mt5_xau_smc.py
│   ├── context.py                # از mt5_xau_context.py
│   ├── plan.py                   # از mt5_xau_plan.py
│   ├── risk.py                   # از mt5_account_risk.py
│   ├── trade_management.py       # از mt5_xau_trade_management.py
│   └── runtime.py                # adapter شده از mt5_xau_runtime.py
├── execution/
│   ├── approval_gate.py          # قانون sacred: no /trade => no order
│   └── proposal.py               # ساخت پیشنهاد معامله
├── notifier/
│   └── telegram.py
├── data/
│   ├── xau_plan/
│   ├── journal/
│   └── commands/
├── scripts/
│   ├── hermes_cron.sh
│   └── bridge_health_monitor.py
└── legacy_backup/
```

اما برای ساده ماندن، در فاز اول لازم نیست همه پوشهها را زیاد کنیم؛ میشود با چند فایل شروع کرد:

```text
bridge_client.py
hermes_runtime.py
hermes_master.py
engines/*.py
```

---

## 13. اصل redesign

در معماری جدید، مغز باید چنین خروجی بدهد:

```json
{
  "ok": true,
  "step": "plan|reassess|monitor|manage|proposal",
  "symbol": "XAUUSD",
  "bias": "bullish|bearish|neutral",
  "defcon": "green|yellow|red",
  "trade_allowed_by_system": true,
  "requires_user_approval": true,
  "will_execute_now": false,
  "proposal": {
    "side": "BUY|SELL",
    "lot": 0.01,
    "entry": 0,
    "sl": 0,
    "tp": 0,
    "reason": "..."
  }
}
```

قانون ثابت:

```text
will_execute_now = true فقط اگر command صریح /trade یا /close یا /modify مصرف شده باشد.
```

حتی اگر engine بگوید market_order، خروجی باید proposal باشد نه order.

---

## 14. اولویت فاز بعد

پیشنهاد عملی من برای قدم بعدی:

### فاز 1: ساخت Skeleton جدید بدون live execution

1. ساخت `engines/` و کپی pure modules legacy
2. اصلاح storage path به Linux
3. ساخت `bridge_client.py` استاندارد
4. ساخت `hermes_runtime.py` adapter شده که مستقیم MetaTrader5 import نکند
5. ساخت report/proposal Telegram
6. اجرای pytest روی logic
7. اجرای یک cycle dry-run بدون order_send

### فاز 2: Bridge پایدار

بعد از اینکه brain آماده شد:

- Bridge ویندوز باید endpointهای واقعی بدهد:
  - `/health`
  - `/api/account`
  - `/api/tick/XAUUSD`
  - `/api/rates/XAUUSD?tf=M15&count=80`
  - `/api/rates/XAUUSD?tf=H1&count=80`
  - `/api/rates/XAUUSD?tf=H4&count=80`
  - `/api/positions?symbol=XAUUSD`
  - `/api/history/deals?symbol=XAUUSD&days=7`
- هر endpoint timeout داخلی داشته باشد.
- `/health` فقط وقتی OK باشد که MT5 tick هم جواب بدهد.

### فاز 3: اجرای کنترلشده

- command file فقط trigger execution باشد.
- DRY_RUN hard gate باشد.
- سپس با دستور صریح مهدی live mode جداگانه فعال شود.

---

## 15. نتیجه نهایی این مرحله

ساختار قبلی ارزشمند است و باید استفاده شود، اما به شکل خام قابل انتقال نیست.

مغز اصلی قبلی:

```text
Plan-First + SMC + Context + DEFCON + Trade Management
```

این دقیقاً همان چیزی است که باید در معماری جدید زنده شود.

اما بخش execution قبلی باید کاملاً جدا و محدود شود، چون قانون جدید این است:

```text
تحلیل خودکار: بله
پیشنهاد معامله: بله
اجرای معامله بدون دستور صریح مهدی: هرگز
```
