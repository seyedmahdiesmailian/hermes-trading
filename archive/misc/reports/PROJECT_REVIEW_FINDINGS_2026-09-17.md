# گزارش بررسی عمیق ریپازیتوری Hermes Trading — نسخهٔ نهایی (دو مرحله‌ای)

تاریخ: ۲۰۲۶-۰۹-۱۷ · روش: خواندن تک‌به‌تک فایل‌ها (دو پاس کامل) + اجرای کل سوئیت تست (۱۷۲۵ تست) + تحلیل ایستا (pyflakes) + ریشه‌یابی تجربی باگ‌ها با اجرای کد.

## پوشش بررسی (شفافیت)

| ناحیه | وضعیت |
|---|---|
| فایل‌های root (۹ فایل py + sh + env) | ✅ کامل خوانده شد |
| `engines/` (۳۴ ماژول) | ✅ کامل — smc/backtest/backtest_real/report/macro_snapshot/trade_management/… خط‌به‌خط |
| `notifier/` (۲ فایل) | ✅ کامل |
| `scripts/` (۲۱۳ فایل) | ✅ ~۲۵ اسکریپت عملیاتی حیاتی کامل (بریج، deploy، cron، autopilot، بکاپ، داشبورد‌بات، verify، گزارش‌ها)؛ بقیهٔ ~۱۹۰ تا اسکریپت آزمایشگاهی یک‌بارمصرف (`ab_*`, `b1xx_*`, `_probe_*`) الگو-محور بررسی شدند (خروجی‌ها به `data/backtest/`) |
| `tests/` (۱۳۸ فایل) | ساختار + hermetic + fixtures + نمونه‌ها؛ سوئیت کامل اجرا شد |
| `ops/`, `docs/`, `data/`, `legacy_*` | ✅ (legacy ها آرشیو تاریخند) |

---

# خلاصهٔ اجرایی

سیستم از میانگین پروژه‌های مشابه **خیلی بالاتر** است (fail-closed در مسیر ورود، تست رگرسیون برای هر باگ، harness «صداقت ledger»، خودپایایی). اما در این بررسی **۲ باگ/حفره در سطح CRITICAL جدید** (علاوه بر موارد پاس اول) پیدا شد که مهم‌ترینشان این است: **بازوی اجرای واقعی ترید (بریج ویندوز) اصلاً در گیت نیست و نسخهٔ داخل ریپو آن بدون احراز هویت است**، و **آخرین بار که verifier خود سیستم روی HEAD اجرا شده، verdict=BROKEN بوده و کامیت‌های بعدی هرگز verify نشده‌اند**. یعنی دقیقاً در نقطه‌ای که سیستم به «همه‌چیز سبز» فکر می‌کند، زنجیرهٔ حاکمیتی‌اش قطع بوده.

---

# بخش ۱ — یافته‌های پاس دوم (عمیق‌تر، فایل‌به‌فایل)

## ۱.۱ 🔴 CRITICAL — بریج MT5 زنده در کنترل نسخه نیست؛ نسخهٔ ریپو بدون auth است

- `scripts/mt5_http_server_v2.py` (۳۱۴ خط) **هیچ بررسی Bearer/توکنی ندارد** — همهٔ endpoint ها از جمله `/api/order`, `/api/close`, `/api/modify`, `/api/partial` کاملاً بازند و روی `0.0.0.0:5050` با **dev server فلسک** (`app.run(threaded=True)`) سرو می‌شوند.
- `bridge_client.py` هدر `Authorization: Bearer` می‌فرستد ولی سرورِ v2 آن را هیچ‌جا نمی‌خواند — توکن فقط در بریج زنده (`C:\Temp\bridge.py`) با `@app.before_request` اعمال می‌شود (طبق کامنت `PENDING_CODE` در `_deploy_pending_bridge.py`).
- بریج زنده **فقط به‌صورت «دانلود → patch رشته‌ای → آپلود»** توسط `_deploy_bridge.py`/`_deploy_pending_bridge.py` دستکاری می‌شود؛ سورس واقعی‌اش هرگز به گیت نمی‌رود (`_pull_live_bridge.py` آن را در `logs/` — که gitignored است — می‌ریزد).
- **RIA دیسستر یک دور تکرار است:** DEPLOY.md گام ۵ می‌گوید بعد از از دست رفتن VM ویندوز `python3 scripts/_deploy_bridge.py` را اجرا کن — ولی این اسکریپت مرحلهٔ اولش **دانلود bridge.py موجود از خود ویندوز** است؛ روی VM تازه fail می‌شود. تنها سورس قابل‌استفاده در ریپو (v2) هم بدون auth و بدون endpoint های pending است.
- **پیامد عملی:** هر کس ریپو را clone کند و v2 را deploy کند = بذر اجرای ترید بدون رمز روی LAN. و drift بین بریج زنده و v2 از کنترل خارج است ( fixtures تست فقط با v2 چک می‌شوند، نه با فایل زنده).

