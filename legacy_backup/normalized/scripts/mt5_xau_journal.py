"""
XAUUSD Decision Journal — records every Hermes trading decision with rationale.

Architecture:
  - Hermes (LLM) makes decision → journal entry saved.
  - Code (executor) only writes execution results, never decisions.
  - Weekly review: Hermes reads journal, learns patterns, updates code.

Journal structure (JSON):
  {
    "id": "j_20260808_153000_01",
    "timestamp": "2026-08-08T15:30:00+03:30",
    "decision_by": "hermes",     # "hermes" or "code_fallback"
    "session": "london",
    "market_snapshot": {
      "price": 4285.12,
      "bias": "neutral",
      "regime": "range",
      "smc_confidence": 0.87,
      "value_zone": [4141.88, 4276.07],
      "atr": 12.5
    },
    "decision": {
      "action": "wait",           # "enter_buy", "enter_sell", "close", "modify", "wait", "no_trade"
      "reasoning": "...",         # Persian rationale
      "risk_check": { ... }
    },
    "execution": null,            # filled after trade executes
    "outcome": null,              # filled after trade closes
    "lessons": null               # filled during weekly review
  }
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path

JOURNAL_DIR = Path(r"C:\Users\Administrator\AppData\Local\hermes\trading\xau_journal")


def _tz_now():
    """Returns datetime in +03:30 (Iran time)."""
    return datetime.now(timezone.utc) if False else datetime.now()


def ensure_journal_dir():
    JOURNAL_DIR.mkdir(parents=True, exist_ok=True)


def generate_entry_id(ts: datetime) -> str:
    """j_YYYYMMDD_HHMMSS_seq"""
    date_part = ts.strftime("%Y%m%d_%H%M%S")
    existing = list(JOURNAL_DIR.glob(f"j_{date_part}_*.json"))
    seq = len(existing) + 1
    return f"j_{date_part}_{seq:02d}"


def create_decision_entry(
    decision_by: str,
    session: str,
    market_snapshot: dict,
    action: str,
    reasoning: str,
    risk_check: dict | None = None,
    blueprint: dict | None = None,
) -> dict:
    """Create a journal entry for a Hermes decision."""
    ensure_journal_dir()
    now = _tz_now()
    entry_id = generate_entry_id(now)

    entry = {
        "id": entry_id,
        "timestamp": now.isoformat(),
        "decision_by": decision_by,
        "session": session,
        "market_snapshot": market_snapshot,
        "decision": {
            "action": action,
            "reasoning": reasoning,
            "risk_check": risk_check or {},
        },
        "execution": None,
        "outcome": None,
        "lessons": None,
    }

    filepath = JOURNAL_DIR / f"{entry_id}.json"
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(entry, f, indent=2, ensure_ascii=False, default=str)

    return entry


def record_execution(entry_id: str, execution_result: dict):
    """Record trade execution details for a journal entry."""
    filepath = JOURNAL_DIR / f"{entry_id}.json"
    if not filepath.exists():
        return

    with open(filepath, "r", encoding="utf-8") as f:
        entry = json.load(f)

    entry["execution"] = execution_result

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(entry, f, indent=2, ensure_ascii=False, default=str)


def record_outcome(entry_id: str, outcome: dict):
    """Record trade outcome (P&L, duration, stop reason) for a journal entry."""
    filepath = JOURNAL_DIR / f"{entry_id}.json"
    if not filepath.exists():
        return

    with open(filepath, "r", encoding="utf-8") as f:
        entry = json.load(f)

    entry["outcome"] = outcome

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(entry, f, indent=2, ensure_ascii=False, default=str)


def record_lessons(entry_id: str, lessons: str):
    """Record lessons learned during weekly review."""
    filepath = JOURNAL_DIR / f"{entry_id}.json"
    if not filepath.exists():
        return

    with open(filepath, "r", encoding="utf-8") as f:
        entry = json.load(f)

    entry["lessons"] = lessons

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(entry, f, indent=2, ensure_ascii=False, default=str)


def load_recent_entries(days: int = 7) -> list[dict]:
    """Load journal entries from the last N days."""
    ensure_journal_dir()
    cutoff = _tz_now()
    entries = []
    for f in sorted(JOURNAL_DIR.glob("j_*.json")):
        try:
            with open(f, "r", encoding="utf-8") as fp:
                entry = json.load(fp)
            entries.append(entry)
        except Exception:
            continue
    return entries


def get_last_hermes_decision_time() -> str | None:
    """Get timestamp of the last Hermes decision (not code fallback)."""
    entries = load_recent_entries()
    hermes_entries = [e for e in entries if e.get("decision_by") == "hermes"]
    if not hermes_entries:
        return None
    return hermes_entries[-1]["timestamp"]


def journal_summary(days: int = 7) -> dict:
    """Return summary stats from recent journal entries."""
    entries = load_recent_entries()
    total = len(entries)
    hermes_decisions = sum(1 for e in entries if e.get("decision_by") == "hermes")
    fallback = sum(1 for e in entries if e.get("decision_by") == "code_fallback")
    trades = [e for e in entries if e.get("outcome")]
    wins = sum(1 for t in trades if float(t.get("outcome", {}).get("pnl", 0) or 0) > 0)
    losses = len(trades) - wins
    total_pnl = sum(float(t.get("outcome", {}).get("pnl", 0) or 0) for t in trades)

    return {
        "total_entries": total,
        "hermes_decisions": hermes_decisions,
        "fallback_decisions": fallback,
        "trades_closed": len(trades),
        "wins": wins,
        "losses": losses,
        "win_rate": round(wins / len(trades) * 100, 1) if trades else 0.0,
        "total_pnl": round(total_pnl, 2),
    }
