# فاز صفر — گزارش معماری، مشکلات و برنامه ادامه مسیر
**سیستم:** hermes-trading (XAUUSD) — `/home/ai/hermes-trading`
**تاریخ:** ۲۰۲۶-۱۰-۰۳ | **برنچ:** `b222-m5-pricing-wip` | **HEAD:** `cc0866d`
**روش:** راستی‌آزمایی داده زنده (SQLite/CSV/بریج/پروسه‌ها) + کد، نه فقط کد.

---

## ۱. معماری فعلی

```
┌─ Linux (192.168.10.18) ────────────────────────────────┐
│                                                         │
│  hermes_master.py ── هر ۵ دقیقه (cron)                  │
│    └─ hermes_runtime.cycle()                            │
│         ├─ context (market data)                        │
│         ├─ smc.py + plan.py → plan_history/             │
│         ├─ orchestrator → risk → auto_executor          │
│         └─ report                                       │
│                                                         │
│  signal_daemon.py (systemd, long-poll)                  │
│    └─ signal_listener.run_signal_check()                │
│         ├─ getUpdates → freshness 600s                 │
│         ├─ signal_parser.parse_signal()                 │
│         ├─ signal_decision.evaluate_signal()            │
│         └─ auto_executor → bridge                       │
│                                                         │
│  position_daemon.py (systemd, هر ۵ ثانیه)               │
│    └─ trade_management (ladder/TP/trail)                │
│                                                         │
│  forwarder (docker) → ۷ کانال → گروه سیگنال            │
└───────────────────────┬─────────────────────────────────┘
                        │ HTTP + Bearer
┌─ Windows VM (192.168.10.51) ────────────────────────────┐
│  bridge.py:5050 → MT5 → بروکر CapitalxtendLLC-MU       │
└─────────────────────────────────────────────────────────┘
```

**تکنولوژی‌ها:** Python ۳.۱۲ + venv، SQLite + CSV/JSON، systemd، cron، Telegram Bot API، HTTP bridge سرhand-written.

**وضعیت زنده (تأییدشده):**
- بریج سالم: `/api/account` بالانس ۵۰۳۶ دلار دمو.
- سرویس‌ها در حال اجرا: `hermes-signal`، `hermes-position`، `hermes-forwarder`.
- daemon سیگنال (pid 643598) زنده، heartbeat پوزیشن‌دیمون تا ۱۹:۱۹.
- **هیچ تریدی در روزهای اخیر اجرا نشده** — daemon فقط skip لاگ می‌کنه.

---

## ۲. مشکلات بحرانی

### ۲.۱ بمباران سیگنال تکراری — **خطری فعال روی پول**
`data/signals/signals_log.json` شامل ۲۰۰ ورودی است که **۱۹۹ تای آن دقیقاً یک متن یکسان** است:
`SELL XAUUSD 4450 SL 4462 TP 4414` در بازه ۱۰:۴۸–۱۹:۴۶ UTC اکتبر ۳ — یعنی هر ~۳.۳ ثانیه یک بار.

سه فرضیه رد شد (با داده):
- فورواردر مقصر نیست: ۲۷۸۱ ارسال، همه با msg-id یکتا.
- گروه سیگنال مقصر نیست: این متن در history رادیان وجود ندارد (۰ مورد).
- poller دوم مقصر نیست: فقط signal_daemon.py به signals_log.json دست دارد (اسکن `/proc/*/fd`).

**ریشه:** `getUpdates` تلگرام پیام را بازمی‌گرداند و `listener_state.json` فقط `last_update_id` را ذخیره می‌کند. **هیچ دی‌دوپی بر اساس محتوا وجود ندارد** (`check_signals`, خط ۲۸۳). یک پیام معتبر هزاران بار تصمیم `execute` تولید می‌کند.
**خطر:** اگر مسیر اجرا واقعاً باز بود، این ۱۹۹ تکرار = ۱۹۹ پوزیشن.

