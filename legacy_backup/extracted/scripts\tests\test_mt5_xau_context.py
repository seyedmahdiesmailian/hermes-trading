from mt5_xau_context import (
    build_plan_context,
    classify_bias,
    compute_value_zone,
    derive_trade_zones,
)


def test_compute_value_zone_uses_midrange_window():
    rows = [
        {"high": 4250.0, "low": 4230.0, "close": 4240.0},
        {"high": 4260.0, "low": 4240.0, "close": 4250.0},
        {"high": 4270.0, "low": 4250.0, "close": 4260.0},
        {"high": 4280.0, "low": 4220.0, "close": 4255.0},
        {"high": 4245.0, "low": 4235.0, "close": 4240.0},
    ]
    low, high = compute_value_zone(rows)
    assert low < high
    # With 10th/90th percentiles, value zone excludes extremes
    assert low >= 4230.0 and low <= 4260.0
    assert high >= 4240.0 and high <= 4280.0


def test_classify_bias_returns_bullish_for_rising_closes():
    rows = [{"close": x} for x in [4200.0, 4210.0, 4220.0, 4235.0, 4250.0]]
    assert classify_bias(rows) == "bullish"


def test_classify_bias_returns_bearish_for_falling_closes():
    rows = [{"close": x} for x in [4250.0, 4240.0, 4230.0, 4220.0, 4210.0]]
    assert classify_bias(rows) == "bearish"


def test_derive_trade_zones_builds_long_and_short_edges_from_value_zone():
    zones = derive_trade_zones(value_low=4238.0, value_high=4250.0, atr=10.0)
    assert zones["long_entry_low"] < zones["long_entry_high"]
    assert zones["short_entry_low"] < zones["short_entry_high"]
    assert zones["long_entry_high"] <= zones["value_low"]
    assert zones["short_entry_low"] >= zones["value_high"]


def test_build_plan_context_returns_expected_structure():
    m15 = [{"high": 4250.0 + i, "low": 4230.0 + i, "close": 4240.0 + i} for i in range(20)]
    h1 = [{"high": 4240.0 + i, "low": 4210.0 + i, "close": 4220.0 + i} for i in range(20)]
    h4 = [{"high": 4230.0 + i, "low": 4190.0 + i, "close": 4210.0 + i} for i in range(20)]
    ctx = build_plan_context(m15_rows=m15, h1_rows=h1, h4_rows=h4, session_name="london")
    assert ctx["symbol"] == "XAUUSD"
    assert ctx["session"] == "london"
    assert ctx["bias"] in {"bullish", "bearish", "neutral"}
    assert "zones" in ctx
    assert "invalidation" in ctx
    assert len(ctx["targets"]) in {0, 2, 3}
    assert "execution" in ctx
    assert "regime" in ctx["quality"]
