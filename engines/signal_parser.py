"""Telegram signal parser — extracts trade signals from text messages.

Supports common signal formats from forex signal groups:
- "XAUUSD BUY 2595.50 SL 2590 TP 2605"
- "🟢 BUY XAUUSD @ 2595 | SL: 2590 | TP: 2605"
- "Sell Gold 2595.50 Stop 2600 Target 2585"
- "XAUUSD SELL LIMIT 2598.00"
- And variations with Persian/Arabic keywords
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


# Common symbol aliases
SYMBOL_MAP = {
    "gold": "XAUUSD", "xauusd": "XAUUSD", "xau": "XAUUSD",
    "گلد": "XAUUSD", "طلا": "XAUUSD",
    "eurusd": "EURUSD", "eur/usd": "EURUSD",
    "gbpusd": "GBPUSD", "gbp/usd": "GBPUSD",
    "usdjpy": "USDJPY", "usd/jpy": "USDJPY",
    "xagusd": "XAGUSD", "silver": "XAGUSD", "نقره": "XAGUSD",
    "btcusd": "BTCUSD", "bitcoin": "BTCUSD",
    "us30": "US30", "dj30": "US30", "dow": "US30",
    "nas100": "NAS100", "nasdaq": "NAS100",
    "spx500": "SPX500", "sp500": "SPX500",
}

BUY_KEYWORDS = {"buy", "long", "buy limit", "buy stop", "خرید", "لانگ", "بای", "🟢", "📈", "⬆️"}
SELL_KEYWORDS = {"sell", "short", "sell limit", "sell stop", "فروش", "شورت", "سل", "🔴", "📉", "⬇️"}

PERSIAN_DIGITS = str.maketrans('۰۱۲۳۴۵۶۷۸۹', '0123456789')
ARABIC_DIGITS = str.maketrans('٠١٢٣٤٥٦٧٨٩', '0123456789')
SUPERSCRIPT_DIGITS = str.maketrans('¹²³⁴⁵⁶⁷⁸⁹⁰', '1234567890')


def normalize_digits(text: str) -> str:
    """Convert Persian/Arabic/superscript numerals to Latin so regexes work."""
    return text.translate(PERSIAN_DIGITS).translate(ARABIC_DIGITS).translate(SUPERSCRIPT_DIGITS)

TP_PATTERNS = [
    r'(?:tp2|target2)[\s:=.]*(\d+\.?\d*)',
    r'(?:tp1|target1)[\s:=.]*(\d+\.?\d*)',
    r'(?:tp|target|take\s*profit|تیک\s*پروفیت|تی\s*پی|تی‌پی|تی‌\s*پی|تي\s*پی|هدف|تارگت|سود)[\s:=.]*(\d+\.?\d*)',
]

SL_PATTERNS = [
    r'(?:sl|stop\s*(?:loss)?|ستاپ|اس\s*ال|حد\s*ضرر|ضرر|استاپ)[\s:=]*(\d+\.?\d*)',
]

ENTRY_PATTERNS = [
    r'(?:entry|price|قیمت|ورود|buyzone|sellzone|buy\s*zone|sell\s*zone)[\s:=]*(\d+\.?\d*)',
    r'(?:at|@\s*)[\s:=]*(\d+\.?\d*)',
]

# b71 — multi-leg entries: channels often post a 2-step entry ("BUY 4471 /
# MORE BUY 4465", "خرید ۸۲ و ۷۲"). The first level is the primary entry, the
# rest are additional legs that get their own LIMIT order at their own price.
LEG_PATTERNS = [
    r'(?:more|add|again|2nd|second|ladder)\s*(?:buy|sell)?\s*(?:at|@|:)?\s*(\d+\.?\d*)',
    r'(?:buy|sell)\s*(?:again|#2|2)\s*(?:at|@|:)?\s*(\d+\.?\d*)',
    r'(?:entry|پله|ورود)\s*(?:2|۲)\s*[:=@]?\s*(\d+\.?\d*)',
    r'(\d+\.?\d*)\s*و\s*(?:\d+\.?\d*\s*)?(?:خرید|فروش)',
    r'و\s*(\d+\.?\d*)\s*(?:خرید|فروش)',
]

LOT_PATTERNS = [
    r'(?:lot|volume|حجم|لот)\s*[:=]?\s*(\d+\.?\d+)',
]

RR_PATTERNS = [
    r'(?:rr|r:r|risk\s*(?:to)?\s*reward|ریسک\s*ریوارد)\s*[:=]?\s*(\d+\.?\d*)',
]

SYMBOL_PATTERN = re.compile(
    r'\b(' + '|'.join(re.escape(k) for k in sorted(SYMBOL_MAP.keys(), key=len, reverse=True)) + r')\b',
    re.IGNORECASE,
)


@dataclass
class Signal:
    symbol: str = ""
    side: str = ""  # BUY or SELL
    entry: float = 0.0
    entries: list = field(default_factory=list)  # b71: all entry legs (primary first)
    sl: float = 0.0
    tp: float = 0.0
    tp2: float = 0.0
    lot: float = 0.0
    rr_ratio: float = 0.0
    order_type: str = ""  # market, limit, stop
    raw_text: str = ""
    confidence: float = 0.0  # 0-1, how confident we are in the parse
    warnings: list = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return bool(self.symbol and self.side and self.entry > 0)

    @property
    def has_sl(self) -> bool:
        return self.sl > 0

    @property
    def has_tp(self) -> bool:
        return self.tp > 0

    @property
    def risk_distance(self) -> float:
        if not self.has_sl:
            return 0
        return abs(self.entry - self.sl)

    @property
    def reward_distance(self) -> float:
        if not self.has_tp:
            return 0
        return abs(self.tp - self.entry)

    @property
    def computed_rr(self) -> float:
        rd = self.risk_distance
        if rd <= 0:
            return 0
        return round(self.reward_distance / rd, 2)

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol, "side": self.side, "entry": self.entry,
            "entries": list(self.entries),
            "sl": self.sl, "tp": self.tp, "tp2": self.tp2, "lot": self.lot,
            "rr_ratio": self.rr_ratio or self.computed_rr,
            "order_type": self.order_type, "confidence": self.confidence,
            "warnings": self.warnings,
        }


def _extract_symbol(text: str) -> str:
    m = SYMBOL_PATTERN.search(text)
    if m:
        return SYMBOL_MAP.get(m.group(1).lower(), m.group(1).upper())
    return ""


def _extract_side(text: str) -> str:
    lower = text.lower()
    if "buyzone" in lower or "buy zone" in lower:
        return "BUY"
    if "sellzone" in lower or "sell zone" in lower:
        return "SELL"
    for kw in SELL_KEYWORDS:
        if kw in lower:
            return "SELL"
    for kw in BUY_KEYWORDS:
        if kw in lower:
            return "BUY"
    # Fallback: check for directional arrows or emojis
    if "🟢" in text or "📈" in text or "⬆️" in text:
        return "BUY"
    if "🔴" in text or "📉" in text or "⬇️" in text:
        return "SELL"
    return ""


def _extract_prices(text: str, patterns: list[str]) -> list[float]:
    results = []
    seen = set()
    for pat in patterns:
        for m in re.finditer(pat, text, re.IGNORECASE):
            try:
                val = float(m.group(1))
                if val > 0 and m.start() not in seen:
                    results.append((m.start(), val))
                    seen.add(m.start())
            except (ValueError, IndexError):
                pass
    results.sort(key=lambda x: x[0])  # sort by position in text
    return [v for _, v in results]


def _extract_order_type(text: str) -> str:
    lower = text.lower()
    if "buy limit" in lower or "sell limit" in lower:
        return "limit"
    if "buy stop" in lower or "sell stop" in lower:
        return "stop"
    return "market"


def expand_abbreviated_price(value: float, current_price: float,
                            prefer_below: bool = False, prefer_above: bool = False) -> float:
    """Group posts short prices: '76' means 4476 when gold is at 4474."""
    if not current_price or current_price <= 0 or value <= 0 or value >= 1000:
        return value
    base = int(current_price // 100) * 100
    candidates = [base - 100 + value, base + value, base + 100 + value]
    if prefer_below:
        candidates = [c for c in candidates if c < current_price] or candidates
    if prefer_above:
        candidates = [c for c in candidates if c > current_price] or candidates
    return min(candidates, key=lambda c: abs(c - current_price))


def parse_signal(text: str, current_price: float = 0.0) -> Signal:
    """Parse a trading signal from text. Returns a Signal object."""
    if not text or not text.strip():
        return Signal(raw_text=text or "")

    text = normalize_digits(text)
    sig = Signal(raw_text=text.strip())
    confidence = 0.0

    # Symbol
    sig.symbol = _extract_symbol(text)
    if sig.symbol:
        confidence += 0.3
    else:
        # Signal group is gold-focused: default to XAUUSD if prices look like gold
        import re as _re
        _nums = [float(n) for n in _re.findall(r'\d{2,5}\.?\d{0,3}', text)]
        _gold_full = _nums and 1500 <= max(_nums) <= 6000
        _gold_abbrev = current_price > 0 and _nums and max(_nums) < 1000 and 1500 <= current_price <= 6000
        if _gold_full or _gold_abbrev:
            sig.symbol = "XAUUSD"
            confidence += 0.25
            sig.warnings.append("symbol_defaulted_xauusd")
        else:
            sig.warnings.append("no_symbol_found")

    # Side
    sig.side = _extract_side(text)
    if sig.side:
        confidence += 0.3
    else:
        sig.warnings.append("no_direction_found")

    # Order type
    sig.order_type = _extract_order_type(text)

    # Entry price
    entries = _extract_prices(text, ENTRY_PATTERNS)
    if entries:
        sig.entry = entries[0]
        confidence += 0.15

    # b71 — additional entry legs ("MORE BUY 4465", "پله 2: 4465", "۸۲ و ۷۲ خرید")
    leg_prices = _extract_prices(text, LEG_PATTERNS)
    _all = [sig.entry] + [p for p in leg_prices if p != sig.entry]
    # zone form: "Buy Zone: 4465 - 4470" → both ends are entries
    _zone = re.search(r'(?:buy|sell)\s*zone[^\d]*(\d+\.?\d*)\s*[-–—]\s*(\d+\.?\d*)',
                      text, re.IGNORECASE)
    if _zone:
        _all += [float(_zone.group(1)), float(_zone.group(2))]
    _seen_e = set()
    sig.entries = [e for e in _all if e > 0 and not (e in _seen_e or _seen_e.add(e))]

    # SL
    sls = _extract_prices(text, SL_PATTERNS)
    if sls:
        sig.sl = sls[0]
        confidence += 0.1

    # TP (may have multiple)
    tps = _extract_prices(text, TP_PATTERNS)
    if tps:
        sig.tp = tps[0]
        confidence += 0.1
        if len(tps) > 1:
            sig.tp2 = tps[1]

    # If no entry found, try to find a bare number near buy/sell
    if sig.entry == 0:
        bare_prices = re.findall(r'(\d{2,6}\.?\d{0,4})', text)
        # Filter out very small numbers (lot sizes, etc.) — entry is usually 2+ digits
        candidates = [float(b) for b in bare_prices if float(b) >= 10]
        if candidates:
            sig.entry = candidates[0]
            confidence += 0.05

    # Expand abbreviated prices ('76' → 4476) using live price + side geometry
    if current_price > 0:
        if 0 < sig.entry < 1000:
            sig.entry = expand_abbreviated_price(sig.entry, current_price)
        # b71: re-sync legs after expansion; expand any abbreviated leg too
        sig.entries = [sig.entry] + [
            (expand_abbreviated_price(e, current_price) if 0 < e < 1000 else e)
            for e in sig.entries if abs(e - sig.entry) > 0.01]
        if 0 < sig.sl < 1000:
            sig.sl = expand_abbreviated_price(sig.sl, current_price)
        # TP must sit on the profit side of entry: below for SELL, above for BUY
        if 0 < sig.tp < 1000 and sig.entry > 0 and sig.side:
            sig.tp = expand_abbreviated_price(
                sig.tp, current_price,
                prefer_below=(sig.side == "SELL"), prefer_above=(sig.side == "BUY"))
        if 0 < sig.tp2 < 1000 and sig.entry > 0 and sig.side:
            sig.tp2 = expand_abbreviated_price(
                sig.tp2, current_price,
                prefer_below=(sig.side == "SELL"), prefer_above=(sig.side == "BUY"))

    # Lot
    lots = _extract_prices(text, LOT_PATTERNS)
    if lots:
        sig.lot = lots[0]

    # R:R
    rr_vals = _extract_prices(text, RR_PATTERNS)
    if rr_vals:
        sig.rr_ratio = rr_vals[0]

    # Validate side consistency with entry/SL/TP
    if sig.side == "BUY" and sig.entry > 0 and sig.sl > 0 and sig.sl > sig.entry:
        sig.warnings.append("sl_above_entry_for_buy")
        confidence -= 0.1
    if sig.side == "SELL" and sig.entry > 0 and sig.sl > 0 and sig.sl < sig.entry:
        sig.warnings.append("sl_below_entry_for_sell")
        confidence -= 0.1

    # b71: final sync — primary entry first, distinct legs after it
    if sig.entry > 0:
        sig.entries = [sig.entry] + [e for e in sig.entries if e > 0 and abs(e - sig.entry) > 0.01]

    sig.confidence = round(min(1.0, max(0.0, confidence)), 2)
    return sig
