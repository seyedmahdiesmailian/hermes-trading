#!/usr/bin/env python3
"""Weekly performance report → Telegram.

Runs Friday 22:30 UTC (market closes 22:00 UTC) via system crontab.
Summarizes the last 7 days: closed trades, PnL, win rate, grades,
rejection funnel, learning state, account snapshot. Pure stdlib.
"""
import csv
import json
import os
import sys
import urllib.request
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
try:
    from dotenv import load_dotenv
except ImportError:
    from env_loader import load_dotenv
load_dotenv(ROOT / '.env')

PLAN_DIR = ROOT / 'data' / 'xau_plan'
JOURNAL = PLAN_DIR / 'trade_journal.csv'
EXEC_LOG = PLAN_DIR / 'execution_log.csv'
LEARNING = PLAN_DIR / 'learning_state.json'
# b52: was os.getenv('BRIDGE_URL', ...) — dead name, so the hardcoded default
# silently won even though HERMES_BRIDGE_URL is configured in .env; a bridge
# host change would have left the weekly report pointing at the old IP.
BRIDGE_URL = os.getenv('HERMES_BRIDGE_URL', 'http://192.168.10.51:5050')
BRIDGE_TOKEN = os.getenv('HERMES_BRIDGE_TOKEN', '')


def _bridge_account():
    try:
        req = urllib.request.Request(
            f'{BRIDGE_URL}/api/account',
            headers={'Authorization': f'Bearer {BRIDGE_TOKEN}'})
        with urllib.request.urlopen(req, timeout=8) as r:
            return json.loads(r.read().decode())
    except Exception:
        return None


def main():
    now = datetime.now(timezone.utc)
    week_ago = now - timedelta(days=7)

    # ── closed trades (journal) ──
    trades = []
    if JOURNAL.exists():
        with JOURNAL.open(newline='', encoding='utf-8') as f:
            for row in csv.DictReader(f):
                try:
                    ct = datetime.fromtimestamp(int(row['close_time']), tz=timezone.utc)
                    trades.append({'at': ct, 'pnl': float(row['profit'] or 0),
                                   'side': row.get('side', '?')})
                except (ValueError, KeyError, TypeError):
                    continue
    recent = [t for t in trades if t['at'] >= week_ago]
    n = len(recent)
    pnl = sum(t['pnl'] for t in recent)
    wins = sum(1 for t in recent if t['pnl'] > 0)
    wr = (100.0 * wins / n) if n else 0.0
    best = max((t['pnl'] for t in recent), default=0)
    worst = min((t['pnl'] for t in recent), default=0)

    # ── executions attempted this week (incl. failures) ──
    exec_rows = []
    if EXEC_LOG.exists():
        with EXEC_LOG.open(newline='', encoding='utf-8') as f:
            for row in csv.DictReader(f):
                try:
                    at = datetime.fromisoformat(row['at'])
                except (ValueError, KeyError):
                    continue
                if at.tzinfo is None:
                    at = at.replace(tzinfo=timezone.utc)
                if at >= week_ago:
                    exec_rows.append(row)
    ok_exec = sum(1 for r in exec_rows if str(r.get('result_ok')).lower() == 'true')
    grades = Counter(r.get('grade') or '?' for r in exec_rows)

    # ── learning state ──
    learn = {}
    if LEARNING.exists():
        try:
            learn = json.loads(LEARNING.read_text())
        except Exception:
            pass

    acct = _bridge_account()
    bal = acct.get('balance') if acct and acct.get('ok') else None

    total_pnl = sum(t['pnl'] for t in trades)
    lines = [
        '📊 <b>گزارش هفتگی هرمس</b>',
        f'{(week_ago.strftime("%m/%d"))} → {now.strftime("%m/%d")} (UTC)',
        '',
        f'<b>۷ روز اخیر:</b>',
        f'معامله بسته‌شده: {n} | برد: {wins} ({wr:.0f}%)',
        f'سود/ضرر هفته: {pnl:+.2f} $',
        f'بهترین: {best:+.2f} | بدترین: {worst:+.2f}',
        '',
        f'<b>اجراهای این هفته:</b> {len(exec_rows)} تلاش / {ok_exec} موفق',
        f'گرید اجراها: {", ".join(f"{k}:{v}" for k, v in sorted(grades.items())) or "—"}',
        '',
        f'<b>کل کارنامه:</b> {len(trades)} معامله / {total_pnl:+.2f} $',
    ]
    if learn:
        lines.append('')
        lines.append(
            f'<b>وضعیت یادگیری:</b> min_rr={learn.get("min_rr")} '
            f'min_grade={learn.get("min_grade")} risk_mult={learn.get("risk_mult")}')
    if bal is not None:
        lines.append(f'<b>موجودی حساب:</b> {bal:.2f} $')
    if n == 0:
        lines.append('')
        lines.append('ℹ️ امشب ستاپ معتبر (B+) شکل نگرفت؛ سیستم بیکار نبود — پایش و تحلیل ادامه داشت.')

    msg = '\n'.join(lines)
    if '--test' in sys.argv:
        msg = '🧪 <b>تست گزارش هفتگی</b> (دستی، نه زمان‌بندی‌شده)\n\n' + msg

    token = os.getenv('TELEGRAM_BOT_TOKEN')
    chat = os.getenv('TELEGRAM_CHAT_ID', '194015957')
    if not token:
        print('[TELEGRAM SKIP] no token')
        print(msg)
        return
    data = json.dumps({'chat_id': chat, 'text': msg,
                       'parse_mode': 'HTML', 'disable_web_page_preview': True}).encode()
    req = urllib.request.Request(
        f'https://api.telegram.org/bot{token}/sendMessage',
        data=data, headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            res = json.loads(r.read().decode())
        print('sent:', res.get('ok'))
    except Exception as e:
        print('send failed:', e)
        print(msg)


if __name__ == '__main__':
    main()
