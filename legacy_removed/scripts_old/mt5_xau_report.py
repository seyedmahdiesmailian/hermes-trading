from __future__ import annotations

from datetime import datetime, timedelta, timezone

IRAN_TZ = timezone(timedelta(hours=3, minutes=30))


def _bias_fa(bias: str | None) -> str:
    mapping = {
        "bullish": "صعودی",
        "bearish": "نزولی",
        "neutral": "خنثی",
    }
    return mapping.get((bias or "").lower(), str(bias))


def _zone_fa(zone: str | None) -> str:
    mapping = {
        "premium": "بالای ناحیه‌های ورود",
        "discount": "پایین ناحیه‌های ورود",
        "value_zone": "داخل محدوده ارزش",
        "long_zone": "داخل محدوده خرید",
        "short_zone": "داخل محدوده فروش",
    }
    return mapping.get(zone, str(zone))


def _action_fa(action: str | None) -> str:
    mapping = {
        "no_trade": "فعلاً ورود نداریم",
        "wait_for_trigger": "منتظر تأیید ورود",
        "market_order": "ورود در بازار",
        "market_entry_now": "ورود فوری",
        "partial_take_profit": "برداشت بخشی از سود",
        "move_stop_to_breakeven": "جابجایی حد ضرر به سربه‌سر",
        "trail_stop": "تریل حد ضرر",
        "scale_in_existing_idea": "اضافه‌کردن پله‌ای",
        "hold": "نگهداری معامله",
        "close_runner": "بستن رانر",
        "close_trade_early": "خروج زودتر از موعد",
    }
    return mapping.get(action, str(action))


def _side_fa(command: str | None) -> str:
    mapping = {
        "buy": "خرید",
        "sell": "فروش",
    }
    return mapping.get((command or "").lower(), str(command))


def _symbol_fa(symbol: str | None) -> str:
    mapping = {
        "XAUUSD": "طلا",
    }
    return mapping.get(symbol, str(symbol))


