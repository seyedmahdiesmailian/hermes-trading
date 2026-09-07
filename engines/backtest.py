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
    protection_mode: str = "partial",   # b123: WHAT arms the exit protection
                                        # (SL->entry at TP1 plus the runner
                                        # trail). "partial" = today's coupling,
                                        # a TP1 partial was actually taken (the
                                        # default; every stored number).
                                        # "tp1" = a TP1 TOUCH arms it whatever
                                        # the share was, so share=0.0 can be
                                        # measured WITH protection — the cell
                                        # the coupled engine cannot express.
                                        # "none" = never arm it, so the share
                                        # can be measured WITHOUT protection.
    time_stop_gate: str = "no_partial",  # b123: "no_partial" = today (the time
                                        # exit only sees trades that never took
                                        # a partial). "age_only" mirrors live
                                        # evaluate_time_exit, which is age
                                        # based and does not care about partials.
    time_stop_hours: float = 0.0,       # b130: THE OTHER CLOCK. Live's
                                        # evaluate_time_exit measures WALL-CLK
                                        # hours between open and now; the lab's
                                        # time_stop_bars measures BAR age, and
                                        # XAUUSD bars do not span the weekend or
                                        # holiday gaps, so the two rules are not
                                        # the same guard. 0.0 = off (every
                                        # pre-b130 measurement, byte-identical);
                                        # >0 closes at the first bar whose row
                                        # timestamp is >= that many hours after
                                        # the entry bar's timestamp.
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
                          # b121: the share the TP1 partial actually took (0.0 =
                          # the ticket never reached TP1). exit_reason cannot
                          # answer "how many trades took the partial-close
                          # path" — which exit a runner reaches is a function of
                          # the price path, not of the share, so a census built
                          # on exit_reason is STRUCTURALLY blind to the one
                          # parameter the share grid varies (measured: identical
                          # for every flat arm 0.1..0.9). This field is the only
                          # honest way to price the operational cost (partial
                          # bridge calls) of a lower share.
                          "partial_taken": float(t.get("partial_taken") or 0.0),
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
                    # b123: the branch used to be gated on partial_tp1_share > 0,
                    # which made it unreachable for a share=0 arm and therefore
                    # impossible to measure "riding with protection" (see
                    # protection_mode). The gate is now share OR mode, and every
                    # default run takes the identical path.
                    _see_tp1 = (partial_tp1_share > 0 or protection_mode == "tp1")
                    # b123: `not t["prot_armed"]` is the once-only guard. Under
                    # the default it is redundant (prot_armed is set exactly
                    # when partial_taken > 0, and a share>=1.0 ticket is closed
                    # before either), but in mode "tp1" with share=0 the share
                    # stays 0 forever, so without this guard the branch would
                    # re-run every bar and re-set SL back to entry, ERASING the
                    # trail it had just walked up.
                    if (_see_tp1 and not t["partial_taken"]
                            and not t["prot_armed"] and risk > 0):
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
                        if share > 0 or protection_mode == "tp1":
                            tp1 = t["entry"] + (t["tp"] - t["entry"]) * tp1_position if side == "BUY" \
                                else t["entry"] - (t["entry"] - t["tp"]) * tp1_position
                            hit_tp1 = high >= tp1 if side == "BUY" else low <= tp1
                            if hit_tp1:
                                if share > 0:
                                    part = ((tp1 - t["entry"]) if side == "BUY"
                                            else (t["entry"] - tp1)) * share - spread * share
                                    t["realized"] = round(part, 6)
                                    t["partial_taken"] = share
                                # b105 PARITY FIX (part 2 of the same defect):
                                # share >= 1.0 is not a partial at all. Live
                                # routes close_fraction>=1.0 to
                                # bridge.close_position (auto_executor, MT5
                                # rejects a 100% partial with retcode 10026), so
                                # the TICKET IS GONE at TP1 — no BE move to
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
                                # b123 PROTECTION AXIS. "partial" (the default, and
                                # what every stored number in this repo means): the
                                # SL->entry move and the runner trail are armed ONLY
                                # because a partial was taken — the coupling that
                                # makes share=0.0 a different TRADE rather than more
                                # of the same. "tp1": a TP1 TOUCH arms them whatever
                                # the share was, so the share can be swept with the
                                # protection held constant. "none": never arm them,
                                # so the share can be swept without protection.
                                arm = (protection_mode == "tp1"
                                       or (protection_mode == "partial" and share > 0))
                                # protection_mode == "none" leaves arm False by
                                # construction: never arm, whatever the share.
                                if arm:
                                    t["be_moved"] = True
                                    t["sl"] = t["entry"]  # live: partial comes with BE move
                                    t["prot_armed"] = True
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
                    # b123: the gate is now `t["prot_armed"]` — "this ticket's
                    # protection was armed at TP1" — instead of the share itself.
                    # Under the default protection_mode="partial" the two are the
                    # SAME SET (a 0<share<1 partial always arms; share>=1.0 is
                    # closed before either line runs), so every stored number is
                    # unchanged; the flag exists so a share=0 arm can be measured
                    # WITH a trail and a share>0 arm WITHOUT one.
                    if (trail_after_partial > 0 and t["prot_armed"] and risk > 0):
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
                    # b123: `partial_taken == 0` is an EXEMPTION for runner trades
                    # that live does not give them — engines/legacy_guards
                    # .evaluate_time_exit is purely age-based. time_stop_gate=
                    # "age_only" measures the coupled-parity cost; the default
                    # keeps every stored number.
                    _ts_exempt = (t["partial_taken"] > 0
                                  if time_stop_gate == "no_partial" else False)
                    if (time_stop_bars > 0 and not _ts_exempt
                            and index - t["entry_index"] >= time_stop_bars):
                        _close(t, float(row.get("close", t["entry"])), index, "time")
                        open_trade = None
                        continue
                    # 4d) b130 WALL-CLOCK TIME STOP — the guard live actually
                    # runs. engines/legacy_guards.evaluate_time_exit compares
                    # datetime.now() against the position's open time, so a
                    # position held across the Sunday-night close (or a holiday
                    # gap) accrues age the bar-count rule cannot see: 144 M15
                    # bars is 36h of CONTINUOUS tape, but a trade that spans a
                    # weekend reaches 36 wall hours at ~110 bars. Same exemption
                    # gate, same close-at-bar-close convention.
                    if (time_stop_hours > 0 and not _ts_exempt
                            and t.get("entry_time") and row.get("time")
                            and (int(row["time"]) - int(t["entry_time"]))
                            >= time_stop_hours * 3600):
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
            # b130: the bar's own timestamp, so the exit can be measured on the
            # SAME clock live uses (wall hours) and not only in bar counts.
            # Additive: trade_log keys are listed explicitly, so no stored row
            # changes shape (pinned by tests/test_b130_wall_clock_parity.py).
            "entry_time": row.get("time"),
            "be_moved": False, "partial_taken": 0, "realized": 0.0,
            # b123: did the TP1 touch arm the protection (SL->entry + trail)?
            # Under the default protection_mode="partial" this is identical to
            # partial_taken > 0; it only diverges for the decomposition arms.
            "prot_armed": False,
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
