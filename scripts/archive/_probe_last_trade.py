#!/usr/bin/env python3
"""Live check of the most recent trade: entry, plan quality, management, PnL."""
import os, sys, json, subprocess
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import env_loader
env_loader.load_dotenv(os.path.join(ROOT, ".env"))
from bridge_client import BridgeClient

B = BridgeClient()
print("now UTC:", subprocess.check_output(["date", "-u", "+%F %T"]).decode().strip())

pos = B.get_positions()
if isinstance(pos, dict):
    pos = pos.get("positions") or pos.get("data") or []
print("open positions:", len(pos))
for p in pos:
    keys = ("ticket", "type", "volume", "price_open", "sl", "tp", "profit", "time")
    print("  ", {k: p.get(k) for k in keys if isinstance(p, dict)})

acc = B.get_account()
if isinstance(acc, dict):
    print("account:", {k: acc.get(k) for k in ("balance", "equity") if k in acc})

print("════ journal tail:")
try:
    with open(os.path.join(ROOT, "data/xau_plan/trade_journal.csv")) as f:
        lines = f.read().strip().splitlines()
    for l in lines[-4:]:
        print(l[:220])
except Exception as e:
    print("journal err", e)

print("════ master log recent trade lines:")
out = subprocess.run(["tail", "-500", os.path.join(ROOT, "logs/master.log")],
                     capture_output=True, text=True).stdout.splitlines()
for l in out:
    low = l.lower()
    if any(k in low for k in ("entry", "exec", "mgmt", "reject", "trade", "buy", "sell", "grade")):
        print(l[:200])
