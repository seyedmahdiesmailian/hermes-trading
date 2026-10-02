"""b67 probe 4: why did the mixed-failure cycle route to 'halted'?
Print the kill switch + policy the cycle actually computed."""
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
_tmp = Path(tempfile.mkdtemp(prefix="b67probe4_"))
import engines.paths as paths  # noqa: E402
paths.set_data_root(_tmp / "data")

import hermes_runtime as hr  # noqa: E402

now = datetime.now(timezone.utc)
TICK_401 = {"ok": False, "error": "HTTP_401", "data": {"raw": "<html>401</html>"}}
open_sell = [{"ticket": 99001, "type": "SELL", "symbol": "XAUUSD",
              "volume": 0.02, "price_open": 4450.0, "sl": 4460.0, "tp": 4400.0,
              "profit": 0.0, "time": int(now.timestamp())}]


class MixedBridge:
    def get_account(self):
        return {"ok": True, "balance": 4982.77, "equity": 4990.0,
                "margin": 100.0, "margin_free": 4890.0, "login": 10382667}

    def get_tick(self, symbol="XAUUSD"):
        return TICK_401

    def get_positions(self, symbol="XAUUSD"):
        return {"ok": True, "data": [dict(p) for p in open_sell], "count": 1}

    def get_history_deals(self, symbol="XAUUSD", days=7):
        return {"ok": True, "data": [], "count": 0}

    def get_rates(self, symbol="XAUUSD", timeframe="M15", count=80):
        return {"ok": True, "data": [], "count": 0}


b = MixedBridge()
acct = b.get_account()
pol = hr._performance_and_policy(b, acct, now)
print("policy:", {k: pol["account_policy"].get(k) for k in
                  ("balance", "equity", "margin", "margin_free", "open_positions",
                   "regime", "trade_allowed", "reasons")})
print("perf  :", {k: pol["performance_state"].get(k) for k in
                  ("day", "daily_pnl", "loss_streak", "trades_today")})
from engines.kill_switch import check_kill_switch
p = pol["account_policy"]; pf = pol["performance_state"]
print("kill  :", check_kill_switch(
    balance=p.get("balance", 0), equity=p.get("equity", 0),
    daily_pnl=float(pf.get("daily_pnl", 0) or 0),
    consecutive_losses=int(pf.get("loss_streak", 0) or 0),
    margin_free=p.get("margin_free", 0), margin=p.get("margin", 0), now=now))
print("tick_price:", hr._tick_price(b.get_tick()), "| positions:",
      len(hr._positions_list(b.get_positions())))
