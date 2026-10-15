# سند مرجع: گیت‌های ایمنی V1 (استخراج‌شده از legacy_v1/engines/auto_executor.py)
**تاریخ استخراج:** 2026-10-15
**منبع:** `legacy_v1/engines/auto_executor.py` — `evaluate_proposal()` (lines 136-553)
**هدف:** انتقال اثبات‌شده‌ترین منطق V1 به V2 بدون بازگشت به مونولیت V1

> **قانون طلایی V1 (b29):** همه گیت‌های ایمنی **fail-closed** هستند — خطای گیت = مسدود شدن ورود، هرگز عبور.

---

## ثابت‌های ایمنی (lines 22-120)

```python
# ریسک
MAX_RISK_PER_TRADE_PCT = 0.02       # 2% از موجودی per trade (سقف سخت)
MAX_DAILY_LOSS_PCT = 0.05           # 5% ضرر روزانه → توقف معامله
MAX_DAILY_TRADES = 5                # حداکثر 5 معامله در روز
MAX_OPEN_POSITIONS = 1              # only 1 پوزیشن همزمان
MIN_RISK_REWARD = 1.0               # حداقل RR (مگر exempt style)
MIN_SETUP_GRADE = "B"               # حداقل کلاسیتی setup (A > B > C)
MAX_LOT = 0.10                      # حداکثر حجم
MIN_STOP_BALANCE = 1000.0           # زیر این موجودی stop فیلترها Loose می‌شود
MIN_STOP_DISTANCE = 8.0             # حداقل فاصله stop (gold noise floor)
MIN_STOP_ATR_MULT = 2.0             # stop ≥ 2×ATR
RR_FLOOR_EXEMPT_STYLES = {...}     # استایل‌های معاف از RR floor
STOP_TRADING_REGIMES = {...}        # regimenهای مسدود
```

---

## گیت‌های fail-closed (به ترتیب اجرا)

### Check 1 — پروپوزال معتبر
- پارامتر: `proposal` نباید None/blocked باشد
- باید `blueprint` داشته باشد
- `side ∈ {BUY, SELL}` و `entry, sl, tp > 0`
- **نتیجه**: `no_proposal` / `no_blueprint` / `invalid_blueprint`

### Check 2 — Account policy
- `trade_allowed == True` و `regime ∉ STOP_TRADING_REGIMES`
- **کاری مهم V1 (b219):** اگر `positions_unreadable` باشد، reason جدا (`bridge_dark_positions_unreadable`) — bridges failure از position limit متمایز شود
- **نتیجه**: `account_policy_{regime}`

### Check 2.5 — تاریخچه closed-trade قابل خواندن
- `history_ok is False` (نه فقط missing) → مسدود
- **چرا مهم:** پنجره خالی = روز پاک (م смерт)
- **نتیجه**: `history_unavailable`

### Check 3 — حد ضرر روزانه
- `daily_loss_pct = |min(0, daily_pnl)| / balance ≥ MAX_DAILY_LOSS_PCT (5%)` → مسدود
- **نتیجه**: `daily_loss_limit` + `daily_loss_{pct}%`

### Check 1⁺ — تسترها
- `trades_today >= MAX_DAILY_TRADES (5)` → مسدود
- **نتیجه**: `daily_trade_limit`

### Check 5 — محدودیت پوزیشن
- `open_positions >= MAX_OPEN_POSITIONS (1)` → مسدود
- **نتیجه**: `position_limit`

### Check 5.5 — هندسه TP/SL
- SELL: `tp < entry` و `sl > entry`
- BUY: `tp > entry` و `sl < entry`
- **نتیجه**: `invalid_geometry`

### Check 5.6 — حداقل Risk:Reward
- `rr = |tp-entry| / |entry-sl|` باید `≥ max(MIN_RISK_REWARD, learning_min_rr)` باشد
- ** exempts:** استایل‌های `RR_FLOOR_EXEMPT_STYLES` (b233d: aggressive_*** مقادیر -66.33 در 38 ترید vs +115.00 در 27 ترید)
- **هوشمندانه:** learning فقط می‌تواند RR floor را **بالاتر** ببرد (تایtiening)
- **نتیجه**: `poor_rr_{rr}`

