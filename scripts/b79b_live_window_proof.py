"""THE ROOT-CAUSE PROOF: replicate hermes_runtime.py:748-752 verbatim and
show m5_confirm_rows is ALWAYS empty because bar timestamps are broker-time
(+3h) while the settled filter compares against REAL UTC wall clock.
"""
import sys, os
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

bridge = BridgeClient()
now = datetime.now(timezone.utc)
_now_epoch = int(now.timestamp())

# ── verbatim from hermes_runtime lines 744-752 ──
m5_confirm_rows = []
for _row in _data_list(bridge.get_rates("XAUUSD", "M5", 12)):
    _bt = _bar_time(_row)
    if _bt is not None and _bt + 300 <= _now_epoch:
        m5_confirm_rows.append(_row)
print(f"real UTC now           : {now.strftime('%H:%M:%S')}Z  epoch={_now_epoch}")
print(f"rows fetched           : {len(_data_list(bridge.get_rates('XAUUSD','M5',12)))}")
print(f"m5_confirm_rows (LIVE) : {len(m5_confirm_rows)}   <-- the M5 gate sees THIS")
rows = _data_list(bridge.get_rates("XAUUSD", "M5", 12))
for r in rows[-3:]:
    bt = _bar_time(r)
    print(f"  bar ts {datetime.fromtimestamp(bt, tz=timezone.utc).strftime('%H:%M')}Z-stamped  "
          f"needs close<=now: {bt}+300={bt+300} vs {_now_epoch} -> {bt+300 <= _now_epoch}")
# what the lab uses instead (broker-consistent): decision = bar_open+300 in BROKER epoch
from engines.backtest_real import settled_m5_rows
lab = settled_m5_rows(rows, int(_bar_time(rows[-1])) + 300)
print(f"\nlab path (settled_m5_rows, broker-clock consistent): {len(lab)} rows")
