#!/usr/bin/env python3
"""Timeline around the two 14:15/14:30 UTC sells."""
import os, sys, subprocess
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

print('── daemon uptime:')
print(subprocess.run(['systemctl', '--user', 'show', 'hermes-position',
                      '-p', 'ActiveEnterTimestamp', '--value'],
                     capture_output=True, text=True).stdout.strip())

print('── position_daemon.log 14:1x-14:4x:')
out = subprocess.run(['grep', '-nE', '2026-08-31T14:(1[0-9]|2[0-9]|3[0-9]|4[0-9])',
                      'logs/position_daemon.log'], capture_output=True, text=True).stdout
lines = out.splitlines()
print('matched:', len(lines))
for l in lines[:80]:
    print(l[:240])
