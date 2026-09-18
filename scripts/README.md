# scripts/ — ایندکس (WP3)

۱۹۰ فایل پایتون + ۴ شل‌اسکریپت + `archive/` (۱۹ پروب بازنشسته). کد زنده
(`engines/` و ریشه) **هیچ‌چیز** از اینجا import نمی‌کند — جهت وابستگی یک‌طرفه است:
اسکریپت‌ها از engines/ریشه می‌خوانند، نه برعکس. تست‌ها به مسیر مستقیم ارجاع
می‌دهند، پس **جابه‌جایی هر فایل بدون به‌روزرسانی تست‌ها ممنوع.**

## ۱. عملیات روزمره (cron/systemd — دست نزنید مگر با دلیل)
| فایل | نقش | اجرا توسط |
|---|---|---|
| `hermes_cron.sh` | چرخه master هر ۱۵ دقیقه (flock + timeout) | cron `*/15` |
| `bridge_health_monitor.py` | سلامت بریج + دایمون‌ها هر ۵ دقیقه → تلگرام | cron `*/5` |
| `offsite_backup.py` | بکاپ شبانه کامل → ویندوز (۱۴ نسخه) | cron روزانه |
| `git_sync.sh` | push خودکار با push-gate (فقط HEAD تأییدشده) | cron `*/15` |
| `autopilot.sh` / `autopilot_digest.py` / `autopilot_report.py` / `autopilot_harvest.py` | ایجنت شبانه + دایجست + گزارش + harvest | cron ساعتی/شبانه |
| `dashboard_bot.py` | پنل ops تلگرام (فقط‌خواندنی) | systemd |
| `weekly_report.py` | گزارش مدیریتی جمعه‌ها (فارسی) | cron جمعه |
| `verify_chain.py` | راستی‌آزمایی زنجیره تحلیل روی دیتای زنده (فقط‌خواندنی) | دستی |
| `verify_head.sh` | تأیید HEAD در worktree تمیز + مهر head_verified | post-commit |

## ۲. بریج و دیپلوی (ویندوز)
- `mt5_http_server_v2.py` — سورس مرجع بریج MT5 (⚠️ نسخه زنده `C:\Temp\bridge.py` فورک قدیمی + پچ دستی است — drift ثبت‌شده در فاز صفر، منتظر آپلود فایل زنده)
- `_deploy_bridge.py` / `_deploy_pending_bridge.py` — دیپلوی/پچ بریج زنده از طریق WinRM
- `_check_bridge.py` — smoke test بریج (قدم ۵ DEPLOY.md)
- `_pull_live_bridge.py` — دانلود بریج زنده برای بازبینی

## ۳. بک‌تست و آزمایشگاه
- `backtest_robustness.py` / `backtest_sweep.py` / `ab.py` / `ab_*.py` (۱۶ فایل) — رانرهای A/B و sweep چند-پنجره‌ای (پروتکل b68)
- `measure_*.py` / `funnel_attribution.py` / `probe_b*.py` / `probe_gates.py` / `probe_news_lock.py` — اندازه‌گیری edge و gate
- `spread_sensitivity.py` / `show_day_low.py` / `replay_today_signals.py` — ابزار تحلیل
- `radin_replay.py` / `verify_radin_300pip.py` / `export_channel_history.py` / `channel_parse_audit.py` — replay و ممیزی سیگنال‌های رادین

## ۴. پژوهش سری b (۱۲۹ فایل `bNNN_*.py`)
هر آیتم بک‌لاگ اتوپایلوت که خروجی دیتایی داشته، یک اسکریپت `bNNN` + یک ledger در
`data/backtest/` دارد که تست هم‌نامش ادعا را باز-استنتاج می‌کند (قانون b127/b128:
هر producer باید reproduction-check ثبت‌شده داشته باشد). این‌ها تاریخچه پژوهش‌اند؛
حذف نکنید، و اگر ledgerای بازتولید شد همان فایل را به‌روز کنید.

## ۵. گزارش‌سازها
`gen_backtest_report.py` / `gen_infra_report.py` / `build_full_report.py` /
`build_intro_report.py` / `report_lib.py` — تولید گزارش‌های HTML/متنی.

## ۶. ابزارهای دستی ( `_*.py` باقی‌مانده)
`_audit_grade_rule.py` / `_check_bridge.py` / `_expectancy.py` / `_make_avatars.py` /
`_make_avatar_trader.py` — پروب‌های دستی کم‌مصرف (ارجاع‌دار، سر جایشان).

## ۷. `archive/` (۱۹ فایل)
پروب‌های یک‌بارمصرف بازنشسته با اثبات zero-reference — جزئیات در
`archive/README.md`. import و cron ممنوع.
