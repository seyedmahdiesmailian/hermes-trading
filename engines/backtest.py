from __future__ import annotations

from typing import Callable

# b109: the ladder-field names live in engines.trade_management (the module
# that READS them). Imported, never restated — a restated tuple is a second
# source of truth that can drift from the reader. trade_management imports
# nothing from here, so this edge is acyclic.
from engines.trade_management import LADDER_FIELDS


def backtest_ohlc(
    rows: list[dict],
    signal_fn: Callable[[dict], dict | None],
    min_rr: float = 0.0,
    min_grade: str | None = None,
    breakeven_at_r: float = 0.0,
    partial_tp1_share: float = 0.0,
    tp1_position: float = 0.5,
    partial_share_fn=None,          # b54c: callable(grade)->share; overrides flat share
    trail_after_partial: float = 0.0,   # b55c: trail SL this many x risk behind the
                                        # bar extreme AFTER a partial fill (0 = off,
                                        # which is what every earlier sweep ran with)
    time_stop_bars: int = 0,            # b57: force-close at bar close after N bars
                                        # without TP1/TP hit (0 = off)
    trail_floor: float = 0.0,           # b117: absolute $ floor under the trail
                                        # distance, mirroring live _trail_params'
                                        # max(risk*mult, 3.0). 0 = off (every
                                        # pre-b117 measurement; the lab default
                                        # stays off until the merit bar is
                                        # deliberately re-baselined — see b118).
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

    def _close(t: dict, exit_price: float, index: int, reason: str):
        nonlocal equity, wins, losses, scratches
        side = t["side"]
        # b105 PARITY FIX: the runner leg is only (1 - partial_taken) of the
        # position. The old code booked it at FULL size on top of the realized
        # partial — with the live b55/b60 ladder (share = 1.0, close the WHOLE
        # ticket at TP1) that double-counted every TP1 winner: realized 1R plus
        # a phantom full-size runner to the final TP. Repro: entry 100/SL 98/
        # TP 104, TP1 102, runner reaches 104 → live nets 2.0 (1R), the old
        # engine printed 6.0 (3R).
        # MT5 candles are bid-based: BUY enters at ask (entry + spread), exits at
        # bid; SELL enters at bid, exits at ask (exit + spread). Either way the
        # round trip costs exactly one spread — paid once, not twice.
        remaining = round(1.0 - float(t.get("partial_taken") or 0.0), 9)
        pnl = ((exit_price - t["entry"] - spread) if side == "BUY"
               else (t["entry"] - exit_price - spread)) * remaining
        net = round(pnl + (t["realized"] or 0.0), 6)
        equity = round(equity + net, 6)
        if reason == "be" and abs(net) <= max(spread, 1e-9):
            scratches += 1          # breakeven exit: at most the spread cost — neither win nor loss
        elif net > 0:
            wins += 1
        else:
            losses += 1
        trade_log.append({**{k: t[k] for k in ("entry_index", "side", "entry", "style", "grade")},
                          "orig_sl": t.get("orig_sl"),
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
                        share = partial_tp1_share
                        if partial_share_fn is not None:
                            # b55 parity fix: pass the WHOLE trade dict — the live
                            # _partial_close_fraction(trade) reads grade AND
                            # momentum/rr/structure from it. (The old grade-string
                            # call crashed / silently diverged from live.)
                            # Accept both contracts: (share, reason) tuple like
                            # live, or a bare float from test lambdas.
                            v = partial_share_fn(t)
                            share = float(v[0]) if isinstance(v, (tuple, list)) else float(v)
                        if share > 0:
                            tp1 = t["entry"] + (t["tp"] - t["entry"]) * tp1_position if side == "BUY" \
                                else t["entry"] - (t["entry"] - t["tp"]) * tp1_position
                            hit_tp1 = high >= tp1 if side == "BUY" else low <= tp1
                            if hit_tp1:
                                part = ((tp1 - t["entry"]) if side == "BUY"
                                        else (t["entry"] - tp1)) * share - spread * share
                                t["realized"] = round(part, 6)
                                t["partial_taken"] = share
                                # b105 PARITY FIX (part 2 of the same defect):
                                # share >= 1.0 is not a partial at all. Live
                                # routes close_fraction>=1.0 to
                                # bridge.close_position (auto_executor, MT5
                                # rejects a 100% partial with retcode 10026),
                                # so the TICKET IS GONE at TP1 — no BE move to
                                # ride, no trail, no final TP, and the single
                                # position slot is FREE from this bar on. The
                                # old engine kept a phantom full-size runner
                                # alive for bars on, which (a) blocked real
                                # entries the live system would have taken and
                                # (b) fed the double-count in _close.
                                if share >= 1.0:
                                    _close(t, tp1, index, "tp1_full")
                                    open_trade = None
                                    continue
                                t["be_moved"] = True
                                t["sl"] = t["entry"]  # live: partial comes with BE move
                    # 4) plain BE move — effective from next bar
                    if breakeven_at_r > 0 and not t["be_moved"] and risk > 0:
                        move = (high - t["entry"]) if side == "BUY" else (t["entry"] - low)
                        if move >= breakeven_at_r * risk:
                            t["sl"] = t["entry"]
                            t["be_moved"] = True
                    # 4b) b55c TRAIL after TP1 — mirrors live update_trailing_stop:
                    # once the partial was taken, SL follows price at trail_mult x
                    # original risk behind the best high/low seen. Set on this bar,
                    # enforced from the NEXT bar (no same-bar lookahead).
                    # b117: live _trail_params returns max(risk*mult, FLOOR) — an
                    # ABSOLUTE dollar floor (3.00 on XAUUSD) that dominates the
                    # multiplier whenever risk < FLOOR/mult. Without it the lab
                    # trails TIGHTER than live on small-risk trades (measured:
                    # 61.8% of W4's trades, 7.3% cached). trail_floor=0.0 keeps
                    # every pre-b117 number byte-identical.
                    if trail_after_partial > 0 and t["partial_taken"] > 0 and risk > 0:
                        dist = max(trail_after_partial * risk, trail_floor)
                        if side == "BUY":
                            cand = high - dist
                            if cand > t["sl"]:
                                t["sl"] = cand
                        else:
                            cand = low + dist
                            if cand < t["sl"]:
                                t["sl"] = cand
                    # 4c) b57 TIME STOP — trade that never reached TP1 within N
                    # bars is dead weight under the one-position gate; exit at
                    # this bar's close (live would do the same on bar close).
                    if (time_stop_bars > 0 and t["partial_taken"] == 0
                            and index - t["entry_index"] >= time_stop_bars):
                        _close(t, float(row.get("close", t["entry"])), index, "time")
                        open_trade = None
                        continue

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
            "grade": signal.get("grade"),
        }
        # b109: carry the LIVE ladder fields from the signal into the trade
        # dict the partial-share function reads. Before this, the
        # "live-parity ladder" was fed a dict with none of them, so
        # rr_remaining defaulted to 0.0, the `<= 1.2` weak branch tripped on
        # EVERY call, and _partial_close_fraction returned the constant
        # (1.0, 'weak_full_exit_at_tp1') — 935/935 calls on the cached funnel,
        # all 84 A-grade signals included. engines.backtest_real.strategy_signal
        # now emits them through the same ladder_fields() helper the two live
        # producers use, so the parity is by construction again.
        # Arms that do not supply them (every standalone lab arm) keep
        # today's behaviour untouched: nothing is copied, the live function
        # defaults as it always did for a grade-B arm.
        for _k in LADDER_FIELDS:
            if _k in signal:
                open_trade[_k] = signal[_k]

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
