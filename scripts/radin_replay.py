"""Replay RADIN channel signals against real broker candles (90 days).

Answers one question with numbers: were Hermes' rejections right?

Pipeline
  1. Read exported channel history (scripts/export_channel_history.py).
  2. Keep signal-like messages (a side keyword plus a stop).
  3. Parse each with the CURRENT parser, feeding it the price and the 24h
     price band as they were *at that moment* — never today's values.
  4. Walk the real M5 path forward from the signal time and resolve each
     entry leg under two exit policies:
       A  'tp1'   : what Hermes does today — close the whole leg at TP1.
       B  'ladder': what the channel tells its members — half at TP1, stop
                    to breakeven, ride the rest to the final rung.
  5. Where a Hermes bias is on record (reassessment log, 28 Aug onward),
     also report the gate verdict so acceptance rate can be measured.

Output: per-signal CSV + an aggregate summary on stdout.

Units: pnl columns are raw price distance in dollars, which equals P&L at
0.01 lot XAUUSD (1 lot = 100 oz, so 0.01 lot = 1 oz = $1 per $1.00 move).
Scale linearly for larger size; add spread/commission separately (this
replay is spread-free, so treat the totals as optimistic).

Usage:
  python3 scripts/radin_replay.py [--days 90] [--out data/radin/replay.csv]
"""
import argparse
import csv
import json
import os
import sys
from datetime import datetime, timedelta, timezone

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
try:
    from dotenv import load_dotenv
except ImportError:
    from env_loader import load_dotenv
load_dotenv(os.path.join(_ROOT, '.env'))

from bridge_client import BridgeClient
from engines.signal_parser import parse_signal

SIDE_WORDS = ('خرید', 'فروش', 'buy', 'sell')
HISTORY = os.path.join(_ROOT, 'data', 'radin', 'history_90d.jsonl')
BIAS_LOG = os.path.join(_ROOT, 'data', 'xau_plan', 'reassessment_log.csv')


def load_candles(symbol='XAUUSD', tf='M5', count=20000):
    r = BridgeClient().get_rates(symbol, tf, count)
    rows = r.get('rates') or r.get('candles') or r.get('data') or []
    out = []
    for row in rows:
        if isinstance(row, dict):
            t, o, h, l, c = (row.get('time'), row.get('open'), row.get('high'),
                             row.get('low'), row.get('close'))
        else:
            t, o, h, l, c = row[0], row[1], row[2], row[3], row[4]
        if t is None or h is None or l is None:
            continue
        out.append((int(t), float(o), float(h), float(l), float(c)))
    out.sort(key=lambda x: x[0])
    return out


def bisect_start(candles, ts):
    lo, hi = 0, len(candles)
    while lo < hi:
        mid = (lo + hi) // 2
        if candles[mid][0] < ts:
            lo = mid + 1
        else:
            hi = mid
    return lo


def price_at(candles, ts):
    """Last close strictly before ts, plus the 24h band ending at ts."""
    i = bisect_start(candles, ts)
    if i == 0:
        return None, None
    px = candles[i - 1][4]
    j = bisect_start(candles, ts - 24 * 3600)
    window = candles[j:i]
    if not window:
        return px, None
    return px, (min(c[3] for c in window), max(c[2] for c in window))


def is_signal(text):
    low = text.lower()
    if not any(w in low for w in SIDE_WORDS):
        return False
    return ('استاپ' in low or 'stp' in low or 'stop' in low
            or 'اسال' in low or 'sl' in low)


def resolve_leg(candles, start_i, side, entry, sl, tps, horizon_h=48):
    """Walk forward once; return (outcome, exit_price, bars) for a leg.

    outcome: 'tp1' | 'ladder:<n>' | 'sl' | 'be' | 'open'
    Fill semantics: a leg on the favourable side of the current price is a
    limit (waits for a touch); on the other side it is a stop (breakout).
    """
    end_i = min(len(candles), start_i + int(horizon_h * 12))
    seg = candles[start_i:end_i]
    if not seg:
        return 'no_data', 0.0, 0
    mkt = candles[start_i - 1][4] if start_i > 0 else seg[0][4]
    want_low = entry < mkt if side == 'BUY' else entry > mkt
    fill_i = None
    for k, c in enumerate(seg):
        if side == 'BUY':
            hit = c[3] <= entry if want_low else c[2] >= entry
        else:
            hit = c[2] >= entry if want_low else c[3] <= entry
        if hit:
            fill_i = k
            break
    if fill_i is None:
        return 'no_fill', 0.0, 0
    return walk(candles, side, entry, sl, tps, fill_i, end_i)


def walk(candles, side, entry, sl, tps, fill_i, end_i):
    """From the fill candle onward, first-touch of SL vs each TP rung."""
    def hits_sl(c):
        return c[2] >= sl if side == 'SELL' else c[3] <= sl

    def hits_tp(c, tp):
        return c[3] <= tp if side == 'SELL' else c[2] >= tp

    for k in range(fill_i, end_i):
        c = candles[k]
        if hits_sl(c):
            return 'sl', sl, k - fill_i
        for n, tp in enumerate(tps, start=1):
            if hits_tp(c, tp):
                return f'tp{n}', tp, k - fill_i
    return 'open', candles[min(end_i, len(candles)) - 1][4], end_i - fill_i


