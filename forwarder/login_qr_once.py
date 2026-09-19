#!/usr/bin/env python3
"""One-shot fresh QR for Telegram login — run when the user is READY to scan.

Telegram's server-side QR token lives ~60s (the 500s window in login_qr2.py
was the bug: by the time the user scanned, the token was long dead server-
side even though our loop still held it). So: generate on demand, send,
scan within a minute.
"""
import asyncio
import json
import os
import sys
import time

import qrcode
from telethon import TelegramClient

BASE = os.path.dirname(os.path.abspath(__file__))
CFG = json.load(open(os.path.join(BASE, 'config.json')))
SESSION = os.path.join(BASE, 'forwarder_session')
QR_PNG = sys.argv[1] if len(sys.argv) > 1 else '/tmp/fwd_login_qr.png'
DEVICE = {'device_model': 'Hermes Forwarder', 'system_version': 'Linux 6.8',
          'app_version': '1.44.0'}


async def main():
    client = TelegramClient(SESSION, CFG['api_id'], CFG['api_hash'], **DEVICE)
    await client.connect()
    if await client.is_user_authorized():
        me = await client.get_me()
        print('ALREADY_LOGGED_IN @%s id=%s' % (me.username, me.id))
        await client.disconnect()
        return
    from telethon.tl.custom.qrlogin import QRLogin
    qr = QRLogin(client, set())
    await qr.recreate()
    qrcode.make(qr.url).save(QR_PNG)
    print('QR_SAVED %s at %s — scan within ~60s' % (QR_PNG, time.strftime('%H:%M:%S')))
    # hold the process open and poll for the confirmation for 90s
    try:
        await qr.wait(timeout=90)
    except Exception:
        pass
    if await client.is_user_authorized():
        me = await client.get_me()
        print('LOGGED_IN @%s id=%s' % (me.username, me.id))
    else:
        print('NOT_AUTHORIZED after window')
    await client.disconnect()


asyncio.run(main())
