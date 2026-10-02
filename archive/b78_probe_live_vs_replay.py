"""b78 probe: why did live say wait_for_pullback at 05:35 when b78 replay fired?"""
import sys, json, glob
import os
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
os.chdir(REPO)

f = sorted(glob.glob('data/xau_plan/plan_history/20260911_053*.json'))
print("files:", [x.split('/')[-1] for x in f])
d = json.load(open(f[-1]))
p = d.get('plan', d)
z = p.get('zones') or {}
ex = p.get('execution') or {}
print(f"LIVE {f[-1].split('_')[-1][:6]}: bias={p.get('bias')} created={p.get('created_at')}")
print("  zones:", json.dumps(z))
print("  triggers: pullback=", ex.get('pullback_trigger'), "breakout=", ex.get('breakout_trigger'))
print("  price m5_last:", (p.get('context') or {}).get('m5_last'))
print("  keys of file:", list(d.keys()))
print("  m5_rows present:", 'm5_rows' in d, type(d.get('m5_rows')))
