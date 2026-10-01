# WP4: SQLite Mirror — `engines/store.py` (2026-09-18)

## مشکل
سه ژورنال CSV (`execution_log`، `risk_ledger`، `trade_journal`) لاگ متنی بدون
ایندکس‌اند: هر پاس learning کل تاریخچه را از نو می‌خواند، مهاجرت هدر دستی است
(b144)، و ستون‌گذاری وسط تاپل همه خواننده‌ها را بی‌صدا می‌شکند (قانون b142).

## راه‌حل (حداقلی و برگشت‌پذیر)
- `engines/store.py` — آینه SQLite (`hermes_state.db`، حالت WAL) کنار CSVها.
- Dual-write در سه choke point و **فقط بعد از write موفق CSV**:
  `storage.append_execution_log`، `storage.append_risk_ledger`، `learning.journal`.
- قراردادها:
  1. **CSV مرجع حقیقت است.** هر خطای SQLite قورت داده می‌شود (fail-open) و مسیر
     ترید هرگز نمی‌شکند. هیچ خواننده‌ای هنوز از SQLite نمی‌خواند.
  2. ستون‌ها TEXT و بایت‌به‌بایت برابر فرم CSV (`""` برای None).
  3. کلیدهای ناشناس در `extra_json` حفظ می‌شوند — هیچ‌وقت drop، هیچ‌وقت ستون
     خودکار (قانون b142: افزودن ستون = مهاجرت اسکیما).
  4. برای جلوگیری از import cycle، `store.py` از producers ایمپورت نمی‌کند؛
     به‌جایش `tests/test_store_parity.py` برابری لیست ستون‌ها با
     `RISK_LEDGER_FIELDS` / `JOURNAL_FIELDS` / هدر ۱۲تایی b142 را پین می‌کند.
  5. چون fail-open باگ wiring را هم پنهان می‌کند، کلاس `TestWiring` صدا زده
     شدن هر سه hook را جداگانه اثبات می‌کند (درس 2026-09-18: دو ویرایش hook
     بی‌صدا ننشست و فقط تست برابری بایتی آن را گرفت).
- `scripts/backfill_sqlite.py` — بازسازی کامل db از CSVها (db قبلی حذف، CSVها
  فقط خوانده می‌شوند؛ خروجی JSON با `match` و کد خروج ۰/۱).

## مهاجرت خواننده‌ها (آینده، فاز ۳/۶)
خواننده‌ها عمداً روی CSV مانده‌اند. مسیر مهاجرت: اثبات پریتی روی دیتای زنده
(مقایسه دوره‌ای `row_counts` با تعداد سطرهای CSV) → خواننده‌ها با fallback به
CSV → حذف fallback. تا آن روز `hermes_state.db` را می‌توان هر لحظه پاک و با
backfill بازسازی کرد.
