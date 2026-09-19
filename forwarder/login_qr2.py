#!/usr/bin/env python3
"""Persistent QR login — keeps ONE QR valid for ~9 minutes (no early rotation).

Previous bug: the loop regenerated the QR every 100s, which INVALIDATED the
token the user was about to scan -> "token expired" in the app. This version
holds one token for its full lifetime and never gives up.
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
STATE = '/tmp/fwd_qr_state.txt'
DEVICE = {'device_model': 'Hermes Forwarder', 'system_version': 'Linux 6.8',
          'app_version': '1.44.0'}
WINDOW = 500  # seconds to keep one token alive before rotating


def log(msg):
    with open(STATE, 'a') as f:
        f.write('%s %s\n' % (time.strftime('%H:%M:%S'), msg))


async def main():
    client = TelegramClient(SESSION, CFG['api_id'], CFG['api_hash'], **DEVICE)
    await client.connect()
    if await client.is_user_authorized():
        me = await client.get_me()
        log('ALREADY_LOGGED_IN @%s' % me.username)
        await client.disconnect()
        return

    qr = QRLogin(client, set())
    while True:
        await qr.recreate()
        qrcode.make(qr.url).save(QR_PNG)
        os.utime(QR_PNG, None)
        log('QR_SAVED fresh token, valid ~%ds' % WINDOW)
        try:
            await qr.wait(timeout=WINDOW)
        except asyncio.TimeoutError:
            log('window ended, rotating token')
            continue
        except SessionPasswordNeededError:
            log('NEED_2FA')
            await client.disconnect()
            return
        except Exception as e:
            log('wait error: %r' % (e,))
            await asyncio.sleep(3)
            continue
        if await client.is_user_authorized():
            me = await client.get_me()
            log('LOGGED_IN @%s id=%s' % (me.username, me.id))
            await client.disconnect()
            return
        log('QR_RESULT_NOT_AUTH %r' % (getattr(qr, '_resp', None),))


asyncio.run(main())
