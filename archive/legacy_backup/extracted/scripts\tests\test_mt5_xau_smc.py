"""SMC/ICT/RTM analysis engine — TDD suite.

Covers: Order Blocks, FVG, Liquidity Sweep, Market Structure,
Premium/Discount, Killzone timing, POI grading, and merge with classic.

Advanced: Breaker Block, Rejection Block, OTE, Power of 3,
Turtle Soup, Silver Bullet, Session Liquidity, Volume Imbalance.
"""

import pytest
from datetime import datetime
from mt5_xau_smc import (
    detect_order_blocks,
    detect_fair_value_gaps,
    detect_liquidity_sweep,
    market_structure_phase,
    premium_discount_zone,
    active_killzone_session,
    grade_poi,
    smc_analyse,
    merge_smc_with_classic,
    # Advanced
    detect_breaker_blocks,
    detect_rejection_blocks,
    compute_ote_zone,
    detect_power_of_three,
    detect_turtle_soup,
    evaluate_silver_bullet_setup,
    compute_session_liquidity,
    detect_volume_imbalance,
)


# ── helpers ──────────────────────────────────────────────────────────────────

def _candle(open_, high, low, close, time_=None, volume=None):
    t = time_ or datetime(2026, 8, 10, 12, 0)
    vol = volume or 1000
    return {"open": open_, "high": high, "low": low, "close": close, "time": t, "tick_volume": vol}


def _candles(*triples, **kw):
    """Each triple: (open, high, low, close) — time auto-increments by 15 min, wraps hours."""
    rows = []
    base = kw.get("base", datetime(2026, 8, 10, 12, 0))
    volume = kw.get("volume", 1000)
    for i, (o, h, l, c) in enumerate(triples):
        total_minutes = i * 15
        hour = total_minutes // 60
        minute = total_minutes % 60
        rows.append(_candle(o, h, l, c, base.replace(hour=base.hour + hour, minute=minute), volume))
    return rows


# ── Order Blocks ─────────────────────────────────────────────────────────────

class TestOrderBlockDetection:
    """Bullish OB: last bearish candle before strong bullish move.
       Bearish OB: last bullish candle before strong bearish move."""

    def test_bullish_ob_basic(self):
        rows = _candles(
            (101, 101.5, 99, 100),
            (101, 108, 100.5, 107),
            (107, 109, 106.5, 108),
        )
        obs = detect_order_blocks(rows)
        assert len(obs) >= 1
        ob = obs[0]
        assert ob["type"] == "bullish"
        assert ob["high"] == 101.5
        assert ob["low"] == 99.0

    def test_bearish_ob_basic(self):
        rows = _candles(
            (100, 101, 99.5, 100.5),
            (99, 101, 92, 94),
            (94, 95, 92.5, 93),
        )
        obs = detect_order_blocks(rows)
        bearish_obs = [o for o in obs if o["type"] == "bearish"]
        assert len(bearish_obs) >= 1

    def test_no_strong_move_no_ob(self):
        rows = _candles(
            (100, 100.5, 99.5, 100),
            (100, 100.5, 99.5, 100),
            (100, 100.5, 99.5, 100),
        )
        obs = detect_order_blocks(rows)
        assert obs == []

    def test_ob_has_mitigated_flag(self):
        rows = _candles(
            (101, 101.5, 99, 100),
            (101, 108, 100.5, 107),
            (107, 109, 106.5, 108),
        )
        obs = detect_order_blocks(rows)
        assert obs[0]["mitigated"] is False

    def test_ob_mitigated_when_price_returns(self):
        rows = _candles(
            (100, 101, 99, 100),
            (101, 108, 100.5, 107),
            (107, 109, 95, 96),
        )
        obs = detect_order_blocks(rows)
        if obs:
            assert obs[0]["mitigated"] is True


# ── Fair Value Gaps ──────────────────────────────────────────────────────────

