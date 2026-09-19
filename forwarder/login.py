#!/usr/bin/env python3
"""One-time Telegram login for the forwarder.

Run in a terminal (it prompts interactively):
    .venv/bin/python login.py
Creates forwarder_session.session next to this file.
"""
import json
import os

from telethon import TelegramClient

BASE = os.path.dirname(os.path.abspath(__file__))
CFG = json.load(open(os.path.join(BASE, 'config.json')))

client = TelegramClient(os.path.join(BASE, 'forwarder_session'),
                        CFG['api_id'], CFG['api_hash'])
client.start(phone=CFG['phone_number'])
me = client.get_me()
print('OK logged in as @%s (id=%s)' % (me.username, me.id))
client.disconnect()
