"""b67 probe 2 (READ-ONLY, dry_run=True, no network): the MIXED-FAILURE case.

positions reply = HEALTHY (real open SELL), tick reply = DEAD (401/MT5 error).
Does the runtime's fallback management path issue a close action?
"""
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

_tmp = Path(tempfile.mkdtemp(prefix="b67probe2_"))
import engines.paths as paths  # noqa: E402
paths.set_data_root(_tmp / "data")
import engines.kill_switch as ks  # noqa: E402
ks._load_state = lambda: {"halted": False, "halt_reason": None, "halted_at": None,
                          "resumes_at": None, "consecutive_losses": 0}
ks._save_state = lambda s: None

import hermes_runtime as hr  # noqa: E402
import engines.bridge_payload as bp  # noqa: E402

TICK_401 = {"ok": False, "error": "HTTP_401", "data": {"raw": "<html>401</html>"}}
TICK_500 = {"ok": False, "error": "['Common::LastError']", "data": {"raw": "no mt5"}}

now = datetime.now(timezone.utc)
open_sell = [{"ticket": 99001, "type": "SELL", "symbol": "XAUUSD",
              "volume": 0.02, "price_open": 4450.0, "sl": 4460.0, "tp": 4400.0,
              "profit": 0.0, "time": int(now.timestamp())}]

plan = {
    "plan_id": "b67probe", "symbol": "XAUUSD", "bias": "bearish",
    "session": "london",
    "zones": {"short_entry_low": 4440.0, "short_entry_high": 4460.0,
              "long_entry_low": None, "long_entry_high": None},
    "atr": 8.0, "invalidation": 4460.0, "targets": [4400.0, 4350.0],
    "execution": {"tp_levels": [4400, 4350, 4300], "tp_shares": [0.5, 0.3, 0.2]},
    "quality": {"regime": "normal", "trend_strength": 2.0, "alignment": "aligned",
                "grade": "A"},
    "created_at": (now - timedelta(minutes=2)).isoformat(),
    "expires_at": (now + timedelta(hours=4)).isoformat(),
    "next_reassessment": (now + timedelta(hours=1)).isoformat(),
    "context": {},
}
hr.save_current_plan(hr._plan_dir(), plan)


class MixedBridge:
    def __init__(self, tick):
        self.tick = tick

    def get_account(self):
        return {"ok": True, "balance": 4982.77, "equity": 4990.0,
                "margin": 100.0, "margin_free": 4890.0, "login": 10382667}

    def get_tick(self, symbol="XAUUSD"):
        return self.tick

    def get_positions(self, symbol="XAUUSD"):
        return {"ok": True, "data": [dict(p) for p in open_sell], "count": 1}

    def get_history_deals(self, symbol="XAUUSD", days=7):
        return {"ok": True, "data": [], "count": 0}

    def get_rates(self, symbol="XAUUSD", timeframe="M15", count=80):
        return {"ok": True, "data": [], "count": 0}


for name, tick in (("401-html", TICK_401), ("500-mt5", TICK_500)):
    res = hr.cycle(MixedBridge(tick), now=now, dry_run=True)
    print(f"--- tick={name} (positions healthy, dry_run=True) ---")
    print("  step        :", res.get("step"))
    print("  ok          :", res.get("ok"), "| error:", res.get("error"))
    mg = res.get("management") or res.get("management_actions") or []
    print("  management  :", str(mg)[:400])
    for k in ("executed_actions", "actions", "position_actions"):
        if k in res:
            print(f"  {k}: {str(res[k])[:300]}")
    print("  keys        :", sorted(res.keys()))
