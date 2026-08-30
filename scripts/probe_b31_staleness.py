"""b31 probe 2 (read-only): age of macro.calendar at plan creation +
runtime_state management pruning check."""
import json, glob
from datetime import datetime, timezone

ages = []
for f in sorted(glob.glob('/home/ai/hermes-trading/data/xau_plan/plan_history/*.json'))[-80:]:
    try:
        p = json.load(open(f))
    except Exception:
        continue
    cal = ((p.get('context') or {}).get('macro') or {}).get('calendar') or {}
    fa, ca = cal.get('fetched_at'), p.get('created_at')
    if fa and ca:
        try:
            a = (datetime.fromisoformat(ca) - datetime.fromisoformat(fa)).total_seconds() / 60
            ages.append(a)
        except Exception:
            pass
ages.sort()
if ages:
    print(f'calendar age at plan-creation: n={len(ages)} median={ages[len(ages)//2]:.0f}min max={ages[-1]:.0f}min')
else:
    print('no paired timestamps')

# runtime_state management keys vs live tickets
rt = json.load(open('/home/ai/hermes-trading/data/xau_plan/runtime_state.json'))
print('runtime management entries:', len(rt.get('management') or {}))

# compute_performance_state day-rollover behaviour
from engines.risk import compute_performance_state
stale = {'day': '2020-01-01', 'daily_pnl': -500.0, 'trades_today': 5,
         'loss_streak': 3, 'recent_closed': []}
out = compute_performance_state(stale, '2026-08-30', 5000.0, [])
print('stale-day rebase ->', {k: out[k] for k in ('day', 'daily_pnl', 'trades_today')})