class TestFairValueGap:
    """FVG: 3-candle pattern where candle 1 and 3 don't overlap."""

    def test_bullish_fvg(self):
        rows = _candles(
            (100, 105, 99, 104),
            (105, 108, 104, 107),
            (108, 115, 107, 114),
        )
        fvgs = detect_fair_value_gaps(rows)
        assert len(fvgs) >= 1
        fvg = fvgs[0]
        assert fvg["type"] == "bullish"
        assert fvg["low"] == 105.0
        assert fvg["high"] == 107.0

    def test_bearish_fvg(self):
        rows = _candles(
            (100, 105, 99, 104),
            (95, 99, 90, 94),
            (93, 94, 85, 87),
        )
        fvgs = detect_fair_value_gaps(rows)
        bearish = [f for f in fvgs if f["type"] == "bearish"]
        assert len(bearish) >= 1

    def test_no_fvg_when_candles_overlap(self):
        rows = _candles(
            (100, 105, 99, 104),
            (102, 106, 101, 105),
            (103, 107, 100, 106),
        )
        fvgs = detect_fair_value_gaps(rows)
        assert fvgs == []

    def test_fvg_filled_detection(self):
        rows = _candles(
            (100, 105, 99, 104),
            (105, 108, 104, 107),
            (108, 115, 107, 114),
            (114, 116, 104, 105),
        )
        fvgs = detect_fair_value_gaps(rows)
        if fvgs:
            assert fvgs[0]["filled"] is True


# ── Liquidity Sweep ──────────────────────────────────────────────────────────

class TestLiquiditySweep:
    def test_sweep_of_previous_high(self):
        rows = _candles(
            (100, 110, 99, 109),
            (109, 111, 108, 110),
            (110, 111.5, 105, 106),
        )
        swept, level = detect_liquidity_sweep(rows, lookback=3)
        assert swept is True

    def test_sweep_of_previous_low(self):
        rows = _candles(
            (100, 101, 95, 100),
            (100, 101, 94, 96),
            (96, 102, 95.5, 101),
        )
        swept, level = detect_liquidity_sweep(rows, lookback=3)
        assert swept is True

    def test_no_sweep_without_reversal(self):
        rows = _candles(
            (100, 110, 99, 109),
            (109, 112, 108, 111),
            (111, 113, 110, 112),
        )
        swept, level = detect_liquidity_sweep(rows, lookback=3)
        assert swept is False


# ── Market Structure ─────────────────────────────────────────────────────────

class TestMarketStructure:
    def test_bullish_bos(self):
        rows = _candles(
            (100, 102, 99, 101),
            (101, 104, 100, 103),
            (103, 106, 102, 105),
        )
        phase, confidence = market_structure_phase(rows)
        assert phase == "bos_bullish"

    def test_bearish_choch(self):
        rows = _candles(
            (100, 105, 99, 104),
            (104, 107, 100, 101),
            (101, 108, 95, 97),
        )
        phase, confidence = market_structure_phase(rows)
        assert phase == "choch_bearish"

    def test_range_structure(self):
        rows = _candles(
            (100, 102, 99, 101),
            (101, 102, 99, 100),
            (100, 102, 99, 101),
        )
        phase, confidence = market_structure_phase(rows)
        assert phase == "range"


# ── Premium / Discount ───────────────────────────────────────────────────────

class TestPremiumDiscount:
    def test_discount_zone(self):
        zone = premium_discount_zone(price=102, swing_high=110, swing_low=100)
        # fib_level = (102-100)/10 = 0.2 → discount (< 0.25)
        assert zone["zone"] == "discount"
        assert zone["fib_level"] < 0.5

    def test_premium_zone(self):
        zone = premium_discount_zone(price=109, swing_high=110, swing_low=100)
        assert zone["zone"] == "premium"
        assert zone["fib_level"] > 0.5

    def test_equilibrium_zone(self):
        zone = premium_discount_zone(price=105, swing_high=110, swing_low=100)
        assert zone["zone"] == "equilibrium"

    def test_discount_quality_score(self):
        zone = premium_discount_zone(price=101.5, swing_high=110, swing_low=100)
        assert zone["quality"] >= 35