### ۲.۲ مسیر اجرای order واقعاً فعال نیست
همه ۱۴۶ ردیف `execution_log.csv` دارای `dry_run=True` و `ticket` خالی هستند، در حالی که `.env` و environ پروسه daemon (pid 643598) هر دو `HERMES_DRY_RUN=false` دارند.
**ریشه:** `signal_daemon.py` با `DRY_RUN` محلی صدا می‌زند، اما driver اجرا در `signal_listener.py` (خطوط ۷۷۸/۸۲۳) `dry_run` را از کانفیگ پایین‌دست می‌گیرد. این دو مسیر هماهنگ نیستند — **پل ارسال order هرگز فعال نمی‌شود.**

### ۲.۳ موتور تصمیم‌گیری بیمار
- ۶۰ پلن اخیر در `plan_history/`: **همگی bearish**، grade نامشخص.
- گزارش‌های قبلی تأیید می‌کنند: ۴۹۵ از ۵۰۰ پلن neutral.
- یعنی سیستم در عمل هیچ ورودی جدیدی تولید نمی‌کند — حتی اگر مسیر اجرا fix شود.

### ۲.۴ suite تست: ۳۸ شکست، HEAD به‌صورت رسمی BROKEN
`python3 -m unittest discover`: **۱۹۷۴ تست، ۲۷ FAIL + ۹ ERROR، EXIT=1**.
**۳۱ از ۳۸ شکست، همگی از یک خانواده‌اند:** anchor ledgerهای پین‌شده (b76/b80/b88/b108/b117/b118/b120/b127) با engine فعلی همگام نیستند. نمونه:
```
AssertionError: (99, 0.796, 78.8) != (75, 0.277, 20.8) : cached: b88 defcon_off diverged from b80
AssertionError: 1216 != 917   (b93: cycles ledger vs plan_history)
```
این‌ها anchorهای stale هستند، نه باگهای runtime. اما **اثر عملی وخیمی دارند**: `git_sync` پوش نمی‌کند، HEAD رسماً BROKEN است، و اتوپایلات برای ریکاور کردن، master را reset و ledgerها را با نسخه‌های قدیمی اسکریپت دوباره مشتق می‌کند — یعنی اصلاحات mid-session ناپدید می‌شوند.

### ۲.۵ اتوپایلات یک خطر فعال است
`hermes -z` (pid 1749932) در حال اجراست و در لاگ نوشته "leftover uncommitted code detected". این پروسه تغییرات uncommitted را `git stash` + `git stash branch` می‌کند و master را reset می‌کند. هر تغییری که بدون محافظت commit نشود، ناپدید می‌شود.

### ۲.۶ بدهی فنی ساختاری
- از ۱۷۵ فایل در `scripts/` (~۳۴ هزار خط)، فقط چند مورد production هستند؛ بقیه probe یک-off هستند (b1–b200+).
- `scripts/b140_signal_lane_regime_census.py` به production data می‌نویسد (هرچند HERMES_DATA_ROOT موقت می‌سازد).
- `tests/` ~۳۹ هزار خط / ۱۶۲ فایل — بیشتر از خود engine بزرگتر است.
- `notifier/dashboards.py` ۶۷KB یک فایل غول‌پیکر.
- پروتکل bridge سرhand-written بدون schema/versioning.

---

## ۳. آیا این معماری مناسب یک ربات حرفه‌ای است؟

**پاسخ کوتاه: نه. پایه‌ها قابل نگهداری نیستند.**

