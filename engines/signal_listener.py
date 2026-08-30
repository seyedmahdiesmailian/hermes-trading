"""Telegram Signal Listener — monitors a group for trading signals.

Uses polling (getUpdates) to receive messages from a specified chat/group.
Filters messages that look like trading signals and passes them through
the signal parser and decision engine.

This is designed to be run as a periodic check (via cron) rather than
a long-running daemon, keeping it simple and reliable.
"""
from __future__ import annotations

import json
import os
import re
import urllib.request
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:
    from env_loader import load_dotenv  # python-dotenv missing → local fallback
load_dotenv(Path(__file__).parent.parent / ".env")

__all__ = ["check_signals", "run_signal_check"]

DATA_DIR = Path('/home/ai/hermes-trading/data/signals')
DATA_DIR.mkdir(parents=True, exist_ok=True)
STATE_FILE = DATA_DIR / 'listener_state.json'
SIGNAL_LOG = DATA_DIR / 'signals_log.json'


def _get_env():
    token = os.getenv('TELEGRAM_BOT_TOKEN', '')
    chat_id = os.getenv('TELEGRAM_CHAT_ID', '194015957')
    return token, chat_id


def _telegram_api(method: str, params: dict = None) -> dict | None:
    """Call Telegram Bot API via urllib."""
    token, _ = _get_env()
    if not token:
        return None
    try:
        url = f"https://api.telegram.org/bot{token}/{method}"
        if params:
            data = urllib.parse.urlencode(params).encode('utf-8')
            req = urllib.request.Request(url, data=data, method='POST')
        else:
            req = urllib.request.Request(url)
        resp = urllib.request.urlopen(req, timeout=15)
        return json.loads(resp.read().decode('utf-8'))
    except Exception:
        return None


def _load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding='utf-8'))
        except Exception:
            pass
    return {"last_update_id": 0}


def _save_state(state: dict):
    STATE_FILE.write_text(json.dumps(state), encoding='utf-8')


def _log_signal(signal_text: str, parsed: dict, decision: dict):
    """Append to signals log."""
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "raw_text": signal_text[:500],
        "parsed": parsed,
        "decision": decision,
    }
    log = []
    if SIGNAL_LOG.exists():
        try:
            log = json.loads(SIGNAL_LOG.read_text(encoding='utf-8'))
        except Exception:
            log = []
    log.append(entry)
    # Keep last 200 entries
    if len(log) > 200:
        log = log[-200:]
    SIGNAL_LOG.write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding='utf-8')


def fetch_new_messages() -> list[dict]:
    """Fetch new messages since last update."""
    state = _load_state()
    params = {"offset": str(state.get("last_update_id", 0) + 1), "timeout": "1"}
    result = _telegram_api("getUpdates", params)
    if not result or not result.get("ok"):
        return []

    updates = result.get("result", [])
    messages = []
    max_update_id = state.get("last_update_id", 0)

    for update in updates:
        uid = update.get("update_id", 0)
        if uid > max_update_id:
            max_update_id = uid
        # Support regular messages, channel posts, and edited variants
        msg = (update.get("message") or update.get("channel_post")
               or update.get("edited_message") or update.get("edited_channel_post") or {})
        text = msg.get("text", "") or msg.get("caption", "")
        if not text:
            continue
        chat = msg.get("chat", {})
        sender = msg.get("from", {}) or msg.get("author_signature", "")
        messages.append({
            "update_id": uid,
            "chat_id": str(chat.get("id", "")),
            "chat_title": chat.get("title") or chat.get("username") or "",
            "from": sender.get("first_name", "") if isinstance(sender, dict) else str(sender),
            "text": text,
            "date": msg.get("date", 0),
        })

    state["last_update_id"] = max_update_id
    state["last_check"] = datetime.now(timezone.utc).isoformat()
    _save_state(state)
    return messages


