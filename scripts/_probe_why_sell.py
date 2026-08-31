#!/usr/bin/env python3
"""Why did Hermes sell twice at 14:15/14:30 UTC? Plans + daemon timeline."""
import os, sys, json, glob, subprocess
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

print('── daemon uptime:')
print(subprocess.run(['systemctl', '--user', 'show', 'hermes-position',
                      '-p', 'ActiveEnterTimestamp', '--value'],
                     capture_output=True, text=True).stdout.strip())

print('── plans 13:30-14:45 UTC:')
for f in sorted(glob.glob('data/xau_plan/plan_history/20260831_1[34]*.json')):
    hh = os.path.basename(f)[9:15]
    if hh < '133000':
        continue
    p = json.load(open(f))
    q = p.get('quality') or {}
    bp = p.get('blueprint') or {}
    print('  ', hh, 'bias=', p.get('bias'), 'grade=', q.get('grade'),
          'mode=', p.get('execution_mode'), 'id=', p.get('plan_id'),
          'zones=', json.dumps(bp.get('entry_zones') or bp.get('zones') or {},
                                ensure_ascii=False)[:160])

print('── daemon log 14:1x-14:4x:')
out = subprocess.run(['grep', '-hE', 'T14:(1[0-9]|2[0-9]|3[0-9]|4[0-9])',
                      'logs/position_daemon.log'], capture_output=True, text=True).stdout
lines = out.splitlines()
print('matched:', len(lines))
for l in lines[-70:]:
    print(l[:230])
