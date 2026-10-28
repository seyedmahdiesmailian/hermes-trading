"""
XAUUSD Heartbeat Module — tracks Hermes presence and decides who controls execution.

States:
  - "hermes_active": last decision < 30 min ago → Hermes decides
  - "hermes_degraded": 30-120 min since last decision → Hermes + conservative code
  - "code_fallback": > 120 min → code takes over with reduced risk

Decision-flow per cron tick:
  1. Check heartbeat file
  2. If hermes_active → collector outputs context for LLM, LLM decides
  3. If hermes_degraded → collector also outputs context, code is more cautious
  4. If code_fallback → script runs full decision internally, delivers result

File: ~/trading/xau_heartbeat/heartbeat.json
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path

HEARTBEAT_DIR = Path("/home/ai/hermes-trading/data/trading/xau_heartbeat")
HEARTBEAT_FILE = HEARTBEAT_DIR / "heartbeat.json"
HERMES_TIMEOUT_MINUTES = 30
DEGRADED_TIMEOUT_MINUTES = 120


def ensure_heartbeat_dir():
    HEARTBEAT_DIR.mkdir(parents=True, exist_ok=True)


def _now_iso() -> str:
    return datetime.now().isoformat()


def record_hermes_decision():
    """Called after every Hermes (LLM) decision to update heartbeat."""
    ensure_heartbeat_dir()
    data = {
        "last_hermes_decision": _now_iso(),
        "last_heartbeat": _now_iso(),
        "mode": "hermes_active",
        "updated_at": _now_iso(),
    }
    with open(HEARTBEAT_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def record_heartbeat_ping():
    """Called by collector script every tick — just marks we're alive."""
    ensure_heartbeat_dir()

    # Try loading existing
    existing = {}
    if HEARTBEAT_FILE.exists():
        try:
            with open(HEARTBEAT_FILE, "r", encoding="utf-8") as f:
                existing = json.load(f)
        except Exception:
            pass

    existing["last_heartbeat"] = _now_iso()
    existing["updated_at"] = _now_iso()

    with open(HEARTBEAT_FILE, "w", encoding="utf-8") as f:
        json.dump(existing, f, indent=2)


def check_hermes_status() -> dict:
    """
    Returns hermes status:
      - mode: "hermes_active" | "hermes_degraded" | "code_fallback" | "unknown"
      - minutes_since_last: int or None
      - should_defer_to_code: bool
      - risk_multiplier: float (1.0 hermes, 0.5 fallback)
    """
    ensure_heartbeat_dir()

    if not HEARTBEAT_FILE.exists():
        return {
            "mode": "unknown",
            "minutes_since_last": None,
            "should_defer_to_code": True,
            "risk_multiplier": 0.5,
        }

    try:
        with open(HEARTBEAT_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return {
            "mode": "unknown",
            "minutes_since_last": None,
            "should_defer_to_code": True,
            "risk_multiplier": 0.5,
        }

    last_decision_str = data.get("last_hermes_decision")
    if not last_decision_str:
        return {
            "mode": "code_fallback",
            "minutes_since_last": None,
            "should_defer_to_code": True,
            "risk_multiplier": 0.5,
        }

    try:
        last_decision = datetime.fromisoformat(last_decision_str)
        now = datetime.now()
        delta = (now - last_decision).total_seconds() / 60.0
    except Exception:
        return {
            "mode": "code_fallback",
            "minutes_since_last": None,
            "should_defer_to_code": True,
            "risk_multiplier": 0.5,
        }

    if delta < HERMES_TIMEOUT_MINUTES:
        mode = "hermes_active"
        defer = False
        risk = 1.0
    elif delta < DEGRADED_TIMEOUT_MINUTES:
        mode = "hermes_degraded"
        defer = False
        risk = 0.75
    else:
        mode = "code_fallback"
        defer = True
        risk = 0.5

    return {
        "mode": mode,
        "minutes_since_last": round(delta, 1),
        "should_defer_to_code": defer,
        "risk_multiplier": risk,
    }


def set_mode(mode: str):
    """Force-set mode (for testing or emergency)."""
    ensure_heartbeat_dir()
    existing = {}
    if HEARTBEAT_FILE.exists():
        try:
            with open(HEARTBEAT_FILE, "r", encoding="utf-8") as f:
                existing = json.load(f)
        except Exception:
            pass
    existing["mode"] = mode
    existing["updated_at"] = _now_iso()
    with open(HEARTBEAT_FILE, "w", encoding="utf-8") as f:
        json.dump(existing, f, indent=2)
