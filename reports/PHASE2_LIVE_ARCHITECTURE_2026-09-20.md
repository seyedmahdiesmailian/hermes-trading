# فاز ۲ — بازبینی معماری روی برنچ به‌روز (پس از rebase روی `2fedb95`)

تاریخ: ۲۰۲۶-۰۹-۲۰
برنچ: `arena/01a0bb28-hermes-trading` — `master` دست‌نخورده
پایه: `origin/master` = `2fedb95`

## معماری زنده (تأیید روی همین درخت)

دو ماشین، یک گلوگاه اجرا:

```
Linux  مغز: hermes_master → hermes_runtime.cycle → plan/SMC → evaluate_proposal → bridge.send_order
        position_daemon هر ۵ث (نردبان/BE/trail + news_lock/time_exit)
        signal_daemon → scorer → همان executor
Windows دست: windows_bridge/bridge.py :5050  ← در این دور دست نخورده
```

ورود fail-closed است (گیت‌های حساب، ضرر روزانه، سقف پوزیشن=۱، RR، گرید، DEFCON، کول‌داون، اخبار، ساعت بازار). سیگنال تلگرام کور اجرا نمی‌شود.

آنچه از فاز ۱ روی این درخت هست و هنوز درست است: رژیم merge از `quality.regime`، هندسه H1، بایاس فقط H4، بدون re-anchor داخل زون، ATR فال‌بک ۵، PD veto، C1 گارد بدون پلن، `daily_pnl` خالص، load بدون mkdir، داشبورد ۹ یونیت.

## یافته‌های این دور (حدس نیست)

### اعمال شد

| کد | مشکل | کار |
|---|---|---|
| Sweep | `smc_analyse` جهت شکار نقدینگی را می‌ساخت (`sweep_side`) ولی به `_derive_smc_bias` همان `bool swept` را می‌داد. `True == "bearish"` هیچ‌وقت برقرار نیست → شکار امتیاز صفر. | آرگومان پنجم = `sweep_side` |
| Learning | `avg<0 و wr<0.40` گرید را سفت می‌کرد؛ `avg<0 و wr≥0.50` کف RR/سایز را. **بازه ۰.۴۰–۰.۴۹ با avg منفی هیچ تغییری نمی‌داد.** | هر expectancy منفی → همان سفت‌کردن RR و سایز (بدون بالا بردن گرید) |

### عمداً دست نخورد

- **بریج / auth / deploy** — دستور ایستاده.
- **`aggressive_premium_entry` نیم‌سایز نشد** — `tests/test_b53_style_risk.py` صریحاً ریسک کامل را پین کرده؛ لِین بد همان discount است.
- **تناوب ۵د در برابر ۱۵د** — `crontab.root.txt` و `next_reassessment` پنج دقیقه‌اند؛ `hermes-trading.timer` و متن داشبورد پانزده. بدون دیدن باکس زنده عوض کردن cadence حدس است. `flock` جلوی دو اجرای هم‌زمان را می‌گیرد.
- **خروج TP1** — b182 قبلاً نصف در میانه را برای حجم ≥۰.۰۲ سوار کرده. دستکاری دوباره بدون قیف تازه ممنوع.
- **پنجره DEFCON / تقارن reanchor BUY/SELL / حذف لِین aggressive** — قبلاً اندازه و رد شده.

### باز، ولی خارج از منطق ترید این دور

- Auth بریج fail-open اگر توکن خالی باشد (دستور: تغییر نده).
- بکاپ offsite روی HTTP بدون توکن.
- `verify_head` از ۱۰ سپتامبر BROKEN.
- `setup.sh` فقط ۳ سرویس را enable می‌کند؛ کرون را از `crontab.root.txt` می‌گذارد نه timer.
- فورواردر در ریپو آینه است؛ اجرا از مسیر دیگر.

## تست

هندسه پلن، یادگیری، b158/b157 SMC، b193، b53، بهداشت معماری: سبز.

حساب دمو. گیت fail-closed شل نشد.
