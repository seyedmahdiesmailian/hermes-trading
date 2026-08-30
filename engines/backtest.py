from __future__ import annotations

from typing import Callable


def backtest_ohlc(
    rows: list[dict],
    signal_fn: Callable[[dict], dict | None],
    min_rr: float = 0.0,
    min_grade: str | None = None,
    breakeven_at_r: float = 0.0,
    partial_tp1_share: float = 0.0,
    spread: float = 0.0,
    exclude_styles: list[str] | None = None,
) -> dict:
    """Backtest with live-modeled constraints.

    - min_rr: skip signals whose reward/risk < min_rr (mirrors live gate 6).
    - min_grade: 'B' or 'A' — mirror live gate 7 (SMC setup grade).
    - breakeven_at_r: move SL to entry once profit reaches N * risk (live BE move).
      The move only takes effect from the NEXT bar (live: decision runs on bar close).
    - partial_tp1_share: fraction closed at a TP1 (half of the way to final TP); the
      remainder rides to the final TP — mirrors the live partial-TP ladder.
    - spread: round-trip cost in price units (e.g. XAUUSD ~0.20). BUY crosses
      ask up, SELL crosses bid down; exits pay the same. This is what turns
      "breakeven scratches" into small real losses, like live.
    Position model: one open trade at a time (mirrors live max-position gate).
    Win/loss accounting mirrors the live report: a BE scratch counts as neither.
    Conservative intrabar rule: the ORIGINAL stop is evaluated before any
    same-bar TP1/BE move — if a bar wicks through the stop, no partial was
    taken and no BE move happened, even if the bar also touched TP1.
    """
    trade_log: list[dict] = []
    equity = 0.0
    wins = losses = scratches = 0
    open_trade = None  # one position at a time, like live gate 5

    def _exit_price(t: dict, price: float) -> float:
        # crossing the spread: BUY exits at bid (price), SELL exits at bid (price - spread)
        return price - spread if t["side"] == "BUY" else price - spread

    def _close(t: dict, exit_price: float, index: int, reason: str):
        nonlocal equity, wins, losses, scratches
        side = t["side"]
        # MT5 candles are bid-based: BUY enters at ask (entry + spread), exits at
        # bid; SELL enters at bid, exits at ask (exit + spread). Either way the
        # round trip costs exactly one spread — paid once, not twice.
        pnl = (exit_price - t["entry"] - spread) if side == "BUY" \
            else (t["entry"] - exit_price - spread)
        net = round(pnl + (t["realized"] or 0.0), 6)
        equity = round(equity + net, 6)
        if reason == "be" and abs(net) <= max(spread, 1e-9):
            scratches += 1          # breakeven exit: at most the spread cost — neither win nor loss
        elif net > 0:
            wins += 1
        else:
            losses += 1
        trade_log.append({**{k: t[k] for k in ("entry_index", "side", "entry", "style")},
                          "exit_index": index, "exit": round(exit_price, 2),
                          "pnl": round(net, 2), "exit_reason": reason})

    for index, row in enumerate(rows):
        # ── manage the currently open position first (bar-by-bar, live order) ──
        if open_trade is not None:
            t = open_trade
            high = float(row.get("high", 0))
            low = float(row.get("low", 0))
            side = t["side"]
            risk = abs(t["entry"] - t["orig_sl"])

            # 1) ORIGINAL stop first — conservative: a bar that wicks through the
            #    stop kills the trade before any TP1/BE move on that same bar.
            hit_sl = low <= t["sl"] if side == "BUY" else high >= t["sl"]
            if hit_sl:
                reason = ("be" if t["sl"] == t["entry"] and not t["realized"]
                          else "sl_part" if t["sl"] == t["entry"]
                          else "sl")
                _close(t, t["sl"], index, reason)
                open_trade = None
            else:
                # 2) final TP
                hit_tp = high >= t["tp"] if side == "BUY" else low <= t["tp"]
                if hit_tp:
                    _close(t, t["tp"], index, "tp")
                    open_trade = None
                else:
                    # 3) partial TP1 (half the distance to final TP, once) —
                    #    stop moves to entry, effective NEXT bar (no same-bar re-entry exit)
                    if partial_tp1_share > 0 and not t["partial_taken"] and risk > 0:
                        tp1 = t["entry"] + (t["tp"] - t["entry"]) * 0.5 if side == "BUY" \
                            else t["entry"] - (t["entry"] - t["tp"]) * 0.5
                        hit_tp1 = high >= tp1 if side == "BUY" else low <= tp1
                        if hit_tp1:
                            part = ((tp1 - t["entry"]) if side == "BUY"
                                    else (t["entry"] - tp1)) * partial_tp1_share - spread * partial_tp1_share
                            t["realized"] = round(part, 6)
                            t["partial_taken"] = partial_tp1_share
                            t["be_moved"] = True
                            t["sl"] = t["entry"]  # live: partial comes with BE move
                    # 4) plain BE move — effective from next bar
                    if breakeven_at_r > 0 and not t["be_moved"] and risk > 0:
                        move = (high - t["entry"]) if side == "BUY" else (t["entry"] - low)
                        if move >= breakeven_at_r * risk:
                            t["sl"] = t["entry"]
                            t["be_moved"] = True

        if open_trade is not None:
            continue  # position occupied — live blocks new entries (gate 5)

        signal = signal_fn(row)
        if not signal:
            continue
        side = str(signal.get("side", "")).upper()
        entry = float(signal["entry"])
        sl = float(signal["sl"])
        tp = float(signal["tp"])
        if side not in {"BUY", "SELL"} or (side == "BUY" and not sl < entry < tp) or (side == "SELL" and not tp < entry < sl):
            continue
        risk = abs(entry - sl)
        reward = abs(tp - entry)
        if min_rr > 0 and risk > 0 and (reward / risk) < min_rr:
            continue
        # Live gate 7 blocks when grade > MIN_SETUP_GRADE (A<B<C alphabetically,
        # C is worst). The old `<` comparison never matched → grade gate was
        # dead in the backtest while live rejected C setups (parity bug).
        if min_grade and str(signal.get("grade", "")).upper() > min_grade:
            continue
        if exclude_styles:
            style = str(signal.get("style") or "")
            if any(style.startswith(p) for p in exclude_styles):
                continue

        open_trade = {
            "entry_index": index, "side": side, "entry": entry,
            "sl": sl, "orig_sl": sl, "tp": tp,
            "be_moved": False, "partial_taken": 0, "realized": 0.0,
            "style": signal.get("style"),
        }

    # unfinished trade: force-close at last bar's close (marked as its raw result)
    if open_trade is not None:
        last = rows[-1]
        _close(open_trade, float(last.get("close", open_trade["entry"])), len(rows) - 1,
               "tp" if (open_trade["tp"] - open_trade["entry"]) * (1 if open_trade["side"] == "BUY" else -1) > 0 else "sl")
        open_trade = None

    decided = wins + losses  # scratches excluded: they are neither
    return {"trades": len(trade_log), "wins": wins, "losses": losses, "scratches": scratches,
            "net_pnl": round(equity, 2),
            "win_rate": round(wins / len(trade_log), 4) if trade_log else 0.0,
            "win_rate_decided": round(wins / decided, 4) if decided else 0.0,
            "trade_log": trade_log}