def resolve_ladder(candles, fill_i, side, entry, sl, rungs, end_i):
    """Channel's own management: half off at TP1, stop to breakeven, ride
    the remainder to the LAST rung. Returns realised $ per 1 unit of size.

    This is policy B and is deliberately different from walk(): walk exits
    the whole position at the first touch, which is what Hermes does today.
    """
    if not rungs:
        return 0.0, 'no_tp'
    d = 1 if side == 'BUY' else -1
    tp1 = rungs[0]
    last = rungs[-1]
    # phase 1: TP1 vs original SL
    for k in range(fill_i, end_i):
        c = candles[k]
        if (c[2] >= sl) if side == 'SELL' else (c[3] <= sl):
            return (sl - entry) * d, 'sl_full'
        if (c[3] <= tp1) if side == 'SELL' else (c[2] >= tp1):
            half = (tp1 - entry) * d * 0.5
            # phase 2: remainder with stop at breakeven, target = last rung
            if last == tp1:
                return half, 'tp1_only'
            for j in range(k, end_i):
                cc = candles[j]
                if (cc[2] >= entry) if side == 'SELL' else (cc[3] <= entry):
                    return half, 'be'
                if (cc[3] <= last) if side == 'SELL' else (cc[2] >= last):
                    return half + (last - entry) * d * 0.5, f'final'
            return half, 'open_runner'
    return 0.0, 'never_tp1'


def extremes(candles, fill_i, end_i, side, entry):
    """MFE / MAE in $ for the leg (favourable and adverse excursion)."""
    d = 1 if side == 'BUY' else -1
    mfe = mae = 0.0
    for c in candles[fill_i:end_i]:
        mfe = max(mfe, (c[2] - entry) * d, (c[3] - entry) * d)
        mae = min(mae, (c[2] - entry) * d, (c[3] - entry) * d)
    return round(mfe, 2), round(mae, 2)


def load_bias_timeline():
    """[(ts, bias)] from the reassessment log — 28 Aug 2026 onward only."""
    out = []
    if not os.path.exists(BIAS_LOG):
        return out
    with open(BIAS_LOG, newline='', encoding='utf-8') as fh:
        for row in csv.DictReader(fh):
            try:
                ts = datetime.fromisoformat(row['at']).timestamp()
            except (KeyError, ValueError):
                continue
            out.append((ts, (row.get('new_bias') or 'neutral').strip()))
    out.sort(key=lambda x: x[0])
    return out


def bias_at(timeline, ts):
    best = None
    for t, b in timeline:
        if t <= ts:
            best = b
        else:
            break
    return best


def find_fill(candles, start_i, side, entry, horizon_h=48):
    """Index of the candle that fills the leg, or None. end_i bounds the walk."""
    end_i = min(len(candles), start_i + int(horizon_h * 12))
    seg = candles[start_i:end_i]
    if not seg:
        return None, start_i, end_i
    mkt = candles[start_i - 1][4] if start_i > 0 else seg[0][4]
    want_low = entry < mkt if side == 'BUY' else entry > mkt
    for k, c in enumerate(seg):
        if side == 'BUY':
            hit = c[3] <= entry if want_low else c[2] >= entry
        else:
            hit = c[2] >= entry if want_low else c[3] <= entry
        if hit:
            return start_i + k, start_i, end_i
    return None, start_i, end_i


