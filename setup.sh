#!/bin/bash
# Hermes Trading — one-shot setup on a fresh Linux server.
# Idempotent: safe to re-run. Full architecture: docs/DEPLOY.md
set -e
BASE_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$BASE_DIR"

echo "═══ HERMES TRADING SETUP ($BASE_DIR) ═══"

# 1. Secrets: .env must come from the off-box backup (never from git)
if [ ! -f .env ]; then
  cp .env.example .env
  echo "⚠️  .env created from template — restore real values from backup:"
  echo "   tar -xzf hermes_backup_*.tar.gz -C /tmp '*/.env' && cp /tmp/.../.env .env"
  echo "   (see docs/DEPLOY.md step 3). Continuing with DRY_RUN=true is safe."
fi

# 2. Python deps
echo "── python deps"
pip3 install -q requests python-dotenv pywinrm requests_ntlm pandas numpy python-telegram-bot 2>/dev/null || \
  echo "⚠️  pip install failed — install deps manually (docs/DEPLOY.md step 2)"

# 3. Directories + exec bits
mkdir -p logs data/commands data/xau_plan data/trading
chmod +x scripts/*.sh scripts/hermes_cron.sh scripts/bridge_health_monitor.py 2>/dev/null || true

# 4. systemd user services (position + signal daemons)
echo "── systemd user services"
mkdir -p ~/.config/systemd/user
cp ops/systemd/hermes-position.service ops/systemd/hermes-signal.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now hermes-position hermes-signal || echo "⚠️  services failed to start — check journalctl --user"
loginctl enable-linger "$(id -un)" 2>/dev/null || true

# 5. crontab (master cycle, health monitor, backup, git sync, autopilot)
if ! crontab -l 2>/dev/null | grep -q "hermes_cron.sh"; then
  echo "── installing crontab from ops/cron/crontab.backup.txt"
  crontab ops/cron/crontab.backup.txt
else
  echo "── crontab already installed"
fi

# 6. Tests
echo "── running test suite"
python3 -m unittest discover -s tests 2>&1 | tail -1

# 7. Connectivity checks (non-fatal)
echo "── bridge"
python3 -c "
from bridge_client import BridgeClient
h = BridgeClient().health()
print('✅ bridge ok' if h.get('ok') else '❌ bridge unreachable — Windows VM :5050 (docs/DEPLOY.md step 5)')" 2>/dev/null || echo "❌ bridge unreachable"

echo ""
echo "Setup done. Next: verify with 'python3 scripts/verify_chain.py'"
echo "and one manual cycle: 'bash scripts/hermes_cron.sh'"
