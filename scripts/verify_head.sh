#!/usr/bin/env bash
# b44/b50 — POST-COMMIT HEAD verification (step 4b of the autopilot procedure).
#
# Why: the pre-commit suite runs against the WORKING TREE. `git commit -am`
# or selective staging can still ship a HEAD that dies on a fresh checkout
# (88cac1e, 43c5f52, 920ed0d — same incident class three times). This script
# re-checks the COMMITTED tree.
#
# b50 upgrade: import checks alone were not enough. 920ed0d shipped b45's
# TESTS without its SOURCE fixes — everything imported fine, 3 tests were RED,
# and the old verdict said OK. Import integrity answers "does the commit
# boot"; only the FULL SUITE answers "does the commit work". So:
#   1. import checks first (a ModuleNotFoundError must still report its own
#      specific shape, and they are fast), then
#   2. engines/head_verify.py runs the WHOLE suite inside a clean detached
#      worktree of HEAD (minimal env + HERMES_DATA_ROOT inside the tree, so
#      production state is never touched) and
#   3. stamps data/ops/head_verified.json — the seam b45's push gate reads.
#
# It LOGS and ALERTS, never blocks (the commit already happened; the point is
# to make a broken HEAD loud within seconds, not at the next cron death).
#
# Usage: scripts/verify_head.sh   (run right after every autopilot commit)
set -u
cd /home/ai/hermes-trading || exit 1

LOCK=/tmp/hermes_verify_head.lock
exec 9>"$LOCK"
flock -n 9 || { echo "$(date -u +%FT%TZ) verify already running, skip"; exit 0; }

LOG=logs/verify_head.log
HEAD=$(git rev-parse --short HEAD)

# NOTE (fixed 2026-08-31): the old shape was `if timeout … unittest; then …`
# followed by `RC=$?` — after an `if` whose condition failed with no else
# branch, `$?` is the exit status of the IF compound (always 0), NOT the
# condition's. The log line recorded "VERDICT=BROKEN rc=0" for a genuinely
# failing run: the verdict was right, the captured code was a lie. Run first,
# capture rc directly, then branch. (Pinned by
# tests/test_b44_clean_checkout.py::test_verify_head_script_captures_real_rc.)

# ── 1. import integrity (fast, specific shape on ModuleNotFoundError) ──
timeout 300 python3 -m unittest \
  tests.test_b42_tracked_imports \
  tests.test_b44_clean_checkout >> "$LOG" 2>&1
RC=$?

if [ "$RC" -ne 0 ]; then
  echo "$(date -u +%FT%TZ) HEAD=$HEAD VERDICT=BROKEN rc=$RC (import checks)" >> "$LOG"
else
  echo "$(date -u +%FT%TZ) HEAD=$HEAD import-checks OK, running full suite on clean checkout" >> "$LOG"
  # ── 2. the FULL suite inside HEAD itself (b50), stamping the verdict ──
  HERMES_STAMP=1 timeout 900 python3 engines/head_verify.py HEAD > /tmp/hermes_head_verify.json 2>> "$LOG"
  RC=$?
  if [ "$RC" -eq 0 ]; then
    echo "$(date -u +%FT%TZ) HEAD=$HEAD VERDICT=OK rc=0 $(tail -c 200 /tmp/hermes_head_verify.json | tr -d '\n')" >> "$LOG"
  else
    echo "$(date -u +%FT%TZ) HEAD=$HEAD VERDICT=BROKEN rc=$RC (full suite on clean checkout) $(tail -c 200 /tmp/hermes_head_verify.json | tr -d '\n')" >> "$LOG"
  fi
fi

if [ "$RC" -eq 0 ]; then
  exit 0
fi

# Loud: the whole point of b44/b50 is that a broken HEAD must not wait for
# the next cron tick to be noticed.
python3 - "$HEAD" <<'PY' >> "$LOG" 2>&1 || true
import sys
sys.path.insert(0, '/home/ai/hermes-trading')
from env_loader import load_dotenv
load_dotenv('/home/ai/hermes-trading/.env')
from notifier.telegram import send_ops
head = sys.argv[1]
try:
    import json
    detail = json.load(open('/tmp/hermes_head_verify.json')).get('note') or ''
except Exception:
    detail = ''
send_ops(f'⚠️ b44/b50: HEAD {head} FAILS clean-checkout verification'
         + (f' ({detail})' if detail else '')
         + ' — cron/fresh-clone may die. See logs/verify_head.log')
PY
exit 1
