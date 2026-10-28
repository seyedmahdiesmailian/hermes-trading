"""b112 probe part 2: does the symbol_defaulted family actually PERFORM worse?

b112's penalty proposal is only worth a human decision if the population it
taxes is a bad population. The flip count (probe 1: 1/29 execute->skip) is the
COST side; this is the BENEFIT side, measured on the channel replay: every
signal message in data/radin/replay*.csv is re-parsed in the LIVE frame (the
price + 24h band as they were at signal time, current parser), tagged
defaulted / named-gold / other, and its already-resolved P&L legs are grouped
by tag. If defaulted legs perform at or above the named-gold legs, the penalty
taxes good trades and the honest recommendation is NO penalty (fix Check 1's
credit instead, or nothing).

Read-only: bridge.get_rates via radin_replay.load_candles. No order endpoints.
"""
import csv
import glob
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
try:
    from dotenv import load_dotenv
except ImportError:
    from env_loader import load_dotenv
load_dotenv(os.path.join(_ROOT, '.env'))

from engines.signal_parser import parse_signal  # noqa: E402
from scripts.radin_replay import load_candles, price_at  # noqa: E402

OUT = os.path.join(_ROOT, 'data', 'backtest', 'b112_defaulted_performance.json')


def main():
    candles = load_candles()
    # date -> full message text (replay.csv truncates text to 70 chars)
    texts = {}
    for p in glob.glob(os.path.join(_ROOT, 'data', 'radin', 'history*.jsonl')):
        for line in open(p, encoding='utf-8'):
            m = json.loads(line)
            texts[m['date']] = m.get('text') or ''

    groups = defaultdict(list)   # tag -> [leg rows]
    seen_legs = 0
    unmatched = 0
    for csv_path in sorted(glob.glob(os.path.join(_ROOT, 'data', 'radin', 'replay*.csv'))):
        channel = os.path.basename(csv_path)
        for r in csv.DictReader(open(csv_path, encoding='utf-8')):
            if r['skip'] or not r['leg']:
                continue
            txt = texts.get(r['date'])
            if txt is None:
                unmatched += 1
                continue
            ts = int(datetime.fromisoformat(r['date']).timestamp())
            px, band = price_at(candles, ts)
            if not px:
                continue
            sig = parse_signal(txt, current_price=px, price_band=band)
            tag = ('defaulted' if 'symbol_defaulted_xauusd' in sig.warnings
                   else 'named_gold' if sig.symbol == 'XAUUSD'
                   else 'other:' + (sig.symbol or 'none'))
            leg = float(r['leg'])
            entry = sig.entry or leg
            risk = abs(leg - float(r['sl'])) if float(r['sl']) else 0
            groups[tag].append({
                'channel': channel,
                'pnl_tp1': float(r['pnl_tp1']),
                'pnl_ladder': float(r['pnl_ladder']),
                'filled': r['outcome_tp1'] != 'no_fill',
                'risk_usd': risk,
                'rr_tp1': float(r['rr_tp1'] or 0),
            })
            seen_legs += 1

    def summarize(rows):
        f = [x for x in rows if x['filled']]
        n = len(f)
        if not n:
            return {'legs': len(rows), 'filled': 0}
        a = sum(x['pnl_tp1'] for x in f)
        b = sum(x['pnl_ladder'] for x in f)
        # R-normalised: $ move / risk distance, so a 20$ stop and a 5$ stop
        # are comparable (the raw $ column is not)
        ra = [x['pnl_tp1'] / x['risk_usd'] for x in f if x['risk_usd'] > 0]
        win = sum(1 for x in f if x['pnl_tp1'] > 0)
        return {'legs': len(rows), 'filled': n,
                'avg_usd_tp1': round(a / n, 2), 'avg_usd_ladder': round(b / n, 2),
                'avg_R_tp1': round(sum(ra) / len(ra), 3) if ra else None,
                'win_rate_tp1': round(win / n, 3),
                'channels': sorted({x['channel'] for x in rows})}

    # channel is a CONFOUND: the four channels differ in style, so a raw
    # defaulted-vs-named gap may be channel quality, not warning quality.
    # Break it down WITHIN each channel and average only over channels that
    # carry BOTH populations (the honest comparison).
    by_ch = defaultdict(lambda: defaultdict(list))
    for tag, rows in groups.items():
        for x in rows:
            by_ch[x['channel']][tag].append(x)
    within = {}
    for ch, tags in sorted(by_ch.items()):
        d, g = tags.get('defaulted', []), tags.get('named_gold', [])
        if d and g:
            within[ch] = {'defaulted': summarize(d), 'named_gold': summarize(g)}
    out = {'legs_total': seen_legs, 'unmatched_dates': unmatched,
           'by_tag': {k: summarize(v) for k, v in sorted(groups.items())},
           'within_channel_both_populations': within}
    json.dump(out, open(OUT, 'w', encoding='utf-8'), indent=1)
    print(json.dumps(out, indent=1))
    d = out['by_tag'].get('defaulted', {})
    g = out['by_tag'].get('named_gold', {})
    if d.get('filled') and g.get('filled'):
        print(f"\nDEFAULTED vs NAMED (policy A, $/leg): {d['avg_usd_tp1']} vs {g['avg_usd_tp1']}")
        print(f"DEFAULTED vs NAMED (avg R/leg)       : {d['avg_R_tp1']} vs {g['avg_R_tp1']}")
        print(f"n filled: {d['filled']} vs {g['filled']}")


if __name__ == '__main__':
    main()
