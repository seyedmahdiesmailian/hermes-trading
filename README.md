# Hermes Trading

سیستم ترید خودکار XAUUSD — مغز روی لینوکس، بازوی اجرا (MT5) روی ویندوز.
**۱۰۰٪ خودکار:** بدون هیچ تأیید دستی. دو پروژهٔ جدا: تریدر اسکنر + listener سیگنال تلگرام.

📖 **برای فهم معماری یا راه‌اندازی روی سرور تازه: [docs/DEPLOY.md](docs/DEPLOY.md)**

## سریع‌ترین شروع (سرور تازه)
```bash
git clone https://github.com/seyedmahdiesmailian/hermes-trading.git /home/ai/hermes-trading
cd /home/ai/hermes-trading && bash setup.sh   # .env + سرویس‌ها + کرون + تست
```

## تست
```bash
python3 -m unittest discover -s tests
python3 scripts/verify_chain.py     # پاریتی با بریج زنده
```

## ساختار
```
hermes_master.py / hermes_runtime.py   پروژه ۱: اسکن→پلن→ورود خودکار (کرون ۱۵د)
position_daemon.py                     مدیریت پوزیشن هر ۵ ثانیه (systemd)
signal_daemon.py + engines/signal_*    پروژه ۲: سیگنال تلگرام→ارزیابی→اجرا (systemd)
engines/                               تحلیل، گیت‌های ایمنی fail-closed، بک‌تست
bridge_client.py                       HTTP به بریج MT5 روی ویندوز :5050
scripts/                               cron، health monitor، بکاپ، سینک گیت‌هاب
ops/systemd/ ops/cron/                 فایل‌های مرجع سرویس و کرون‌تب
data/                                  state زنده (پلن/ژورنال/یادگیری) — فقط در بکاپ
legacy_backup/ legacy_removed/         بایگانی نسخه‌های قدیمی — قابل نادیده‌گرفتن
```

## رازها
`.env` هرگز commit نمی‌شود. الگو: `.env.example`. بازیابی از بکاپ ویندوز
(`C:\HermesBackups`) — جزئیات در docs/DEPLOY.md.
