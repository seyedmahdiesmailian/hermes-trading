#!/usr/bin/env python3
"""Why did the engine sell at 14:15 & 14:30 UTC into a rising market?"""
import os, sys, json, subprocess
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

for pid in ('xau-c278a8c5', 'xau-7fae336d'):
    print('════════', pid)
    for f in sorted(glob_g := [__import__('glob').glob(f'data/xau_plan/plan_history/*{pid}*.json')][0]):
        p = json.load(open(f))
        print('── file:', os.path.basename(f))
        for k in ('bias', 'execution_mode', 'action', 'reason', 'session', 'atr'):
            print('   ', k, '=', p.get(k))
        q = p.get('quality') or {}
        print('    quality:', json.dumps(q, ensure_ascii=False)[:400])
        bp = p.get('blueprint') or {}
        print('    blueprint keys:', list(bp))
        print('    blueprint:', json.dumps(bp, ensure_ascii=False)[:900])
        break

print('════════ daemon log 14:15-14:40 UTC:')
out = subprocess.run(['grep', '-hE', '2026-08-31 17:(1[5-9]|2[0-9]|3[0-9])',
                      'logs/position_daemon.log'], capture_output=True, text=True).stdout
print(out[:4000])