**درستش:** سورس واقعی بریج زنده (با auth و waitress) به‌عنوان فایل canonical در ریپو commit شود؛ v2 یا auth بگیرد یا حذف/علامت‌گذاری شود؛ deploy از روی فایل گیت باشد نه patch زنده.

## ۱.۲ 🔴 CRITICAL — زنجیرهٔ verify/push از ۲۰۲۶-۰۹-۱۰ قطع شده: آخرین استمپ = BROKEN

`data/ops/head_verified.json` (آخرین استمپ موجود در snapshot):
```json
{"sha": "18cc1ea…", "verdict": "BROKEN", "at": "2026-09-10T12:28:24Z", "tests": 1706}
```
- کامیت‌های بعد از این تاریخ — از جمله HEAD فعلی (`d21ab9e` «b79d tail») — **هیچ استمپ تأییدی ندارند**؛ یعنی `verify_head.sh` مدتی است دیگر اجرا/استمپ نمی‌زند و push gate طبق طراحی fail-open خودش پوش کرده.
- آخرین باری که هم اجرا شده verdict=**BROKEN** بوده (۱۷۰۶ تست).
- اجرای مستقل من روی همین snapshot: **۱۵ failure + ۵ error از ۱۷۲۵ تست** — هم‌راستا با BROKEN.
- نتیجه: ادعای «۷۲۵/۱۷۰۰ تست سبز روی clean checkout» در داکیومنت‌ها **منقضی** است و خود-تأییدی سیستم (b45/b50/b51) — که باکیفیت طراحی شده — عملاً از کار افتاده و کسی متوجه نشده.

## ۱.۳ 🔴 HIGH — باگ wiring در `merge_smc_with_classic`: رژیم از کلید اشتباه خوانده می‌شود (اثبات با اجرا)

`engines/smc.py::merge_smc_with_classic`:
```python
classic_regime = classic_context.get("regime", "range")   # ❌ وجود خارجی ندارد
```
در حالی که `build_plan_context` رژیم را در `quality.regime` می‌گذارد (خروجی واقعی تست من: `ctx['regime'] exists at top level? False`). نتیجه:
- `classic_regime` همیشه `"range"` → `classic_confidence *= 0.5` **همیشه** اعمال می‌شود؛ confidence کلاسیک (۰.۷ هم‌راستا) همیشه به ۰.۳۵ نصف می‌شود.
- مقدار تحریف‌شده به `merged['confidence']` می‌رود که مستقیماً در `apply_smc_merge` با `RANGE_KILL_CONF` مقایسه می‌شود و در `quality.smc_confidence` پلن stamp می‌خورد.
- جالب: `apply_smc_merge` همان کلید را **درست** می‌خواند (`ctx.get('quality', {}).get('regime')`) — دو مصرف‌کننده، دو تعریف (دقیقاً کلاس b109/b136 که خود پروژه کاتالوگ کرده).
- چون بک‌تست هم از همین تابع مشترک می‌گذرد، parity حفظ شده و **همهٔ اعداد backtest روی مقدار تحریف‌شده کالیبره‌اند** — فیکس آن یک تغییر رفتار واقعی است و re-measurement می‌خواهد (همان دیوار b88/b210).

## ۱.۴ 🟠 MEDIUM — DR ناقص: فورواردر سیگنال و gateway و omniroute اصلاً در ریپو نیستند

