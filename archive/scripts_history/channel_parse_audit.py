"""Audit parser coverage per signal channel (b74).

The replay numbers are only as good as the parse. For every channel this
reports how many signal-shaped messages produced a usable entry+SL, how
many TP rungs were recovered vs how many the raw text actually mentions,
and flags messages where the parser silently dropped targets.

Run: python3 scripts/channel_parse_audit.py
"""
import json
import os
import re
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from engines.signal_parser import parse_signal  # noqa: E402

HIST_DIR = os.path.join(_ROOT, 'data', 'radin')

CHANNELS = {
    'radin': 'history_90d.jsonl',
    'olivex': 'history_olivex.jsonl',
    'otsfx': 'history_otsfx.jsonl',
    'goldsystem': 'history_goldsystem.jsonl',
    'goldfree': 'history_goldfree.jsonl',
    'gtmo': 'history_gtmo.jsonl',
    'gtmofx': 'history_gtmofx.jsonl',
}

# How many targets does a human reading the raw text see?
RAW_TP_MENTIONS = re.compile(
    r'(?:TP|Target|T/P|تی\s*پی|تارگت)\s*[¹²³⁴⁵⁶⁷⁸⁹1-9]?\s*[:=]?\s*'
    r'\$?\d{3,5}(?:\.\d+)?', re.I)
RAW_SL = re.compile(r'(?:SL|Stop\s*loss|Stoploss|استاپ|اسلپ)\s*[:=]?\s*'
                    r'\$?\d{2,5}(?:\.\d+)?', re.I)
RAW_SIDE = re.compile(r'\b(buy|sell|خرید|فروش)\b', re.I)


def main():
    print('%-11s %6s %6s %6s %7s %7s %8s' % (
        'channel', 'msgs', 'sig', 'parsed', 'tp_raw', 'tp_got', 'dropped'))
    for name, fn in CHANNELS.items():
        path = os.path.join(HIST_DIR, fn)
        if not os.path.exists(path):
            continue
        rows = [json.loads(l) for l in open(path, encoding='utf-8')]
        sig = parsed = 0
        tp_raw = tp_got = dropped = 0
        for m in rows:
            t = m.get('text', '')
            if not RAW_SIDE.search(t):
                continue
            sig += 1
            # gold trades in the 4000s; use a band around the quoted numbers
            nums = [float(x) for x in re.findall(r'\d{4}(?:\.\d+)?', t)]
            px = max(nums) if nums else 4400.0
            s = parse_signal(t, current_price=px,
                             price_band=(px - 120, px + 120))
            if s.side and s.entry > 0 and s.sl > 0:
                parsed += 1
            n_raw = len(RAW_TP_MENTIONS.findall(t))
            n_got = len(s.tps or []) + (1 if s.tp else 0)
            tp_raw += n_raw
            tp_got += min(n_got, n_raw)
            if n_raw > n_got:
                dropped += 1
        print('%-11s %6d %6d %6d %7d %7d %8d' % (
            name, len(rows), sig, parsed, tp_raw, tp_got, dropped))


if __name__ == '__main__':
    main()
