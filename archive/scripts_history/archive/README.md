# scripts/archive/ — پروب‌های یک‌بارمصرف بازنشسته (WP3)

۱۹ فایل `_probe_*` / `_check_live` / `_risk_audit` / `_root_cause` / `_today_pnl` /
`_trade_audit` / `_trade_vs_plan` / `_why_big_loss` در WP3 به اینجا منتقل شدند.

**چرا امن است (اثبات، نه حدس):**
- صفر ارجاع در `tests/` ،`engines/` ، کد ریشه، `scripts/` ،`docs/` ،`ops/` و `setup.sh`
- همه فقط-خواندنی‌اند (`print(json.dumps(...))` به stdout) — هیچ‌کدام producer
  نیستند، پس ratchet پوشش b128 (که فقط `scripts/*.py` را اسکن می‌کند) بی‌اثر ماند
- تاریخچه گیت حفظ شده (`git mv`) — با `git log --follow` قابل پیگیری‌اند

**قانون:** چیزی از اینجا import نکنید و به cron/systemd وصل نکنید. اگر پروبی دوباره
لازم شد، با دلیل کتبی به `scripts/` برگردانید و تست مرتبط را به‌روز کنید.
