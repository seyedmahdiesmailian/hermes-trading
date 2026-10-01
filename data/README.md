# data/ — سیاست ترک در گیت (WP1)

این درخت دو نوع فایل دارد. **فقط گروه اول در گیت ترک می‌شود:**

## ✅ ترک‌شده (شواهد پژوهشی + اسناد — تست‌ها روی آن‌ها pin شده‌اند)
| مسیر | چرا ترک است |
|---|---|
| `backtest/` | خروجی‌های A/B و census سری b؛ ~۳۰ تست ادعاها را از همین فایل‌ها باز-استنتاج می‌کنند |
| `radin/` | تاریخچه و replay کانال رادین (ورودی اسکریپت‌های replay) |
| `calendar/events_archive_*.json` | آرشیو واقعی رویدادها (سند b132) |
| `ops/autopilot_backlog.md` | بک‌لاگ اتوپایلوت (سند زنده، کامیت‌شونده) |
| `ops/daemon_code_drift_b114_finding.json` | یافته فریز‌شده b114 (تست b114 روی آن skip-guard دارد ولی فایل ثابت است) |

## 🚫 ترک‌نشده (state زنده — فقط در بکاپ آف‌باکس + روی ماشین)
| مسیر | تولیدکننده |
|---|---|
| `xau_plan/` (پلن جاری، plan_history، ژورنال، ledger، learning، performance، heartbeat) | master/daemons |
| `signals/signals_log.json` و `pending_orders.json` | signal_daemon |
| `trading/` | master |
| `calendar/economic_calendar.json` (کش) | economic_calendar fetcher |
| `bridge_health_state.json`، `cooldown_state.json`، `kill_switch_state.json` | health monitor / engines |
| `ops/*_state.json`، `ops/head_verified.json`، `ops/daemon_code_drift.json` | autopilot/digest/verify/daemon probe |

تست‌هایی که به state زنده نیاز دارند (`b106`، `b93`، `b114`) روی checkout بدون state با
`skipTest` رد می‌شوند — همان الگوی `b165`. منطق تست‌ها تغییر نکرده است.

## بازیابی روی سرور تازه
state زنده از بکاپ ویندوز می‌آید، نه از گیت (مراحل در `docs/DEPLOY.md` قدم ۳):
```bash
mkdir -p /tmp/restored && tar -xzf hermes_backup_*.tar.gz -C /tmp/restored
cp -a /tmp/restored/data/xau_plan data/   # + signals/ trading/ ops-states اگر لازم بود
```
`setup.sh` ساختار دایرکتوری خالی را می‌سازد؛ اولین چرخه master و دایمون‌ها
فایل‌های state را خودکار ایجاد می‌کنند.
