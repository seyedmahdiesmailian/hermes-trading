from mt5_xau_context import build_plan_context, classify_bias


def test_classify_bias_returns_neutral_when_move_is_too_small():
    rows = [{"close": x} for x in [4200.0, 4200.4, 4200.6, 4200.5, 4200.7]]
    assert classify_bias(rows) == "neutral"


def test_classify_bias_requires_structure_not_just_last_minus_first():
    rows = [{"close": x} for x in [4200.0, 4215.0, 4202.0, 4212.0, 4201.0]]
    assert classify_bias(rows) == "neutral"


def test_build_plan_context_exposes_quality_signals_for_runtime_decisions():
    m15 = [{"high": 4250.0 + i, "low": 4238.0 + i, "close": 4244.0 + i} for i in range(20)]
    h1 = [{"high": 4240.0 + i, "low": 4210.0 + i, "close": 4220.0 + i} for i in range(20)]
    h4 = [{"high": 4230.0 + i, "low": 4190.0 + i, "close": 4210.0 + i} for i in range(20)]
    ctx = build_plan_context(m15_rows=m15, h1_rows=h1, h4_rows=h4, session_name="london")
    assert "quality" in ctx
    assert ctx["quality"]["trend_strength"] > 0
    assert ctx["quality"]["alignment"] in {"aligned", "mixed"}
    assert ctx["quality"]["distance_to_value_low_atr"] >= 0
