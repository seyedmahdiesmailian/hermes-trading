#!/usr/bin/env python3
"""QR login for the forwarder — NO SMS codes, NO failed-login attempts.

Uses Telethon's built-in QRLogin: we present a tg://login?token=... QR, the
user scans it with an ALREADY-logged-in official Telegram app (Settings ->
Devices -> Link Desktop Device), and the session authorizes on the spot.
Nothing touches the account unless the user physically scans.
"""
import asyncio
import json
import os
import time

import qrcode
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError
from telethon.tl.custom.qrlogin import QRLogin

BASE = os.path.dirname(os.path.abspath(__file__))
CFG = json.load(open(os.path.join(BASE, 'config.json')))
SESSION = os.path.join(BASE, 'forwarder_session')
QR_PNG = '/tmp/fwd_login_qr.png'
DEVICE = {'device_model': 'Hermes Forwarder', 'system_version': 'Linux 6.8',
          'app_version': '1.44.0'}


async def main():
    client = TelegramClient(SESSION, CFG['api_id'], CFG['api_hash'], **DEVICE)
    await client.connect()
    if await client.is_user_authorized():
        me = await client.get_me()
        print('ALREADY_LOGGED_IN @%s id=%s' % (me.username, me.id), flush=True)
        await client.disconnect()
        return

    qr = QRLogin(client, set())
    deadline = time.time() + 600
    while time.time() < deadline:
        await qr.recreate()
        qrcode.make(qr.url).save(QR_PNG)
        print('QR_SAVED %s' % time.strftime('%H:%M:%S'), flush=True)
        try:
            await qr.wait(timeout=100)
        except asyncio.TimeoutError:
            print('QR_EXPIRED, regenerating', flush=True)
            continue
        except SessionPasswordNeededError:
            print('NEED_2FA', flush=True)
            await client.disconnect()
            return
        if await client.is_user_authorized():
            me = await client.get_me()
            print('LOGGED_IN @%s id=%s' % (me.username, me.id), flush=True)
        else:
            print('QR_RESULT_NOT_AUTH %s' % (getattr(qr, '_resp', None),), flush=True)
            await client.disconnect()
            return
        await client.disconnect()
        return
    print('GAVE_UP', flush=True)
    await client.disconnect()


asyncio.run(main())
