# Hermes Trading — معماری و راه‌اندازی از صفر (Disaster Recovery Playbook)

> اگر این سرور کامل از بین برود، با همین فایل + ریپوی گیت‌هاب + بکاپ ویندوز،
> سیستم روی هر سرور لینوکسی تازه در ~۳۰ دقیقه بالا می‌آید.

## نقشهٔ کل سیستم (۲ ماشین)

```
┌─────────────────────────────┐      HTTP :5050 (Bearer)   ┌──────────────────────────┐
│  لینوکس 192.168.10.18       │ ──────────────────────────▶ │  ویندوز 192.168.10.51     │
│  مغز: تحلیل/تصمیم/مدیریت    │                             │  فقط بازوی اجرا:          │
│  /home/ai/hermes-trading    │                             │  MT5 Terminal             │
│                             │                             │  C:\Temp\bridge.py        │
│  ۱. master (کرون ۱۵د)       │                             │  (اسکریپت: scripts/       │
│  ۲. position_daemon (systemd)│                            │   mt5_http_server_v2.py)  │
│  ۳. signal_daemon (systemd) │                             └──────────────────────────┘
│  ۴. health monitor (کرون ۵د)│
│  ۵. backup (کرون روزانه) ───┼── HTTP pull ──▶ C:\HermesBackups (روی ویندوز)
└──────────────┬──────────────┘
               │ HTTPS
        github.com/seyedmahdiesmailian/hermes-trading (خصوصی)
        + بکاپ روزانه: hermes_backup_*.tar.gz + repo.bundle
```

**دو پروژهٔ کاملاً جدا (هرگز قاطی نشوند):**
1. **هرمس تریدر خودکار** — `hermes_master.py` → اسکن/پلن/ورود خودکار + `position_daemon.py` مدیریت SL/BE/trail
2. **سیگنال تلگرام** — `signal_daemon.py` → خواندن کانال سیگنال، ارزیابی، اجرای خودکار

## اجزای ریپو

| مسیر | نقش |
|---|---|
| `hermes_master.py` | چرخهٔ ۱۵ دقیقه‌ای: اسکن → پلن → ستاپ → ورود خودکار |
| `hermes_runtime.py` | هستهٔ مشترک master (تحلیل، پلن‌سازی، گیت‌ها) |
| `position_daemon.py` | هر ۵ ثانیه: مدیریت پوزیشن‌های باز (SL/BE/trail/TP) |
| `signal_daemon.py` | پروژهٔ ۲: listener سیگنال تلگرام |
| `engines/` | تحلیل (context/smc), گیت‌های ایمنی (defcon/cooldown/kill_switch/learning), executor, بک‌تست |
| `bridge_client.py` | کلاینت HTTP به بریج ویندوز |
| `scripts/hermes_cron.sh` | ورودی کرون master (flock + timeout) |
| `scripts/bridge_health_monitor.py` | هر ۵ دقیقه: بریج + سلامت دایمون‌ها → تلگرام |
| `scripts/offsite_backup.py` | بکاپ روزانه کامل به ویندوز |
| `scripts/git_sync.sh` | سینک خودکار master به گیت‌هاب |
| `scripts/autopilot.sh` | بهبود شبانهٔ خودکار (read-only، بدون ترید) |
| `ops/systemd/` | فایل‌های سرویس (نسخهٔ مرجع) |
| `ops/cron/crontab.backup.txt` | کرون‌تب کامل فعلی (نسخهٔ مرجع) |
| `tests/` | ۱۲۰+ تست hermetic (`python3 -m unittest discover -s tests`) |
| `data/` | state زنده: پلن، ژورنال، یادگیری — **در بکاپ، نه در گیت** |

## ریکاوری روی سرور تازه — مرحله‌به‌مرحله

### ۰. پیش‌نیاز
Ubuntu/Debian با python3.11+. اگر بکاپ ویندوز در دسترس است آن را بردار:
`C:\HermesBackups\hermes_backup_YYYYMMDD_HHMMSS.tar.gz`

### ۱. کد از گیت‌هاب
```bash
git clone https://github.com/seyedmahdiesmailian/hermes-trading.git /home/ai/hermes-trading
cd /home/ai/hermes-trading
```
(اگر گیت‌هاب هم در دسترس نبود: فایل `hermes_repo_*.bundle` کنار همان بکاپ در
`C:\HermesBackups` است — `git clone hermes_repo_*.bundle /home/ai/hermes-trading`)

### ۲. وابستگی‌ها
```bash
sudo apt install -y python3-pip
pip3 install requests python-dotenv pywinrm requests_ntlm pandas numpy python-telegram-bot
```

