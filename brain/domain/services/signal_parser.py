"""Telegram Signal Parser V2 - Clean Architecture.

Extracts trading signals from Telegram messages.
Supports multiple formats: English, Farsi, Arabic, emoji.

Adapted from V1 signal_parser.py (proven in production).
"""

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, List, Tuple

from brain.domain.entities.signal import Signal, SignalSource, SignalQuality


# Symbol aliases
SYMBOL_MAP = {
    "gold": "XAUUSD", "xauusd": "XAUUSD", "xau": "XAUUSD",
    "گلد": "XAUUSD", "طلا": "XAUUSD",
    "eurusd": "EURUSD", "eur/usd": "EURUSD",
    "gbpusd": "GBPUSD", "gbp/usd": "GBPUSD",
    "usdjpy": "USDJPY", "usd/jpy": "USDJPY",
    "xagusd": "XAGUSD", "silver": "XAGUSD", "نقره": "XAGUSD",
}

BUY_WORDS = {"buy", "long", "buy limit", "buy stop", "خرید", "لانگ", "بای"}
SELL_WORDS = {"sell", "short", "sell limit", "sell stop", "فروش", "شورت", "سل"}
DIRECTION_EMOJI_BUY = {"🟢", "📈", "⬆️", "🔼"}
DIRECTION_EMOJI_SELL = {"🔴", "📉", "⬇️", "🔽"}

BUY_KEYWORDS = BUY_WORDS | DIRECTION_EMOJI_BUY
SELL_KEYWORDS = SELL_WORDS | DIRECTION_EMOJI_SELL

# Digit normalization
PERSIAN_DIGITS = str.maketrans('۰۱۲۳۴۵۶۷۸۹', '0123456789')
ARABIC_DIGITS = str.maketrans('٠١٢٣٤٥٦٧٨٩', '0123456789')


def normalize_digits(text: str) -> str:
    """Convert Persian/Arabic numerals to Latin."""
    return text.translate(PERSIAN_DIGITS).translate(ARABIC_DIGITS)


# Patterns
TP_PATTERNS = [
    r'(?:tp2|target2)[\s:=]*(\d+\.?\d*)',
    r'(?:tp1|target1)[\s:=]*(\d+\.?\d*)',
    r'(?:tp|target|take\s*profit|تیک\s*پروفیت|تی\s*پی|هدف|تارگت|سود)'
    r'\s*(?:\d\s*(?=[:=]?\s*\d{4}))?\s*[:=]?\s*(\d+\.?\d*)',
]

SL_PATTERNS = [
    r'(?:sl|stop\s*(?:loss)?|ستاپ|اس\s*ال|حد\s*ضرر|استاپ)[\s:=]*(\d+\.?\d*)',
]

ENTRY_PATTERNS = [
    r'(?:entry|price|قیمت|ورود|zone)[\s:=]*(\d+\.?\d*)',
    r'(?:at|@)[\s:=]*(\d+\.?\d*)',
]

SYMBOL_PATTERN = re.compile(
    r'\b(' + '|'.join(re.escape(k) for k in sorted(SYMBOL_MAP.keys(), key=len, reverse=True)) + r')\b',
    re.IGNORECASE
)


@dataclass
class ParseResult:
    """Signal parse result."""
    success: bool
    signal: Optional[Signal] = None
    error: Optional[str] = None


