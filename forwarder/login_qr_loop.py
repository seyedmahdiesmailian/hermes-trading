#!/usr/bin/env python3
"""QR login loop: saves a fresh QR every ~90s and appends its path + timestamp
to /tmp/fwd_qr_ready.txt so the agent can deliver each new image immediately.
Stops on LOGIN_OK / NEED_2FA / 12 regenerations."""
import asyncio
import json
import os
import time

import qrcode
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError
from telethon.tl.custom.qrlogin import QRLogin

BASE = os.path.dirname(os.path.abspath(__file__))
CFG = json.load(open(os.path.join(BASE, "config.json")))
SESSION = os.path.join(BASE, "data", "forwarder")
READY = "/tmp/fwd_qr_ready.txt"
STATE = "/tmp/fwd_qr_state.txt"


def note(msg):
    with open(STATE, "a") as f:
        f.write(f"{time.strftime('%H:%M:%S')} {msg}\n")
    print(msg, flush=True)


async def main():
    client = TelegramClient(SESSION, CFG["api_id"], CFG["api_hash"])
    await client.connect()
    if await client.is_user_authorized():
        note("ALREADY_LOGGED_IN")
        await client.disconnect()
        return

    for i in range(12):
        try:
            qr = await QRLogin.create(client, size=(384, 384), qr_login=None)
        except Exception as e:  # flood-wait etc: back off, never hammer
            note(f"CREATE_WAIT {type(e).__name__} {e}")
            await asyncio.sleep(60)
            continue

        png = f"/tmp/fwd_qr_{i}.png"
        img = qrcode.make(qr.url)
        img.save(png)
        with open(READY, "a") as f:
            f.write(png + "\n")
        note(f"QR_SAVED {png}")

        try:
            accepted = await qr.wait(timeout=85)
        except TimeoutError:
            await qr.discard()
            note("QR_EXPIRED")
            continue

        if accepted:
            try:
                await qr.check_and_export_authorization(SESSION)
                note("LOGIN_OK")
            except SessionPasswordNeededError:
                note("NEED_2FA")
            break
        note("QR_DENIED_ON_PHONE")
        await qr.discard()
    else:
        note("GAVE_UP")

    try:
        os.remove(READY)
    except OSError:
        pass


asyncio.run(main())
