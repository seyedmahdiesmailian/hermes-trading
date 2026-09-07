"""b112 probe: measure the parser-warning census in the frame the LIVE gate sees,
and price the proposed Check-8 penalty as a counterfactual.

WHY: b106 filed b112 with a census measured by re-parsing raw_text OFFLINE
(current_price=0). That is not the frame production runs in: the live listener
passes the real tick + 24h band, and the parser's `_gold_abbrev` branch only
fires when current_price>0. This probe measures BOTH frames side by side,
reconstructs the price each signal actually saw from read-only bridge M5
candles, re-parses with the CURRENT parser, and then prices the penalty
counterfactual through the real evaluate_signal (no hand-copied gate).

Read-only: bridge.get_rates only. No order endpoints.
"""
import csv
import json
import os
import sys
from collections import Counter
from datetime import datetime, timezone

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
try:
    from dotenv import load_dotenv
except ImportError:
    from env_loader import load_dotenv
load_dotenv(os.path.join(_ROOT, '.env'))

from engines.signal_parser import parse_signal, names_other_instrument  # noqa: E402
from engines.signal_decision import evaluate_signal  # noqa: E402
from scripts.radin_replay import load_candles, price_at, bias_at, load_bias_timeline  # noqa: E402

JOURNAL = os.path.join(_ROOT, 'data', 'signals', 'signals_log.json')
OUT = os.path.join(_ROOT, 'data', 'backtest', 'b112_warning_frame.json')


def gate(sig_dict, bias):
    """The gate as radin_replay runs it: neutral account, bias on record."""
    return evaluate_signal(dict(sig_dict), {'bias': bias or 'neutral'},
                           {'trade_allowed': True, 'open_positions': 0})


def main():
    journal = json.load(open(JOURNAL, encoding='utf-8'))
    candles = load_candles()
    timeline = load_bias_timeline()
    first = datetime.fromtimestamp(candles[0][0], timezone.utc)

    rows = []
    for i, e in enumerate(journal):
        ts = datetime.fromisoformat(e['timestamp']).timestamp()
        raw = e.get('raw_text') or ''
        px, band = price_at(candles, int(ts))
        bias = bias_at(timeline, int(ts))
        rec = {'i': i, 'ts': e['timestamp'], 'in_candle_window': bool(px),
               'bias': bias, 'other_instrument': names_other_instrument(raw),
               'logged_warnings': e['parsed'].get('warnings', []),
               'logged_verdict': e['decision'].get('verdict'),
               'logged_score': e['decision'].get('score')}
        # frame A: b106's frame — offline re-parse, no price
        a = parse_signal(raw)
        rec['offline_warnings'] = a.warnings
        rec['offline_symbol'] = a.symbol
        # frame B: the live frame — current parser, price + band as they were
        if px:
            b = parse_signal(raw, current_price=px, price_band=band)
            rec['live_warnings'] = b.warnings
            rec['live_symbol'] = b.symbol
            rec['live_side'] = b.side
            rec['live_entry'] = b.entry
            rec['live_sl'] = b.sl
            rec['live_tp'] = b.tp
            rec['live_confidence'] = b.confidence
            rec['live_valid'] = b.is_valid
            # counterfactual gate runs on the live-frame parse
            if b.is_valid:
                g = gate(b.to_dict(), bias)
                rec['cf_verdict'] = g['verdict']
                rec['cf_score'] = g['score']
                rec['cf_reasons'] = g['reasons']
        rows.append(rec)

    covered = [r for r in rows if r['live_valid'] is not None and r.get('live_symbol')]
    n = len(covered)

    def census(key):
        c = Counter()
        for r in rows:
            for w in (r.get(key) or []):
                c[w] += 1
        return dict(c)

    # ── counterfactual penalty schemes (all TIGHTENINGS; measured, not shipped)
    schemes = {
        'defaulted_minus_0.5': lambda ws: -0.5 if 'symbol_defaulted_xauusd' in ws else 0.0,
        'defaulted_minus_1.0': lambda ws: -1.0 if 'symbol_defaulted_xauusd' in ws else 0.0,
        'check1_half_on_default': lambda ws: -0.5 if 'symbol_defaulted_xauusd' in ws else 0.0,
    }
    flips = {}
    for name, fn in schemes.items():
        ex_before = ex_after = 0
        changed = []
        for r in covered:
            if not r.get('cf_verdict'):
                continue
            before = r['cf_verdict'] == 'execute'
            after = (r['cf_score'] + fn(r['live_warnings'])) >= 6.0
            ex_before += before
            ex_after += after
            if before != after:
                changed.append(r['i'])
        flips[name] = {'execute_before': ex_before, 'execute_after': ex_after,
                       'flipped_signals': changed}

    # ── what would the penalty TAX? defaulted vs FX-mangling population
    defaulted = [r for r in covered if 'symbol_defaulted_xauusd' in (r.get('live_warnings') or [])]
    named_gold = [r for r in covered if not r.get('live_warnings')]

    out = {
        'journal_n': len(rows),
        'candle_window_start': first.isoformat(),
        'candles': len(candles),
        'census_logged_frame': census('logged_warnings'),
        'census_offline_frame_b106': census('offline_warnings'),
        'census_live_frame_current_parser': census('live_warnings'),
        'n_gate_reachable': n,
        'n_other_instrument_dropped_upstream': sum(1 for r in rows if r['other_instrument']),
        'n_defaulted_live': len(defaulted),
        'n_clean_named_live': len(named_gold),
        'defaulted_share_of_gate_reachable': round(len(defaulted) / max(1, n), 3),
        'counterfactual_flips': flips,
        'rows': rows,
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(out, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)

    print(f'journal: {len(rows)} signals | candle window from {first:%Y-%m-%d} | '
          f'{len(candles)} M5 bars')
    print(f'gate-reachable (valid parse in live frame): {n}')
    print(f'dropped upstream by names_other_instrument (b74g): '
          f'{out["n_other_instrument_dropped_upstream"]}')
    print()
    print('WARNING CENSUS, three frames:')
    print('  as-logged (old parser, live price):', out['census_logged_frame'])
    print('  b106 frame (offline, no price)    :', out['census_offline_frame_b106'])
    print('  live frame (current parser+price) :', out['census_live_frame_current_parser'])
    print()
    print(f'defaulted share of gate-reachable: {out["defaulted_share_of_gate_reachable"]:.0%} '
          f'({len(defaulted)}/{n})   clean-named: {len(named_gold)}')
    print()
    print('COUNTERFACTUAL (threshold 6.0, neutral account, bias on record):')
    for k, v in flips.items():
        print(f'  {k:24s} execute {v["execute_before"]} -> {v["execute_after"]}  '
              f'flipped: {v["flipped_signals"]}')
    print(f'\nledger: {OUT}')


if __name__ == '__main__':
    main()
