#!/bin/bash
# Hermes Trading — Setup Script
# Run once after cloning/installing the project
set -e

BASE_DIR="/home/ai/hermes-trading"
cd "$BASE_DIR"

echo "═══════════════════════════════════════════"
echo "  HERMES TRADING SETUP"
echo "═══════════════════════════════════════════"

# 1. Create .env if missing
if [ ! -f .env ]; then
  echo "Creating .env from template..."
  cp .env.example .env
  echo "⚠️  Edit .env and set TELEGRAM_BOT_TOKEN"
fi

# 2. Create directories
mkdir -p logs data/commands data/xau_plan data/trading

# 3. Make scripts executable
chmod +x scripts/hermes_cron.sh
chmod +x scripts/bridge_health_monitor.py

# 4. Install cron jobs if not present
if ! crontab -l 2>/dev/null | grep -q "hermes_cron.sh"; then
  echo "Installing cron jobs..."
  (crontab -l 2>/dev/null; cat <<'CRON'
# Hermes Trading — Every 15 minutes
SHELL=/bin/bash
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
*/15 * * * * cd /home/ai/hermes-trading && bash scripts/hermes_cron.sh >> /home/ai/hermes-trading/logs/cron.log 2>&1
*/5 * * * * cd /home/ai/hermes-trading && python3 scripts/bridge_health_monitor.py >> /home/ai/hermes-trading/logs/bridge_health.log 2>&1
CRON
  ) | crontab -
  echo "✅ Cron jobs installed"
else
  echo "✅ Cron jobs already installed"
fi

# 5. Test bridge connectivity
echo ""
echo "Testing bridge connectivity..."
python3 -c "
from bridge_client import BridgeClient
b = BridgeClient()
h = b.health()
if h.get('ok'):
    print('✅ Bridge connected')
    a = b.get_account()
    if isinstance(a, dict) and a.get('ok'):
        print(f'   Account: \${a.get(\"balance\", 0):.2f}')
    t = b.get_tick('XAUUSD')
    if isinstance(t, dict) and t.get('ok'):
        print(f'   XAUUSD: {t.get(\"bid\", 0):.2f}')
else:
    print('❌ Bridge unreachable — check Windows VM at 192.168.10.51:5050')
"

# 6. Test Telegram (if configured)
if grep -q "YOUR_BOT_TOKEN_HERE" .env 2>/dev/null; then
  echo ""
  echo "⚠️  Telegram not configured yet"
  echo "   1. Open Telegram, search @BotFather"
  echo "   2. Send /newbot and follow instructions"
  echo "   3. Copy the token to .env → TELEGRAM_BOT_TOKEN"
  echo "   4. Send a message to your bot, then visit:"
  echo "      https://api.telegram.org/bot<TOKEN>/getUpdates"
  echo "   5. Copy chat.id to .env → TELEGRAM_CHAT_ID"
else
  echo ""
  echo "Testing Telegram..."
  python3 -c "
import os, requests
token = os.getenv('TELEGRAM_BOT_TOKEN', '')
chat_id = os.getenv('TELEGRAM_CHAT_ID', '')
if token and chat_id and token != 'YOUR_BOT_TOKEN_HERE':
    r = requests.post(f'https://api.telegram.org/bot{token}/sendMessage',
                      data={'chat_id': chat_id, 'text': '🤖 Hermes Trading setup complete'}, timeout=10)
    if r.status_code == 200:
        print('✅ Telegram connected')
    else:
        print(f'❌ Telegram error: {r.status_code}')
else:
    print('⚠️  Telegram not configured')
"
fi

echo ""
echo "═══════════════════════════════════════════"
echo "Setup complete!"
echo ""
echo "Quick commands:"
echo "  python3 cli.py status    — Show trading status"
echo "  python3 cli.py report    — Show last report"
echo "  python3 cli.py send '/trade BUY 0.05 4590 4620'"
echo "  python3 cli.py run       — Run a cycle now"
echo "═══════════════════════════════════════════"
