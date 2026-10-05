"""Why are signals hitting account_locked:locked? Reproduce the exact
policy vote the live signal path computes, per signal record.

Known quirk: the bridge does not return margin (returns 0), so
margin_ratio is 999 and margin_health cannot be the cause. That leaves
drawdown_limit: drawdown_pct >= 0.05 or daily_pnl <= -3% of balance.
"""
import sys, json
sys.path.insert(0, '.'); sys.path.insert(0, 'engines')
from env_loader import load_dotenv
load_dotenv('.env')
from engines import paths
from engines.risk import assess_account_policy

recs = paths.read_json_safe(paths.signals_log(), [], label="signals_log") or []
locked = []
for r in recs:
    d = r.get("decision") or {}
    rs = d.get("reasons") or []
    if any(str(x).startswith("account_locked") for x in rs):
        snap = r.get("decision", {}).get("account_snapshot") or {}
        # pull the snapshot attached at decision time if present
        locked.append({"ts": r.get("timestamp"), "snap": snap, "score": d.get("score")})

print("account_locked records:", len(locked))
if locked:
    print("sample:", json.dumps(locked[0], ensure_ascii=False, indent=1)[:900])
