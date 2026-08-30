# Autopilot — خودگردان شبانه‌روزی

## چطور کار می‌کند
- `scripts/autopilot.sh` هر ساعت (cron: `5 * * * *`، flock از هم‌پوشانی جلوگیری می‌کند) یک اجرای headless
  `hermes -z` (کلیدی: **مسیر مطلق** `/home/ai/.local/bin/hermes` — cron PATH
  ندارد `~/.local/bin`) با prompt مشخص شروع می‌کند.
- عامل، **قلم اول با وضعیت `todo`** را از `data/ops/autopilot_backlog.md` برمی‌دارد،
  کامل پیاده/تحلیل می‌کند، تست می‌گیرد (unittest + یک سایکل واقعی master)،
  در بک‌لاگ `done` می‌کند و commit می‌زند.
- `scripts/autopilot_digest.py` هر شب ۰۲:۰۰ UTC خلاصه را از توکن ربات تریدینگ
  به چت ۱۹۴۰۱۵۹۵۷ می‌فرستد (پیشرفت بک‌لاگ، کارها، خطاها، سلامت دایمون‌ها).

## خط قرمزها (در prompt + ساختار)
- هرگز ترید نمی‌زند: bridge order endpoints ممنوع؛ فقط read-only.
- .env / DRY_RUN / systemd / crontab / ویندوز ۵۱/۱۹۲.۱۶۸.۱۰ دست‌نخوردنی.
- گیت‌های ریسک (min_rr، کپ پوزیشن، cooldown، DEFCON، market-hours) فقط سفت‌تر.
- بک‌تست فقط با `engines/backtest_real.run_backtest` (پاریتی با قیف لایو).

## اعتبارسنجی (۲۰۲۶-۰۸-۲۹)
- اجرای اول: A/B مسیر aggressive → کشف: ~۸۰٪ سود از aggressive premium/discount
  (۱۵۶ ترید / ۵۷٪ / +۸۰۸ در ۳۱ روز) — commit `7f465b9`.
- اجرای دوم (PATH خراب rc=127) → فیکس مسیر مطلق — commit `3542ed3`.
- اجرای سوم: در حال تأیید در محیط شبیه cron (env -i).

## لاگ‌ها
- `logs/autopilot.log` — خروجی کامل هر اجرا
- `logs/autopilot_cron.log` — cron wrapper
- `data/ops/autopilot_state.json` — آخرین اجرا + کامیت‌ها