# ── Killzone Timing ──────────────────────────────────────────────────────────

class TestKillzone:
    """London open: 07:00-09:00 UTC. NY open: 12:00-14:00 UTC.
       Asia: 00:00-05:00 UTC."""

    def test_london_killzone(self):
        dt = datetime(2026, 8, 10, 7, 30)
        session, weight = active_killzone_session(dt)
        assert session == "london"
        assert weight > 0

    def test_ny_killzone(self):
        dt = datetime(2026, 8, 10, 13, 0)
        session, weight = active_killzone_session(dt)
        assert session == "newyork"

    def test_dead_zone(self):
        dt = datetime(2026, 8, 10, 16, 30)
        session, weight = active_killzone_session(dt)
        assert session == "dead"
        assert weight == 0.0

    def test_asia_session(self):
        dt = datetime(2026, 8, 10, 2, 0)
        session, weight = active_killzone_session(dt)
        assert session == "asia"
        assert weight < 1.0


# ── POI Grading ──────────────────────────────────────────────────────────────

class TestPOIGrading:
    def test_grade_a_perfect_confluence(self):
        grade = grade_poi(
            has_ob=True, ob_mitigated=False,
            has_fvg=True, fvg_filled=False,
            liq_sweep=True,
            discount=True,
            killzone_weight=1.0,
            structure_aligned=True,
        )
        assert grade in ("A", "A+")

    def test_grade_c_weak_signals(self):
        grade = grade_poi(
            has_ob=False, ob_mitigated=True,
            has_fvg=False, fvg_filled=True,
            liq_sweep=False,
            discount=False,
            killzone_weight=0.3,
            structure_aligned=False,
        )
        assert grade == "C"

    def test_grade_b_moderate(self):
        grade = grade_poi(
            has_ob=True, ob_mitigated=False,
            has_fvg=False, fvg_filled=False,
            liq_sweep=True,
            discount=True,
            killzone_weight=0.5,
            structure_aligned=False,
        )
        assert grade == "B"


# ── Full SMC Analysis Pipeline ───────────────────────────────────────────────

class TestFullSMCAnalysis:
    def test_smc_analyse_returns_full_report(self):
        rows = _candles(
            (100, 102, 99, 101),
            (101, 103, 100, 102),
            (102, 105, 101, 104),
            (104, 107, 103, 106),
            (106, 108, 105, 107),
            (107, 115, 106, 114),
            (114, 116, 108, 115),
            (115, 117, 113, 116),
        )
        result = smc_analyse(rows, now=datetime(2026, 8, 10, 11, 0))
        assert "order_blocks" in result
        assert "fvgs" in result
        assert "liquidity_sweep" in result
        assert "market_structure" in result
        assert "premium_discount" in result
        assert "killzone" in result
        assert "bias" in result
        assert "poi" in result
        assert "signal" in result
        assert "confidence" in result


# ── Merge SMC with Classic ───────────────────────────────────────────────────

