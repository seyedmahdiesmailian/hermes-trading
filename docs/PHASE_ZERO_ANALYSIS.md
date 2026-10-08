# فاز صفر: گزارش جامع تحلیل معماری سیستم Hermes Trading

**تاریخ تحلیل:** 2026-10-08  
**تحلیلگر:** Hermes Agent  
**وضعیت:** بررسی کامل انجام شد

---

## 🎯 خلاصه اجرایی (Executive Summary)

**سیستم فعلی:** یک سیستم ترید خودکار XAUUSD با معماری **دو لایه** (لینوکس=مغز، ویندوز=بازوی اجرا) که **در حال اجراست** و عملیاتی است.

**وضعیت کلی:**
- ✅ معماری پایه **صحیح** و **عملیاتی**
- ✅ دو پروژه مجزا (تریدر خودکار + سیگنال تلگرام)
- ✅ تست‌های جامع و بک‌تست موجود
- ⚠️ **پیچیدگی بالا** — بیش از 11,000 خط کد در engines/
- ⚠️ برخی **لایه‌های اضافی** که نیاز به ساده‌سازی دارند
- ❌ **نیاز به مهندسی مجدد** برای تبدیل به "مغز هوشمند"

---

## 📊 معماری فعلی سیستم

### 1. نقشه کلی (Architecture Map)

