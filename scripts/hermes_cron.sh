#!/bin/bash
# HERMES TRADING CRON - every 15 minutes
# Phase 1: Autonomous trading cycle
# Phase 2: Signal monitor (Telegram group)
set -u
# b66: the repo root is DERIVED from this script's own location, never
# hardcoded. A literal /home/ai/hermes-trading here meant a relocated repo
# (or a second checkout) silently ran the cron of the OLD tree while
# reporting success — the b46/b48 disease from the filesystem side. The ONLY
# place the install path may live is the bootstrap layer (crontab/systemd),
# which is where the OS learns about the repo in the first place.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$REPO_ROOT" || exit 1

# Load .env
if [ -f "$REPO_ROOT/.env" ]; then
  set -a
  # shellcheck disable=SC1091
  source "$REPO_ROOT/.env"   # was: export $(grep|xargs) — breaks on any spaced value
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

export PYTHONPATH="$REPO_ROOT"
NOW=$(date '+%Y-%m-%d %H:%M:%S')
echo "[$NOW] Cron triggered" >> logs/cron.log

# b31: flock — if a previous master cycle is still hung (bridge stall,
# calendar fetch), SKIP this tick instead of running two masters racing on
# cooldown/plan state.
#
# b216: the ceiling was 840s, chosen as "just under the 15-min period". The
# live crontab (ops/cron/crontab.root.txt, pulled off the running box) fires
# this script every 5 MINUTES, so 840s was nearly 3 periods long: one stuck
# cycle could hold the lock across two further ticks, and every skipped tick
# is a plan refresh and an entry opportunity that silently never happened.
# flock keeps that safe (no double-run) but silent — the ceiling must be
# under the period so a wedged cycle is killed before the next one is due.
# 280s leaves 20s of headroom inside the 300s period.
exec 9>/tmp/hermes_master.lock
if ! flock -n 9; then
  echo "[$NOW] Phase 1 SKIPPED (previous cycle still running)" >> logs/cron.log
  exit 0
fi

# Phase 1: Autonomous trading
timeout 280 python3 "$REPO_ROOT/hermes_master.py" >> logs/master_cron.log 2>&1
RESULT=$?
if [ $RESULT -eq 0 ]; then
  echo "[$NOW] Phase 1 OK" >> logs/cron.log
elif [ $RESULT -eq 124 ]; then
  echo "[$NOW] Phase 1 TIMEOUT (killed at 280s)" >> logs/cron.log
else
  echo "[$NOW] Phase 1 FAILED (exit $RESULT)" >> logs/cron.log
fi

# Phase 2: REMOVED 2026-08-29 — signal_daemon.service (systemd, polls every 2s)
# already consumes signals via the same listener_state.json. Running
# signal_monitor.py here too created a getUpdates offset race between the two
# pollers (messages could be eaten by whichever polled first). Manual one-off
# checks are still possible: python3 signal_monitor.py
exit $RESULT