class TestSMCMerge:
    def test_smc_agrees_with_classic_bullish(self):
        classic = {"bias": "bullish", "regime": "pullback_continuation", "quality": {"trend_strength": 5.0, "alignment": "aligned"}}
        smc = {"bias": "bullish", "signal": "long", "confidence": 0.85, "smc_weight": 0.7}
        merged = merge_smc_with_classic(classic, smc)
        assert merged["bias"] == "bullish"
        assert merged["confidence"] >= 0.60

    def test_smc_conflicts_with_classic(self):
        classic = {"bias": "bearish", "regime": "range", "quality": {"trend_strength": 1.5, "alignment": "mixed"}}
        smc = {"bias": "bullish", "signal": "long", "confidence": 0.80, "smc_weight": 0.7}
        merged = merge_smc_with_classic(classic, smc)
        assert merged["bias"] == "bullish"

    def test_both_weak_stays_neutral(self):
        classic = {"bias": "neutral", "regime": "range", "quality": {"trend_strength": 1.0, "alignment": "neutral"}}
        smc = {"bias": "neutral", "signal": "wait", "confidence": 0.20, "smc_weight": 0.3}
        merged = merge_smc_with_classic(classic, smc)
        assert merged["bias"] == "neutral"
        assert merged.get("action") == "wait"

    def test_merge_preserves_both_sources(self):
        classic = {"bias": "bullish", "regime": "breakout_continuation"}
        smc = {"bias": "bullish", "signal": "long", "confidence": 0.90}
        merged = merge_smc_with_classic(classic, smc)
        assert "classic_source" in merged
        assert "smc_source" in merged


# ═══════════════════════════════════════════════════════════════════════════════
# ADVANCED SMC/ICT CONCEPTS
# ═══════════════════════════════════════════════════════════════════════════════

# ── 1. Breaker Block ─────────────────────────────────────────────────────────

class TestBreakerBlock:
    """OB that was broken → price returns to test it → flips to support/resistance."""

    def test_bullish_ob_becomes_breaker(self):
        # Data: keep bodies small so OB threshold stays low
        rows = _candles(
            (100, 100.5, 99, 99.5),     # idx0: bearish → OB base
            (99.5, 103, 99, 102.5),     # idx1: strong bullish breakout → creates bullish OB
            (102, 102.5, 101.5, 102),   # idx2: minor
            (101.5, 102, 98, 98.5),     # idx3: broke below OB low (99)
            (98, 100.5, 97.5, 100),     # idx4: retest inside OB [99-100.5]
        )
        breakers = detect_breaker_blocks(rows)
        assert len(breakers) >= 1
        bb = breakers[0]
        assert bb["type"] == "bearish_breaker"  # bullish OB broken → bearish
        assert bb["flipped"] is True

    def test_bearish_ob_becomes_breaker(self):
        rows = _candles(
            (105, 107, 104, 106),       # idx0: bullish → OB base
            (105, 106, 99, 100),        # idx1: bearish breakout → bearish OB, body=5
            (100, 101, 99.5, 100.5),    # idx2: minor
            (100, 108, 100, 108),       # idx3: broke above OB high (107)
            (107, 107.5, 105, 106),     # idx4: retest inside OB [104-107]
        )
        breakers = detect_breaker_blocks(rows)
        assert len(breakers) >= 1
        bb = breakers[0]
        assert bb["type"] == "bullish_breaker"

    def test_no_breaker_without_break(self):
        rows = _candles(
            (100, 100.5, 99, 99.5),
            (99.5, 103, 99, 102.5),
            (102, 102.5, 101.5, 102),
            (101.5, 102, 100, 101),     # never broke below OB low (99)
        )
        breakers = detect_breaker_blocks(rows)
        assert breakers == []


# ── 2. Rejection Block ───────────────────────────────────────────────────────

class TestRejectionBlock:
    """Pin bar / long wick rejection at an OB zone."""

    def test_bullish_rejection_at_ob(self):
        rows = _candles(
            (100, 100.5, 99, 99.5),     # bearish → OB base
            (99.5, 103, 99, 102.5),     # strong bullish → creates OB at 99-100.5
            (102, 102.5, 101.5, 102),   # minor
            (101.5, 102, 100, 100.5),   # approaches OB
            (100, 105, 97, 104),        # long lower wick (97) into OB, strong close
        )
        rejections = detect_rejection_blocks(rows)
        assert len(rejections) >= 1, f"Got {len(rejections)}"
        r = rejections[0]
        assert r["type"] == "bullish_rejection"

    def test_bearish_rejection_at_ob(self):
        rows = _candles(
            (105, 107, 104, 106),       # bullish → OB base
            (105, 106, 100, 101),       # bearish breakout → bearish OB at 104-107
            (101, 102, 100.5, 101.5),   # minor
            (101.3, 101.5, 101, 101.3), # approaches OB
            (101, 107, 100, 101),       # long upper wick (107) into OB, bearish close
        )
        rejections = detect_rejection_blocks(rows)
        assert len(rejections) >= 1, f"Got {len(rejections)}"
        r = rejections[0]
        assert r["type"] == "bearish_rejection"

    def test_no_rejection_without_ob(self):
        rows = _candles(
            (100, 102, 99, 101),
            (101, 102, 100, 101.5),
            (101, 105, 100, 104),
        )
        rejections = detect_rejection_blocks(rows)
        assert rejections == []


