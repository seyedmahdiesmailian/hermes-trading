"""For each of b78's 13 executor-parity legit fires, what did LIVE master.log
actually say at that same cycle minute? Quantifies the replay-vs-live gap."""
import json, re, subprocess, os, sys
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(REPO)
fires = json.load(open('data/backtest/b78_grade_parity_census.json'))
par = [f for f in fires if f['exec_ok']]
# build map "MM-DD HH:MM" -> live log line
log = open('logs/master.log', encoding='utf-8', errors='replace').read()
live = {}
for m in re.finditer(r'\[(2026-(\d\d)-(\d\d) (\d\d):(\d\d):\d\d)\] Step=(\S+) execute=(\S+) action=(\S+)', log):
    key = f"{m.group(2)}-{m.group(3)} {m.group(4)}:{m.group(5)}"
    live[key] = f"step={m.group(6)} execute={m.group(7)} action={m.group(8)}"
hit = miss = absent = 0
for f in par:
    k = f['decision_utc']
    L = live.get(k)
    if L is None:
        absent += 1
        print(f"{k}  replay=FIRE  live=<no cycle line>")
    elif 'market_entry_now' in L:
        hit += 1
        print(f"{k}  replay=FIRE  live={L}  ✅ MATCH")
    else:
        miss += 1
        print(f"{k}  replay=FIRE  live={L}  ❌ DIVERGE")
print(f"\nMATCH={hit} DIVERGE={miss} NOCYCLE={absent} of {len(par)} legit replay fires")
