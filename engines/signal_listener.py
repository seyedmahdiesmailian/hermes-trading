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

from engines import paths  # resolved at CALL time so tests can redirect the tree
from engines import signal_pending


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
            # Telegram Bot API expects list/dict params as JSON strings;
            # urlencode would mangle a Python list into str(list).
            flat = {k: (json.dumps(v) if isinstance(v, (list, dict)) else str(v))
                    for k, v in params.items()}
            data = urllib.parse.urlencode(flat).encode('utf-8')
            req = urllib.request.Request(url, data=data, method='POST')
        else:
            req = urllib.request.Request(url)
        resp = urllib.request.urlopen(req, timeout=15)
        return json.loads(resp.read().decode('utf-8'))
    except Exception:
        return None


def _load_state() -> dict:
    state_file = paths.listener_state()
    if state_file.exists():
        try:
            return json.loads(state_file.read_text(encoding='utf-8'))
        except Exception:
            pass
    return {"last_update_id": 0}


def _save_state(state: dict):
    paths.write_json_atomic(paths.listener_state(), state)


def _log_signal(signal_text: str, parsed: dict, decision: dict):
    """Append to signals log."""
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "raw_text": signal_text[:500],
        "parsed": parsed,
        "decision": decision,
    }
    log_file = paths.signals_log()
    log = paths.read_json_safe(log_file, [], label="signals_log")
    if not isinstance(log, list):
        log = []
    log.append(entry)
    # Keep last 200 entries
    if len(log) > 200:
        log = log[-200:]
    paths.write_json_atomic(log_file, log, indent=2)


def _serve_trade_command(chat_id: str, text: str):
    """b38: /panel /status /plan /positions /pnl /risk on the trade bot."""
    from notifier import dashboards
    cmd = text.split()[0].lstrip('/').split('@')[0].lower()
    panel = {'panel': 'home', 'status': 'home', 'start': 'home', 'help': 'home',
             'plan': 'plan', 'positions': 'pos', 'pos': 'pos',
             'pnl': 'pnl', 'risk': 'risk', 'stats': 'stats',
             'signals': 'sig', 'sig': 'sig', 'control': 'control'}.get(cmd, 'home')
    try:
        body, kb = dashboards.trade_render(panel)
        if panel == 'home' and cmd in ('help', 'start'):
            body += ('\n\nدستورات: /plan /positions /pnl /stats /signals /risk /control\n'
                     'یا از دکمه‌های زیر استفاده کن.')
        _telegram_api("sendMessage", {
            "chat_id": chat_id, "text": body, "parse_mode": "HTML",
            "reply_markup": json.dumps({"inline_keyboard": kb}, ensure_ascii=False)})
    except Exception:
        pass


def _serve_trade_callback(cb: dict):
    """b38/b40: trader dashboard buttons. SECURITY: only the owner chat is
    served; anyone else gets a bare 'no access' answer and no data.
    b40 adds nested panels (tr:<panel>, tr:pos:<id>, tr:ask:<action>) and
    two-step-confirmed operator actions (tr:cfm:<action>)."""
    from notifier import dashboards
    qid = cb.get("id", "")
    data = ((cb.get("data") or "") + "")
    chat = str(((cb.get("message") or {}).get("chat") or {}).get("id", ""))
    owner = str(os.getenv('TELEGRAM_CHAT_ID', '194015957'))
    if chat != owner:
        _telegram_api("answerCallbackQuery", {"callback_query_id": qid,
                                              "text": "دسترسی نیست", "show_alert": True})
        return
    msg_id = (cb.get("message") or {}).get("message_id")
    panel = data[3:] if data.startswith("tr:") else "home"

    def _show(text, kb, alert=False):
        _telegram_api("editMessageText", {
            "chat_id": chat, "message_id": msg_id,
            "text": text, "parse_mode": "HTML",
            "reply_markup": json.dumps({"inline_keyboard": kb}, ensure_ascii=False)})
        _telegram_api("answerCallbackQuery", {"callback_query_id": qid,
                                              "text": "", "show_alert": alert})

    try:
        if panel.startswith("cfm:"):
            # confirmed operator action — execute, then show fresh control panel
            ok, msg = dashboards.handle_control(panel[4:])
            body, kb = dashboards.trade_render("control")
            _show(f"{msg}\n\n{body}", kb, alert=True)
            return
        text, kb = dashboards.trade_render(panel)
        _show(text, kb)
    except Exception:
        _telegram_api("answerCallbackQuery", {"callback_query_id": qid,
                                              "text": "خطا در نمایش پنل", "show_alert": True})


