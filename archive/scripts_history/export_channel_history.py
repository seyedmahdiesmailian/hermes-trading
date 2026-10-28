"""Export RADIN channel history to JSONL for offline signal replay.

Reads a COPY of the forwarder's Telethon session so the live forwarding
service is never touched. Walks messages backwards from now to --days,
storing text + date + sender so the parser can be replayed offline.

Usage:
  /home/ai/tgenv/bin/python scripts/export_channel_history.py \
      --entity -1003417665507 --days 90 --out data/radin/history.jsonl
"""
import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
try:
    from dotenv import load_dotenv
except ImportError:
    from env_loader import load_dotenv
load_dotenv(os.path.join(_ROOT, '.env'))

from telethon import TelegramClient
import telethon.sync  # noqa: F401  patches TelegramClient with blocking variants
from telethon.errors import SessionPasswordNeededError

FWD_DIR = '/home/ai/projects/forwarder-telegram-dockerized'


def creds():
    cfg = json.load(open(os.path.join(FWD_DIR, 'config.json')))
    return int(cfg['api_id']), cfg['api_hash']


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--entity', required=True)
    ap.add_argument('--days', type=int, default=90)
    ap.add_argument('--session', default='/home/ai/radin_hist')
    ap.add_argument('--out', default=os.path.join(_ROOT, 'data', 'radin', 'history.jsonl'))
    ap.add_argument('--limit', type=int, default=0)
    args = ap.parse_args()

    api_id, api_hash = creds()
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    since = datetime.now(timezone.utc) - timedelta(days=args.days)

    client = TelegramClient(args.session, api_id, api_hash)
    client.connect()
    if not client.is_user_authorized():
        print('NOT_AUTHORIZED — session copy is not logged in', file=sys.stderr)
        sys.exit(2)

    entity = int(args.entity)
    n = 0
    kept = 0
    with open(args.out, 'w', encoding='utf-8') as fh:
        for msg in client.iter_messages(entity):
            n += 1
            dt = msg.date
            if dt is None or dt < since:
                break
            text = msg.message or ''
            if not text.strip():
                continue
            rec = {
                'id': msg.id,
                'date': dt.isoformat(),
                'text': text,
                'sender': getattr(msg, 'sender_login_name', None) or (
                    msg.sender.username if msg.sender else None),
                'fwd_from': (msg.forward.chat.title
                             if getattr(msg, 'forward', None) and
                             getattr(msg.forward, 'chat', None) else None),
                'media': type(msg.media).__name__ if msg.media else None,
            }
            fh.write(json.dumps(rec, ensure_ascii=False) + '\n')
            kept += 1
            if args.limit and kept >= args.limit:
                break
    print(f'scanned={n} kept={kept} out={args.out}')


if __name__ == '__main__':
    main()
