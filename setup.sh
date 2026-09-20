#!/bin/bash
# Hermes Trading one-shot setup for a fresh Linux server.
# Idempotent — safe to re-run. Full architecture: docs/DEPLOY.md
set -e
BASE_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$BASE_DIR"

echo "═══ HERMES TRADING SETUP ($BASE_DIR) ═══"

# 1. Secrets: .env must come from off-box backup (never from git)
if [ ! -f .env ]; then
  cp .env.example .env
  echo "⚠️ .env created as template — restore real values from backup:"
  echo "   tar -xzf hermes_backup_*.tar.gz -C /tmp; cp /tmp/hermes/.env .env"
  echo "   (see docs/DEPLOY.md step 3). Continuing with DRY_RUN=true is safe."
fi

# 2. Python deps
# Keep project dependencies isolated from the system interpreter. This avoids
# Ubuntu/Debian PEP 668 failures and makes every service use the same runtime.
echo "── python deps"
VENV_DIR="${HERMES_VENV_DIR:-$BASE_DIR/.venv}"
if [ ! -x "$VENV_DIR/bin/python" ]; then
  python3 -m venv "$VENV_DIR" || {
    echo "❌ Cannot create $VENV_DIR — install the python3-venv package first"
    exit 1
  }
fi
PYTHON="$VENV_DIR/bin/python"
"$PYTHON" -m pip install -q -r "$BASE_DIR/requirements.txt"

# 3. Directories + exec bits
mkdir -p logs data/commands data/xau_plan data/trading
chmod +x scripts/*.sh scripts/hermes_cron.sh scripts/bridge_health_monitor.py 2>/dev/null || true

# 4. systemd user services (position + signal daemons + ops dashboard bot)
echo "── systemd user services"
mkdir -p ~/.config/systemd/user
cp ops/systemd/hermes-position.service \
   ops/systemd/hermes-signal.service \
   ops/systemd/hermes-dashboard.service \
   ~/.config/systemd/user/
# Containers and CI often have systemctl installed but no user bus. Do not
# abort dependency setup and verification in that environment; a real Linux
# deployment still reloads/enables the services when the user bus exists.
if systemctl --user daemon-reload 2>/dev/null; then
  systemctl --user enable --now hermes-position hermes-signal hermes-dashboard \
    || echo "⚠️ services failed to start — check journalctl --user"
  loginctl enable-linger "$(id -un)" 2>/dev/null || true
else
  echo "⚠️ user systemd unavailable — service activation skipped"
fi

# 5. crontab (master cycle, health monitor, backup, git sync, autopilot)
if ! command -v crontab >/dev/null 2>&1; then
  echo "⚠️ crontab unavailable — scheduled jobs skipped"
elif crontab -l 2>/dev/null | grep -q "hermes_cron.sh"; then
  echo "── crontab already set (hermes_cron.sh present); not overwriting"
else
  echo "── installing crontab from ops/cron/crontab.root.txt"
  crontab ops/cron/crontab.root.txt
fi

# 6. Tests
# Preserve the test exit code instead of piping through `tail`, which would
# otherwise make a failed suite look successful to setup's `set -e`.
echo "── running test suite"
TEST_LOG="$(mktemp)"
if ! "$PYTHON" -m unittest discover -s tests >"$TEST_LOG" 2>&1; then
  echo "❌ test suite failed — last 80 lines:"
  tail -n 80 "$TEST_LOG"
  rm -f "$TEST_LOG"
  exit 1
fi
tail -1 "$TEST_LOG"
rm -f "$TEST_LOG"

# 7. Connectivity checks (non-fatal)
echo "── bridge"
"$PYTHON" -c "
from bridge_client import BridgeClient
h = BridgeClient().health()
print('✅ bridge ok' if h.get('ok') else '❌ bridge unreachable — Windows VM :5050 (docs/DEPLOY.md step 5)')" 2>/dev/null || echo "❌ bridge unreachable"

echo ""
echo "Setup done. Next: verify with '$PYTHON scripts/verify_chain.py'"
echo "and one manual cycle: 'bash scripts/hermes_cron.sh'"