```
┌─────────────────────────────────────────────────────────────────────┐
│                    LINUX SERVER (192.168.10.18)                     │
│                          مغز تصمیم‌گیری                              │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌─────────────────────┐        ┌─────────────────────┐            │
│  │  PROJEKT 1:         │        │  PROJEKT 2:         │            │
│  │  Hermes Trader      │        │  Signal Listener    │            │
│  │  (خودکار)           │        │  (تلگرام)           │            │
│  └─────────────────────┘        └─────────────────────┘            │
│           │                              │                          │
│           ├─ hermes_master.py            ├─ signal_daemon.py       │
│           ├─ hermes_runtime.py           ├─ signal_parser.py       │
│           ├─ position_daemon.py          └─ signal_decision.py     │
│           └─ engines/ (11,443 خط)                                  │
│                    │                                                │
│         ┌──────────┴──────────┐                                    │
│         │  engines/ MODULES   │                                    │
│         ├─────────────────────┤                                    │
│         │ • smc.py (1032L)         - تحلیل SMC/ICT              │
│         │ • auto_executor.py (714L) - اجرای خودکار              │
│         │ • signal_listener.py (940L) - گوش دادن تلگرام        │
│         │ • plan.py (629L)          - برنامه‌ریزی               │
│         │ • backtest.py (405L)      - بک‌تست                    │
│         │ • learning.py (568L)      - یادگیری                   │
│         │ • defcon.py (200L)        - سیستم هشدار               │
│         │ • risk.py (300L)          - مدیریت ریسک               │
│         │ • storage.py (327L)       - ذخیره state              │
│         └─────────────────────┘                                    │
│                    │                                                │
│                    ▼                                                │
│         ┌──────────────────────┐                                   │
│         │  bridge_client.py    │  ◄─ HTTP Client                   │
│         └──────────────────────┘                                   │
│                    │                                                │
└────────────────────┼────────────────────────────────────────────────┘
                     │
                     │ HTTP :5050 (Bearer Token)
                     │
                     ▼
┌─────────────────────────────────────────────────────────────────────┐
│              WINDOWS SERVER (192.168.10.51)                         │
│                   بازوی اجرا فقط                                    │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│   ┌────────────────────┐          ┌─────────────────────┐          │
│   │  MetaTrader 5      │  ◄────   │  Flask Bridge       │          │
│   │  Terminal          │          │  (bridge.py)        │          │
│   │  (CapitalxtendLLC) │          │  :5050              │          │
│   └────────────────────┘          └─────────────────────┘          │
│         │                                                           │
│         └─ Demo Account: 10382667                                  │
│         └─ Server: CapitalxtendLLC-MU                              │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### 2. اجزای اصلی سیستم

#### 2.1 لینوکس (مغز)

| Component | Type | وظیفه | زمان‌بندی |
|-----------|------|-------|----------|
| `hermes_master.py` | Cron | اسکن → پلن → ستاپ → ورود | هر 5 دقیقه |
| `hermes_runtime.py` | Library | هسته مشترک (تحلیل، پلن، گیت‌ها) | - |
| `position_daemon.py` | Systemd | مدیریت پوزیشن (SL/BE/trail) | هر 5 ثانیه |
| `signal_daemon.py` | Systemd | گوش دادن به سیگنال تلگرام | Long-poll |
| `bridge_client.py` | Library | HTTP client به MT5 bridge | - |
| `engines/*` | Library | 30+ ماژول تحلیل/ریسک/تصمیم | - |

#### 2.2 ویندوز (بازو)

| Component | Type | وظیفه |
|-----------|------|-------|
| `MetaTrader 5` | Application | اتصال به بروکر + اجرای معاملات |
| `windows_bridge/bridge.py` | Flask Server | HTTP API روی :5050 |
| Python 3.x + MetaTrader5 lib | Runtime | واسط MT5 |

#### 2.3 ارتباطات

```python
# Linux → Windows
HTTP POST http://192.168.10.51:5050/api/order
Headers: Authorization: Bearer <TOKEN>
Payload: {symbol, type, volume, sl, tp, comment}

# Response
{ok: true, ticket: 12345, retcode: 10009}
```

---

## 🔍 تحلیل عمیق کدها

### 1. engines/ — قلب سیستم (11,443 خط کد)

#### ماژول‌های اصلی:

**1. `smc.py` (1,032 خط)**
- تحلیل SMC/ICT
- Order Block detection
- Fair Value Gap (FVG)
- Liquidity sweep
- Premium/Discount zones
- ✅ **کد تمیز** و **مستند**
- ⚠️ **پیچیدگی بالا** — نیاز به ساده‌سازی برای فهم آسان‌تر

**2. `auto_executor.py` (714 خط)**
- موتور اجرای خودکار
- ارزیابی proposal
- محاسبه position size
- مدیریت ریسک (2% per trade, RR≥2.0)
- MAX_OPEN_POSITIONS = 1
- ✅ قوانین ریسک **مهندسی شده**
- ❌ **نیاز به بازنویسی** — منطق تصمیم‌گیری پراکنده

**3. `signal_listener.py` (940 خط)**
- Long-poll از Telegram
- پارس سیگنال‌ها
- ارزیابی و فیلتر
- ⚠️ **کد طولانی** — نیاز به تفکیک به ماژول‌های کوچک‌تر

**4. `plan.py` (629 خط)**
- ساخت plan از تحلیل
- Setup grading (A/B/C/D)
- Merge SMC + Classic
- ✅ منطق خوب اما نیاز به **بازطراحی OOP**

**5. `defcon.py` (200 خط)**
- Closed-trade feedback loop
- سطوح: GREEN / YELLOW / RED
- YELLOW: loss_streak ≥ 2 → نصف ریسک
- RED: پنج معامله بسته + SL dominant → توقف ورود
- ✅ منطق درست اما **NOT WIRED** (عمداً غیرفعال)

**6. `learning.py` (568 خط)**
- یادگیری از معاملات گذشته
- تشخیص الگوها
- ⚠️ **نیمه‌تمام** — نیاز به توسعه جدی

**7. `backtest.py` + `backtest_real.py` (756 خط)**
- Parity backtest با MT5 واقعی
- شبیه‌سازی معاملات
- ✅ **محکم** — قابل اعتماد برای تست استراتژی

#### ماژول‌های پشتیبان:
- `context.py` — بازار context
- `risk.py` — مدیریت ریسک
- `storage.py` — ذخیره state
- `economic_calendar.py` — اخبار اقتصادی
- `broker_clock.py` — ساعت بازار
- `market_hours.py` — بررسی ساعات معاملاتی
- `kill_switch.py` — کشتن اضطراری سیستم
- `guard_status.py` — وضعیت گارد‌ها
- `cooldown.py` — تأخیر بین عملیات

### 2. دیمون‌ها و سرویس‌ها

#### Systemd Services (فعال):
```bash
hermes-signal.service     - گوش دادن تلگرام (32.2M RAM, 11min CPU)
hermes-position.service   - مدیریت پوزیشن (22.9M RAM, 2min CPU)
hermes-dashboard.service  - پنل تلگرام
hermes-forwarder.service  - forward سیگنال‌ها
hermes-gateway.service    - gateway پیام‌رسانی
hermes-webui.service      - داشبورد وب
```

#### Cron Jobs:
```bash
*/5 * * * *    hermes_cron.sh              # چرخه اصلی تریدر
*/5 * * * *    bridge_health_monitor.py    # سلامت بریج
5 * * * *      autopilot.sh                # خلبان خودکار
0 2 * * *      autopilot_digest.py         # گزارش روزانه
45 23 * * *    offsite_backup.py           # بکاپ روی ویندوز
*/15 * * * *   git_sync.sh                 # سینک گیت‌هاب
```

### 3. ساختار Data

```
data/
├── xau_plan/
│   ├── current_plan.json           (30KB) - پلن فعلی
│   ├── performance_state.json      (2.9KB) - عملکرد
│   ├── learning_state.json         (107B) - یادگیری
│   ├── macro_snapshot.json         (1.8KB) - وضعیت کلان
│   └── plan_history/               - تاریخچه
├── signals/                        - سیگنال‌های تلگرام
├── backtest/                       - نتایج بک‌تست
├── calendar/                       - رویدادهای اقتصادی
├── locks/                          - قفل‌های process
└── ops/                            - عملیات
```

---

## ⚠️ مشکلات و نقاط ضعف فعلی

### 1. پیچیدگی بیش از حد (Over-Engineering)

**مشکل:**
- 11,443 خط کد در engines/
- 30+ فایل Python
- وابستگی‌های پیچیده بین ماژول‌ها
- منطق پراکنده در چند لایه

**تأثیر:**
- سخت برای فهمیدن
- سخت برای دیباگ
- سخت برای توسعه
- ریسک بالا برای باگ

**راه‌حل:**
- ساده‌سازی معماری
- ادغام ماژول‌های مشابه
- حذف لایه‌های اضافی

### 2. عدم تفکیک واضح مسئولیت‌ها

**مشکل:**
- `auto_executor.py` هم ارزیابی می‌کند هم اجرا می‌کند
- `signal_listener.py` هم می‌خواند هم تصمیم می‌گیرد
- منطق تصمیم‌گیری در چند جا تکرار شده

**تأثیر:**
- کد تکراری (DRY violation)
- تست سخت
- تغییر یک قانون نیاز به تغییر چند فایل

**راه‌حل:**
- طراحی Clean Architecture
- تفکیک: Analysis → Decision → Execution
- Single Responsibility Principle

### 3. سیستم یادگیری ناقص

**مشکل:**
- `learning.py` وجود دارد اما **نیمه‌تمام**
- فقط آمار ساده ذخیره می‌شود
- هیچ feedback loop واقعی وجود ندارد
- DEFCON عمداً غیرفعال است

**تأثیر:**
- سیستم از اشتباهات یاد نمی‌گیرد
- نمی‌تواند رفتار خود را بهبود دهد
- نیاز به تنظیم دستی پارامترها

**راه‌حل:**
- ساخت Feedback Loop واقعی
- یادگیری از معاملات بسته
- تطبیق پارامترها بر اساس عملکرد

### 4. تحلیل بازار غیرهوشمند

**مشکل:**
- تحلیل فقط **تکنیکال** است (SMC + Classic)
- هیچ تحلیل فاندامنتال واقعی نیست
- فقط XAUUSD
- تصمیم‌گیری rule-based است (نه AI)

**تأثیر:**
- نمی‌تواند شرایط خاص بازار را تشخیص دهد
- فاکتورهای کلان را نادیده می‌گیرد
- انعطاف‌پذیری پایین

**راه‌حل:**
- افزودن لایه تحلیل فاندامنتال
- استفاده از sentiment analysis
- ادغام machine learning

### 5. ارتباط با MT5 شکننده

**مشکل:**
- بریج ساده Flask روی ویندوز
- هیچ retry logic قوی
- Order idempotency تازه اضافه شده (roadmap 4.1)
- بریج می‌تواند crash کند

**تأثیر:**
- ریسک از دست رفتن orders
- ریسک دوبار باز شدن پوزیشن
- نیاز به restart دستی

**راه‌حل:**
- Queue-based architecture
- Persistent message queue
- Automatic reconnection
- Health monitoring

### 6. ارزیابی سیگنال‌های تلگرام ساده

**مشکل:**
- فقط پارس متن
- ارزیابی ساده (grade, risk check)
- **NOT** مانند یک تریدر حرفه‌ای

**تأثیر:**
- سیگنال‌های بد اجرا می‌شوند
- نمی‌تواند signal quality را بسنجد
- blind follow

**راه‌حل:**
- تحلیل عمیق context بازار
- cross-validation با تحلیل خود
- signal source reputation tracking

---

## ✅ نقاط قوت سیستم فعلی

### 1. معماری دو لایه (Linux/Windows)
✅ **صحیح** و **عملیاتی**
- جداسازی واضح: مغز / بازو
- لینوکس پایدار برای logic
- ویندوز فقط برای MT5

### 2. پوشش تست بالا
✅ 156 تست unit
✅ Parity backtest با MT5 واقعی
✅ Systematic testing

### 3. مدیریت ریسک محکم
✅ 2% risk per trade
✅ RR ≥ 2.0 (بک‌تست شده)
✅ MAX_OPEN_POSITIONS = 1
✅ Daily loss limit (5%)

### 4. کد تمیز و مستند
✅ Docstrings فارسی/انگلیسی
✅ Type hints
✅ کامنت‌های توضیحی
✅ Git history غنی

### 5. Observability
✅ Logging جامع
✅ Telegram notifications
✅ Performance tracking
✅ Weekly reports

### 6. عملیاتی و زنده
✅ در حال اجرا از 2026-08
✅ Auto-backup روزانه
✅ Git sync هر 15 دقیقه
✅ Health monitoring

---

## 🎯 ارزیابی برای ساخت "مغز هوشمند"

### آیا معماری فعلی مناسب است؟

**پاسخ کوتاه:** ❌ **خیر** — نیاز به مهندسی مجدد

**پاسخ بلند:**

سیستم فعلی یک **تریدر rule-based** است که **خوب کار می‌کند** اما:

❌ **نه هوشمند:**
- تصمیم‌گیری if/else است
- یادگیری واقعی ندارد
- انعطاف‌پذیری پایین

❌ **نه مانند تریدر حرفه‌ای:**
- فقط تکنیکال
- context awareness ضعیف
- نمی‌تواند "احساس" بازار را درک کند

❌ **پیچیدگی بالا:**
- سخت برای توسعه
- سخت برای اضافه کردن هوش

### چه باید کرد؟

**مسیر پیشنهادی:**

**فاز 1: ساده‌سازی (Simplification)**
- حذف لایه‌های اضافی
- ادغام ماژول‌های مشابه
- طراحی Clean Architecture

**فاز 2: هوشمندسازی (Intelligence Layer)**
- اضافه کردن AI/ML
- ساخت Decision Engine واقعی
- Context-aware analysis

**فاز 3: یادگیری (Learning Loop)**
- Feedback loop واقعی
- Self-improvement
- Parameter adaptation

**فاز 4: سیگنال حرفه‌ای (Professional Signal Eval)**
- تحلیل عمیق سیگنال
- Cross-validation
- Reputation tracking

---

## 📋 برنامه پیشنهادی (Roadmap)

### فاز یک: ساده‌سازی و بازطراحی پایه (2-3 هفته)

**هدف:** کد تمیز، ساده، قابل‌فهم

**اقدامات:**
1. ✅ بررسی کامل (این سند)
2. طراحی معماری جدید Clean
3. تفکیک واضح: Analysis → Decision → Execution
4. ساده‌سازی engines/:
   - ادغام ماژول‌های مشابه
   - حذف کد تکراری
   - Single Responsibility
5. بازنویسی core modules:
   - `brain.py` — مغز تصمیم‌گیری
   - `analyzer.py` — تحلیلگر بازار
   - `executor.py` — اجراکننده
6. تست کامل

**خروجی:**
- کدبیس ساده‌تر (هدف: <5000 خط)
- معماری واضح
- تست‌های جامع

### فاز دو: لایه هوش (3-4 هفته)

**هدف:** تبدیل به تریدر هوشمند

**اقدامات:**
1. طراحی Decision Engine:
   - Multi-factor analysis
   - Weight-based scoring
   - Context awareness
2. افزودن تحلیل فاندامنتال:
   - Economic calendar integration
   - News sentiment
   - Market regime detection
3. ساخت Market Intelligence:
   - Pattern recognition
   - Anomaly detection
   - Risk assessment
4. یادگیری ماشین (Phase 1):
   - Feature engineering
   - Simple ML models
   - Backtesting

**خروجی:**
- مغز هوشمند
- تصمیم‌گیری چندبُعدی
- تحلیل جامع

### فاز سه: Feedback Loop واقعی (2 هفته)

**هدف:** سیستم یادگیرنده

**اقدامات:**
1. Trade outcome analysis
2. Performance attribution
3. Parameter adaptation
4. Strategy optimization
5. فعال‌سازی DEFCON با A/B test

**خروجی:**
- سیستم خودبهبود
- Adaptive parameters
- Continuous learning

### فاز چهار: ارزیابی حرفه‌ای سیگنال (2-3 هفته)

**هدف:** سیگنال‌ها مانند تریدر حرفه‌ای ارزیابی شوند

**اقدامات:**
1. Deep signal analysis:
   - Parse + Context
   - Market validation
   - Risk assessment
2. Cross-validation:
   - سیگنال vs تحلیل خود
   - Confluence scoring
   - Rejection criteria
3. Signal source tracking:
   - Win rate per source
   - Reputation score
   - Auto-weight adjustment
4. Smart execution:
   - Entry optimization
   - Position sizing
   - Exit strategy

**خروجی:**
- ارزیابی حرفه‌ای
- Selective execution
- Quality filtering

### فاز پنج: تکمیل و بهینه‌سازی (2 هفته)

**اقدامات:**
1. Performance optimization
2. Monitoring & observability
3. Documentation
4. Training & handover

---

## 🔧 توصیه‌های فنی

### 1. معماری پیشنهادی جدید

```
┌─────────────────────────────────────────────────────────────┐
│                    HERMES BRAIN (Linux)                     │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌───────────────────────────────────────────────────────┐ │
│  │         INTELLIGENCE LAYER (مغز هوشمند)              │ │
│  ├───────────────────────────────────────────────────────┤ │
│  │                                                       │ │
│  │  ┌──────────────┐  ┌──────────────┐  ┌────────────┐ │ │
│  │  │  Market      │  │  Decision    │  │  Learning  │ │ │
│  │  │  Analyzer    │─▶│  Engine      │◀─│  Loop      │ │ │
│  │  └──────────────┘  └──────────────┘  └────────────┘ │ │
│  │         │                  │                │        │ │
│  │         ▼                  ▼                ▼        │ │
│  │  ┌────────────────────────────────────────────────┐ │ │
│  │  │         KNOWLEDGE BASE (State + History)       │ │ │
│  │  └────────────────────────────────────────────────┘ │ │
│  └───────────────────────────────────────────────────────┘ │
│                            │                                │
│                            ▼                                │
│  ┌───────────────────────────────────────────────────────┐ │
│  │         EXECUTION LAYER (اجرا)                        │ │
│  ├───────────────────────────────────────────────────────┤ │
│  │                                                       │ │
│  │  ┌──────────────┐  ┌──────────────┐  ┌────────────┐ │ │
│  │  │  Risk        │  │  Position    │  │  Order     │ │ │
│  │  │  Manager     │─▶│  Manager     │─▶│  Executor  │ │ │
│  │  └──────────────┘  └──────────────┘  └────────────┘ │ │
│  └───────────────────────────────────────────────────────┘ │
│                            │                                │
└────────────────────────────┼────────────────────────────────┘
                             │
                             ▼
                    ┌─────────────────┐
                    │  MT5 Bridge     │
                    │  (Windows)      │
                    └─────────────────┘
