#!/usr/bin/env python3
"""Audit: for every executed trade, what was the plan quality behind it?
Answers: would 'mixed alignment = C' have blocked the losers and kept the winners?
"""
import os, sys, json, csv, glob
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# map plan_id -> best quality snapshot from plan_history
plans = {}
for f in sorted(glob.glob('data/xau_plan/plan_history/*.json')):
    p = json.load(open(f))
    pid = p.get('plan_id')
    if pid:
        plans[pid] = p

rows = list(csv.DictReader(open('data/xau_plan/execution_log.csv')))
print('executions logged:', len(rows))
print()
hdr = f"{'when':16} {'side':5} {'lot':5} {'grade':5} {'align':8} {'trend':6} {'regime':22} {'votes'}"
print(hdr)
for r in rows:
    pid = r.get('plan_id')
    p = plans.get(pid) or {}
    q = p.get('quality') or {}
    v = q.get('bias_votes') or {}
    votes = ''.join(
        {'bullish': '▲', 'bearish': '▼', 'neutral': '='}.get(v.get(tf, ''), '?')
        for tf in ('m5', 'm15', 'h1', 'h4'))
    print(f"{r.get('at','')[:16]:16} {r.get('side',''):5} {r.get('lot',''):5} "
          f"{r.get('grade',''):5} {str(q.get('alignment')):8} "
          f"{round(float(q.get('trend_strength') or 0),2):<6} {str(q.get('regime')):22} {votes}")

# now join with journal outcomes
print()
print('── outcomes by alignment label:')
jrows = list(csv.DictReader(open('data/xau_plan/trade_journal.csv')))
by_pos = {}
for j in jrows:
    t = j.get('position_id') or j.get('ticket')
    by_pos.setdefault(t, 0.0)
    by_pos[t] += float(j.get('profit') or 0)
print('journal rows:', len(jrows), 'distinct positions:', len(by_pos))