دلیل اصلی **بدهی فرآیند** است، نه فقط کد:
۱. **HEAD رسماً BROKEN است.** هیچ راهی برای اعتبارسنجی تغییر وجود ندارد. هر تغییری روی شناسه‌های پین‌شده خراب می‌شود.
۲. **اتوپایلات در حال نابود کردن کار است.** یک سرویس که master را reset می‌کند، قابل اعتماد نیست.
۳. **۳۸ شکست، همگی anchor stale.** یعنی suite تست به جای اعتبارسنجی engine، فقط snapshotهای قدیمی را چک می‌کند — ارزش صفر برای refactor.
۴. **۹۵ هزار خط کد، که ~۷۳ هزار آن probe و test است.** بخش production واقعی ~۲۲ هزار خط است، اما پیدا کردن آن در میان ۵۰۳ فایل سخت است.
۵. **سیستم در حال حاضر هیچ تریدی اجرا نمی‌کند.** پل order فعال نیست و موتور تصمیم neutral تولید می‌کند. یعنی "سیستم زنده" در عمل یک پیاده‌سازی ناقص است.

**اجزای باارزش که باید حفظ شوند:**
- `windows_bridge` (سالم، در حال کار، فقط endpoint order دارد).
- `signal_parser.py` (parse تلگرام → ساختار، منطقی).
- `trade_management.py` (ladder/TP/trail — هندسه خروج، طراحی خوب).
- `market_hours.py`، `kill_switch.py`، `defcon.py` (گاردهای fail-closed، کیفیت بالا).
- داده‌های `trade_journal` (۵۹ ترید واقعی بسته‌شده — برای یادگیری ارزشمند).

---

## ۴. برنامه ادامه مسیر

### فاز ۱ — تثبیت (فوری)
**هدف:** یک HEAD سبز، یک محیط توسعه امن، و توقف خطرات فعال.
1.1 محافظت از working tree در برابر اتوپایلات: branch جداگانه + commit سریع هر تغییر.
1.2 افزودن دی‌دوپ محتوا به `check_signals` (hash متن + chat_id + date).
1.3 یک‌سازی مسیر dry_run: یک منبع واحد در `engines/config.py`.
1.4 رفع ۳۸ شکست تست: یا anchorها را به‌روز کن، یا staleها را delete کن. هدف: HEAD سبز.
1.5 محدود کردن یا متوقف کردن اتوپایلات تا فاز ۲.

### فاز ۲ — بازطراحی زیرساخت
2.1 پاکسازی `scripts/`: انتقال probe‌ها به `archive/`، نگه‌داشتن فقط production.
2.2 تقسیم `notifier/dashboards.py` (۶۷KB).
2.3 اضافه کردن schema + versioning به پروتکل bridge.
2.4 test suite واقعی: unit test‌های سبک به جای anchor ledger.

### فاز ۳ — موتور تحلیل بازار
3.1 بازنویسی `plan.py` grade assignment (مشکل ۴۹۵/۵۰۰ neutral).
3.2 بررسی `smc.py` (۴۲KB) — آیا سیگنال واقعی تولید می‌کند؟
3.3 اتصال macro_filter به مسیر تصمیم.

### فاز ۴ — سیستم اجرای معاملات
4.1 فعال‌سازی واقعی مسیر order (پس از fix ۱.۳).
4.2 replay-controll روی execution: یک سیگنال → یک پوزیشن، نه ۱۹۹.
4.3 audit trail کامل: هر order با ticket، سیگنال مبدأ، timestamp.

### فاز ۵ — تلگرام و تحلیل سیگنال
5.1 دی‌دوپ + freshness + rate-limit روی سیگنال‌ها.
5.2 observability: چرا skip شد، چه چیزی اجرا شد.

### فاز ۶ — یادگیری و بهبود
6.1 استفاده از ۵۹ ترید واقعی + داده‌های بک‌تست.
6.2 بک‌تست framework واقعی به جای probe‌های one-off.

---

## ۵. تصمیم‌های نیاز شده

۱. **فاز ۱ تایید می‌شود؟** (محافظت working tree + دی‌دوپ + یک‌سازی dry_run + fix تست‌ها)
۲. **اتوپایلات متوقف شود یا محدود؟** (الان فعال و خطرناک)
۳. **رویکرد fix تست‌ها:** anchorها به‌روز شوند یا staleها حذف؟
