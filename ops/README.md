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
- hermes-trading.service / .timer
- hermes-webui.service (داشبورد وب)
- omniroute.service (روتر LLM)

دقت: مسیرها مطلق `/home/ai/hermes-trading` هستند (این ماشین). برای DR جای مسیر
را عوض کن.

## cron/crontab.root.txt — کرون واقعی

شامل: hermes_cron.sh هر ۵دقیقه، bridge_health_monitor، autopilot.sh ساعتی،
autopilot_digest، weekly_report، offsite_backup شبانه، git_sync هر ۱۵دقیقه.
