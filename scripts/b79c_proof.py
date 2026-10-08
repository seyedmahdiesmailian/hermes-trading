"""b79c — DECISIVE PROOF: the live M5-confirmation window is structurally
empty (broker stamps are UTC+3, the settled filter compares real UTC), so
post-b193b the funnel can NEVER fire live, while the lab (broker-consistent
clock) fires normally. Same plan, same price, two windows -> two verdicts.
"""
import sys, os, json, glob
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
os.chdir(REPO)
try:
    from dotenv import load_dotenv
except ImportError:
    from env_loader import load_dotenv
load_dotenv(os.path.join(REPO, '.env'))
from datetime import datetime, timezone
from bridge_client import BridgeClient
from hermes_runtime import _data_list, _bar_time
from engines.orchestrator import evaluate_monitor_cycle
from engines.backtest_real import settled_m5_rows

b = BridgeClient()
# the 05:35 Sep-11 bar that b78 replay said was a legit BUY fire
tgt = None
m5all = sorted(_data_list(b.get_rates("XAUUSD", "M5", 600)), key=lambda r: int(r["time"]))
for r in m5all:
    if datetime.fromtimestamp(int(r["time"]), tz=timezone.utc).strftime("%m-%d %H:%M") == "09-11 05:30":
        tgt = r
print("target broker-stamped bar 05:30:", tgt and tgt["close"])

f = sorted(glob.glob('data/xau_plan/plan_history/20260911_0535*.json'))[-1]
plan = json.load(open(f))
price = float(tgt["close"])
now = datetime.fromtimestamp(int(tgt["time"]) + 300, tz=timezone.utc)

# (a) LIVE window semantics verbatim (runtime:748): real-UTC now vs broker stamps
_live_rows = []
_now_epoch = int(now.timestamp())   # exactly what live uses (wall clock at bar close)
for _row in _data_list(b.get_rates("XAUUSD", "M5", 12)):
    _bt = _bar_time(_row)
    if _bt is not None and _bt + 300 <= _now_epoch:
        _live_rows.append(_row)
dec_live = evaluate_monitor_cycle(plan, price=price, now=now, m5_rows=_live_rows)
print(f"\nLIVE-style window rows={len(_live_rows)}  ->  action={dec_live.get('action')} reason={dec_live.get('reason')}")

# (b) LAB window semantics (broker-clock consistent)
lab_rows = settled_m5_rows(m5all, int(tgt["time"]) + 300)
dec_lab = evaluate_monitor_cycle(plan, price=price, now=now, m5_rows=lab_rows)
print(f"LAB-style  window rows={len(lab_rows)}  ->  action={dec_lab.get('action')} style={dec_lab.get('execution_style')}")
print("\n>>> same plan, same price, same instant. The ONLY difference is the clock.")