- `export_channel_history.py` نشان می‌دهد فورواردر تلگرام (Telethon) در `/home/ai/projects/forwarder-telegram-dockerized` زندگی می‌کند — **بیرون از این ریپو**. `hermes-gateway` و `omniroute` هم فقط در گزارش وضعیت упом شده‌اند؛ کد و unit شان اینجا نیست.
- `ops/systemd/` فقط ۳ سرویس دارد (position/signal/dashboard) ولی `dashboards._services()` **۴ سرویس** چک می‌کند (`hermes-gateway` را هم می‌خواند که unit ش در ریپو نیست) و `hermes-forwarder` و `omniroute` را **اصلاً مانیتور نمی‌کند**.
- پیامد: پنل ops می‌تواند «🟢 همه‌چیز روال است» بگوید در حالی که منبع سیگنال مرده است — سازگار با معمای «۲۲ رویداد، صفر اجرا». و ادعای «ریکاوری ۳۰ دقیقه‌ای» DEPLOY.md فقط برای نصف سیستم درست است.

## ۱.۵ 🟠 MEDIUM — بدون requirements.txt / قفل وابستگی

هیچ `requirements.txt`/`pyproject` وجود ندارد؛ `setup.sh` لیست شل‌خورده نصب می‌کند (`requests python-dotenv pywinrm requests_ntlm pandas numpy python-telegram-bot`). ریسک‌ها: drift نسخه در DR، تغییر رفتار API (مثلاً urllib3/requests یا python-telegram-bot که نسخه‌هایش breaking بوده). ضمناً همان نصب روی Ubuntu 24.04 با PEP 668 رد می‌شود (یافتهٔ پاس اول).

## ۱.۶ 🟡 LOW — باگ‌های کوچک تأییدشده

- `smc.evaluate_silver_bullet_setup`: پنجرهٔ PM دو ساعت است (ساعت ۱۸ **و** ۱۹ UTC) با لیبل «2-3 PM NY» (باید ۱ ساعت باشد)؛ و DST حساب نمی‌شود — زمستان هر دو پنجره ۱ ساعت جابه‌جا می‌شوند. فقط observability است ولی غلط.
- `scripts/b118_merit_bar_rebaseline.py:179` — `undefined name 'attr'` (pyflakes): اگر آن مسیر اجرا شود کرش می‌کند (اسکریپت lab).
- `smc_analyse` با `now=None` از `datetime.utcnow()` خام (naive) استفاده می‌کند — با قرارداد timezone-aware بقیهٔ سیستم ناسازگار (deprecation در 3.12+).
- `verify_chain.py` بعد از b193b بدون `m5_rows` صدا می‌زند → تریگر تأیید M5 در smoke-check هرگز pass نمی‌شود؛ چک فقط «action برمی‌گرداند» را تست می‌کند (arity شبیه‌سازی ضعیف شده).
- `dashboards`: فقط دو نقطه escape HTML دارند؛ فیلدهای داینامیک مثل `comment` بروکر/بک‌لاگ raw می‌روند به `parse_mode='HTML'` — تئوریکاً یک `<` در کامنت بروکر کل پنل را با 400 می‌شکند (کم‌خطر).
- فوروارد کردن dead-import در `hermes_master.py` (`run_signal_check` import می‌شود، هرگز صدا زده نمی‌شود) — باگ نیست ولی نشانهٔ refactor ناتمام.

## ۱.۷ ✅ نقاط قوت جدیدی که در این پاس دیدم

- `tests/fixtures_bridge.py` + تست drift با AST-parse کردن سورس سرور — الگوی بی‌نظیر برای جلوگیری از واگرایی fake/producer.
- موتور بک‌تست (`backtest.py`): قواعد intrabar محافظه‌کار (SL قبل از TP در همان کندل)، بدون look-ahead (BE/trail از کندل بعد)، مدل اسپرد، parity با گیت‌های live — از اکثر بک‌تست‌های业余 خیلی تمیزتر.
- `head_verify.py` (منطق pure جدا از glue، سه-حالته بودن پیام‌ها، anti-vacuity با شمارش تست‌ها) طراحی درستی دارد — مشکل فقط این است که اجرایش متوقف شده (۱.۲).
- honesty-harness آزمایشگاه (`lab_harness.check_honesty`, `DishonestLedger`) — پایش اینکه آزمایش‌ها خودشان دروغ نگویند.

---

# بخش ۲ — یافته‌های پاس اول (خلاصهٔ کامل؛ جزئیات قبلی حفظ شد)