# ── 3. OTE (Optimal Trade Entry) ─────────────────────────────────────────────

class TestOTEZone:
    """Fibonacci 0.62-0.79 retracement = OTE zone."""

    def test_ote_bullish_setup(self):
        # Up move 1000→2000, OTE = 0.62-0.79 retrace = 1210-1380
        ote = compute_ote_zone(swing_low=1000, swing_high=2000, direction="bullish")
        assert ote["low"] == 1210.0
        assert ote["high"] == 1380.0
        assert ote["high"] > ote["low"]

    def test_ote_bearish_setup(self):
        ote = compute_ote_zone(swing_low=200, swing_high=800, direction="bearish")
        assert ote["low"] > 200
        assert ote["high"] < 600

    def test_price_in_ote_zone(self):
        ote = compute_ote_zone(swing_low=1000, swing_high=2000, direction="bullish")
        # OTE = 0.62-0.79 retrace = 1210-1380
        assert ote["in_zone"](1300) is True
        assert ote["in_zone"](1700) is False
        assert ote["in_zone"](1000) is False


# ── 4. Power of 3 ────────────────────────────────────────────────────────────

class TestPowerOfThree:
    """Accumulation → Manipulation → Distribution / daily cycle."""

    def test_power_of_three_daily_phases(self):
        # 6 candles: first 2 accumulating, middle 2 manipulate, last 2 distribute
        rows = _candles(
            (100, 101, 99.5, 100.5),   # acc
            (100.5, 101, 99, 100),     # acc
            (100, 100.5, 95, 96),      # manipulation (down sweep)
            (96, 97, 94, 95),          # manipulation
            (95, 105, 94.5, 104),      # distribution up
            (104, 107, 103, 106),      # distribution up
        )
        po3 = detect_power_of_three(rows)
        assert "accumulation" in po3
        assert "manipulation" in po3
        assert "distribution" in po3
        assert po3["phase"] in ("distribution", "accumulation", "manipulation")

    def test_power_of_three_short_data(self):
        rows = _candles(
            (100, 101, 99, 100),
            (100, 102, 99.5, 101),
        )
        po3 = detect_power_of_three(rows)
        assert po3["phase"] in ("not_enough_data", "accumulation")


# ── 5. Turtle Soup ───────────────────────────────────────────────────────────

class TestTurtleSoup:
    """Fake breakout above/below previous swing, then sharp reversal."""

    def test_turtle_soup_bullish(self):
        rows = _candles(
            (100, 102, 98, 101),
            (101, 103, 99, 102),
            (102, 103.5, 97, 98),   # fake break below 98 → reversal up
            (98, 105, 97.5, 104),   # strong close above fake low
        )
        ts = detect_turtle_soup(rows)
        assert ts["found"] is True
        assert ts["type"] == "bullish"

    def test_turtle_soup_bearish(self):
        rows = _candles(
            (100, 102, 98, 101),
            (101, 102, 99, 101.5),
            (101, 104, 100.5, 103),  # fake break above 102 → reversal down
            (103, 103.5, 96, 97),    # collapse below
        )
        ts = detect_turtle_soup(rows)
        assert ts["found"] is True
        assert ts["type"] == "bearish"

    def test_no_turtle_soup_without_reversal(self):
        rows = _candles(
            (100, 102, 98, 101),
            (101, 103, 99, 102),
            (102, 106, 101, 105),   # real breakout, no reversal
            (105, 108, 104, 107),
        )
        ts = detect_turtle_soup(rows)
        assert ts["found"] is False


