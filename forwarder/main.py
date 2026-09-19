import os
import json
import asyncio
import logging
import sys
from telethon import TelegramClient, events

# ---------------------------
# مسیر داده‌ها و فایل‌ها
# ---------------------------
# For exe: use the directory where the exe is located
if getattr(sys, 'frozen', False):
    # Running as compiled executable
    DATA_DIR = os.path.dirname(sys.executable)
else:
    # Running as script
    DATA_DIR = os.path.dirname(os.path.abspath(__file__))

os.makedirs(DATA_DIR, exist_ok=True)

CONFIG_PATH = os.path.join(DATA_DIR, "config.json")
STORAGE_FILE = os.path.join(DATA_DIR, "forwarded_messages.json")
LOG_FILE = os.path.join(DATA_DIR, "logs.txt")

# ---------------------------
# تنظیم logging (هم فایل هم کنسول)
# ---------------------------
logger = logging.getLogger("Forwarder")
logger.setLevel(logging.INFO)
formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")

file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
file_handler.setFormatter(formatter)
stream_handler = logging.StreamHandler()
stream_handler.setFormatter(formatter)

logger.addHandler(file_handler)
logger.addHandler(stream_handler)

# ---------------------------
# بارگذاری config
# ---------------------------
if not os.path.exists(CONFIG_PATH):
    sample_config = {
        "api_id": 1234567,
        "api_hash": "your_api_hash_here",
        "source_channels": {},
        "target_group": None
    }
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(sample_config, f, indent=2, ensure_ascii=False)
    logger.warning(f"⚠️ فایل config.json ایجاد شد در {CONFIG_PATH}. لطفاً آن را ویرایش کنید.")
    exit(0)

with open(CONFIG_PATH, "r", encoding="utf-8") as f:
    config = json.load(f)

api_id = config.get("api_id")
api_hash = config.get("api_hash")
source_channels = {int(k): v for k, v in config.get("source_channels", {}).items()}
target_group = config.get("target_group")

if not api_id or not api_hash:
    logger.error("⚠️ لطفاً api_id و api_hash را در config.json وارد کنید.")
    exit(0)

if not source_channels or not target_group:
    logger.error("⚠️ لطفاً کانال‌ها و گروه هدف را در config.json وارد کنید.")
    exit(0)

# ---------------------------
# شماره تلفن از env یا input
# ---------------------------
phone_number = os.environ.get("TG_PHONE") or config.get("phone_number") or input("Enter your Telegram phone number: ")

# ---------------------------
# ساخت client
# ---------------------------
client = TelegramClient(os.path.join(DATA_DIR, 'forwarder_session'), api_id, api_hash)

# ---------------------------
# بارگذاری forwarded_messages
# ---------------------------
forwarded_messages = {}
if os.path.exists(STORAGE_FILE):
    try:
        with open(STORAGE_FILE, 'r', encoding="utf-8") as f:
            forwarded_messages = {tuple(map(int, k.split(','))): v for k, v in json.load(f).items()}
        logger.info(f"Loaded {len(forwarded_messages)} forwarded messages.")
    except Exception as e:
        logger.warning(f"⚠️ Could not load forwarded messages: {e}")

