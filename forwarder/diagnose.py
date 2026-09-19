#!/usr/bin/env python3
"""Read-only diagnosis of the forwarder session. Sends NO code request."""
import asyncio
import json
import os
import sys

from telethon import TelegramClient

BASE = os.path.dirname(os.path.abspath(__file__))
CFG = json.load(open(os.path.join(BASE, 'config.json')))
SESSION = os.path.join(BASE, 'forwarder_session')


async def main():
    print('api_id:', CFG.get('api_id'), '| phone:', str(CFG.get('phone_number'))[-4:].rjust(4, '*'))
    print('device_model:', repr(CFG.get('device_model')), '| app_version:', repr(CFG.get('app_version')),
          '| system_version:', repr(CFG.get('system_version')))
    sess_file = SESSION + '.session'
    print('session file:', sess_file, os.path.getsize(sess_file) if os.path.exists(sess_file) else 'MISSING')
    client = TelegramClient(SESSION, CFG['api_id'], CFG['api_hash'],
                            device_model=CFG.get('device_model', 'Desktop'),
                            system_version=CFG.get('system_version', '10'),
                            app_version=CFG.get('app_version', '4.16.8'))
    await client.connect()
    print('session file:', sess_file, os.path.getsize(sess_file) if os.path.exists(sess_file) else 'MISSING')
    print('is_user_authorized:', await client.is_user_authorized())
    if await client.is_user_authorized():
        me = await client.get_me()
        print('AUTHORIZED as @%s (id=%s)' % (me.username, me.id))
    await client.disconnect()

asyncio.run(main())