def gate_verdict(sig, bias):
    """Hermes' real gate, with the bias on record at that moment.

    account_policy is neutral (trade_allowed=True, 0 open positions) because
    per-trade account state at a past timestamp is not reconstructable; the
    macro/news filter is likewise unavailable historically. Both are noted
    in the report as optimistic assumptions.
    """
    from engines.signal_decision import evaluate_signal
    analysis = {'bias': bias or 'neutral'}
    policy = {'trade_allowed': True, 'open_positions': 0}
    return evaluate_signal(sig.to_dict(), analysis, policy)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--days', type=int, default=90)
    ap.add_argument('--history', default=HISTORY)
    ap.add_argument('--out', default=os.path.join(_ROOT, 'data', 'radin', 'replay.csv'))
    args = ap.parse_args()

    candles = load_candles()
    if not candles:
        print('no candles from bridge', file=sys.stderr)
        sys.exit(1)
    span_days = (candles[-1][0] - candles[0][0]) / 86400
    print(f'candles: {len(candles)} M5 bars, {span_days:.1f} days '
          f'({datetime.fromtimestamp(candles[0][0], timezone.utc):%Y-%m-%d} → '
          f'{datetime.fromtimestamp(candles[-1][0], timezone.utc):%Y-%m-%d})')

    timeline = load_bias_timeline()
    msgs = [json.loads(l) for l in open(args.history, encoding='utf-8')]
    msgs.sort(key=lambda m: m['date'])
    cutoff = datetime.now(timezone.utc) - timedelta(days=args.days)

    rows = []
    for m in msgs:
        try:
            dt = datetime.fromisoformat(m['date'])
        except ValueError:
            continue
        if dt < cutoff or not is_signal(m.get('text', '')):
            continue
        ts = int(dt.timestamp())
        px, band = price_at(candles, ts)
        if px is None:
            continue
        sig = parse_signal(m['text'], current_price=px, price_band=band)
        bias = bias_at(timeline, ts)
        if not sig.side or sig.sl <= 0 or sig.entry <= 0:
            rows.append({'date': m['date'], 'text': m['text'][:70], 'leg': 0,
                         'skip': 'unparsed', 'side': sig.side or '',
                         'entry': sig.entry, 'sl': sig.sl, 'tp1': sig.tp,
                         'rungs': len(sig.tps or []), 'pnl_tp1': 0.0,
                         'pnl_ladder': 0.0, 'outcome_tp1': '', 'outcome_ladder': '',
                         'bias': bias or '', 'verdict': '', 'score': '',
                         'rr_tp1': 0.0, 'rr_ladder': 0.0, 'mfe': 0.0, 'mae': 0.0})
            continue
        verdict = gate_verdict(sig, bias) if bias else {}
        legs = sig.entries or [sig.entry]
        rungs = sig.tps or ([sig.tp] if sig.tp else [])
        start_i = bisect_start(candles, ts)
        for leg in legs:
            fill_i, _, end_i = find_fill(candles, start_i, sig.side, leg)
            if fill_i is None:
                o1, pnl_a, oN, pnl_b, mfe, mae = 'no_fill', 0.0, 'no_fill', 0.0, 0.0, 0.0
            else:
                d = 1 if sig.side == 'BUY' else -1
                o1, px1, _ = walk(candles, sig.side, leg, sig.sl, rungs[:1],
                                  fill_i, end_i)
                pnl_b, oN = resolve_ladder(candles, fill_i, sig.side, leg, sig.sl,
                                           rungs, end_i)
                mfe, mae = extremes(candles, fill_i, end_i, sig.side, leg)
                # walk() returns an exit PRICE; convert to a $ move. 'open'
                # means neither SL nor TP touched inside the horizon — mark
                # it flat rather than booking the last close as realised.
                pnl_a = ((px1 - leg) * d) if o1 in ('sl', 'tp1') else 0.0
            rows.append({'date': m['date'], 'text': m['text'][:70], 'leg': leg,
                         'skip': '', 'side': sig.side, 'entry': leg, 'sl': sig.sl,
                         'tp1': rungs[0] if rungs else 0, 'rungs': len(rungs),
                         'pnl_tp1': round(pnl_a, 2), 'pnl_ladder': round(pnl_b, 2),
                         'outcome_tp1': o1, 'outcome_ladder': oN,
                         'bias': bias or '',
                         'verdict': verdict.get('verdict', ''),
                         'score': verdict.get('score', ''),
                         'rr_tp1': round(sig.computed_rr, 2),
                         'rr_ladder': round(sig.ladder_rr, 2),
                         'mfe': mfe, 'mae': mae})

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    if rows:
        with open(args.out, 'w', newline='', encoding='utf-8') as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)

    report(rows, args.out)


def report(rows, out_path):
    traded = [r for r in rows if not r['skip']]
    filled = [r for r in traded if r['outcome_tp1'] != 'no_fill']
    print(f'\nsignal messages: {len(set(r["date"] for r in rows))}   '
          f'legs: {len(traded)}   filled: {len(filled)}   '
          f'never filled: {len(traded) - len(filled)}')
    if not filled:
        print('no fills — check candle coverage')
        return
    tp1 = sum(r['pnl_tp1'] for r in filled)
    lad = sum(r['pnl_ladder'] for r in filled)
    print(f'policy A  close whole leg at TP1 (what Hermes does): '
          f'{tp1:+8.1f}$   avg {tp1/len(filled):+.2f}$')
    print(f'policy B  half at TP1 + runner to last rung (channel): '
          f'{lad:+8.1f}$   avg {lad/len(filled):+.2f}$')
    wa = sum(1 for r in filled if r['pnl_tp1'] > 0)
    wb = sum(1 for r in filled if r['pnl_ladder'] > 0)
    print(f'win rate: A {100*wa/len(filled):.0f}%   B {100*wb/len(filled):.0f}%')

    gated = [r for r in traded if r['verdict']]
    if gated:
        ex = [r for r in gated if r['verdict'] == 'execute']
        print(f'\nwindow with Hermes bias on record: {len(gated)} legs, '
              f'gate said execute on {len(ex)} ({100*len(ex)/len(gated):.0f}%)')
        if ex:
            print(f'  those {len(ex)} legs: policy A '
                  f'{sum(r["pnl_tp1"] for r in ex):+.1f}$, '
                  f'policy B {sum(r["pnl_ladder"] for r in ex):+.1f}$')
        rej = [r for r in gated if r['verdict'] != 'execute']
        if rej:
            print(f'  rejected {len(rej)} legs would have made (policy B): '
                  f'{sum(r["pnl_ladder"] for r in rej):+.1f}$')
    print(f'out -> {out_path}')


if __name__ == '__main__':
    main()