# ── 6. Silver Bullet ─────────────────────────────────────────────────────────

class TestSilverBullet:
    """ICT's 1-hour window setups: 10-11am or 2-3pm NY time."""

    def test_silver_bullet_window_active(self):
        # 10:30 AM NY = 14:30 UTC
        dt = datetime(2026, 8, 10, 14, 30)
        sb = evaluate_silver_bullet_setup(dt)
        assert sb["active"] is True
        assert "window" in sb

    def test_silver_bullet_window_inactive(self):
        dt = datetime(2026, 8, 10, 16, 30)
        sb = evaluate_silver_bullet_setup(dt)
        assert sb["active"] is False

    def test_silver_bullet_pm_window(self):
        dt = datetime(2026, 8, 10, 19, 0)  # 3 PM NY = 19:00 UTC
        sb = evaluate_silver_bullet_setup(dt)
        assert sb["active"] is True


# ── 7. Session Liquidity ─────────────────────────────────────────────────────

class TestSessionLiquidity:
    """Track session-level highs and lows for liquidity reference."""

    def test_compute_session_liquidity(self):
        # Asian session hours: 00-05 UTC, London: 07-09
        rows = _candles(
            (100, 105, 99, 104,),
            (104, 108, 103, 107,),
            (107, 110, 106, 109,),
            (109, 111, 108, 110,),
            (110, 112, 105, 106,),
        )
        liq = compute_session_liquidity(rows, session="asia")
        assert "session_high" in liq
        assert "session_low" in liq
        assert "midpoint" in liq
        assert liq["session_high"] >= liq["session_low"]

    def test_liquidity_sweep_detection(self):
        rows = _candles(
            (100, 105, 99, 104),
            (104, 108, 103, 107),
            (107, 109, 100, 106),  # wicked below session low?
        )
        liq = compute_session_liquidity(rows, session="london")
        assert liq["session_low"] <= rows[0]["low"]


# ── 8. Volume Imbalance ──────────────────────────────────────────────────────

class TestVolumeImbalance:
    """Volume spike / gap relative to surrounding candles."""

    def test_volume_imbalance_detected(self):
        rows = _candles(
            (100, 102, 99, 101),
            (101, 103, 100, 102),
            (102, 108, 101, 107),
        )
        rows[0]["tick_volume"] = 500
        rows[1]["tick_volume"] = 600
        rows[2]["tick_volume"] = 3500  # spike: 3500/1367=2.56 > 2.0
        imbalances = detect_volume_imbalance(rows, threshold=2.0)
        assert len(imbalances) >= 1
        assert imbalances[0]["volume_multiple"] >= 2.0

    def test_no_imbalance_with_flat_volume(self):
        rows = _candles(
            (100, 101, 99, 100),
            (100, 101, 99, 100),
            (100, 101, 99, 100),
        )
        for r in rows:
            r["tick_volume"] = 1000
        imbalances = detect_volume_imbalance(rows, threshold=2.0)
        assert imbalances == []

    def test_imbalance_direction_label(self):
        rows = _candles(
            (100, 101, 99, 100),
            (100, 101.5, 99.5, 101),
            (101, 108, 100.5, 107),  # up on big volume
        )
        rows[0]["tick_volume"] = 400
        rows[1]["tick_volume"] = 500
        rows[2]["tick_volume"] = 5000
        imbalances = detect_volume_imbalance(rows, threshold=2.0)
        if imbalances:
            assert imbalances[0]["direction"] in ("bullish", "bearish")