## الف) باگ‌های تأییدشده با اجرا

- **A1** `engines/storage.py::ensure_xau_plan_dirs` — `mkdir` داخل مسیر **خواندن** state → روی هر مسیر جز `/home/ai/hermes-trading` → `PermissionError` → سیگنال‌ها با `policy_error` رد، ۳ تست fail (اثبات با trace). تست‌ها location-independent نیستند؛ DR روی مسیر متفاوت = سیستم کرخته بدون پیام.
- **A2** تست freshness (b93) fail: «live_record is 7.6 days stale» — snapshot دیتای commit شده کهنه؛ چند تست دیگر (b94/b103/b50/b114/b117/b42/b127/b132) به تاریخچهٔ کامیت ماشین اصلی قفل‌اند.
- **A3** `data/` زنده (۱۷۸۷ فایل: متن سیگنال‌های تلگرام، ژورنال، تاریخچهٔ کانال‌ها) داخل گیت — برخلاف README؛ + فایل‌های حجیم backtest (تا ۶.۶MB) و `legacy_backup/` با ۳× `state.db` ۳.۵MB و zip کامل.
- **A4** `notifier/telegram.py:40` — `"\\n"` literal → کل لاگ پیام‌ها در یک خط.
- **A5** `economic_calendar.get_news_blackout_check` — بدون caller و با منطق ناسازگار با `macro_filter` (پنجرهٔ ۶۰ دقیقهٔ یک‌طرفه).

## ب) امنیت

- **B1** `offsite_backup.py` — serve کردن آرشیو حاوی کل `.env` (توکن‌ها + پسورد ویندوز + `.git_token`) روی `HTTPServer('0.0.0.0')` **بدون احراز هویت** روی LAN؛ هر اسکنر پورت در آن پنجره = مالک کل secret ها. + WinRM/NTLM بدون TLS.
- **B2** `git_sync.sh` — توکن گیت‌هاب در argv پروسس (`password=$TOK` در credential helper) → قابل خواندن با `ps`.
- **B3** chat-id مالک (`194015957`) به‌عنوان default هاردکد در ۸+ فایل.
- **B4** بریج روی HTTP خام LAN (طراحی پذیرفته‌شده ولی یعنی sniff = کنترل کامل ترید). — با ۱.۱ تکمیل شود: نسخهٔ ریپو اصلاً token ندارد.

## ج) حفره‌های fail-open در مسیر «مدیریت»

