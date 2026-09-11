"""Root-cause the 16:15 divergence: what plan was LIVE evaluating, vs what
b78's fresh-constructed plan said at the same bar?"""
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
from engines.storage import load_runtime_state, load_current_plan
from engines.orchestrator import evaluate_monitor_cycle

# 1) live state right after 16:15 cycle: which plan was active?
d = sorted(glob.glob('data/xau_plan/plan_history/20260910_16*.json'))
print("16:xx plan files:", [x.split('/')[-1] for x in d])
cur = None
for x in d:
    hhmm = os.path.basename(x)[9:15]   # YYYYMMDD_HHMMSS_...
    if hhmm <= '161503':
        cur = x
print("last plan file <= 16:15:", cur)
if cur:
    dd = json.load(open(cur))
    p = dd.get('plan', dd)
    z = p.get('zones') or {}
    ex = p.get('execution') or {}
    print(f"  plan_id={p.get('plan_id')} bias={p.get('bias')} created={p.get('created_at')}")
    print(f"  value_low={z.get('value_low')} value_high={z.get('value_high')}")
    print(f"  long_zone=[{z.get('long_entry_low')},{z.get('long_entry_high')}] short_zone=[{z.get('short_entry_low')},{z.get('short_entry_high')}]")
    print(f"  pullback_trigger={ex.get('pullback_trigger')} breakout_trigger={ex.get('breakout_trigger')}")
    print(f"  regime={(p.get('quality') or {}).get('regime')} align={(p.get('quality') or {}).get('alignment')}")

# what price at 16:15?
from bridge_client import BridgeClient
b = BridgeClient()
m5 = sorted(b.get_rates("XAUUSD", "M5", 600).get("data", []), key=lambda r: int(r["time"]))
tgt = None
for r in m5:
    ts = int(r["time"])
    dt = datetime.fromtimestamp(ts, tz=timezone.utc)
    if dt.strftime("%m-%d %H:%M") == "09-10 16:10":   # bar close 16:15
        tgt = r
if tgt:
    px = float(tgt["close"])
    print(f"\nbars: M5 16:10 close={px}")
    if cur:
        dd = json.load(open(cur)); p = dd.get('plan', dd)
        now = datetime.fromtimestamp(int(tgt['time'])+300, tz=timezone.utc)
        rows = [x for x in m5 if int(x['time']) <= int(tgt['time'])][-12:]
        dec = evaluate_monitor_cycle(p, price=px, now=now, m5_rows=rows)
        print(f"  evaluate(LIVE plan, live price, settled rows) -> {dec.get('action')} reason={dec.get('reason')}")
