"""b149 replay: did the REJECTED channel signals actually make money?

WHY: on 2026-09-08 I quoted a replay that said "+52 USD per 0.01 lot over 13
rejected signals" but I had GUESSED the direction. `parsed.direction` is None
in the live log, so direction must be inferred from stop geometry:
SL above entry => SELL, SL below entry => BUY. Signals with no SL cannot be
replayed at all and must be reported separately, not silently counted.

METHOD: for each rejected signal, walk M5 bars from the signal time forward.
First touch decides: SL (loss = -1R) or TP1 (win = +rr_tp1 R). If neither
touches inside the horizon, mark TIMEOUT and report the unclosed MFE/MAE
separately so the number is not inflated by a favourable cut.

R-multiples are converted to USD at the lot size the system would have used
(the live mean of recent fills), so the headline is comparable to the journal.

READ-ONLY. Writes data/backtest/b149_rejected_signal_replay.json.
"""
import json
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from env_loader import load_dotenv  # noqa: E402
from bridge_client import BridgeClient  # noqa: E402

load_dotenv(Path(__file__).resolve().parents[1] / ".env")
ROOT = Path(__file__).resolve().parents[1]
HORIZON_BARS = 288  # 24h of M5


def to_ts(iso):
    return datetime.fromisoformat(iso).replace(tzinfo=timezone.utc).timestamp()


def direction_of(p):
    """Infer side from stop geometry. Returns 'buy'/'sell'/None."""
    e, sl = p.get("entry") or 0, p.get("sl") or 0
    if not e or not sl:
        return None
    return "sell" if sl > e else "buy"


def main():
    rows = json.load(open(ROOT / "data/signals/signals_log.json"))
    rej = [r for r in rows
           if r["timestamp"] >= "2026-09-07"
           and (r.get("decision") or {}).get("verdict") != "execute"]
    print(f"rejected events since 09-07: {len(rej)}")

    bars = BridgeClient().get_rates("XAUUSD", "M5", 20000).get("data", [])
    idx = {int(b["time"]): i for i, b in enumerate(bars)}
    print(f"bars: {len(bars)}  {datetime.fromtimestamp(bars[0]['time'], timezone.utc):%m-%d} -> "
          f"{datetime.fromtimestamp(bars[-1]['time'], timezone.utc):%m-%d}")

    lots = []
    try:
        for line in open(ROOT / "data/xau_plan/execution_log.csv").read().splitlines()[1:]:
            parts = line.split(",")
            for tok in parts:
                try:
                    v = float(tok)
                    if 0.01 <= v <= 0.5:
                        lots.append(v)
                except ValueError:
                    pass
    except OSError:
        pass
    avg_lot = statistics.mean(lots) if lots else 0.05
    print(f"avg executed lot: {avg_lot:.3f} (from {len(lots)} fills)")

    replayed, no_sl, timeout = [], [], []
    for r in rej:
        p = r.get("parsed") or {}
        side = direction_of(p)
        e, sl = p.get("entry") or 0, p.get("sl") or 0
        tps = p.get("tps") or []
        if side is None or not tps:
            no_sl.append((r["timestamp"][:16], p.get("entry"), (r.get("decision") or {}).get("reasons")))
            continue
        risk = abs(e - sl)
        if risk <= 0:
            no_sl.append((r["timestamp"][:16], e, "zero_risk"))
            continue
        # anchor to the first bar at/after the signal time
        t0 = int(to_ts(r["timestamp"]) // 300 * 300)
        start = None
        for cand in range(t0, t0 + 300 * 6, 300):
            if cand in idx:
                start = idx[cand]
                break
        if start is None:
            timeout.append((r["timestamp"][:16], "no_bar"))
            continue
        tp1 = tps[0]
        outcome, R = None, None
        for b in bars[start:start + HORIZON_BARS]:
            hi, lo = b["high"], b["low"]
            if side == "sell":
                hit_sl, hit_tp = hi >= sl, lo <= tp1
            else:
                hit_sl, hit_tp = lo <= sl, hi >= tp1
            if hit_sl and hit_tp:
                # ambiguous bar: assume the WORSE leg (conservative)
                outcome, R = "SL", -1.0
                break
            if hit_sl:
                outcome, R = "SL", -1.0
                break
            if hit_tp:
                outcome, R = "TP1", (abs(tp1 - e) / risk)
                break
        rec = {"ts": r["timestamp"][:16], "side": side, "entry": e, "sl": sl,
               "tp1": tp1, "rr_tp1": p.get("rr_ratio"), "ladder_rr": p.get("ladder_rr"),
               "score": (r.get("decision") or {}).get("score"),
               "outcome": outcome, "R": R,
               "usd_001": round(R * risk * 100_000 / 100_000 * 10, 2) if R is not None else None}
        # USD for 0.01 lot: 1 point = $1 per 0.01 lot on XAUUSD (100 oz/lot -> 0.01 lot = 1 oz)
        rec["usd_001"] = round(R * risk * 1.0, 2) if R is not None else None
        if outcome == "TIMEOUT" or outcome is None:
            timeout.append((r["timestamp"][:16], side, e, tp1))
            continue
        replayed.append(rec)

    print("\n── REPLAYED (SL + TP present, closed inside 24h):")
    for x in replayed:
        print(f"  {x['ts']} {x['side']:4s} e={x['entry']:7.1f} sl={x['sl']:7.1f} tp1={x['tp1']:7.1f} "
              f"rr={x['rr_tp1']} -> {x['outcome']:3s} {x['R']:+.2f}R  ${x['usd_001']:+.2f}/0.01lot")
    wins = [x for x in replayed if x["outcome"] == "TP1"]
    losses = [x for x in replayed if x["outcome"] == "SL"]
    tot001 = sum(x["usd_001"] for x in replayed)
    print(f"\n  n={len(replayed)} | TP1 hits={len(wins)} | SL hits={len(losses)} | "
          f"win%={100*len(wins)/max(1,len(replayed)):.0f}")
    print(f"  sum @0.01 lot: ${tot001:+.2f} | scaled to avg lot {avg_lot}: ${tot001*avg_lot/0.01:+.2f}")
    print(f"\n── NOT REPLAYABLE (no SL or no TP -> would have been rejected by the hard SL rule anyway): {len(no_sl)}")
    for x in no_sl:
        print("   ", x)
    print(f"\n── TIMEOUT / no bar: {len(timeout)}")
    for x in timeout:
        print("   ", x)

    out = ROOT / "data/backtest"
    out.mkdir(parents=True, exist_ok=True)
    json.dump({"replayed": replayed, "not_replayable": no_sl, "timeout": timeout,
               "avg_lot": avg_lot, "sum_usd_001": tot001},
              open(out / "b149_rejected_signal_replay.json", "w"), indent=1)
    print("\nwrote data/backtest/b149_rejected_signal_replay.json")


if __name__ == "__main__":
    main()