### Check 5.65 — Gold noise floor
- `sl_distance ≥ MIN_STOP_DISTANCE (8.0)` یا `≥ 2×ATR` (کوچکترِ دو)
- **زیر `MIN_STOP_BALANCE` (1000)** فیلتر looser می‌شود (حساب کوچک)
- **نتیجه**: `stop_too_tight`

### Check 6 — Setup grade
- `grade ≤ MIN_SETUP_GRADE (B)` — A بهترین
- **نتیجه**: `setup_grade_{grade}`

### Check 6.5 — Learning grade gate (fail-closed!)
- `grade_idx ≥ GRADES.index(learning_state.min_grade)`
- **b29:** خطای learning = مسدود (نه bypass)
- **نتیجه**: `learned_min_grade_{X}` / `learning_gate_error`

### Check 6.6 — DEFCON feedback loop (fail-closed!)
- GREEN: full risk / YELLOW: half risk, no runner / **RED: no new entries**
- محاسبه: `loss_streak`, `daily_pnl`, `balance`, `classified exits`
- **b29:** خطای DEFCON = مسدود
- **نتیجه**: `defcon_red_entry_blocked` / `defcon_gate_error`

### Check 6.7 — Cooldown (fail-closed!)
- `check_entry_cooldown(now)` — post-open/restart cooldown
- **b29:** خطای cooldown = مسدود
- **nتیجه**: `cooldown` / `cooldown_gate_error`

### Check 7 — Macro/news blackout
- `proposal.blocked_by_macro` → مسدود
- **نتیجه**: `macro_blackout`

### Check 7.5 — Market session
- `is_market_open()` — XAUUSD: Sun 22:00 → Fri 21:00 UTC
- **نتیجه**: `market_closed`

---

## Position sizing (lines 438-510)

```python
# Pool: موجودی واقعی حساب
base_pct = min(policy_base_risk_pct, MAX_RISK_PER_TRADE_PCT)  # هرگز بالاتر از 2%
# DEFCON YELLOW → half risk
risk_pct = base_pct * (0.5 if DEFCON == YELLOW else 1.0)
# Adjustments: آموزش فقط در محدوده clamp
# MAX_LOT = 0.10 cap
```

**اصول کلیدی:**
1. **سقف سخت:** `MAX_RISK_PER_TRADE_PCT` هرگز نقض نمی‌شود (fail-closed)
2. **Base variable:** `assess_account_policy` بر اساس tier موجودی
3. **DEFCON multiplier:** YELLOW = نصف ریسک
4. **Learning clamps:** در محدوده learning.py hard clamps

---

## Management actions (evaluate_management_action, lines 555-637)

خروجی‌های management: partial close (b55: TP1 = full exit نه 100% partial)، trailing، BE.
**اصل مهم (b55):** MT5_partial close 100% را reject می‌کند → full exit.

---

## Execute trade (lines 640-716)

- **فیلتر نهایی market-hours** — همه callerها محافظت می‌شوند، نه فقط evaluate_proposal
- **b55:** `executed` یعنی "broker پذیرفت" — نه "ما فرستادیم"
- **بدون inline imports:** all imports در بالای فایل

---

## درس‌های آماری_erase یادگرفته‌شده (از کامنت‌های b-series)

| ID | درس | عدد |
|----|------|------|
| b29 | گیت‌های ایمنی همیشه fail-closed | — |
| b55 | partial close 100% → full exit; executed = broker accepted | — |
| b196 | حجم بر اساس balance-tier حساب، نه flat 2% | — |
| b219 | bridge_dark از position limit متمایز شود | — |
| b233d | RR floor فقط برای استایل‌های ضعیف | -66.33 vs +115.00 |
| b262 | stop floor scales با ATR (8.0 ثابت قطع می‌کرد) | 60% پنجره‌ها زیر ATR 4.0 |
| b267 | learning state override در تست‌ها | risk_mult 0.5 vs 1.0 |
| b296 | learning فقط tightening می‌کند | — |

---

## خروجی for V2

این گیت‌ها باید در V2 به صورت **ExecutionGuard** (domain service) پیاده‌سازی شوند — نه کپی کد، بلکه معادل clean architecture:
- gaugeها در `brain/domain/services/execution_guard.py`
- constants در `brain/domain/value_objects/risk_parameters.py`
- Fail-closed در همه جا
