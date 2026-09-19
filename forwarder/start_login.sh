#!/usr/bin/env bash
# Start one clean Telegram login attempt for the forwarder (waits 15m for code).
cd "$(dirname "$0")" || exit 1
rm -f /tmp/fwd_code.txt /tmp/fwd_login.log
nohup .venv/bin/python login_wait.py > /tmp/fwd_login.log 2>&1 &
sleep 6
cat /tmp/fwd_login.log
