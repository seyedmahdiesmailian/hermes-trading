# forwarder/ — فورواردر سیگنال تلگرام (سورس)

کد فورواردر از `~/projects/forwarder-telegram-dockerized` (ریپوی جدا:
esmailian-team/forwarder-telegram-dockerized) — کپی 2026-09-19 در این ریپو تا
ایجنتها سورس واقعی منبع سیگنال را ببینند.

اجرا: `main.py` بهصورت native (سرویس hermes-forwarder)، نه docker.

⚠️ فایلهای محرمانه عمداً اینجا نیستند: `config.json`، `config.json.bak-*`،
`forwarder_session*`، `forwarded_messages.json`، عکسها/مدیا. از `config.example.json`
و `.env`/کانفیگ محلی استفاده کن. مدیا و `data/` هم خارج از git هستند.
