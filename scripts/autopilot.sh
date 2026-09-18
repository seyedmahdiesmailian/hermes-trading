#!/usr/bin/env bash
# Hermes Trading autopilot — runs the coding agent against the backlog every
# 3h, market hours or not. NEVER trades: the prompt forbids execution paths,
# and the agent profile has no bridge token access to order endpoints.
# Output: logs/autopilot.log + state in data/ops/autopilot_state.json
set -u
# b66: derive the repo root from this script's own location (the cron entry
# only needs to know where the script lives, never where the repo lives —
# a relocated checkout used to keep launching the OLD tree's autopilot).
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$REPO_ROOT" || exit 1
# the state-stamp python below runs in a quoted heredoc (no shell expansion)
# — it reads the root from this exported seam instead of a literal (b66).
export HERMES_AUTOPILOT_REPO_ROOT="$REPO_ROOT"

LOCK=/tmp/hermes_autopilot.lock
exec 9>"$LOCK"
flock -n 9 || { echo "$(date -u +%FT%TZ) already running, skip"; exit 0; }

# review-fix (2026-09-17): logs/ is gitignored — a fresh
# clone has no logs/ and every append below would die.
mkdir -p logs
LOG=logs/autopilot.log

# b40: operator pause — dashboard control panel writes this flag; the hourly
# run skips itself while it exists. Resume = delete the flag from the panel.
if [ -f data/ops/autopilot_paused ]; then
  echo "$(date -u +%FT%TZ) autopilot paused by operator ($(cat data/ops/autopilot_paused)) — skipping run" >> "$LOG"
  exit 0
fi

echo "$(date -u +%FT%TZ) === autopilot run start ===" >> "$LOG"

# b51: HEAL AN UNVERIFIED HEAD before doing anything else. The procedure
# verifies HEAD as step 4b AFTER the commit — so a run that died between
# step 4 and 4b (or a hand commit by an operator) leaves a fresh HEAD with
# no stamp, and git_sync's deliberate fail-open pushes it unverified once
# the old stamp ages out (~1h). Ask engines/head_verify.py `start-verify`
# (pure stamp+HEAD+ahead decision, exit 0 = verify now, 1 = skip, other =
# gate broken): when it says needed, run verify_head.sh RIGHT NOW — a
# crashed run then heals its own verification on the next tick and the push
# gate closes again. Read-only w.r.t. trading, never blocks the run: every
# failure path logs and falls through (b49 posture — rc distinguishes
# skip / heal / broken machinery). Placed BEFORE the harvest block so the
# tree the harvest may commit is verified from a known-good base.
SV="$(timeout 30 python3 engines/head_verify.py start-verify 2>>logs/autopilot_selfcheck.err)"
SV_RC=$?
case "$SV_RC" in
  0) echo "$(date -u +%FT%TZ) b51: HEAD unverified — healing at run start: $SV" >> "$LOG"
     bash scripts/verify_head.sh >> "$LOG" 2>&1
     ;;
  1) : ;;  # nothing to heal (HEAD verified & pushed) — silent idle tick
  *) echo "$(date -u +%FT%TZ) b51 start-verify gate rc=$SV_RC (verifier broken?) — continuing without healing" >> "$LOG"
     ;;
esac

# b47: HARVEST abandoned work before picking a new item. b36 proved a
# finished 403-line deliverable can sit uncommitted in the tree, invisible
# to cron/git_sync/verify_head (all see only HEAD) and to an agent that
# starts by reading the backlog. scripts/autopilot_harvest.py prints a
# STEP 0 instruction block when engines/dirty_work finds leftover code;
# print-only, fail-safe (broken check never blocks the run).
#
# b49: run it WITH --self-check. The old blind `|| true` made a BROKEN
# harvester byte-identical to a CLEAN one (empty HARVEST, run continues) —
# exactly the ambiguity b49 exists to kill. --self-check keeps the never-
# block posture (the run continues on failure) but the exit code now says
# WHICH happened: rc=0 + empty = genuinely clean, rc!=0 = machinery broken,
# logged loudly. The assignment's $? is the script's real status (b44:
# capture immediately, never after an `if` compound).
HARVEST="$(python3 scripts/autopilot_harvest.py --self-check 2>>logs/autopilot_selfcheck.err)"
HARVEST_RC=$?
if [ "$HARVEST_RC" -ne 0 ]; then
  echo "$(date -u +%FT%TZ) b49 SELFCHECK FAILED rc=$HARVEST_RC — harvest/dirty_work machinery is BROKEN (its silence is NOT 'clean tree'); see logs/autopilot_selfcheck.err" >> "$LOG"
fi

PROMPT='You are the Hermes trading-system autopilot. Work autonomously, no questions.

TASK: Read '"$REPO_ROOT"'/data/ops/autopilot_backlog.md. Pick the TOP item
with status todo THAT IS ABOUT THE AUTO-TRADER ITSELF (standing user order
2026-09-06: focus = trader code review, optimization, research, backtests,
architecture fixes; meta/harness/tripwire todos are LOW PRIORITY — skip them
unless NO trader item applies). Implement/analyze it fully in '"$REPO_ROOT"', then:
1. Run: python3 -m unittest discover -s tests  (must stay green; fix or revert)
2. Run one real cycle: timeout 120 python3 hermes_master.py  (must complete)
3. Mark the item done in the backlog with a 1-line dated finding.
4. git add -A && git -c user.email=hermes@local -c user.name=Autopilot commit -m "autopilot: <item>"
4b. bash scripts/verify_head.sh  (b44/b50: re-verifies the FRESH HEAD by
    running the FULL suite inside a clean detached worktree of it; logs the
    verdict to logs/verify_head.log, stamps data/ops/head_verified.json
    (b45: the cron git_sync job refuses to push an unverified/BROKEN HEAD), and
    pages ops if broken. If it reports BROKEN, fix and commit again — never
    end a run on a broken HEAD.)
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

TIME BUDGET: this run is hard-killed at 55 minutes (rc=124). Check the clock
(date -u) as you go; at ~42 minutes elapsed STOP starting new analysis and
wrap up: commit, verify_head, final report. A finished small step beats an
abandoned big one.

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
if [ -n "$HARVEST" ]; then
  echo "$(date -u +%FT%TZ) b47 harvest: leftover uncommitted code detected, STEP 0 prepended to prompt" >> "$LOG"
  PROMPT="$HARVEST

$PROMPT"
fi
timeout 3300 "$HERMES_BIN" -z "$PROMPT" --cli >> "$LOG" 2>&1
RC=$?

echo "$(date -u +%FT%TZ) === autopilot run end rc=$RC ===" >> "$LOG"

# per-run Telegram report (only when something happened / on failure)
python3 scripts/autopilot_report.py "$RC" >> "$LOG" 2>&1 || true

# surface a compact status line for the daily digest
python3 - <<'PY'
import json, os, subprocess, datetime, pathlib
# b66: the root arrives through the exported seam (the heredoc is quoted, so
# shell expansion cannot reach inside it) — never a literal install path.
_root = pathlib.Path(os.environ['HERMES_AUTOPILOT_REPO_ROOT'])
state = _root / 'data/ops/autopilot_state.json'
try:
    commits = subprocess.run(['git','-C',str(_root),'log','--oneline','-5'],
                             capture_output=True, text=True, timeout=10).stdout.strip()
except Exception:
    commits = ''
data = {'last_run_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'recent_commits': commits.splitlines()}
state.write_text(json.dumps(data, indent=1))
PY
exit $RC
