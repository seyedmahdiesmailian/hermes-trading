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

# 2. Python deps (single source of truth: requirements.txt)
echo "── python deps"
if [ -f requirements.txt ]; then
  pip3 install -r requirements.txt \
    || echo "⚠️ pip install failed — install manually (docs/DEPLOY.md step 2; see requirements.txt)"
else
  pip3 install requests python-dotenv pywinrm requests-ntlm pandas numpy python-telegram-bot flask waitress \
    || echo "⚠️ pip install failed — install manually (docs/DEPLOY.md step 2)"
fi

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
systemctl --user daemon-reload
systemctl --user enable --now hermes-position hermes-signal hermes-dashboard \
  || echo "⚠️ services failed to start — check: journalctl --user -u hermes-signal"
loginctl enable-linger "$(id -un)" 2>/dev/null || true

# 5. crontab (master cycle, health monitor, backup, git sync, autopilot)
echo "── installing crontab"
if crontab -l 2>/dev/null | grep -q "hermes_cron.sh"; then
  echo "── crontab already set (hermes_cron.sh present); not overwriting"
else
  crontab ops/cron/crontab.root.txt 2>/dev/null \
    || echo "⚠️ could not install crontab — review ops/cron/crontab.root.txt manually"
fi

# 6. Tests
echo "── running test suite"
if command -v pytest >/dev/null 2>&1; then
  python3 -m pytest tests/ -q || echo "⚠️ some tests failed — see output above"
else
  python3 -m unittest discover -s tests 2>/dev/null || echo "⚠️ test discovery failed"
fi

echo "═══ SETUP DONE — verify services: systemctl --user status hermes-signal ═══"
