"""Kill Switch — automatic trading halt on severe drawdown.

Monitors account health and stops all trading when:
- Daily loss exceeds threshold
- Consecutive losses too high
- Equity drops below critical level
- Margin health critical

This is the safety net that prevents catastrophic losses.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

STATE_FILE = Path("/home/ai/hermes-trading/data/kill_switch_state.json")

# ─── Kill Switch Thresholds ───
DAILY_LOSS_LIMIT_PCT = 0.05       # 5% daily loss → HALT
EQUITY_DRAWDOWN_LIMIT_PCT = 0.10  # 10% equity drawdown → HALT
CONSECUTIVE_LOSSES_LIMIT = 4      # 4 consecutive losses → HALT
MARGIN_RATIO_MIN = 10             # margin ratio < 10 → HALT
COOLDOWN_HOURS = 4                # hours to wait after halt


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {
        "halted": False,
        "halt_reason": None,
        "halted_at": None,
        "resumes_at": None,
        "consecutive_losses": 0,
        "last_check": None,
    }


def _save_state(state: dict):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def check_kill_switch(
    balance: float,
    equity: float,
    daily_pnl: float,
    consecutive_losses: int,
    margin_free: float,
    margin: float,
    now: datetime | None = None,
) -> dict:
    """Check if kill switch should be activated.

    Returns:
        dict with:
        - halted: bool (True = stop all trading)
        - reason: str (why it's halted)
        - resumes_at: str (when trading can resume)
    """
    now = now or _now()
    state = _load_state()

    # Check if already halted and if cooldown has passed
    if state.get("halted") and state.get("resumes_at"):
        resumes = datetime.fromisoformat(state["resumes_at"])
        if now < resumes:
            return {
                "halted": True,
                "reason": state.get("halt_reason", "unknown"),
                "resumes_at": state["resumes_at"],
                "remaining_minutes": int((resumes - now).total_seconds() / 60),
            }
        else:
            # Cooldown passed, resume
            state["halted"] = False
            state["halt_reason"] = None
            state["halted_at"] = None
            state["resumes_at"] = None
            _save_state(state)

    # ─── Check 1: Daily loss limit ───
    if balance > 0:
        daily_loss_pct = abs(min(0, daily_pnl)) / balance
        if daily_loss_pct >= DAILY_LOSS_LIMIT_PCT:
            return _activate_kill(state, f"daily_loss_{daily_loss_pct:.1%}", now)

    # ─── Check 2: Equity drawdown ───
    if balance > 0:
        drawdown_pct = (balance - equity) / balance
        if drawdown_pct >= EQUITY_DRAWDOWN_LIMIT_PCT:
            return _activate_kill(state, f"equity_drawdown_{drawdown_pct:.1%}", now)

    # ─── Check 3: Consecutive losses ───
    if consecutive_losses >= CONSECUTIVE_LOSSES_LIMIT:
        return _activate_kill(state, f"consecutive_losses_{consecutive_losses}", now)

    # ─── Check 4: Margin health ───
    margin_ratio = 999.0 if margin <= 0 else margin_free / margin
    if margin_ratio < MARGIN_RATIO_MIN:
        return _activate_kill(state, f"margin_ratio_{margin_ratio:.1f}", now)

    # ─── All clear ───
    state["last_check"] = now.isoformat()
    state["consecutive_losses"] = consecutive_losses
    _save_state(state)

    return {
        "halted": False,
        "reason": None,
        "resumes_at": None,
    }


def _activate_kill(state: dict, reason: str, now: datetime) -> dict:
    """Activate kill switch with cooldown."""
    from datetime import timedelta
    resumes_at = now + timedelta(hours=COOLDOWN_HOURS)

    state["halted"] = True
    state["halt_reason"] = reason
    state["halted_at"] = now.isoformat()
    state["resumes_at"] = resumes_at.isoformat()
    state["last_check"] = now.isoformat()
    _save_state(state)

    return {
        "halted": True,
        "reason": reason,
        "resumes_at": resumes_at.isoformat(),
        "remaining_minutes": COOLDOWN_HOURS * 60,
    }


def force_resume():
    """Manually resume trading (emergency override)."""
    state = _load_state()
    state["halted"] = False
    state["halt_reason"] = None
    state["halted_at"] = None
    state["resumes_at"] = None
    _save_state(state)
    return {"resumed": True}


def force_halt(reason: str = "manual_halt"):
    """Manually halt trading."""
    now = _now()
    state = _load_state()
    return _activate_kill(state, reason, now)
