"""b79 — CRITICAL: broker-time vs real-UTC offset probe.

Hypothesis chain from b78: the LIVE runtime compares BAR times (which come
from the MT5 bridge, stamped in BROKER server time) against
datetime.now(timezone.utc) (REAL UTC) in three places:
  1. hermes_runtime m5_confirm_rows filter: `_bt + 300 <= now_epoch`
     -> if broker clock != UTC, the M5 confirmation window is shifted by
        the offset: either stale rows only, or UNSETTLED (forming) rows.
  2. _detect_session uses real UTC hour; the plan zones came from broker-time
     bars (zones don't care, but session/killzone weighting does if the
     funnel later mixes them).
  3. cooldown / expiry logic mixing wall clock with bar clock.
This probe MEASURES the offset and shows which way the m5 window falls.
Read-only.
"""
import sys, os, time
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

b = BridgeClient()
now_utc = datetime.now(timezone.utc)
now_epoch = int(now_utc.timestamp())
rates = b.get_rates("XAUUSD", "M5", 10).get("data", [])
rates = sorted(rates, key=lambda r: int(r["time"]))
print(f"real UTC now : {now_utc.strftime('%Y-%m-%d %H:%M:%S')}  epoch={now_epoch}")
for r in rates[-4:]:
    bt = int(r["time"])
    bar_close = bt + 300
    print(f"  bar open(broker ts) {datetime.fromtimestamp(bt, tz=timezone.utc).strftime('%m-%d %H:%M')}  "
          f"close-tick {datetime.fromtimestamp(bar_close, tz=timezone.utc).strftime('%m-%d %H:%M')}  "
          f"delta_close_minus_now = {(bar_close - now_epoch)/60:+.1f} min  close={r['close']}")
# The freshest *open* bar should have open <= now < open+300 IF broker==UTC.
last_open = int(rates[-1]["time"])
offset_h = (last_open - (now_epoch - (now_epoch % 300))) / 3600
print(f"\nfreshest bar open minus current UTC 5-min bucket: {offset_h:+.2f} h  (0.00 = broker is UTC)")
h1 = sorted(b.get_rates("XAUUSD", "H1", 3).get("data", []), key=lambda r: int(r["time"]))
last_h1 = int(h1[-1]["time"])
bucket = now_epoch - (now_epoch % 3600)
print(f"H1 check: freshest H1 open minus current UTC hour bucket: {(last_h1 - bucket)/3600:+.2f} h")
tick = (b.get_tick("XAUUSD").get("data") or {})
print("tick keys:", {k: tick[k] for k in list(tick)[:8]})