def fetch_new_messages() -> list[dict]:
    """Fetch new messages since last update."""
    state = _load_state()
    # b38fix: this bot token is shared with the Hermes gateway, which set
    # allowed_updates=[message, channel_post] server-side — Telegram then
    # NEVER delivers callback_query, so dashboard buttons looked dead.
    # Declaring the types per-request overrides the server-side filter.
    params = {"offset": str(state.get("last_update_id", 0) + 1), "timeout": "1",
              "allowed_updates": ["message", "channel_post", "edited_message",
                                  "edited_channel_post", "callback_query"]}
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
        # b38: inline-keyboard callbacks for the trader dashboard are served in
        # THIS loop on purpose — a second getUpdates poller on the same bot
        # token would 409 and silently drop signals.
        cb = update.get("callback_query")
        if cb:
            _serve_trade_callback(cb)
            continue
        # Support regular messages, channel posts, and edited variants
        msg = (update.get("message") or update.get("channel_post")
               or update.get("edited_message") or update.get("edited_channel_post") or {})
        # b38: '/' commands from the owner chat open/refresh the dashboard
        # instead of falling through to the signal parser. Age-gated like
        # signals: getUpdates replays a 24h buffer after a restart.
        _txt = ((msg.get("text") or "") or "").strip()
        _cid = str(((msg.get("chat") or {}).get("id", "")))
        if _txt.startswith('/') and _cid == str(os.getenv('TELEGRAM_CHAT_ID', '194015957')):
            if datetime.now(timezone.utc).timestamp() - float(msg.get("date") or 0) <= 600:
                _serve_trade_command(_cid, _txt)
            continue
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
    from engines.signal_parser import parse_signal, names_other_instrument
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
        # b74g: the forwarder dumps all 7 channels into one group, and some of
        # them (otsfx is ~69%) post FX pairs. A 5-digit FX price gets resolved
        # into a plausible-looking gold number, so this must be rejected on the
        # TEXT, before any gold price logic touches it.
        if names_other_instrument(msg["text"]):
            continue

        # Live price for abbreviated-price expansion ('76' → 4476)
        cur_price = 0.0
        price_band = None
        try:
            if bridge is not None:
                tick = bridge.get_tick("XAUUSD") or {}
                cur_price = float(tick.get("ask") or tick.get("bid") or 0)
                price_band = bridge.get_price_band("XAUUSD", hours=24)
        except Exception:
            pass

        parsed = parse_signal(msg["text"], current_price=cur_price,
                              price_band=price_band)
        if not parsed.is_valid:
            continue

        parsed_dict = parsed.to_dict()

        # Get Hermes current analysis
        hermes_analysis = {}
        account_policy = {"trade_allowed": True, "regime": "normal", "open_positions": 0}
        try:
            from engines.storage import load_current_plan
            plan = load_current_plan(paths.plan_dir())
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
            _perf = load_performance_state(paths.plan_dir())
            _kill = check_kill_switch(
                balance=float(acct.get("balance", 0) or 0),
                equity=float(acct.get("equity", 0) or 0),
                daily_pnl=float(_perf.get("daily_pnl", 0) or 0),
                consecutive_losses=int(_perf.get("loss_streak", 0) or 0),
                margin_free=float(acct.get("margin_free", 0) or 0),
                margin=float(acct.get("margin", 0) or 0),
                now=_now,
            )
            # REAL open-position count — hardcoded 0 made the decision engine
            # blind to existing exposure (already_in_position check never fired)
            _open_ct = 0
            try:
                from engines.bridge_payload import position_count
                _pr = bridge.get_positions("XAUUSD") or {} if bridge is not None else {}
                # b66-follow-up: shape-safe reader — a 401/MT5-error reply
                # carries data as a DICT; len() of it used to count envelope
                # KEYS as positions (and a non-list would raise → caught →
                # _open_ct=0 → the already_in_position gate goes blind).
                _open_ct = position_count(_pr)
            except Exception:
                pass
            account_policy = {
                "trade_allowed": not _kill.get("halted", False),
                "regime": "halted" if _kill.get("halted") else "normal",
                "open_positions": _open_ct,
                "balance": float(acct.get("balance", 0) or 0),
            }
            # b140 TIGHTENING: the regime used to be hardcoded "normal" here,
            # so the SCORER never saw drawdown states (locked/defensive/
            # recovery) even though the sizing lane (run_signal_check ->
            # _performance_and_policy) did. Wire the real emitter in: kill-
            # switch halt still wins the NAME ("halted"), but trade_allowed is
            # now the AND of both gates, and a locked account costs the -5.0
            # penalty in evaluate_signal's Check 6 exactly like the plan lane.
            try:
                from engines.risk import assess_account_policy as _assess
                _real_pol = _assess(
                    balance=float(acct.get("balance", 0) or 0),
                    equity=float(acct.get("equity", 0) or 0),
                    free_margin=float(acct.get("margin_free", 0) or 0),
                    margin=float(acct.get("margin", 0) or 0),
                    daily_pnl=float(_perf.get("daily_pnl", 0) or 0),
                    loss_streak=int(_perf.get("loss_streak", 0) or 0),
                    open_positions=_open_ct)
                account_policy["trade_allowed"] = bool(
                    account_policy["trade_allowed"]
                    and _real_pol.get("trade_allowed", True))
                if not _kill.get("halted", False):
                    account_policy["regime"] = _real_pol.get("regime", "normal")
            except Exception as _ae:
                # fail-CLOSED: an uncomputable regime must not silently
                # downgrade to "normal" — block like the outer handler does.
                account_policy = {
                    "trade_allowed": False, "regime": "policy_error",
                    "open_positions": 0, "balance": 0,
                    "policy_error": f"regime:{str(_ae)[:180]}"}
        except Exception as e:
            # b29 FAIL-CLOSED: if the kill-switch/account check itself errors,
            # the previous behavior fell back to trade_allowed=True — a broken
            # safety gate must block, never green-light.
            account_policy = {"trade_allowed": False, "regime": "policy_error",
                              "open_positions": 0, "balance": 0,
                              "policy_error": str(e)[:200]}

        # News blackout for the signal path too — evaluate_signal has the
        # gate (Check 7) but nobody ever passed macro_filter, so it was dead.
        # b30 FAIL CLOSED: an exception here used to leave _macro_filter=None,
        # which the decision engine reads as 'no gate' → trade allowed with no
        # news visibility. A broken calendar now blocks the signal.
        _macro_filter = None
        try:
            from engines.economic_calendar import fetch_economic_calendar
            from engines.macro_filter import evaluate_macro_filter
            _macro_filter = evaluate_macro_filter(fetch_economic_calendar(), _now)
        except Exception as e:
            _macro_filter = {"allowed": False, "reason": "macro_gate_error",
                             "events": [], "error": str(e)[:200]}

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


