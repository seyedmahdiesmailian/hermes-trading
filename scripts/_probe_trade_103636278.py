#!/usr/bin/env python3
"""Reconstruct trade #103636278 from raw broker deals + entry plan quality."""
import os, sys, json
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import env_loader
env_loader.load_dotenv(os.path.join(ROOT, ".env"))
from bridge_client import BridgeClient
B = BridgeClient()

deals = B.get_history_deals(days=1)
if isinstance(deals, dict):
    deals = deals.get("deals") or deals.get("data") or []
tgt = [d for d in deals if str(d.get("position_id") or d.get("order")) == "103636278"
       or "103636278" in json.dumps(d)]
print("deals for #103636278:", len(tgt))
tot = 0.0
for d in sorted(tgt, key=lambda x: str(x.get("time", ""))):
    pnl = float(d.get("profit", 0) or 0) + float(d.get("commission", 0) or 0)
    tot += pnl
    print(" ", d.get("time"), d.get("type") or d.get("entry"), d.get("volume"),
          d.get("price"), "profit:", d.get("profit"), "comm:", d.get("commission"))
print("REALIZED TOTAL USD:", round(tot, 2))

tick = B.get_tick()
print("live tick:", json.dumps(tick)[:160])

pf = os.path.join(ROOT, "data/xau_plan/current_plan.json")
p = json.load(open(pf))
print("plan:", {k: p.get(k) for k in ("bias", "quality", "setup_grade", "mode", "created_at", "updated_at")})
print("votes:", p.get("tf_votes") or p.get("votes"))
