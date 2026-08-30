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

export PYTHONPATH=/home/ai/hermes-trading
NOW=$(date '+%Y-%m-%d %H:%M:%S')
echo "[$NOW] Cron triggered" >> logs/cron.log

# Phase 1: Autonomous trading
python3 /home/ai/hermes-trading/hermes_master.py >> logs/master_cron.log 2>&1
RESULT=$?
if [ $RESULT -eq 0 ]; then
  echo "[$NOW] Phase 1 OK" >> logs/cron.log
else
  echo "[$NOW] Phase 1 FAILED (exit $RESULT)" >> logs/cron.log
fi

# Phase 2: REMOVED 2026-08-29 — signal_daemon.service (systemd, polls every 2s)
# already consumes signals via the same listener_state.json. Running
# signal_monitor.py here too created a getUpdates offset race between the two
# pollers (messages could be eaten by whichever polled first). Manual one-off
# checks are still possible: python3 signal_monitor.py
exit $RESULT