def is_likely_signal(text: str) -> bool:
    """Quick heuristic: does this message look like a trading signal?"""
    from engines.signal_parser import normalize_digits
    text = normalize_digits(text)
    lower = text.lower()
    has_direction = any(kw in lower for kw in [
        "buy", "sell", "long", "short",
        "\u062e\u0631\u06cc\u062f", "\u0641\u0631\u0648\u0634",  # خرید فروش
        "\u0633\u0644", "\u0628\u0627\u06cc",  # سل بای
        "\u0627\u0633\u062a\u0627\u067e", "\u0647\u062f\u0641",  # استاپ هدف
        "\U0001f7e2", "\U0001f534", "\U0001f4c8", "\U0001f4c9",
    ])
    # 2+ digits: signal groups abbreviate prices ('76' = 4476)
    has_price = bool(re.search(r'\d{2,6}(?:\.\d{1,4})?', text))
    has_symbol = any(sym in lower for sym in [
        "xau", "gold", "eur", "gbp", "usd", "btc", "nas",
        "us30", "silver", "\u0646\u0642\u0631\u0647", "\u0637\u0644\u0627",
    ])
    return has_direction and (has_price or has_symbol)


def check_signals(bridge=None) -> list[dict]:
    """Main entry: check for new signal messages, parse and evaluate them."""
    from engines.signal_parser import parse_signal
    from engines.signal_decision import evaluate_signal

    messages = fetch_new_messages()
    signals_found = []
    allowed_chats = {c.strip() for c in (os.getenv('TELEGRAM_SIGNAL_GROUP', '') or '').split(',') if c.strip()}

    for msg in messages:
        # Only accept signals from the configured signal group(s)
        if allowed_chats and msg.get("chat_id") not in allowed_chats:
            continue
        # Freshness gate: getUpdates replays the 24h buffer after downtime —
        # a 5h-old signal executed at today's price is a guaranteed loss.
        _age = datetime.now(timezone.utc).timestamp() - float(msg.get("date") or 0)
        if _age > 600:
            continue
        if not is_likely_signal(msg["text"]):
            continue

        # Live price for abbreviated-price expansion ('76' → 4476)
        cur_price = 0.0
        try:
            if bridge is not None:
                tick = bridge.get_tick("XAUUSD") or {}
                cur_price = float(tick.get("ask") or tick.get("bid") or 0)
        except Exception:
            pass

        parsed = parse_signal(msg["text"], current_price=cur_price)
        if not parsed.is_valid:
            continue

        parsed_dict = parsed.to_dict()

        # Get Hermes current analysis
        hermes_analysis = {}
        account_policy = {"trade_allowed": True, "regime": "normal", "open_positions": 0}
        try:
            from engines.storage import load_current_plan
            plan = load_current_plan(Path('/home/ai/hermes-trading/data/xau_plan'))
            if plan:
                hermes_analysis = {
                    "bias": plan.get("bias", "neutral"),
                    "quality": plan.get("quality", {}),
                }
        except Exception:
            pass
        # REAL account policy: kill-switch, daily loss, regime — the hard-coded
        # trade_allowed=True above bypassed every safety gate for signals.
        try:
            from engines.kill_switch import check_kill_switch
            account = bridge.get_account() if bridge is not None else {}
            acct = account.get("data", account) if isinstance(account, dict) else {}
            _now = datetime.now(timezone.utc)
            from engines.storage import load_performance_state
            _perf = load_performance_state(Path('/home/ai/hermes-trading/data/xau_plan'))
            _kill = check_kill_switch(
                balance=float(acct.get("balance", 0) or 0),
                equity=float(acct.get("equity", 0) or 0),
                daily_pnl=float(_perf.get("daily_pnl", 0) or 0),
                consecutive_losses=int(_perf.get("loss_streak", 0) or 0),
                margin_free=float(acct.get("margin_free", 0) or 0),
                margin=float(acct.get("margin", 0) or 0),
                now=_now,
            )
            account_policy = {
                "trade_allowed": not _kill.get("halted", False),
                "regime": "halted" if _kill.get("halted") else "normal",
                "open_positions": 0,
            }
        except Exception:
            pass  # fail-open to the previous behavior rather than blocking signals on tooling bugs

        # News blackout for the signal path too — evaluate_signal has the
        # gate (Check 7) but nobody ever passed macro_filter, so it was dead.
        _macro_filter = None
        try:
            from engines.economic_calendar import fetch_economic_calendar
            from engines.macro_filter import evaluate_macro_filter
            _macro_filter = evaluate_macro_filter(fetch_economic_calendar(), _now)
        except Exception:
            pass

        decision = evaluate_signal(parsed_dict, hermes_analysis, account_policy,
                                   macro_filter=_macro_filter)

        signal_record = {
            "from": msg["from"],
            "text": msg["text"][:300],
            "parsed": parsed_dict,
            "decision": decision,
            "timestamp": msg.get("date"),
        }
        signals_found.append(signal_record)
        _log_signal(msg["text"], parsed_dict, decision)

    return signals_found