def save_forwarded_messages():
    try:
        with open(STORAGE_FILE, 'w', encoding="utf-8") as f:
            json.dump({f"{k[0]},{k[1]}": v for k, v in forwarded_messages.items()}, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
    except Exception as e:
        logger.error(f"⛔ Error saving forwarded messages: {e}")

# ---------------------------
# هندلر پیام جدید
# ---------------------------
async def forward_one(msg, source_id):
    """Forward a single source message to the target group (dedup-safe)."""
    source_name = source_channels.get(source_id, str(source_id))
    logger.info(f"📥 رویداد از «{source_name}» msg={msg.id} "
                f"متن={'بله' if (msg.text or msg.message) else 'خیر/رسانه'}")
    source_name = source_channels.get(source_id, "کانال ناشناس")
    if (source_id, msg.id) in forwarded_messages:
        return None
    try:
        caption_text = msg.text or msg.message or ""
        prefix = f"[💬 از {source_name}]"
        reply_to = None
        if msg.reply_to_msg_id:
            key = (source_id, msg.reply_to_msg_id)
            if key in forwarded_messages:
                reply_to = forwarded_messages[key]
        if msg.media:
            # Protected channels reject direct media forwarding; download to a
            # temp file and re-upload instead so nothing is silently lost.
            payload = msg.media
            try:
                payload = await msg.download_media()
            except Exception:
                payload = msg.media
            try:
                sent = await client.send_file(
                    target_group,
                    file=payload,
                    caption=f"{prefix}\n{caption_text}".strip(),
                    reply_to=reply_to
                )
            except Exception as e2:
                if payload is not msg.media:
                    os.path.exists(payload) and os.remove(payload)
                raise e2
            try:
                payload is not msg.media and os.path.exists(payload) and os.remove(payload)
            except Exception:
                pass
        else:
            sent = await client.send_message(
                target_group,
                message=f"{prefix}\n{caption_text}".strip(),
                reply_to=reply_to
            )
        forwarded_messages[(source_id, msg.id)] = sent.id
        save_forwarded_messages()
        logger.info(f"✅ Forwarded message from {source_name} (ID {msg.id})")
        return sent.id
    except Exception as e:
        logger.error(f"⛔ Error while sending message: {e}")
        return None

@client.on(events.NewMessage(chats=list(source_channels.keys())))
async def handler(event):
    await forward_one(event.message, event.chat_id)

# ---------------------------
# هندلر ویرایش پیام
# ---------------------------
@client.on(events.MessageEdited(chats=list(source_channels.keys())))
async def edit_handler(event):
    key = (event.chat_id, event.message.id)
    if key in forwarded_messages:
        try:
            msg = event.message
            source_name = source_channels.get(event.chat_id, "کانال ناشناس")
            caption_text = msg.text or msg.message or ""
            prefix = f"[💬 از {source_name}]"
            new_text = f"{prefix}\n{caption_text}".strip()
            await client.edit_message(target_group, forwarded_messages[key], new_text)
            logger.info(f"✏️ Edited message from {source_name} (ID {event.message.id})")
        except Exception as e:
            logger.error(f"⛔ Error while editing message: {e}")

# ---------------------------
# هندلر حذف پیام
# ---------------------------
@client.on(events.MessageDeleted(chats=list(source_channels.keys())))
async def delete_handler(event):
    for msg_id in event.deleted_ids:
        for (chat_id, original_id), forwarded_id in list(forwarded_messages.items()):
            if chat_id == event.chat_id and original_id == msg_id:
                try:
                    await client.send_message(
                        target_group,
                        "⚠️ این پیام توسط نویسنده حذف شد.",
                        reply_to=forwarded_id
                    )
                    del forwarded_messages[(chat_id, original_id)]
                    save_forwarded_messages()
                    logger.info(f"🗑️ Deleted message reflected for {chat_id}:{msg_id}")
                except Exception as e:
                    logger.error(f"⛔ Error handling deleted message: {e}")

# ---------------------------
# جبران پیام‌های جاافتاده (بعد از استارت/ری‌استارت)
# ---------------------------
async def catch_up():
    """Disabled by user request: forwarding stale/missed signals is harmful
    (a signal past its time is worse than no signal). Kept as a no-op gate;
    set catchup_hours > 0 in config.json only if this is ever wanted again."""
    hours = float(config.get("catchup_hours", 0))
    if hours <= 0:
        return
    import datetime
    since = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=hours)
    total = 0
    for source_id, source_name in source_channels.items():
        try:
            msgs = await client.get_messages(source_id, limit=50)
            missed = [m for m in reversed(msgs) if m and m.date and m.date >= since]
            for m in missed:
                if await forward_one(m, source_id):
                    total += 1
        except Exception as e:
            logger.error(f"⛔ Catch-up failed for {source_name}: {e}")
    if total:
        logger.info(f"🔄 Catch-up forwarded {total} missed message(s).")

# ---------------------------
# اجرای دائمی با reconnect خودکار
# ---------------------------
async def connection_watchdog(interval=120, max_fail=2):
    """b70: telethon connections can go half-dead (no exception, no updates).
    Every `interval`s hit a no-cache API; on repeated failure, force a full
    reconnect so the listener cannot silently stop receiving.
    b71: GetAccountTtlRequest was removed in telethon 1.44 — the watchdog was
    fail-CLOSED on an AttributeError and could never recover a dead socket
    (2026-09-08 outage, 2 days silent). Ping = real authenticated RPC with a
    hard timeout: a half-dead socket cannot answer it, so timeout => reconnect."""
    fails = 0
    while True:
        await asyncio.sleep(interval)
        try:
            me = await asyncio.wait_for(client.get_me(input_peer=False), timeout=20)
            if me is None:
                raise ConnectionError("get_me returned None (not authorized/connected)")
            fails = 0
        except Exception as e:
            fails += 1
            logger.warning(f"🩺 watchdog: ping failed ({fails}/{max_fail}): {e}")
            if fails >= max_fail:
                logger.error("🩺 watchdog: connection stale → forcing reconnect")
                fails = 0
                try:
                    await client.disconnect()
                except Exception:
                    pass
                try:
                    await client.connect()
                    logger.info("🩺 watchdog: reconnected")
                except Exception as e2:
                    logger.error(f"🩺 watchdog reconnect failed: {e2}")

async def run_client():
    while True:
        try:
            await client.start(phone=phone_number)
            logger.info("✅ Bot started successfully.")
            await catch_up()
            wd = asyncio.create_task(connection_watchdog())
            try:
                await client.run_until_disconnected()
            finally:
                wd.cancel()
        except Exception as e:
            logger.error(f"⚠️ Disconnected or error: {e}. Reconnecting in 10s...")
            await asyncio.sleep(10)

async def main():
    await run_client()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("🔒 Saving data and shutting down...")
        save_forwarded_messages()