def _log_signal_risk_stack(eval_result: dict, command: dict,
                           ticket=None) -> None:
    """b139: persist the per-trade shrink stack for a signal-lane entry.

    The signal lane's execution_log rows carry plan_id='signal' and are
    SKIPPED by learning.py's join, so a per-trade style audit needs BOTH
    call sites (this one and hermes_runtime's plan lane), not just one.
    b144: `ticket` is the join key that makes this row reachable from
    realized P&L without a timestamp guess — every signal row used to say
    plan_id='signal', so the lane that trades most was unauditable. For the
    market path it is the deal/order ticket the broker returned; for the
    limit path it is the pending order ticket (which the entry deal's `order`
    field points back to). Observability only: never let a ledger failure
    touch the trade path.
    """
    try:
        from engines import paths
        from engines.storage import append_risk_ledger
        append_risk_ledger(paths.plan_dir(), dict(
            eval_result.get("risk_stack") or {},
            at=datetime.now(timezone.utc).isoformat(), lane="signal",
            plan_id="signal", side=command.get("side"),
            lot=command.get("lot"), entry=command.get("entry"),
            sl=command.get("sl"), tp=command.get("tp"),
            grade=eval_result.get("grade", "signal"),
            risk_usd=eval_result.get("risk_usd", 0),
            ticket=ticket))
    except Exception:
        pass


