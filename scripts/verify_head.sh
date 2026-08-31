#!/usr/bin/env bash
# b44 — POST-COMMIT HEAD verification (step 4b of the autopilot procedure).
#
# Why: the pre-commit suite runs against the WORKING TREE. `git commit -am`
# can still ship a HEAD that dies on a fresh checkout (88cac1e, and the
# untracked b42 test file — same bug class twice). This script closes the
# gap: it re-checks the COMMITTED tree, via `git archive` (no .env, no
# untracked files, no __pycache__ — exactly what cron and a deploy box see).
#
# It LOGS and ALERTS, never blocks (the commit already happened; a hook
# cannot undo it — the point is to make a broken HEAD loud within seconds,
# not at the next cron death).
#
# Usage: scripts/verify_head.sh   (run right after every autopilot commit)
set -u
cd /home/ai/hermes-trading || exit 1

LOCK=/tmp/hermes_verify_head.lock
exec 9>"$LOCK"
flock -n 9 || { echo "$(date -u +%FT%TZ) verify already running, skip"; exit 0; }

LOG=logs/verify_head.log
HEAD=$(git rev-parse --short HEAD)

# NOTE (fixed 2026-08-31): the old shape was `if cmd; then ...; fi` followed
# by `RC=$?` — after an `if` whose condition failed with no else branch, `$?`
# is the exit status of the IF compound (always 0), NOT the condition's. The
# log line recorded "VERDICT=BROKEN rc=0" for a genuinely failing run: the
# verdict was right, the captured code was a lie. Run first, capture rc
# directly, then branch.
timeout 300 python3 -m unittest \
  tests.test_b42_tracked_imports \
  tests.test_b44_clean_checkout >> "$LOG" 2>&1
RC=$?

if [ "$RC" -eq 0 ]; then
  echo "$(date -u +%FT%TZ) HEAD=$HEAD VERDICT=OK" >> "$LOG"
  exit 0
fi

echo "$(date -u +%FT%TZ) HEAD=$HEAD VERDICT=BROKEN rc=$RC" >> "$LOG"
# Loud: the whole point of b44 is that a broken HEAD must not wait for the
# next cron tick to be noticed.
python3 - "$HEAD" <<'PY' >> "$LOG" 2>&1 || true
import sys
sys.path.insert(0, '/home/ai/hermes-trading')
from env_loader import load_dotenv
load_dotenv('/home/ai/hermes-trading/.env')
from notifier.telegram import send_ops
head = sys.argv[1]
send_ops(f'⚠️ b44: HEAD {head} FAILS clean-checkout verification — '
         f'cron/fresh-clone may die. See logs/verify_head.log')
PY
exit 1
