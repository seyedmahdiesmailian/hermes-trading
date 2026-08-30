#!/usr/bin/env bash
# Hermes Trading autopilot — runs the coding agent against the backlog every
# 3h, market hours or not. NEVER trades: the prompt forbids execution paths,
# and the agent profile has no bridge token access to order endpoints.
# Output: logs/autopilot.log + state in data/ops/autopilot_state.json
set -u
cd /home/ai/hermes-trading

LOCK=/tmp/hermes_autopilot.lock
exec 9>"$LOCK"
flock -n 9 || { echo "$(date -u +%FT%TZ) already running, skip"; exit 0; }

LOG=logs/autopilot.log

# b40: operator pause — dashboard control panel writes this flag; the hourly
# run skips itself while it exists. Resume = delete the flag from the panel.
if [ -f data/ops/autopilot_paused ]; then
  echo "$(date -u +%FT%TZ) autopilot paused by operator ($(cat data/ops/autopilot_paused)) — skipping run" >> "$LOG"
  exit 0
fi

echo "$(date -u +%FT%TZ) === autopilot run start ===" >> "$LOG"

PROMPT='You are the Hermes trading-system autopilot. Work autonomously, no questions.

TASK: Read /home/ai/hermes-trading/data/ops/autopilot_backlog.md. Pick the TOP item
with status todo. Implement/analyze it fully in /home/ai/hermes-trading, then:
1. Run: python3 -m unittest discover -s tests  (must stay green; fix or revert)
2. Run one real cycle: timeout 120 python3 hermes_master.py  (must complete)
3. Mark the item done in the backlog with a 1-line dated finding.
4. git add -A && git -c user.email=hermes@local -c user.name=Autopilot commit -m "autopilot: <item>"
5. If you learned a reusable procedure, add it to the backlog as a new todo.

HARD RULES (violating any = revert everything):
- NEVER place/close/modify trades. Never call bridge order endpoints
  (open/close/modify). Read-only bridge calls (rates/tick/history/balance) are fine.
- NEVER edit .env, DRY_RUN, systemd units, crontab, or anything on 192.168.10.51.
- NEVER weaken risk gates, min_rr, position caps, cooldown, DEFCON, market hours.
- Backtests must use engines/backtest_real.run_backtest (live-parity funnel),
  not hand-written copies of the funnel.
- Keep changes small, tested, committed. If an item cannot be finished in this
  run, leave it todo and add a progress note under it instead.

FINAL OUTPUT: your last message MUST be a Persian (Farsi) management report,
plain prose (no English, no markdown headers). Structure it as:
۱) چه کاری انجام شد — آیتم بک‌لاگ و خلاصهٔ تغییر (فایل‌ها/تست‌ها/کامیت)
۲) چه چیزی کشف شد — یافتهٔ مهم یا ریشهٔ مشکل، به زبان ساده
۳) نتیجه — تعداد تست‌ها، وضعیت چرخه زنده، وضعیت کامیت
۴) قدم بعدی — کدام آیتم در نوبت است و چرا
If the run failed or changed nothing, say exactly that in Persian and why.'

# Agent: hermes -z (headless). Absolute path — cron PATH lacks ~/.local/bin.
# It loads the same persistent memory, which carries the autonomy rule
# (no manual approval anywhere; the system trades on its own judgement).
HERMES_BIN="$(command -v hermes || echo /home/ai/.local/bin/hermes)"
timeout 2700 "$HERMES_BIN" -z "$PROMPT" --cli >> "$LOG" 2>&1
RC=$?

echo "$(date -u +%FT%TZ) === autopilot run end rc=$RC ===" >> "$LOG"

# per-run Telegram report (only when something happened / on failure)
python3 scripts/autopilot_report.py "$RC" >> "$LOG" 2>&1 || true

# surface a compact status line for the daily digest
python3 - <<'PY'
import json, subprocess, datetime, pathlib
state = pathlib.Path('/home/ai/hermes-trading/data/ops/autopilot_state.json')
try:
    commits = subprocess.run(['git','-C','/home/ai/hermes-trading','log','--oneline','-5'],
                             capture_output=True, text=True, timeout=10).stdout.strip()
except Exception:
    commits = ''
data = {'last_run_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'recent_commits': commits.splitlines()}
state.write_text(json.dumps(data, indent=1))
PY
exit $RC
