"""Bridge smoke test — read-only (docs/DEPLOY.md step 5).

b64: was a hand-rolled urllib call with the bridge host hardcoded as
a literal URL and NO env read at all. That is the exact shape
the b63 audit found in the health watchdog: this file is the command an
operator runs to verify a FRESH server, so a hardcoded host means the smoke
test keeps poking the OLD box after a relocation and reports a healthy
bridge that the trading path is not even talking to. Now it resolves through
bridge_client → engines.config — the ONE canonical resolver
(HERMES_BRIDGE_URL > derived from HERMES_WIN_IP > last-known default) — so
it can never disagree with the trading path.
Read-only endpoints only (account/tick/positions/deals).
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
try:
    from dotenv import load_dotenv
except ImportError:
    from env_loader import load_dotenv  # python-dotenv missing → local fallback
load_dotenv(Path(__file__).resolve().parent.parent / '.env')

from bridge_client import BridgeClient, BRIDGE_URL  # noqa: E402

c = BridgeClient()  # token from HERMES_BRIDGE_TOKEN in the loaded env
print("bridge:", BRIDGE_URL)
h = c.health()
print("health:", "OK" if h.get("ok") else f"BAD {json.dumps(h, ensure_ascii=False)[:200]}")
acc = c.get_account()
tick = c.get_tick("XAUUSD")
pos = c.get_positions("XAUUSD")
print("balance:", acc.get("balance"), "| equity:", acc.get("equity"))
print("tick:", tick.get("bid"), tick.get("ask"))
print("open positions:", len(pos.get("data", pos.get("positions", []))))
if not (h.get("ok") and isinstance(acc, dict) and acc.get("balance") is not None):
    sys.exit(1)