```

### 2. تکنولوژی‌های پیشنهادی

**برای Intelligence Layer:**
- **scikit-learn** — ML ساده و سریع
- **pandas** — data analysis (already used)
- **numpy** — محاسبات سریع (already used)

**برای Decision Engine:**
- **Rule engine** سفارشی (lightweight)
- **Fuzzy logic** برای decision making
- **Bayesian inference** برای probability

**برای Learning:**
- **Simple online learning** (incremental)
- **Reinforcement learning** (advanced, فاز بعدی)

**برای Message Queue (بهبود bridge):**
- **Redis** — in-memory queue (سبک)
- **ZeroMQ** — messaging library

### 3. Principles برای بازنویسی

1. **KISS** (Keep It Simple, Stupid)
   - ساده‌ترین راه‌حل که کار کند
   
2. **SOLID**
   - Single Responsibility
   - Open/Closed
   - Liskov Substitution
   - Interface Segregation
   - Dependency Inversion

3. **DRY** (Don't Repeat Yourself)
   - هر منطق فقط یکبار
   
4. **Separation of Concerns**
   - تحلیل ≠ تصمیم ≠ اجرا
   
5. **Testability First**
   - کد باید testable باشد

---

## 📊 ریسک‌ها و نکات مهم

### ریسک‌های بازنویسی

⚠️ **HIGH RISK:**
1. **از کار افتادن سیستم زنده**
   - Mitigation: موازی توسعه، cutover برنامه‌ریزی‌شده
   
2. **از دست رفتن logic موجود**
   - Mitigation: مستندسازی دقیق قبل از حذف
   
3. **باگ‌های جدید**
   - Mitigation: تست جامع، backtest قبل از live

⚠️ **MEDIUM RISK:**
1. **زمان بیشتر از تخمین**
   - Mitigation: فازبندی، MVP approach
   
2. **پیچیدگی بیش از حد در نسخه جدید**
   - Mitigation: code review مداوم

### نکات مهم

✅ **باید:**
- همیشه backtest قبل از live
- نسخه قدیم را نگه دار (branch)
- تست روی demo account ابتدا
- مستندسازی مداوم

❌ **نباید:**
- مستقیم روی production تغییر داد
- بدون تست deploy کرد
- همه چیز را یکجا بازنویسی کرد
- logic قدیم را بدون فهمیدن حذف کرد

---

## 🎯 تصمیم نهایی و پیشنهاد

### ارزیابی کلی

**سیستم فعلی:**
- ✅ **عملیاتی** و **کارآمد**
- ✅ معماری پایه **صحیح**
- ⚠️ **پیچیدگی بیش از حد**
- ❌ **نه هوشمند**

### پیشنهاد

**مسیر A: بازنویسی کامل (پیشنهاد من) ✅**

**مزایا:**
- کد تمیز و ساده
- معماری مهندسی‌شده
- آماده برای هوش
- نگهداری آسان

**معایب:**
- زمان‌بر (8-12 هفته)
- ریسک بالا
- نیاز به تست جامع

**مسیر B: بهبود تدریجی**

**مزایا:**
- ریسک پایین‌تر
- سیستم زنده می‌ماند
- تغییرات کوچک

**معایب:**
- پیچیدگی باقی می‌ماند
- محدودیت در هوشمندسازی
- technical debt انباشته

### توصیه نهایی

**من پیشنهاد می‌کنم: مسیر A (بازنویسی)**

**دلیل:**
1. سیستم فعلی خوب است اما **ceiling** دارد
2. برای "مغز هوشمند" نیاز به **foundation** جدید
3. بهتر است یکبار درست بسازیم
4. سرمایه‌گذاری بلندمدت

**با این شرایط:**
1. ✅ Development موازی (سیستم زنده باقی بماند)
2. ✅ Backtest جامع قبل از cutover
3. ✅ Rollback plan واضح
4. ✅ فازبندی دقیق

---

## 📝 مراحل بعدی (Next Steps)

### گام 1: تصمیم‌گیری
**شما باید تصمیم بگیرید:**
- مسیر A یا B؟
- بودجه زمانی؟
- اولویت‌ها؟

### گام 2: طراحی تفصیلی (در صورت تأیید مسیر A)
**من طراحی می‌کنم:**
- معماری دقیق
- Class diagram
- Data flow
- API design
- Database schema

### گام 3: شروع فاز یک
**اقدامات:**
1. ساخت branch جدید: `feature/brain-rewrite`
2. ساخت skeleton جدید
3. Migration تدریجی
4. تست موازی

---

## 📎 پیوست‌ها

### A. فهرست کامل فایل‌های engines/

```
auto_executor.py (714L)      - اجرای خودکار
autopilot_report_lib.py      - گزارش autopilot  
backtest.py (405L)           - بک‌تست
backtest_real.py (351L)      - بک‌تست واقعی
bridge_payload.py            - payload بریج
broker_clock.py              - ساعت بروکر
config.py                    - تنظیمات
context.py (392L)            - context بازار
cooldown.py                  - تأخیر
defcon.py (200L)             - سطح هشدار
dirty_work.py                - کارهای کثیف
economic_calendar.py (319L)  - تقویم اقتصادی
guard_status.py              - وضعیت گارد
head_verify.py (614L)        - تأیید سر
kill_switch.py               - کشتن اضطراری
lab_decay.py                 - آزمایش decay
lab_fire_rate.py             - آزمایش fire rate
lab_harness.py (356L)        - harness آزمایش
learning.py (568L)           - یادگیری
legacy_guards.py             - گارد‌های قدیمی
macro_filter.py              - فیلتر کلان
macro_snapshot.py            - snapshot کلان
market_hours.py              - ساعات بازار
orchestrator.py              - هماهنگ‌کننده
paths.py                     - مسیرها
plan.py (629L)               - برنامه‌ریزی
process_lock.py              - قفل پروسه
report.py                    - گزارش
risk.py (300L)               - مدیریت ریسک
selfcheck.py                 - خودآزمایی
signal_decision.py           - تصمیم سیگنال
signal_listener.py (940L)    - گوش دادن سیگنال
signal_parser.py (526L)      - پارس سیگنال
signal_pending.py            - سیگنال معلق
smc.py (1032L)               - تحلیل SMC
storage.py (327L)            - ذخیره‌سازی
trade_management.py (406L)   - مدیریت معامله
```

**جمع:** 11,443 خط کد

### B. سرویس‌های systemd

```bash
hermes-dashboard.service  - پنل تلگرام
hermes-forwarder.service  - forward سیگنال
hermes-gateway.service    - gateway
hermes-position.service   - مدیریت پوزیشن
hermes-signal.service     - listener تلگرام  
hermes-webui.service      - داشبورد وب
```

### C. Cron jobs

```bash
*/5   hermes_cron.sh              # چرخه اصلی
*/5   bridge_health_monitor.py    # سلامت بریج
5     autopilot.sh                # خلبان خودکار
0 2   autopilot_digest.py         # گزارش
45 23 offsite_backup.py           # بکاپ
*/15  git_sync.sh                 # سینک گیت
```

---

## 🔚 نتیجه‌گیری

سیستم فعلی **یک تریدر خودکار عملیاتی** است که **خوب کار می‌کند**.

اما برای تبدیل به **"مغز هوشمند تریدینگ"** نیاز به **مهندسی مجدد** دارد.

**توصیه:** بازنویسی فازبندی‌شده با حفظ سیستم زنده.

**زمان تخمینی:** 8-12 هفته

**ریسک:** متوسط تا بالا (قابل مدیریت با فازبندی)

**ROI:** بسیار بالا (foundation برای آینده)

---

**آماده برای شروع فاز بعدی هستم. منتظر تصمیم شما.**

**تهیه‌کننده:** Hermes Agent  
**تاریخ:** 2026-10-08  
**نسخه:** 1.0
