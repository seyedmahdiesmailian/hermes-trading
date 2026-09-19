#!/usr/bin/env python3
"""Login that waits for the code file /tmp/fwd_code.txt (written by the agent)."""
import asyncio
import json
import os
import time

from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError

BASE = os.path.dirname(os.path.abspath(__file__))
CFG = json.load(open(os.path.join(BASE, 'config.json')))
CODE_FILE = '/tmp/fwd_code.txt'
SESSION = os.path.join(BASE, 'forwarder_session')


async def main():
    if os.path.exists(CODE_FILE):
        os.remove(CODE_FILE)
    client = TelegramClient(SESSION, CFG['api_id'], CFG['api_hash'])
    await client.connect()
    if await client.is_user_authorized():
        me = await client.get_me()
        print('ALREADY_LOGGED_IN @%s' % me.username, flush=True)
        await client.disconnect()
        return
    req = await client.send_code_request(CFG['phone_number'])
    print('CODE_SENT at %s' % time.strftime('%H:%M:%S'), flush=True)
    deadline = time.time() + 900
    while time.time() < deadline:
        if os.path.exists(CODE_FILE):
            code = open(CODE_FILE).read().strip()
            os.remove(CODE_FILE)
            if not code:
                continue
            try:
                await client.sign_in(phone=CFG['phone_number'], code=code,
                                     phone_code_hash=req.phone_code_hash)
            except SessionPasswordNeededError:
                print('NEED_2FA', flush=True)
                await client.disconnect()
                return
            except Exception as exc:
                print('FAILED: %s: %s' % (type(exc).__name__, exc), flush=True)
                await client.disconnect()
                return
            me = await client.get_me()
            print('LOGGED_IN id=%s user=@%s' % (me.id, me.username), flush=True)
            await client.disconnect()
            return
        await asyncio.sleep(2)
    print('TIMEOUT', flush=True)


asyncio.run(main())