class SignalParser:
    """Parse trading signals from text messages.
    
    Supports:
    - English/Farsi/Arabic keywords
    - Emoji direction indicators
    - Multiple TP levels (takes highest)
    - Flexible formats
    
    Example formats:
    - "XAUUSD BUY 2595.50 SL 2590 TP 2605"
    - "🟢 BUY GOLD @ 2595 | SL: 2590 | TP: 2605"
    - "گلد خرید 2595 استاپ 2590 هدف 2605"
    """
    
    def parse(self, text: str, source_id: str = "") -> ParseResult:
        """Parse signal from text.
        
        Args:
            text: Message text
            source_id: Message ID or source identifier
            
        Returns:
            ParseResult with signal or error
        """
        # Normalize
        text_normalized = normalize_digits(text.lower())
        
        # Extract components
        symbol = self._extract_symbol(text_normalized)
        if not symbol:
            return ParseResult(success=False, error="Symbol not found")
        
        direction = self._extract_direction(text_normalized)
        if not direction:
            return ParseResult(success=False, error="Direction (BUY/SELL) not found")
        
        entry = self._extract_entry(text_normalized)
        if not entry:
            return ParseResult(success=False, error="Entry price not found")
        
        stop_loss = self._extract_stop_loss(text_normalized)
        if not stop_loss:
            return ParseResult(success=False, error="Stop loss not found")
        
        take_profit = self._extract_take_profit(text_normalized)
        if not take_profit:
            return ParseResult(success=False, error="Take profit not found")
        
        # Validate
        if direction == "buy":
            if stop_loss >= entry:
                return ParseResult(success=False, error=f"Invalid BUY: SL ({stop_loss}) must be < entry ({entry})")
            if take_profit <= entry:
                return ParseResult(success=False, error=f"Invalid BUY: TP ({take_profit}) must be > entry ({entry})")
        else:  # sell
            if stop_loss <= entry:
                return ParseResult(success=False, error=f"Invalid SELL: SL ({stop_loss}) must be > entry ({entry})")
            if take_profit >= entry:
                return ParseResult(success=False, error=f"Invalid SELL: TP ({take_profit}) must be < entry ({entry})")
        
        # Calculate quality
        risk = abs(entry - stop_loss)
        reward = abs(take_profit - entry)
        risk_reward = reward / risk if risk > 0 else 0
        
        if risk_reward >= 2.0:
            quality = SignalQuality.EXCELLENT
            confidence = 0.8
        elif risk_reward >= 1.5:
            quality = SignalQuality.GOOD
            confidence = 0.7
        elif risk_reward >= 1.0:
            quality = SignalQuality.ACCEPTABLE
            confidence = 0.6
        else:
            quality = SignalQuality.POOR
            confidence = 0.4
        
        # Build signal
        signal = Signal(
            symbol=symbol,
            direction=direction,
            entry_price=entry,
            stop_loss=stop_loss,
            take_profit=take_profit,
            source=SignalSource.TELEGRAM,
            raw_message=text,
            source_id=source_id,
            confidence_score=confidence,
            quality=quality
        )
        
        return ParseResult(success=True, signal=signal)
    
    def _extract_symbol(self, text: str) -> Optional[str]:
        """Extract symbol."""
        match = SYMBOL_PATTERN.search(text)
        if match:
            symbol_raw = match.group(1).lower()
            return SYMBOL_MAP.get(symbol_raw)
        return None
    
    def _extract_direction(self, text: str) -> Optional[str]:
        """Extract direction (buy/sell)."""
        words = text.split()
        
        # Check keywords
        for word in words:
            if word in BUY_KEYWORDS:
                return "buy"
            if word in SELL_KEYWORDS:
                return "sell"
        
        # Check emoji
        for char in text:
            if char in DIRECTION_EMOJI_BUY:
                return "buy"
            if char in DIRECTION_EMOJI_SELL:
                return "sell"
        
        return None
    
    def _extract_entry(self, text: str) -> Optional[float]:
        """Extract entry price."""
        for pattern in ENTRY_PATTERNS:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                try:
                    return float(match.group(1))
                except (ValueError, IndexError):
                    continue
        
        # Fallback: any 4-digit number that looks like a price
        match = re.search(r'\b(\d{4}\.?\d*)\b', text)
        if match:
            try:
                return float(match.group(1))
            except ValueError:
                pass
        
        return None
    
    def _extract_stop_loss(self, text: str) -> Optional[float]:
        """Extract stop loss."""
        for pattern in SL_PATTERNS:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                try:
                    price = float(match.group(1))
                    # XAUUSD fix: if SL is 2-3 digits, it's likely last digits only
                    if price < 100 and 'xauusd' in text.lower():
                        price += 2000  # assume 2000s range
                    return price
                except (ValueError, IndexError):
                    continue
        return None
    
    def _extract_take_profit(self, text: str) -> Optional[float]:
        """Extract take profit (highest if multiple)."""
        tps = []
        
        for pattern in TP_PATTERNS:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                try:
                    price = float(match.group(1))
                    # XAUUSD fix
                    if price < 100 and 'xauusd' in text.lower():
                        price += 2000
                    tps.append(price)
                except (ValueError, IndexError):
                    continue
        
        return max(tps) if tps else None