def run_signal_check(bridge, dry_run: bool = False) -> dict:
    """Main entry for integration with hermes_master.

    Checks for new signals, evaluates them, executes approved ones,
    and returns execution results for reporting.
    """
    PLAN_DIR = Path("/home/ai/hermes-trading/data/xau_plan")

    signals = check_signals(bridge=bridge)
    if not signals:
        return {"ok": True, "signals_found": 0, "executions": []}

    # Get real account state
    account_resp = bridge.get_account()
    executions = []

    for sig_record in signals:
        decision = sig_record.get("decision", {})

        if not decision.get("trade_allowed"):
            executions.append({
                "signal": sig_record["parsed"],
                "verdict": decision.get("verdict", "skip"),
                "reasons": decision.get("reasons", []),
                "executed": False,
            })
            continue

        # Build execution command from signal
        parsed = sig_record["parsed"]

        # Staleness guard: if price moved far from signal entry, skip
        try:
            tick = bridge.get_tick(parsed["symbol"]) or {}
            cur = float(tick.get("ask") or tick.get("bid") or 0)
            entry = float(parsed.get("entry") or 0)
            sl = float(parsed.get("sl") or 0)
            risk_dist = abs(entry - sl) if sl > 0 else 10.0
            if cur > 0 and entry > 0 and abs(cur - entry) > max(risk_dist * 0.5, 5.0):
                executions.append({
                    "signal": parsed, "verdict": "skip",
                    "reasons": [f"stale_entry_price_moved_{abs(cur-entry):.1f}pts (current {cur})"],
                    "executed": False,
                })
                continue
        except Exception:
            pass

        command = {
            "side": parsed["side"],
            "lot": parsed.get("lot", 0.01) or 0.01,
            "symbol": parsed["symbol"],
            "sl": parsed["sl"],
            "tp": parsed["tp"],
            "entry": parsed["entry"],
            "sl_points": int(round(abs(parsed["entry"] - parsed["sl"]) / 0.01)) if parsed["sl"] > 0 else 0,
            "tp_points": int(round(abs(parsed["tp"] - parsed["entry"]) / 0.01)) if parsed["tp"] > 0 else 0,
        }

        # ── Final safety gates BEFORE any order (same as the plan path) ──
        # 1) market hours — the signal path used to skip this entirely
        from engines.market_hours import is_market_open
        if not is_market_open():
            executions.append({
                "signal": parsed, "verdict": "skip",
                "reasons": ["market_closed"],
                "executed": False,
            })
            continue
        # 2) open-positions cap — signals used to bypass MAX_OPEN_POSITIONS
        try:
            _pos_resp = bridge.get_positions(parsed["symbol"]) or {}
            _live = _pos_resp.get("data", _pos_resp.get("positions", []))
            if isinstance(_live, list) and len(_live) >= 2:
                executions.append({
                    "signal": parsed, "verdict": "skip",
                    "reasons": ["position_limit"],
                    "executed": False,
                })
                continue
        except Exception:
            pass

        # Execute via auto_executor
        from engines.auto_executor import execute_trade
        result = execute_trade(command, bridge, dry_run=dry_run)

        executions.append({
            "signal": parsed,
            "verdict": "execute",
            "reasons": decision.get("reasons", []),
            "executed": result.get("executed", False),
            "result": result,
        })

        # Log execution
        from engines.storage import append_execution_log
        append_execution_log(PLAN_DIR, {
            "at": datetime.now(timezone.utc).isoformat(),
            "source": "signal_listener",
            "plan_id": "signal",
            "side": command["side"],
            "lot": command["lot"],
            "entry": command["entry"],
            "sl": command["sl"],
            "tp": command["tp"],
            "grade": "signal",
            "risk_usd": 0,
            "dry_run": dry_run,
            "result_ok": result.get("ok", False),
            "ticket": (result.get("result") or {}).get("ticket"),
        })

    return {
        "ok": True,
        "signals_found": len(signals),
        "executions": executions,
    }
