"""b31 probe (read-only): does evaluate_news_lock ever fire with the calendar
shape production actually writes?  No bridge calls, no state writes."""
import os, sys
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
from datetime import datetime, timedelta, timezone
from engines.legacy_guards import evaluate_news_lock

now = datetime.now(timezone.utc)
ev = {'title': 'FOMC Rate Decision', 'currency': 'USD', 'impact': 'high',
      'date': (now + timedelta(minutes=10)).isoformat()}

# shape A: exactly what get_upcoming_events() returns and macro_snap['calendar'] stores
calA = {'source': 'forexfactory', 'high_impact': [ev], 'medium_impact': [],
        'total_events': 110, 'fetched_at': now.isoformat()}
# shape B: raw calendar dict with 'events' (what evaluate_macro_filter consumes)
calB = {'source': 'forexfactory', 'events': [ev]}

trade = {'side': 'SELL', 'entry_price': 4450, 'sl': 4460, 'atr': 5}
print('FOMC in 10min, shape A (PRODUCTION):', evaluate_news_lock(trade, 4450, calA, now))
print('FOMC in 10min, shape B (raw events):', evaluate_news_lock(trade, 4450, calB, now))

# Also: what does the live plan_history actually contain in macro.calendar?
import json, glob
files = sorted(glob.glob(os.path.join(_ROOT, 'data/xau_plan/plan_history/*.json')))
n_cal = n_hi = 0
sample = None
for f in files[-60:]:
    try:
        p = json.load(open(f))
    except Exception:
        continue
    cal = ((p.get('context') or {}).get('macro') or {}).get('calendar')
    if cal:
        n_cal += 1
        if cal.get('high_impact'):
            n_hi += 1
            if sample is None:
                sample = cal['high_impact'][0]
print(f'last 60 archived plans: macro.calendar present={n_cal}, with high_impact events={n_hi}')
print('sample high_impact event keys:', list(sample.keys()) if sample else None)