- **C1** `position_daemon`: `if not DRY_RUN and plan:` — نبود/خرابی `current_plan.json` = خاموشی بی‌صدا کل مدیریت (TP/BE/trail/**news_lock/time_exit**) بدون هیچ هشدار ops. fallback هرمس هم پلن می‌خواهد. تنها محافظ باقی‌مانده SL/TP بروکر.
- **C2** گیت اسپرد مسیر پلن: `_tick_obj` با تیک فقط-ask → `bid:=ask` → spread=0 → گیت پاس (مسیر سیگنال همین را fail-closed بسته با `tick_incomplete_fail_closed`).
- **C3** (b210 خودشان) همهٔ گیت‌های پولی `daily_pnl` را gross-of-cost می‌بینند؛ کمیسیون/سواپ (~۲.۷٪ ضرر) دیده نمی‌شود؛ جهت خطا همیشه به سمت ترید. فیکس پشت «دیوار ۵۰ دقیقه‌ای» ledgers پinned به sha256 گیر کرده.
- **C4** `realized_pnl_usd(days=1)` — پوزیشن بلندتر از ۲۴ ساعت کمیسیون ورودش را در گزارش PnL گم می‌کند.

## د) مسابقه/اطمینان

- **D1** `dashboard_bot.save_offset` — write غیراتمیک → کرش = offset صفر → replay تا ۲۴h آپدیت‌ها → اجرای مجدد callback های تأییدشده (`trade:resume`!). نقض کنوانسیون اتمیک خودشان.
- **D2** `check_kill_switch` از ۳ پروسس read-modify-write می‌شود (master/signal/runtime) — last-writer-wins.
- **D3** `close_reason` — برچسب خروج از قیمت لحظهٔ polling؛ برای خروج‌های modify شده غلط است (فقط گزارش).

## هـ) کیفیت/فرآیند

- ~۶۰ مورد pyflakes در کد اصلی (import/متغیر مرده، f-string بی‌placeholder، import تکراری در حلقه).
- تناقض README ↔ واقعیت (data/ و legacy در گیت هستند).
- `setup.sh`: `pip3 install` بدون `--break-system-packages` روی Ubuntu 24.04 fail می‌کند (فقط warning)؛ `crontab ops/...` **جایگزین** کل crontab موجود می‌شود (ادعای idempotent غلط).
- `dashboard_bot.STATE` و `bridge_health_monitor` مستقیم به `ROOT/data` می‌نویسند نه از `engines.paths` (نقض b39).
- ۴۰ `except Exception` باز در `engines/` (بیشتر آگاهانه، ولی چندتا ساکت واقعی).

## و) ریسک استراتژیک

- SPOF تقویم (ForexFactory+TradingView) → قطعی >۲۴h = قفل کامل هر دو مسیر (fail-closed آگاهانه، ولی دسترسی وب پیش‌شرط ترید است).
- مسیر سیگنال: ۲۲ رویداد/صفر اجرا؛ + حالا با ۱.۴ معلوم می‌شود مانیتورینگ فورواردر هم وجود ندارد.
- پروفایل سود شکننده (۷۹٪ WR ولی avg +۲۰$/-۵۰$).
- بدهی فرآیندی autopilot: بودجهٔ ۵۵ دقیقه در برابر بازتولید ۵۰ دقیقه‌ای ledgers → باگ‌های پولی شناخته‌شده (b210) و حالا wiring مرج (۱.۳) پشت همین دیوار صف می‌شوند.

---

# اولویت‌بندی نهایی فیکس

| # | مورد | سطح | فایل |
|---|---|---|---|
| ۱ | بریج زنده در گیت + auth برای v2 + درست‌کردن DR بریج | 🔴 | `scripts/mt5_http_server_v2.py`, `_deploy_*.py` |
| ۲ | باز‌راه‌اندازی زنجیرهٔ verify_head (استمپ BROKEN/قدیمی) | 🔴 | `scripts/verify_head.sh`, `autopilot.sh` |
| ۳ | مدیریت پوزیشن بدون پلن + هشدار (C1) | 🔴 | `position_daemon.py` |
| ۴ | بستن HTTP بکاپ بدون auth (B1) | 🔴 | `scripts/offsite_backup.py` |
| ۵ | فیکس wiring رژیم در merge (۱.۳) + re-measurement | 🟠 | `engines/smc.py` |
| ۶ | mkdir در مسیر read (A1) | 🟠 | `engines/storage.py` |
| ۷ | daily_pnl نتِ (C3/b210) + بازکردن قفل sha256 | 🟠 | `engines/risk.py` |
| ۸ | خارج‌کردن data/ و legacy از گیت + تازه‌سازی snapshot ها (A2/A3) | 🟠 | repo hygiene |
| ۹ | requirements.txt + درست‌کردن setup.sh (۱.۵) | 🟠 | `setup.sh` |
| ۱۰ | گیت اسپرد نیم‌تیک مسیر پلن (C2) | 🟡 | `hermes_runtime.py` |
| ۱۱ | اتمیک‌کردن offset داشبورد (D1) | 🟡 | `scripts/dashboard_bot.py` |
| ۱۲ | توکن خارج از argv (B2)، حذف default های حساس (B3) | 🟡 | `git_sync.sh` و… |
| ۱۳ | موارد کم: newline لاگ (A4)، تابع مرده blackout (A5)، Silver Bullet، pyflakes | ⚪ | متفرقه |

**جمع‌بندی یک‌خطی:** مغز سیستم (تحلیل/گیت/تست) مهندسی‌شده و بالاتر از استاندارد است؛ ولی **دستِ اجرا (بریج) از کنترل نسخه خارج است، بازوی خود-تأییدی از ۱۰ سپتامبر خوابیده، و سه باگ wiring شناخته‌شده (رژیم در merge، daily_pnl خام، مدیریت بدون پلن) دقیقاً در لایه‌های «پول» و «محافظت» نشسته‌اند.** قبل از هر تغییر استراتژی، این ۴ مورد سطح قرمز باید بسته شوند.