def run_signal_check(bridge, dry_run: bool = False) -> dict:
    """Main entry for integration with hermes_master.

    Checks for new signals, evaluates them, executes approved ones,
    and returns execution results for reporting.
    """
    PLAN_DIR = paths.plan_dir()

    signals = check_signals(bridge=bridge)
    if not signals:
        return {"ok": True, "signals_found": 0, "executions": []}

    # Get real account state
    account_resp = bridge.get_account()
    executions = []

    for sig_record in signals:
        decision = sig_record.get("decision", {})
        _use_pending = False  # b70: set when entry not reached → LIMIT instead of market

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
        # b30 FAIL CLOSED: the whole block used to end in `except Exception:
        # pass`, so a failed tick read skipped BOTH the staleness guard and
        # the spread gate and the order went out unchecked. No tick = no
        # entry (the plan path refuses the same way — an entry without a
        # spread check is exactly the news-spike hole the gate exists for).
        try:
            tick = bridge.get_tick(parsed["symbol"]) or {}
            cur = float(tick.get("ask") or tick.get("bid") or 0)
            entry = float(parsed.get("entry") or 0)
            sl = float(parsed.get("sl") or 0)
            risk_dist = abs(entry - sl) if sl > 0 else 10.0
            if cur <= 0:
                executions.append({
                    "signal": parsed, "verdict": "skip",
                    "reasons": ["tick_unavailable_fail_closed"],
                    "executed": False,
                })
                continue
            if entry > 0 and abs(cur - entry) > max(risk_dist * 0.5, 5.0):
                # b70: price hasn't REACHED the entry yet (BUY above entry /
                # SELL below) and the gap is within 1R → don't throw the signal
                # away; park a LIMIT order at the channel's entry price and
                # wait. Price already PASSED the entry (BUY below / SELL
                # above) → the premise is broken, keep the old skip.
                _not_reached = ((parsed["side"] == "BUY" and cur > entry) or
                                (parsed["side"] == "SELL" and cur < entry))
                if (_not_reached and abs(cur - entry) <= risk_dist
                        and signal_pending.pending_enabled()
                        and not dry_run):
                    _use_pending = True
                else:
                    executions.append({
                        "signal": parsed, "verdict": "skip",
                        "reasons": [f"stale_entry_price_moved_{abs(cur-entry):.1f}pts (current {cur})"],
                        "executed": False,
                    })
                    continue
            # Spread gate (parity with the plan path, hermes_runtime MAX_ENTRY_SPREAD):
            # news/rollover spikes blow XAUUSD past 2.0$ (normal 0.18). Signals used
            # to enter straight into them — the plan path refuses, the signal path didn't.
            from hermes_runtime import MAX_ENTRY_SPREAD
            _bid = float(tick.get("bid") or 0)
            _ask = float(tick.get("ask") or 0)
            if _bid <= 0 or _ask <= 0:
                executions.append({
                    "signal": parsed, "verdict": "skip",
                    "reasons": ["tick_incomplete_fail_closed"],
                    "executed": False,
                })
                continue
            _spr = _ask - _bid
            if _spr > MAX_ENTRY_SPREAD:
                executions.append({
                    "signal": parsed, "verdict": "skip",
                    "reasons": [f"spread_too_wide_{_spr:.2f}>{MAX_ENTRY_SPREAD:.2f}"],
                    "executed": False,
                })
                continue
        except Exception as e:
            executions.append({
                "signal": parsed, "verdict": "skip",
                "reasons": [f"tick_gate_error_fail_closed:{str(e)[:120]}"],
                "executed": False,
            })
            continue

        # ── Final safety gates BEFORE any order ──
        # CRITICAL FIX 2026-08-30: the signal path called execute_trade()
        # directly, bypassing EVERY gate the plan path enforces — cooldown,
        # daily loss limit, daily trade cap, position cap, RR floor, and
        # risk-based sizing. A channel posting "lot: 5" would have opened 5
        # lots (~10% of account at risk). Signals now run the SAME
        # evaluate_proposal() gauntlet; the parsed lot is only a ceiling,
        # actual size comes from our own risk model.
        from engines.auto_executor import evaluate_proposal, execute_trade

        _blueprint = {
            "side": parsed["side"],
            "entry_price": parsed["entry"],
            "sl": parsed["sl"],
            "tp": parsed["tp"],
            "symbol": parsed["symbol"],
        }
        _proposal = {
            "blueprint": _blueprint,
            "monitor_action": "signal_market_entry",
            "at": datetime.now(timezone.utc).isoformat(),
            # map the 8-check score onto the shared grade gate
            "grade": "A" if decision.get("score", 0) >= 8.0 else "B",
        }
        try:
            # real current plan → DEFCON context + grade fallback see the same
            # quality data the scanner wrote
            from engines.storage import load_current_plan as _load_plan
            _cur_plan = _load_plan(PLAN_DIR) or {}
            from hermes_runtime import _performance_and_policy
            _pp = _performance_and_policy(
                bridge, bridge.get_account() or {}, datetime.now(timezone.utc))
            _perf_state = _pp['performance_state']
            _acct_policy = _pp['account_policy']
            _acct_data = (account_resp or {}).get('data', account_resp) or {}
            _acct_policy["open_positions"] = max(
                _acct_policy.get("open_positions", 0),
                int(_acct_data.get("positions", 0) or 0))
        except Exception as _pe:
            # fail-CLOSED: if we cannot compute the account state, the gates
            # cannot be trusted — do not trade on a blind spot
            executions.append({
                "signal": parsed, "verdict": "skip",
                "reasons": [f"policy_unavailable:{_pe}"],
                "executed": False,
            })
            continue

        eval_result = evaluate_proposal(_proposal, _acct_policy, _perf_state,
                                        _cur_plan, bridge)
        if not eval_result.get("execute"):
            executions.append({
                "signal": parsed, "verdict": "skip",
                "reasons": eval_result.get("reasons", []) + [eval_result.get("reason", "")],
                "executed": False,
            })
            continue

        command = eval_result.get("command")
        # never exceed the lot the signal channel itself specified
        if parsed.get("lot") and command:
            _capped = min(command["lot"], float(parsed["lot"]))
            if _capped < command["lot"]:
                # scale the logged risk to the lot we actually send
                eval_result["risk_usd"] = round(
                    float(eval_result.get("risk_usd", 0) or 0)
                    * _capped / command["lot"], 2)
            command["lot"] = _capped

        result = None
        if _use_pending:
            # b70: vetted signal whose entry price hasn't been reached yet →
            # park a LIMIT order at the channel's entry instead of skipping.
            # Market-hours gate parity with execute_trade: no parking while
            # the market is closed (stale ticks could otherwise slip through).
            from engines.market_hours import is_market_open
            if not is_market_open():
                executions.append({
                    "signal": parsed, "verdict": "skip",
                    "reasons": ["market_closed_pending"], "executed": False,
                })
                continue
            pres = signal_pending.place_signal_limit(
                bridge, command, symbol=parsed.get("symbol", "XAUUSD"))
            executions.append({
                "signal": parsed,
                "verdict": "limit_pending" if pres.get("ok") else "skip",
                "reasons": ([] if pres.get("ok")
                            else [f"pending_failed:{pres.get('error')}"]),
                "executed": False,
                "pending_ticket": pres.get("ticket"),
                "lot": command["lot"],
            })
            from engines.storage import append_execution_log
            append_execution_log(PLAN_DIR, {
                "at": datetime.now(timezone.utc).isoformat(),
                "source": "signal_listener", "plan_id": "signal",
                "action": "limit_pending",
                "side": command["side"], "lot": command["lot"],
                "entry": command["entry"], "sl": command["sl"], "tp": command["tp"],
                "grade": eval_result.get("grade", "signal"),
                "risk_usd": eval_result.get("risk_usd", 0),
                "dry_run": dry_run,
                "result_ok": pres.get("ok", False),
                "ticket": pres.get("ticket"),
            })
            _log_signal_risk_stack(eval_result, command,
                                   ticket=pres.get("ticket"))
            continue

        result = execute_trade(command, bridge, dry_run=dry_run)

        # Alert hygiene (b10 bug class, signal side): a broker rejection after
        # passing every gate must NOT report verdict='execute' + executed=False —
        # signal_daemon only alerts on executed or verdict=='skip', so the
        # rejection was silent. Surface it as a skip with a reason.
        # (dry_run keeps verdict='execute': executed=False there is BY DESIGN.)
        _accepted = result.get("executed", False) or (dry_run and result.get("dry_run"))
        executions.append({
            "signal": parsed,
            "verdict": "execute" if _accepted else "skip",
            "reasons": (decision.get("reasons", []) if _accepted else
                        ["broker_rejected: " + str((result.get("result") or {}).get("error")
                         or result.get("error") or "unknown")[:120]]),
            "executed": result.get("executed", False),
            "result": result,
            "lot": command["lot"],
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
            "grade": eval_result.get("grade", "signal"),
            # real risk from the sizing model (was hardcoded 0 → the journal
            # could never reconcile signal trades against risk taken)
            "risk_usd": eval_result.get("risk_usd", 0),
            "dry_run": dry_run,
            "result_ok": result.get("ok", False),
            "ticket": (result.get("result") or {}).get("ticket"),
        })
        _log_signal_risk_stack(eval_result, command,
                               ticket=(result.get("result") or {}).get("ticket"))

    return {
        "ok": True,
        "signals_found": len(signals),
        "executions": executions,
    }