### ۳. رازها (فقط از بکاپ — در گیت‌هاب نیستند!)
آرشیو بکاپ ریشه‌اش `./data` و `./.env` است:
```bash
mkdir -p /tmp/restored && tar -xzf hermes_backup_*.tar.gz -C /tmp/restored
cp /tmp/restored/.env .env
cp -a /tmp/restored/data/* data/
printf '%s' '<توکن گیت‌هاب>' > .git_token && chmod 600 .git_token
```
کلیدهای `.env`: `TELEGRAM_BOT_TOKEN` (ربات ترید/سیگنال)، `TELEGRAM_CHAT_ID`،
`TELEGRAM_SIGNAL_GROUP`، `AUTOPILOT_REPORT_BOT_TOKEN` + `AUTOPILOT_REPORT_CHAT_ID`
(ربات سوم = گزارش‌های سیستم: autopilot، سلامت، بکاپ، واتچ‌داگ — b37)،
`HERMES_BRIDGE_TOKEN`، `WIN_USER`/`WIN_PASS`،
`HERMES_DRY_RUN` (برای شروع `true` بگذار، بعد از تأیید `false`).

**قاعدهٔ مسیریابی تلگرام (b37):** رویداد ترید (باز/بسته/سیگنال/بایز) → ربات ترید؛
وضعیت سیستم (خطای دایمون، بریج، kill-switch، بکاپ، گزارش autopilot) → ربات سوم.
`send_ops()` در `notifier/telegram.py` تنها نقطهٔ این تفکیک است.

### ۴. سرویس‌ها و کرون
```bash
cp ops/systemd/*.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now hermes-position hermes-signal hermes-dashboard
crontab ops/cron/crontab.backup.txt
loginctl enable-linger $USER   # سرویس‌ها بدون لاگین هم زنده بمانند
```

### ۵. بریج ویندوز (اگر VM ویندوز هم رفته)
روی ویندوز: MT5 را نصب و لاگین کن (اکانت دمو/ریل بروکر)، بعد:
```bash
python3 scripts/_deploy_bridge.py   # از لینوکس، با WIN_USER/WIN_PASS در .env
```
بریج روی `:5050` با Bearer token بالا می‌آید. تست: `python3 scripts/_check_bridge.py`

### ۶. آزمون سلامت
```bash
python3 -m unittest discover -s tests        # باید OK باشد
python3 scripts/verify_chain.py              # پاریتی زنده با بریج/تقویم
python3 scripts/hermes_cron.sh               # یک چرخهٔ کامل master دستی
systemctl --user status hermes-position hermes-signal hermes-dashboard
```

## گیت‌های ایمنی (چرا سیستم خودکار بی‌خطر است)
- **fail-closed:** خطا در هر گیت (DEFCON/cooldown/kill-switch/یادگیری/تقویم) = ترید ممنوع
- **قفل خبر:** ۳۰ دقیقه قبل/بعد رویدادهای مهم USD ترید نمی‌خورد
- **ساعت بازار:** خارج از سشن XAUUSD (Sun 23:00 → Fri 22:00 UTC) ورود ندارد
- **DRY_RUN:** با `HERMES_DRY_RUN=true` همه‌چیز شبیه‌سازی است
- **کپ ریسک:** حجم/تعداد پوزیشن/min-RR در `engines/auto_executor.py`
- هیچ تأیید انسانی/دستی در هیچ مسیری وجود ندارد — سیستم ۱۰۰٪ خودکار است

## بکاپ‌ها
- **گیت‌هاب (روزانه خودکار):** کد + تاریخچه + تست (بدون راز، بدون state)
- **ویندوز `C:\HermesBackups` (هر شب ۲۳:45 UTC):** tar.gz کامل شامل `data/`،
  `.env`، `.git_token` + `repo.bundle` (کل تاریخچهٔ git)
- نگه‌دارنده: ۱۴ نسخهٔ اخیر

## کجا چه چیزی است (خلاصهٔ مکان‌ها)
| مکان | محتوا |
|---|---|
| لینوکس `/home/ai/hermes-trading` | نصب فعال |
| لینوکس `~/.config/systemd/user/` | سرویس‌ها (مرجع در `ops/systemd/`) |
| ویندوز `C:\Temp\bridge.py` | بریج MT5 (پورت ۵۰۵۰) |
| ویندوز `C:\HermesBackups` | بکاپ روزانهٔ کامل |
| گیت‌هاب `seyedmahdiesmailian/hermes-trading` | کد + تاریخچه (خصوصی) |
