# Reporting Cadence For Plan-Driven MT5/XAU Automation

## Goal

Keep the runtime useful to the user without turning it into scanner spam.

## Preferred Cadence

### User-facing reports
Send only when one of these happens:
- a new plan is created
- reassessment changes the plan or stance
- price moves into a materially different zone
- trigger is confirmed
- order is placed
- setup is invalidated
- another meaningful state transition occurs

### Silent cases
Do not emit a user-facing message when:
- the action is unchanged
- the zone is unchanged
- the runtime only repeated the same no-trade state
- nothing meaningful changed since the last emitted report

## Suggested Session Rhythm

For plan-style operation, prefer:
- morning plan
- london reassessment
- new york reassessment
- optional end-of-day wrap

A backend poll can still run more often, but it should stay quiet unless the emitted-report key changed.

## Emitted-report Key

A simple durable approach is to save a compact last-report key in runtime state, for example:
- `plan:<plan_id>`
- `<action>:<zone>`
- `execution:<ok>`

If the next candidate report resolves to the same key, emit nothing.

## User-facing Message Shape

### Plan message
- پلن طلا | XAUUSD | bias=...
- ناحیه خرید | ...
- ناحیه فروش | ...
- ابطال | ...
- تارگت‌ها | ...
- بازبینی بعدی | ...

### Monitor message
- پایش طلا | XAUUSD | bias=...
- اقدام | ... | ناحیه | ... | قیمت | ...

## Implementation Note

When using Hermes cron with `no_agent=true`, empty stdout means silent delivery. Design watchdog-style runtimes to print only on meaningful change and print nothing otherwise.
