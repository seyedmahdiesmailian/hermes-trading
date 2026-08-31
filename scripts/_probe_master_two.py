#!/usr/bin/env python3
"""Master log + telegram reports for the two sells at 14:15/14:30 UTC."""
import os, sys, subprocess
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

print('── master.log 14:0x-14:4x:')
out = subprocess.run(['grep', '-hE', '2026-08-31T14:[0-4]', 'logs/master.log'],
                     capture_output=True, text=True).stdout
lines = out.splitlines()
print('matched:', len(lines))
for l in lines[:60]:
    print(l[:250])

print('── telegram messages about these trades:')
out2 = subprocess.run(['grep', '-hE', '98367013|98368015|98371735|4427.7|4420.1',
                       'logs/telegram_messages.log'], capture_output=True, text=True).stdout
for l in out2.splitlines()[:40]:
    print(l[:300])
