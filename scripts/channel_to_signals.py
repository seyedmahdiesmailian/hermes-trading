# -*- coding: utf-8 -*-
"""پل: تاریخچه خام کانال‌ها → signals_log.json با همان ساختار فوروارددر.

این ماژول مسیر بازپخش (channel replay) است: پیام‌های raw کانال را با
پارسر V1 (که در تولید ثابت کرده) می‌خواند، قیمت لحظه‌ای بازار را از
کندل‌ها تزریق می‌کند و خروجی را دقیقاً با ساختاری می‌نویسد که
SignalsAdapter/_load_signals در entry/backtest.py می‌خواند.

ساختار خروجی (همان signals_log.json):
  {"timestamp", "raw_text", "parsed": {...}, "decision": {...}}

نکته حل‌شده: پارسر V1 روی فرمت‌های Olivex (TP/SL دایره‌ای) کور بود.
به جای تغییر پارسر، یک فیلتر سازگارکننده اضافه شد: نشانه‌های دایره‌ای
①②③ و ❌/✔️ به فرمت متنی قابل پارس تبدیل می‌شوند تا پارسر اصلی
دست‌نخورده بماند.
"""
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from legacy_v1.engines.signal_parser import parse_signal  # noqa: E402

# ── فیلتر سازگارکننده لهجه‌ها ════════════════════════════
# نشانه‌های دایره‌ای Olivex → TP1/TP2/TP3 برای پارسر اصلی
_CIRCLED = {
    '①': '1', '②': '2', '③': '3', '④': '4', '⑤': '5',
    '⑥': '6', '⑦': '7', '⑧': '8', '⑨': '9',
}
_CIRCLED_RE = re.compile('[' + ''.join(_CIRCLED) + ']')


def normalize_dialect(text: str) -> str:
    """تبدیل لهجه‌های تصویری کانال‌ها به فرمت قابل پارس.

    فقط یک قاعده: جایگزینی نشانه‌های دایره‌ای با شمارهٔ رung.
    پارسر اصلی نباید دست بخورد.
    """
    def _sub(m: "re.Match[str]") -> str:
        return f"TP{_CIRCLED[m.group(0)]} "

    out = _CIRCLED_RE.sub(_sub, text)
    # جداکننده‌های نمادین Olivex → فاصله ساده
    # (پارسر V1 فقط [\s:=] را بین کلمه‌کلیدی و عدد می‌پذیرد، نه '|')
    out = out.replace('│', ' ').replace('|', ' ')
    # ❌ Stop Loss → SL (پارسر V1 به این شکل می‌شناسد)
    out = re.sub(r'❌\s*stop\s*loss', 'SL', out, flags=re.IGNORECASE)
    out = re.sub(r'✔️\s*targets?', 'TP', out, flags=re.IGNORECASE)
    out = re.sub(r'📍\s*entry', 'Entry', out, flags=re.IGNORECASE)
    return out


# نمایش پایه برای ساختن ردیف سیگنال ──────────────────
def build_signal_row(
        msg: dict,
        current_price: float,
        band: tuple | None) -> dict | None:
    """ساختن یک ردیف signals_log از پیام خام کانال.

    Returns None اگر پیام سیگنال نباشد یا entry/sl پیدا نشود.
    """
    raw = msg.get('text') or ''
    if not raw.strip():
        return None
    norm = normalize_dialect(raw)
    try:
        sig = parse_signal(norm, current_price=current_price,
                           price_band=band)
    except Exception:
        return None
    if sig is None:
        return None
    if not (sig.symbol == 'XAUUSD'
            and str(sig.side).lower() in ('buy', 'sell')
            and sig.entry > 0 and sig.sl > 0):
        return None
    # رد شدن سیگنال‌هایی که entry دور از بازار است (>۵٪) — آگهی نیست
    if abs(sig.entry - current_price) / current_price > 0.05:
        return None

    tp = sig.tp if sig.tp > 0 else (
        sig.tps[0] if getattr(sig, 'tps', None) else 0.0)
    # پلکان اهداف: آخرین پله = هدف نهایی واقعی سیگنال.
    # کانال‌ها TP1 را ۳ پیپ می‌گذارند ولی سود اصلی از پله‌های دور است.
    # ExitManager با breakeven+trailing دقیقاً همین مسیر را مدیریت می‌کند.
    ladder = [float(t) for t in (getattr(sig, 'tps', None) or []) if t > 0]
    if ladder:
        tp = ladder[-1]
    rr = (abs(tp - sig.entry) / abs(sig.sl - sig.entry)
          if tp > 0 and sig.sl != sig.entry else 0.0)
    parsed = {
        'symbol': 'XAUUSD',
        'side': str(sig.side).upper(),
        'entry': round(float(sig.entry), 2),
        'entries': [round(float(e), 2) for e
                    in (getattr(sig, 'entries', None) or [sig.entry])],
        'sl': round(float(sig.sl), 2),
        'tp': round(float(tp), 2),
        'tp2': round(float(sig.tp2), 2) if getattr(sig, 'tp2', 0) else 0.0,
        'lot': float(getattr(sig, 'lot', 0) or 0),
        'rr_ratio': round(float(rr), 2),
        'computed_rr': round(float(rr), 2),
        'tps': [round(float(t), 2) for t
                in (getattr(sig, 'tps', None) or [])],
        'ladder_rr': 0.0,
        'order_type': str(getattr(sig, 'order_type', 'market') or 'market'),
        'confidence': float(getattr(sig, 'confidence', 0) or 0),
        'warnings': list(getattr(sig, 'warnings', []) or []),
    }
    return {
        'id': str(msg.get('id', '')),
        'timestamp': msg.get('date', ''),
        'raw_text': raw,
        'parsed': parsed,
        'decision': {'verdict': 'pending'},
    }


def build_bars_index(bars: list[dict]) -> list[int]:
    return [int(b['time']) for b in bars]


def find_price(
        bars: list[dict],
        times: list[int],
        ts: float) -> tuple[float, tuple[float, float]] | None:
    """آخرین کندل قبل از ts → (close, (low_24h, high_24h)) یا None."""
    import bisect
    i = bisect.bisect_right(times, int(ts)) - 1
    if i < 0:
        return None
    close = float(bars[i]['close'])
    lo = min(float(x['low']) for x in bars[max(0, i - 95):i + 1])
    hi = max(float(x['high']) for x in bars[max(0, i - 95):i + 1])
    return close, (lo, hi)


def convert(history_files: list[str], bars_file: str, out_file: str,
            verbose: bool = True) -> dict:
    """تبدیل تاریخچه خام → signals_log.json در فرمت فوروارددر."""
    bars = json.loads(Path(bars_file).read_text())
    times = build_bars_index(bars)

    kept: list[dict] = []
    n_scanned = n_signal = 0
    for hf in history_files:
        for line in open(hf, encoding='utf-8'):
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            n_scanned += 1
            date = msg.get('date') or ''
            try:
                ts = datetime.fromisoformat(date).timestamp()
            except ValueError:
                continue
            hit = find_price(bars, times, ts)
            if hit is None:
                continue
            px, band = hit
            row = build_signal_row(msg, px, band)
            if row is not None:
                kept.append(row)
                n_signal += 1
    kept.sort(key=lambda r: r['timestamp'])
    Path(out_file).write_text(json.dumps(kept, ensure_ascii=False,
                                         indent=1))
    if verbose:
        print(f'پیام‌های اسکن‌شده: {n_scanned}')
        print(f'سیگنال‌های استخراج‌شده: {n_signal}')
    return {'scanned': n_scanned, 'signals': n_signal, 'out': out_file}
