#!/bin/bash
# HERMES TRADING CRON V2 - every 5 minutes
# Autonomous trading cycle with V2 architecture
set -u

# b66: repo root derived from script location
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$REPO_ROOT" || exit 1

# Load .env
if [ -f "$REPO_ROOT/.env" ]; then
  set -a
  # shellcheck disable=SC1091
  source "$REPO_ROOT/.env"
  set +a
fi

# Log hygiene: cap logs over 5MB
for f in logs/*.log; do
  [ -f "$f" ] || continue
  sz=$(stat -c%s "$f" 2>/dev/null || echo 0)
  if [ "$sz" -gt 5242880 ]; then
    tail -c 2097152 "$f" > "$f.tmp" && mv "$f.tmp" "$f"
  fi
done

export PYTHONPATH="$REPO_ROOT"
NOW=$(date '+%Y-%m-%d %H:%M:%S')
echo "[$NOW] V2 Cron triggered" >> logs/cron.log

# Flock: prevent overlapping runs
exec 9>/tmp/hermes_master_v2.lock
if ! flock -n 9; then
  echo "[$NOW] SKIPPED (previous cycle still running)" >> logs/cron.log
  exit 0
fi

# V2: Use cron_master.py instead of hermes_master.py
PYTHON_BIN="${HERMES_PYTHON:-$REPO_ROOT/.venv/bin/python}"
if [[ "$PYTHON_BIN" != */* ]]; then
  PYTHON_BIN="$(command -v "$PYTHON_BIN" 2>/dev/null || true)"
fi

if [ ! -x "$PYTHON_BIN" ]; then
  echo "[$NOW] FAILED: Python not executable: $PYTHON_BIN" >> logs/cron.log
  exit 1
fi

# Run V2 autonomous cycle with 280s timeout
timeout 280 "$PYTHON_BIN" "$REPO_ROOT/entry_points/cron_master.py" >> logs/master_cron.log 2>&1

RESULT=$?
if [ $RESULT -eq 0 ]; then
  echo "[$NOW] V2 Cycle OK" >> logs/cron.log
elif [ $RESULT -eq 124 ]; then
  echo "[$NOW] V2 TIMEOUT (killed at 280s)" >> logs/cron.log
else
  echo "[$NOW] V2 FAILED (exit $RESULT)" >> logs/cron.log
fi

exit $RESULT
