# ops/ — سرویسها و کرون واقعی سیستم

این پوشه آینهٔ تنظیمات **واقعی و در حال اجرا** است که پروژه به آن وابسته است
(جمعآوری 2026-09-19). قبلاً فقط ۳ سرویس در repo بود ولی سیستم ۹ سرویس اجرا
میکرد — باعث میشد ابزارها «همهچیز سبز» بگویند در حالی که بخشی از زنجیره خارج
از دید بود.

## systemd/ — یونیتهای واقعی (از ~/.config/systemd/user/)

- hermes-dashboard.service (بات پنل ops)
- hermes-forwarder.service (فورواردر سیگنال — native، main.py)
- hermes-gateway.service (گیتوی هرمس)
- hermes-position.service (مدیریت پوزیشن)
- hermes-signal.service (داemon سیگنال)
- hermes-trading.service / .timer ⚠️ **دوتایی با کرون — نباید فعال باشد**
- hermes-webui.service (داشبورد وب)
- omniroute.service (روتر LLM)

⚠️ **b216 — زمان‌بندی چرخهٔ master یک مرجع دارد، نه دو تا:**

`hermes-trading.timer` (هر ۱۵ دقیقه) و کرون `*/5` در `crontab.root.txt` **دقیقاً
یک اسکریپت را اجرا می‌کنند** (`scripts/hermes_cron.sh`). مرجع واقعی **کرون** است:
کرون از خود باکس زنده کشیده شده و `setup.sh` هم فقط کرون را نصب می‌کند و این
تایمر را اصلاً کپی نمی‌کند. تایمر اینجا فقط به‌عنوان آینهٔ وضعیت نگه داشته شده.

اگر تایمر را فعال کنید، دو زمان‌بند روی یک چرخه می‌دوند. `flock` از اجرای همزمان
جلوگیری می‌کند، ولی نتیجه این است که تیک‌ها **بی‌صدا رد می‌شوند** و فرکانس واقعی
غیرقابل‌پیش‌بینی می‌شود. **فعالش نکنید** مگر اینکه کرون را حذف کنید.

دقت: مسیرها مطلق `/home/ai/hermes-trading` هستند (این ماشین). برای DR جای مسیر
را عوض کن.

## cron/crontab.root.txt — کرون واقعی

شامل: hermes_cron.sh هر ۵دقیقه، bridge_health_monitor، autopilot.sh ساعتی،
autopilot_digest، weekly_report، offsite_backup شبانه، git_sync هر ۱۵دقیقه.
