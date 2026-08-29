from mt5_xau_context import build_plan_context


def _rows_from_closes(closes, width=8.0):
    rows = []
    for close in closes:
        rows.append({
            "open": close - 0.8,
            "high": close + (width / 2),
            "low": close - (width / 2),
            "close": close,
        })
    return rows


def test_build_plan_context_marks_breakout_regime_when_price_pushes_above_value():
    m15 = _rows_from_closes([4322, 4326, 4330, 4335, 4340, 4344, 4348, 4352, 4356, 4359, 4361, 4364, 4367, 4370, 4372])
    h1 = _rows_from_closes([4300, 4308, 4316, 4324, 4332, 4340, 4348, 4356, 4364, 4372], width=12.0)
    h4 = _rows_from_closes([4260, 4280, 4300, 4320, 4340, 4360, 4380, 4400, 4420, 4440], width=20.0)

    ctx = build_plan_context(m15, h1, h4, "london")

    assert ctx["quality"]["regime"] == "breakout_continuation"
    assert ctx["execution"]["entry_mode"] == "breakout_pullback_hybrid"
    assert ctx["execution"]["breakout_trigger"] >= ctx["zones"]["value_high"]
    assert len(ctx["execution"]["tp_levels"]) == 3


def test_build_plan_context_marks_pullback_regime_when_price_is_near_value_low_in_bull_trend():
    m15 = _rows_from_closes([4318, 4321, 4325, 4328, 4330, 4333, 4335, 4337, 4339, 4340, 4336, 4332, 4328, 4325, 4322])
    h1 = _rows_from_closes([4285, 4294, 4303, 4312, 4321, 4330, 4339, 4348, 4357, 4366], width=12.0)
    h4 = _rows_from_closes([4240, 4260, 4280, 4300, 4320, 4340, 4360, 4380, 4400, 4420], width=20.0)

    ctx = build_plan_context(m15, h1, h4, "london")

    assert ctx["quality"]["regime"] == "pullback_continuation"
    assert ctx["execution"]["entry_mode"] == "scale_in_pullback"
    assert len(ctx["execution"]["scale_in_levels"]) == 2
    assert ctx["execution"]["scale_in_levels"][0] >= ctx["zones"]["long_entry_low"]


def test_build_plan_context_marks_range_regime_when_bias_is_mixed_and_strength_is_small():
    m15 = _rows_from_closes([4328, 4330, 4329, 4331, 4330, 4332, 4331, 4330, 4332, 4331, 4330, 4331, 4330, 4332, 4331])
    h1 = _rows_from_closes([4325, 4328, 4330, 4331, 4330, 4332, 4331, 4330, 4331, 4330], width=10.0)
    h4 = _rows_from_closes([4320, 4324, 4328, 4330, 4331, 4330, 4331, 4330, 4332, 4331], width=12.0)

    ctx = build_plan_context(m15, h1, h4, "asia")

    assert ctx["quality"]["regime"] == "range"
    assert ctx["bias"] == "neutral"
    assert ctx["execution"]["entry_mode"] == "mean_reversion_wait"
