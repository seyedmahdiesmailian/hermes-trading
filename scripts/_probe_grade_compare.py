#!/usr/bin/env python3
"""Compare plan quality: morning winners vs afternoon losing sells."""
import os, sys, json, glob
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

CASES = [
    ('win 04:15', '20260831_0415*'),
    ('win 04:30', '20260831_0430*'),
    ('sell 14:15', '20260831_1415*'),
    ('sell 14:30', '20260831_1430*'),
]
for label, pat in CASES:
    for f in sorted(glob.glob('data/xau_plan/plan_history/' + pat + '_xau-*.json')):
        p = json.load(open(f))
        q = p.get('quality') or {}
        print(label, os.path.basename(f)[9:15],
              '| bias=', p.get('bias'),
              '| align=', q.get('alignment'),
              '| trend=', round(float(q.get('trend_strength') or 0), 2),
              '| regime=', q.get('regime'),
              '| votes=', q.get('bias_votes'),
              '| smc=', q.get('smc_signal'), q.get('smc_confidence'),
              '| grade_inferred=', _g(q) if (_g := None) else '')
        # grade inference inline
        al = q.get('alignment'); tr = float(q.get('trend_strength') or 0); rg = q.get('regime')
        g = 'A' if (al == 'aligned' and tr >= 3.0 and rg in {'breakout_continuation', 'pullback_continuation'}) else ('B' if (al in {'aligned', 'mixed'} and tr >= 1.2) else 'C')
        print('     → grade =', g, '| mode=', p.get('execution_mode'), '| id=', p.get('plan_id'))