def _coerce_dt(value: str | datetime | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(value)


def _fmt_price(value) -> str:
    if value is None:
        return "نامشخص"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    text = f"{number:.2f}"
    return text.rstrip("0").rstrip(".") if "." in text else text


def _fmt_range(low, high) -> str:
    return f"{_fmt_price(low)} تا {_fmt_price(high)}"


def format_reassessment_time(value: str | None, now_value: str | datetime | None = None) -> str:
    if not value:
        return "نامشخص"
    dt = _coerce_dt(value)
    iran_dt = dt.astimezone(IRAN_TZ)
    now_dt = _coerce_dt(now_value) or datetime.now(timezone.utc)
    now_iran = now_dt.astimezone(IRAN_TZ)
    date_label = iran_dt.strftime('%Y-%m-%d')
    if iran_dt.date() == now_iran.date():
        prefix = "امروز"
    elif iran_dt.date() == (now_iran.date() + timedelta(days=1)):
        prefix = "فردا"
    else:
        prefix = date_label
    diff = dt - now_dt
    relative = ""
    if timedelta(0) < diff <= timedelta(hours=6):
        hours = int(round(diff.total_seconds() / 3600))
        if hours <= 0:
            hours = 1
        relative = f" | حدود {hours} ساعت دیگر"
    return f"{prefix} {iran_dt.strftime('%H:%M')} | ساعت ایران{relative}"


def _plan_scenario_fa(plan: dict) -> str:
    bias = (plan.get("bias") or "").lower()
    price = plan.get("reference_price")
    zones = plan.get("zones", {})
    long_low = zones.get("long_entry_low")
    long_high = zones.get("long_entry_high")
    short_low = zones.get("short_entry_low")
    short_high = zones.get("short_entry_high")

    if bias == "bullish":
        if price is not None and long_high is not None and price > long_high:
            return "فعلاً منتظر برگشت قیمت به محدوده خرید هستیم"
        if price is not None and long_low is not None and long_high is not None and long_low <= price <= long_high:
            return "قیمت داخل محدوده خرید است؛ اگر تأیید بدهد برای ورود آماده می‌مانیم"
        return "اگر قیمت به محدوده خرید برسد، دنبال تأیید ورود می‌مانیم"

    if bias == "bearish":
        if price is not None and short_low is not None and short_high is not None and short_low <= price <= short_high:
            return "قیمت نزدیک محدوده فروش است؛ اگر رد شود برای فروش آماده می‌مانیم"
        if price is not None and short_low is not None and price < short_low:
            return "فعلاً منتظر برگشت قیمت به محدوده فروش هستیم"
        return "اگر قیمت به محدوده فروش برسد، دنبال تأیید ورود می‌مانیم"

    return "فعلاً پلن خنثی است و عجله‌ای برای ورود نداریم"


def _monitor_explanation_fa(monitor: dict) -> str:
    action = monitor.get("action")
    zone = monitor.get("zone")
    if action == "wait_for_trigger" and zone == "long_zone":
        return "قیمت داخل محدوده خرید است"
    if action == "wait_for_trigger" and zone == "short_zone":
        return "قیمت داخل محدوده فروش است"
    if action == "no_trade" and zone == "premium":
        return "قیمت بالاتر از ناحیه ورود است"
    if action == "no_trade" and zone == "discount":
        return "قیمت پایین‌تر از ناحیه ورود است"
    return f"قیمت {_zone_fa(zone)} است"


def render_plan_brief(plan: dict) -> str:
    zones = plan.get("zones", {})
    symbol = _symbol_fa(plan.get("symbol"))
    bias = _bias_fa(plan.get("bias"))
    scenario = _plan_scenario_fa(plan)
    return "\n".join([
        f"📘 پلن جدید | {symbol}",
        f"جهت | {bias}",
        f"محدوده خرید | {_fmt_range(zones.get('long_entry_low'), zones.get('long_entry_high'))}",
        f"محدوده فروش | {_fmt_range(zones.get('short_entry_low'), zones.get('short_entry_high'))}",
        f"سناریو | {scenario}",
        f"بازبینی بعدی | {format_reassessment_time(plan.get('next_reassessment'))}",
    ])


def render_reassess_brief(old_plan: dict | None, new_plan: dict) -> str:
    symbol = _symbol_fa(new_plan.get("symbol"))
    old_bias = _bias_fa((old_plan or {}).get("bias"))
    new_bias = _bias_fa(new_plan.get("bias"))
    zones = new_plan.get("zones", {})
    change_line = f"جهت | {new_bias}" if old_bias == new_bias else f"تغییر جهت | از {old_bias} به {new_bias}"
    return "\n".join([
        f"🔄 بازبینی پلن | {symbol}",
        change_line,
        f"محدوده خرید | {_fmt_range(zones.get('long_entry_low'), zones.get('long_entry_high'))}",
        f"محدوده فروش | {_fmt_range(zones.get('short_entry_low'), zones.get('short_entry_high'))}",
        f"بازبینی بعدی | {format_reassessment_time(new_plan.get('next_reassessment'))}",
    ])


def render_monitor_brief(plan: dict, monitor: dict) -> str:
    symbol = _symbol_fa(plan.get("symbol"))
    return "\n".join([
        f"👀 پایش | {symbol}",
        f"جهت | {_bias_fa(plan.get('bias'))}",
        f"وضعیت | {_action_fa(monitor.get('action'))}",
        f"توضیح | {_monitor_explanation_fa(monitor)}",
        f"قیمت | {_fmt_price(monitor.get('price'))}",
    ])


def render_execution_brief(plan: dict, execution: dict) -> str:
    command = execution.get("command") or []
    side = _side_fa(command[0] if len(command) > 0 else None)
    symbol = _symbol_fa(command[1] if len(command) > 1 else plan.get("symbol"))
    volume = command[2] if len(command) > 2 else "?"
    status = "موفق" if execution.get("ok") else "ناموفق"
    return "\n".join([
        f"✅ اجرای معامله | {symbol}",
        f"اقدام | {side}",
        f"حجم | {volume}",
        f"نتیجه | {status}",
    ])


def render_management_brief(plan: dict, management: dict) -> str:
    symbol = _symbol_fa(plan.get("symbol"))
    action = management.get("action")
    lines = [
        f"🛠 مدیریت معامله | {symbol}",
        f"اقدام | {_action_fa(action)}",
    ]
    if action == "partial_take_profit":
        ratio = float(management.get("close_fraction", 0.0) or 0.0)
        lines.append(f"حجم خروج | {int(round(ratio * 100))}٪")
        lines.append(f"تارگت خورده | {_fmt_price(management.get('target_hit'))}")
    elif action in {"move_stop_to_breakeven", "trail_stop"}:
        lines.append(f"حد ضرر جدید | {_fmt_price(management.get('new_sl'))}")
    elif action == "scale_in_existing_idea":
        lines.append(f"پله جدید | {_fmt_price(management.get('scale_level'))}")
    elif action in {"close_runner", "close_trade_early"}:
        lines.append("حجم خروج | خروج کامل")
    return "\n".join(lines)
