---
name: plan-driven-trading-reporting
description: "Use for concise Persian reports in plan-driven trading."
version: 1.0.0
author: Hermes Agent
license: MIT
---

# Plan-Driven Trading Reporting

## When to use
Use when a trading automation job, cron workflow, or recurring market monitor should behave like a disciplined analyst rather than a noisy scanner.

Typical triggers:
- The system is plan-driven, zone-driven, or scenario-driven.
- The user wants fewer but more meaningful messages.
- Reports should explain what the current plan is and what the system is waiting for.
- Recurring jobs should be silent when nothing important changed.
- Time labels should be shown in the user's local market-relevant timezone.
- The user wants concise Persian output with important English market terms preserved where useful.

## Core behavior
The reporting layer should communicate in this order:
1. **Plan** — what is the directional view and what zones matter?
2. **Intent** — what does the system want to do if price reaches the relevant area?
3. **Current state** — what is happening now?
4. **Next meaningful time** — when is reassessment expected?
5. **Silence by default** — if there is no meaningful change, emit nothing.

## Required reporting policy

### 1) Prefer plan-style reports over polling-style chatter
Do **not** send repetitive messages such as "checked again" or "still nothing".

Instead, send messages that read like:
- today's plan
- current state versus the plan
- what condition would activate an entry
- when the next reassessment is due

### 2) Silent unless meaningful change
For cron/watchdog-style trading jobs, default to **no output** when all of the following are unchanged:
- current action/state
- zone classification
- active plan identity
- execution status

Emit a report only when one of these changes meaningfully:
- a new plan is created
- reassessment replaces or materially updates the plan
- price enters a meaningful zone
- action changes (`no_trade` → `wait_for_trigger`, etc.)
- an order is executed
- the setup is invalidated

### 3) Use concise Persian, not code-shaped jargon dumps
The user should understand the report without decoding raw internal fields.

Prefer:
- `جهت | صعودی`
- `وضعیت | فعلاً ورود نداریم`
- `سناریو | اگر قیمت به محدوده خرید برسد دنبال تأیید ورود می‌مانیم`

Avoid leaving raw machine labels untranslated when a human-readable Persian phrase exists.

### 4) Explain intent, not just state
A good report says both:
- what the system sees now
- what the system is waiting to do next

For example, do not stop at:
- `action: no_trade`

Also explain:
- price is above the entry zones
- therefore no entry now
- if price returns to the buy zone, wait for confirmation

### 5) Show time in the user's local trading context
If the user asks for local time, render reassessment and key timing fields in that timezone instead of raw UTC timestamps.

For Iran time, convert UTC to `UTC+03:30` and label it clearly as `ساعت ایران`.

## Recommended message shapes

### Plan message
Use a compact multi-line form:

```text
پلن طلا | XAUUSD
جهت | صعودی
خرید | 4106.16-4111.12
فروش | 4248.24-4253.20
سناریو | اگر قیمت به محدوده خرید برسد دنبال تأیید ورود می‌مانیم
بازبینی بعدی | 2026-08-07 16:30 | ساعت ایران
```

### Monitor message
Use a compact explanatory form:

```text
پایش طلا | XAUUSD | صعودی
وضعیت | فعلاً ورود نداریم
توضیح | قیمت بالای ناحیه‌های ورود است
قیمت | 4305.93
```

### Execution message
When execution occurs, keep it compact but explicit:

```text
اجرای طلا | XAUUSD | ورود بازار
جهت | خرید
حجم | 0.01
دلیل | تأیید در محدوده خرید
```

## Translation guidance
Map internal labels to human-facing Persian phrases.

Suggested mappings:
- `bullish` → `صعودی`
- `bearish` → `نزولی`
- `neutral` → `خنثی`
- `no_trade` → `فعلاً ورود نداریم`
- `wait_for_trigger` → `منتظر تأیید ورود`
- `market_order` → `ورود بازار`
- `premium` → `بالای ناحیه‌های ورود`
- `discount` → `پایین ناحیه‌های ورود`
- `value_zone` → `داخل محدوده ارزش`
- `long_zone` → `محدوده خرید`
- `short_zone` → `محدوده فروش`

## Pitfalls
- **Do not** report every polling cycle just because the cron fired.
- **Do not** leave timestamps as raw UTC if the user asked for local time.
- **Do not** dump JSON-shaped labels directly into chat when a concise Persian rendering is possible.
- **Do not** omit the scenario/intent line in plan messages; the user wants to know what the system plans to do next.
- **Do not** make the message so long that it stops being scan-friendly.

## Verification checklist
Before finishing implementation, verify:
- recurring no-change runs produce empty stdout
- meaningful state changes produce a non-empty report
- plan reports include direction, buy zone, sell zone, scenario, and next reassessment time
- monitor reports include current state and a short explanation
- local time conversion is correct for the requested timezone
- translated labels are human-readable in Persian

## Notes
This skill is especially useful for autonomous MT5/XAU workflows where the user wants analyst-style updates, not scanner spam.
