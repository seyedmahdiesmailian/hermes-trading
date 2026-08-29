"""
Session Analysis — London/NY/Asian session behavior and liquidity zones.

Professional traders know:
  - Asian: low volatility, accumulation, fakeouts common
  - London: highest volatility, trend initiation
  - NY: continuation/reversal, overlap with London is peak
  - Kill zones: specific hours within sessions for high-probability setups
"""
from datetime import datetime, timezone
from typing import Optional


# Session definitions (UTC)
# Using Iran = UTC+3:30, but we store in UTC for consistency
SESSIONS = {
    "asia":     {"start": 0, "end": 7,  "label": "Asian",     "volatility": "low",    "liquidity": "thin"},
    "london":   {"start": 7, "end": 13, "label": "London",    "volatility": "high",   "liquidity": "deep"},
    "newyork":  {"start": 13, "end": 20, "label": "New York",  "volatility": "high",   "liquidity": "deep"},
    "closed":   {"start": 20, "end": 24, "label": "Closed",    "volatility": "none",   "liquidity": "none"},
}

# Kill zones (UTC) — ICT concepts
KILL_ZONES = [
    {"name": "Asian Range",         "start": 0,  "end": 2,   "session": "asia",    "quality": "low"},
    {"name": "London Open",         "start": 7,  "end": 9,   "session": "london",  "quality": "high"},
    {"name": "London Close",        "start": 11, "end": 13,  "session": "london",  "quality": "medium"},
    {"name": "NY Open",             "start": 13, "end": 15,  "session": "newyork", "quality": "high"},
    {"name": "London/NY Overlap",   "start": 13, "end": 16,  "session": "newyork", "quality": "very_high"},
    {"name": "NY Close",            "start": 18, "end": 20,  "session": "newyork", "quality": "medium"},
    {"name": "Silver Bullet AM",    "start": 7,  "end": 9,   "session": "london",  "quality": "high"},
    {"name": "Silver Bullet PM",    "start": 12, "end": 14,  "session": "london",  "quality": "high"},
]


def get_session(now: Optional[datetime] = None) -> dict:
    """Detect current session. Returns dict with name, label, characteristics."""
    if now is None:
        now = datetime.now(timezone.utc)
    hour = now.hour

    # Weekend check (UTC: Fri 20:00 — Sun 22:00)
    if now.weekday() >= 5 and (now.weekday() > 5 or hour >= 20):
        return {"name": "weekend", "label": "Weekend", "volatility": "none",
                "liquidity": "none", "trade_allowed": False}

    for name, info in SESSIONS.items():
        if info["start"] <= hour < info["end"]:
            return {
                "name": name, "label": info["label"],
                "volatility": info["volatility"],
                "liquidity": info["liquidity"],
                "trade_allowed": name != "closed",
            }

    return {"name": "closed", "label": "Closed", "volatility": "none",
            "liquidity": "none", "trade_allowed": False}


def get_active_killzones(now: Optional[datetime] = None) -> list[dict]:
    """Return list of active kill zones right now."""
    if now is None:
        now = datetime.now(timezone.utc)
    hour = now.hour
    return [kz for kz in KILL_ZONES if kz["start"] <= hour < kz["end"]]


def is_high_quality_window(now: Optional[datetime] = None) -> bool:
    """True if we're in a high-quality trading window (London/NY)."""
    kzs = get_active_killzones(now)
    return any(kz["quality"] in ("high", "very_high") for kz in kzs)


def session_summary(now: Optional[datetime] = None) -> str:
    """Persian one-liner describing current session state."""
    s = get_session(now)
    kzs = get_active_killzones(now)
    kz_names = ", ".join(kz["name"] for kz in kzs) if kzs else "none"

    quality = "✅ HIGH" if is_high_quality_window(now) else "⚠️ LOW/MEDIUM"

    labels = {
        "asia": "آسیا — نوسان کم, نقدینگی رقیق",
        "london": "لندن — نوسان بالا, نقدینگی عمیق",
        "newyork": "نیویورک — نوسان بالا, ادامه/بازگشت",
        "closed": "بسته",
        "weekend": "آخر هفته — بازار بسته",
    }

    return f"سشن: {labels.get(s['name'], '?')} | کیفیت: {quality} | KillZone: {kz_names}"


def session_risk_adjustment(now: Optional[datetime] = None) -> dict:
    """Return risk adjustment based on session. Risk lower in Asian, normal in London/NY."""
    s = get_session(now)
    adjustments = {
        "asia":    {"multiplier": 0.5,  "reason": "نوسان کم — ریسک نصف"},
        "london":  {"multiplier": 1.0,  "reason": "نوسان نرمال"},
        "newyork": {"multiplier": 1.0,  "reason": "نوسان نرمال"},
        "closed":  {"multiplier": 0.0,  "reason": "بازار بسته"},
        "weekend": {"multiplier": 0.0,  "reason": "آخر هفته"},
    }
    return adjustments.get(s["name"], {"multiplier": 0.0, "reason": "unknown"})


def should_trade(now: Optional[datetime] = None) -> tuple[bool, str]:
    """Should we trade right now? Returns (should, reason)."""
    s = get_session(now)
    if not s["trade_allowed"]:
        return False, f"بازار {s['label']} — معامله مجاز نیست"
    if s["name"] == "asia" and not is_high_quality_window(now):
        return False, "سشن آسیا بدون killzone با کیفیت — skip"
    return True, f"سشن {s['label']} — معامله مجاز"


# ── Test ──
if __name__ == "__main__":
    now = datetime.now(timezone.utc)
    print(f"Now (UTC): {now.strftime('%H:%M %a')}")
    print(f"Session: {get_session(now)}")
    print(f"Kill zones: {get_active_killzones(now)}")
    print(f"High quality: {is_high_quality_window(now)}")
    print(f"\n{session_summary(now)}")
    print(f"Risk adj: {session_risk_adjustment(now)}")
    should, reason = should_trade(now)
    print(f"Trade? {should} — {reason}")
