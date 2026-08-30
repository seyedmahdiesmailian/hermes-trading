#!/bin/bash
# HERMES TRADING CRON - every 15 minutes
# Phase 1: Autonomous trading cycle
# Phase 2: Signal monitor (Telegram group)
set -u
cd /home/ai/hermes-trading

# Load .env
if [ -f /home/ai/hermes-trading/.env ]; then
  set -a
  # shellcheck disable=SC1091
  source /home/ai/hermes-trading/.env   # was: export $(grep|xargs) — breaks on any spaced value
  set +a
fi

# Log hygiene: cap any log over 5MB by keeping its last 2MB (no logrotate dep;
# master.log grows every 15-min tick forever otherwise)
for f in logs/*.log; do
  sz=$(stat -c%s "$f" 2>/dev/null || echo 0)
  if [ "$sz" -gt 5242880 ]; then
    tail -c 2097152 "$f" > "$f.tmp" && mv "$f.tmp" "$f"
  fi
done

export PYTHONPATH=/home/ai/hermes-trading
NOW=$(date '+%Y-%m-%d %H:%M:%S')
echo "[$NOW] Cron triggered" >> logs/cron.log

# b31: flock — if a previous master cycle is still hung (bridge stall,
# calendar fetch), SKIP this tick instead of running two masters racing on
# cooldown/plan state. timeout 840s = hard ceiling below the 15-min period.
exec 9>/tmp/hermes_master.lock
if ! flock -n 9; then
  echo "[$NOW] Phase 1 SKIPPED (previous cycle still running)" >> logs/cron.log
  exit 0
fi

# Phase 1: Autonomous trading
timeout 840 python3 /home/ai/hermes-trading/hermes_master.py >> logs/master_cron.log 2>&1
RESULT=$?
if [ $RESULT -eq 0 ]; then
  echo "[$NOW] Phase 1 OK" >> logs/cron.log
elif [ $RESULT -eq 124 ]; then
  echo "[$NOW] Phase 1 TIMEOUT (killed at 840s)" >> logs/cron.log
else
  echo "[$NOW] Phase 1 FAILED (exit $RESULT)" >> logs/cron.log
fi

# Phase 2: REMOVED 2026-08-29 — signal_daemon.service (systemd, polls every 2s)
# already consumes signals via the same listener_state.json. Running
# signal_monitor.py here too created a getUpdates offset race between the two
# pollers (messages could be eaten by whichever polled first). Manual one-off
# checks are still possible: python3 signal_monitor.py
exit $RESULT
