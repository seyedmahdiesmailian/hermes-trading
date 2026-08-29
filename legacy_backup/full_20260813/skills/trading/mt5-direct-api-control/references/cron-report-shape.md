# Compact Cron Report Shape

Use this format for recurring MT5 trading cron outputs when the user wants less verbosity.

## Goal
Keep recurring reports short, decision-oriented, and easy to scan in chat.

## Preferred Shape
Maximum: 6 short bullets.

Recommended fields:
- account status
- strongest symbol
- likely direction
- short setup reason
- action taken or skipped
- one-line risk note if needed

## Example
- حساب: 1304.5 دلار، بدون پوزیشن باز
- بهترين نماد: USDJPY
- جهت محتمل: BUY watch
- دليل: مومنتوم بهتر از بقيه، اما تاييد HTF کامل نيست
- اقدام: فعلا ورود انجام نشد
- ريسک: فقط در صورت order_check تميز و ستاپ واضح

## Anti-Pattern
Avoid long narrative market commentary in recurring cron runs. Save deeper reasoning for foreground sessions or only summarize the conclusion in cron output.
