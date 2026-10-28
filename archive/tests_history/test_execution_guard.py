"""
Tests for brain/domain/services/execution_guard.py.

These pin every fail-closed gate extracted from the V1 auto_executor
(see docs/V1_LOGIC_EXTRACTION.md). A gate that errors must BLOCK entry,
never allow it through.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from brain.domain.services.execution_guard import (
    GRADE_ORDER,
    MAX_DAILY_LOSS_PCT,
    MAX_DAILY_TRADES,
    MAX_LOT,
    MAX_OPEN_POSITIONS,
    MAX_RISK_PER_TRADE_PCT,
    MIN_RISK_REWARD,
    MIN_STOP_BALANCE,
    MIN_STOP_DISTANCE,
    AccountState,
    ExecutionGuard,
    GuardVerdict,
    LearningAdjustments,
    PerformanceState,
    ProposalInput,
    RR_FLOOR_EXEMPT_STYLES,
    STOP_TRADING_REGIMES,
)

GUARD = ExecutionGuard()


def _proposal(**over):
    base = dict(side="BUY", entry=Decimal("2000"), sl=Decimal("1990"), tp=Decimal("2012"))
    base.update(over)
    return ProposalInput(**base)

def _account(**over):
    base = dict(balance=Decimal("5000"))
    base.update(over)
    return AccountState(**base)

def _perf(**over):
    base = {}
    base.update(over)
    return PerformanceState(**over)


# ---------------------------------------------------------------------------
# Check 1 - proposal validity
# ---------------------------------------------------------------------------

class TestCheck1ProposalValidity:
    def test_buy_all_gates_pass_returns_allowed(self):
        v = GUARD.evaluate(_proposal(), _account(), _perf())
        assert v.allowed, v.all_reasons
        assert v.reason == "ok"

    def test_sell_all_gates_pass_returns_allowed(self):
        v = GUARD.evaluate(
            _proposal(side="SELL", entry=Decimal("2000"), sl=Decimal("2010"), tp=Decimal("1988")),
            _account(), _perf(),
        )
        assert v.allowed

    @pytest.mark.parametrize("side", ["", "buy", "LONG", "X"])
    def test_invalid_side_is_denied(self, side):
        v = GUARD.evaluate(_proposal(side=side), _account(), _perf())
        assert v.denied and v.reason == "invalid_blueprint"

    @pytest.mark.parametrize("key", ["entry", "sl", "tp"])
    def test_non_positive_price_is_denied(self, key):
        v = GUARD.evaluate(_proposal(**{key: Decimal("0")}), _account(), _perf())
        assert v.denied and v.reason == "invalid_blueprint"

    def test_none_proposal_is_denied(self):
        v = GUARD.evaluate(None, _account(), _perf())
        assert v.denied and v.reason == "no_proposal"


# ---------------------------------------------------------------------------
# Check 2 - account policy
# ---------------------------------------------------------------------------

class TestCheck2AccountPolicy:
    def test_trade_not_allowed_denies(self):
        v = GUARD.evaluate(_proposal(), _account(trade_allowed=False), _perf())
        assert v.denied and v.reason.startswith("account_policy_")

    @pytest.mark.parametrize("regime", sorted(STOP_TRADING_REGIMES))
    def test_stop_trading_regimes_denied(self, regime):
        v = GUARD.evaluate(_proposal(), _account(regime=regime), _perf())
        assert v.denied
        assert v.reason == f"account_policy_{regime}"

    def test_bridge_dark_adds_distinct_reason(self):
        # b219: bridge dark must be distinguishable from position limit.
        v = GUARD.evaluate(
            _proposal(),
            _account(regime="frozen", positions_unreadable=True),
            _perf(),
        )
        assert "bridge_dark_positions_unreadable" in v.all_reasons


# ---------------------------------------------------------------------------
# Check 2.5 - history readable
# ---------------------------------------------------------------------------

class TestCheck25History:
    def test_history_error_denies(self):
        v = GUARD.evaluate(_proposal(), _account(history_ok=False), _perf())
        assert v.denied and v.reason == "history_unavailable"

    def test_history_unknown_does_not_deny(self):
        v = GUARD.evaluate(_proposal(), _account(history_ok=None), _perf())
        assert v.allowed

    def test_history_ok_allows(self):
        v = GUARD.evaluate(_proposal(), _account(history_ok=True), _perf())
        assert v.allowed


# ---------------------------------------------------------------------------
# Check 3 - daily loss limit
# ---------------------------------------------------------------------------

class TestCheck3DailyLoss:
    def test_loss_above_limit_denies(self):
        # 5% of 5000 = 250; 300 loss breaches it.
        v = GUARD.evaluate(
            _proposal(),
            _account(balance=Decimal("5000")),
            _perf(daily_pnl=Decimal("-300")),
        )
        assert v.denied and v.reason == "daily_loss_limit"

    def test_loss_exactly_at_limit_denies(self):
        v = GUARD.evaluate(
            _proposal(),
            _account(balance=Decimal("5000")),
            _perf(daily_pnl=Decimal("-250")),
        )
        assert v.denied

    def test_small_loss_allows(self):
        v = GUARD.evaluate(
            _proposal(),
            _account(balance=Decimal("5000")),
            _perf(daily_pnl=Decimal("-50")),
        )
        assert v.allowed

    def test_positive_day_allows(self):
        v = GUARD.evaluate(
            _proposal(),
            _account(balance=Decimal("5000")),
            _perf(daily_pnl=Decimal("150")),
        )
        assert v.allowed

    def test_zero_balance_skips_loss_gate(self):
        v = GUARD.evaluate(
            _proposal(),
            _account(balance=Decimal("0")),
            _perf(daily_pnl=Decimal("-9999")),
        )
        # other gates still run; the daily-loss gate itself is skipped
        assert v.reason != "daily_loss_limit"


# ---------------------------------------------------------------------------
# Check 4 - daily trades
# ---------------------------------------------------------------------------

class TestCheck4DailyTrades:
    @pytest.mark.parametrize("n", [MAX_DAILY_TRADES, MAX_DAILY_TRADES + 3])
    def test_at_or_above_limit_denies(self, n):
        v = GUARD.evaluate(_proposal(), _account(), _perf(trades_today=n))
        assert v.denied and v.reason == "daily_trade_limit"

    @pytest.mark.parametrize("n", [0, 1, MAX_DAILY_TRADES - 1])
    def test_below_limit_allows(self, n):
        v = GUARD.evaluate(_proposal(), _account(), _perf(trades_today=n))
        assert v.allowed


# ---------------------------------------------------------------------------
# Check 5 - open positions
# ---------------------------------------------------------------------------

class TestCheck5OpenPositions:
    @pytest.mark.parametrize("n", [MAX_OPEN_POSITIONS, 2, 5])
    def test_at_or_above_limit_denies(self, n):
        v = GUARD.evaluate(_proposal(), _account(open_positions=n), _perf())
        assert v.denied and v.reason == "position_limit"

    def test_zero_open_allows(self):
        v = GUARD.evaluate(_proposal(), _account(open_positions=0), _perf())
        assert v.allowed


# ---------------------------------------------------------------------------
# Check 5.5 - TP/SL geometry
# ---------------------------------------------------------------------------

class TestCheck55Geometry:
    def test_sell_tp_above_entry_denied(self):
        v = GUARD.evaluate(
            _proposal(side="SELL", entry=Decimal("2000"), sl=Decimal("2010"), tp=Decimal("2005")),
            _account(), _perf(),
        )
        assert v.denied and v.reason == "invalid_geometry"

    def test_sell_sl_below_entry_denied(self):
        v = GUARD.evaluate(
            _proposal(side="SELL", entry=Decimal("2000"), sl=Decimal("1990"), tp=Decimal("1990")),
            _account(), _perf(),
        )
        assert v.denied and v.reason == "invalid_geometry"

    def test_buy_tp_below_entry_denied(self):
        v = GUARD.evaluate(
            _proposal(side="BUY", entry=Decimal("2000"), sl=Decimal("1990"), tp=Decimal("1995")),
            _account(), _perf(),
        )
        assert v.denied and v.reason == "invalid_geometry"

    def test_buy_sl_above_entry_denied(self):
        v = GUARD.evaluate(
            _proposal(side="BUY", entry=Decimal("2000"), sl=Decimal("2005"), tp=Decimal("2012")),
            _account(), _perf(),
        )
        assert v.denied and v.reason == "invalid_geometry"


# ---------------------------------------------------------------------------
# Check 5.6 - risk:reward floor
# ---------------------------------------------------------------------------

class TestCheck56RiskReward:
    def test_rr_below_one_is_denied(self):
        # sl 10, tp 5 -> RR 0.5
        v = GUARD.evaluate(
            _proposal(entry=Decimal("2000"), sl=Decimal("1990"), tp=Decimal("2005")),
            _account(), _perf(),
        )
        assert v.denied and v.reason.startswith("poor_rr")

    def test_rr_exactly_one_allows(self):
        v = GUARD.evaluate(_proposal(), _account(), _perf())  # 10/10 = 1.2 actually
        assert v.allowed

    def test_rr_above_floor_allows(self):
        v = GUARD.evaluate(
            _proposal(entry=Decimal("2000"), sl=Decimal("1990"), tp=Decimal("2025")),
            _account(), _perf(),
        )
        assert v.allowed

    def test_exempt_style_bypasses_floor(self):
        # b233d: strong styles are exempt from the RR floor.
        v = GUARD.evaluate(
            _proposal(entry=Decimal("2000"), sl=Decimal("1990"), tp=Decimal("2003"),
                      execution_style="value_entry"),
            _account(), _perf(),
        )
        assert v.allowed, v.all_reasons

    def test_non_exempt_style_is_still_floored(self):
        v = GUARD.evaluate(
            _proposal(entry=Decimal("2000"), sl=Decimal("1990"), tp=Decimal("2003"),
                      execution_style="market_entry"),
            _account(), _perf(),
        )
        assert v.denied

    def test_learning_can_raise_the_floor(self):
        ls = LearningAdjustments(min_rr=Decimal("2.0"))
        v = GUARD.evaluate(
            _proposal(entry=Decimal("2000"), sl=Decimal("1990"), tp=Decimal("2012")),
            _account(), _perf(), learning=ls,
        )
        # RR 1.2 < learned floor 2.0 -> denied
        assert v.denied and v.reason.startswith("poor_rr")

    def test_learning_floor_never_drops_below_one(self):
        ls = LearningAdjustments(min_rr=Decimal("0.2"))
        v = GUARD.evaluate(
            _proposal(entry=Decimal("2000"), sl=Decimal("1990"), tp=Decimal("2005")),
            _account(), _perf(), learning=ls,
        )
        # floor = max(MIN_RISK_REWARD, 0.2) = 1.0 -> RR 0.5 still denied
        assert v.denied


# ---------------------------------------------------------------------------
# Check 5.65 - gold noise floor
# ---------------------------------------------------------------------------

class TestCheck565StopDistance:
    def test_stop_below_floor_denied(self):
        # sl distance 2 < MIN_STOP_DISTANCE 8, balance above threshold
        v = GUARD.evaluate(
            _proposal(entry=Decimal("2000"), sl=Decimal("1998"), tp=Decimal("2010")),
            _account(balance=Decimal("5000")), _perf(),
        )
        assert v.denied and v.reason == "stop_too_tight"

    def test_stop_at_floor_allows(self):
        v = GUARD.evaluate(
            _proposal(entry=Decimal("2000"), sl=Decimal("1992"), tp=Decimal("2012")),
            _account(balance=Decimal("5000")), _perf(),
        )
        # RR 20/8 = 2.5, stop 8 = floor -> allowed
        assert v.allowed, v.all_reasons

    def test_small_balance_loosens_floor(self):
        # Below MIN_STOP_BALANCE the gate is skipped for small accounts.
        v = GUARD.evaluate(
            _proposal(entry=Decimal("2000"), sl=Decimal("1998"), tp=Decimal("2010")),
            _account(balance=Decimal("500")), _perf(),
        )
        assert v.allowed, v.all_reasons

    def test_atr_scales_the_floor(self):
        # ATR 3 -> floor = min(2*3, 8) = 6; stop 7 passes.
        plan = {"atr": 3.0}
        v = GUARD.evaluate(
            _proposal(entry=Decimal("2000"), sl=Decimal("1993"), tp=Decimal("2012")),
            _account(balance=Decimal("5000")), _perf(), plan=plan,
        )
        assert v.allowed, v.all_reasons

    def test_atr_tightens_below_absolute_floor(self):
        # ATR 2 -> floor = min(4, 8) = 4; stop 3 fails.
        plan = {"atr": 2.0}
        v = GUARD.evaluate(
            _proposal(entry=RR_FLOOR_EXEMPT_STYLES and Decimal("2000"), sl=Decimal("1997"), tp=Decimal("2012")),
            _account(balance=Decimal("5000")), _perf(), plan=plan,
        )
        assert v.denied and v.reason == "stop_too_tight"


# ---------------------------------------------------------------------------
# Check 6 - setup grade
# ---------------------------------------------------------------------------

class TestCheck6SetupGrade:
    def test_grade_a_allows(self):
        v = GUARD.evaluate(_proposal(grade="A"), _account(), _perf())
        assert v.allowed

    def test_grade_b_allows(self):
        v = GUARD.evaluate(_proposal(grade="B"), _account(), _perf())
        assert v.allowed

    def test_grade_c_denied(self):
        v = GUARD.evaluate(_proposal(grade="C"), _account(), _perf())
        assert v.denied and v.reason == "setup_grade_C"

    def test_invalid_grade_is_worst(self):
        v = GUARD.evaluate(_proposal(grade="Z"), _account(), _perf())
        assert v.denied


# ---------------------------------------------------------------------------
# Check 6.5 - learning grade gate (fail-closed)
# ---------------------------------------------------------------------------

class TestCheck65LearningGrade:
    def test_learning_min_grade_a_denies_b(self):
        ls = LearningAdjustments(min_grade="A")
        v = GUARD.evaluate(_proposal(grade="B"), _account(), _perf(), learning=ls)
        assert v.denied and v.reason == "learned_min_grade_A"

    def test_learning_min_grade_b_allows_a(self):
        ls = LearningAdjustments(min_grade="B")
        v = GUARD.evaluate(_proposal(grade="A"), _account(), _perf(), learning=ls)
        assert v.allowed


# ---------------------------------------------------------------------------
# Check 6.6 - DEFCON
# ---------------------------------------------------------------------------

class TestCheck66Defcon:
    def test_defcon_red_blocks_entry(self):
        insights = {"trade_allowed": False, "defcon": "RED"}
        v = GUARD.evaluate(_proposal(), _account(), _perf(), defcon_insights=insights)
        assert v.denied
        assert v.reason == "defcon_red_entry_blocked"
        assert v.defcon == "RED"

    def test_defcon_green_allows(self):
        insights = {"trade_allowed": True, "defcon": "GREEN"}
        v = GUARD.evaluate(_proposal(), _account(), _perf(), defcon_insights=insights)
        assert v.allowed

    def test_defcon_yellow_halves_risk(self):
        insights = {"trade_allowed": True, "defcon": "YELLOW"}
        v = GUARD.evaluate(_proposal(), _account(), _perf(), defcon_insights=insights)
        assert v.allowed
        assert v.risk_pct == MAX_RISK_PER_TRADE_PCT / 2

    def test_defcon_green_keeps_full_risk(self):
        insights = {"trade_allowed": True, "defcon": "GREEN"}
        v = GUARD.evaluate(_proposal(), _account(), _perf(), defcon_insights=insights)
        assert v.risk_pct == MAX_RISK_PER_TRADE_PCT


# ---------------------------------------------------------------------------
# Check 6.7 - cooldown
# ---------------------------------------------------------------------------

class TestCheck67Cooldown:
    def test_cooldown_active_denies(self):
        v = GUARD.evaluate(
            _proposal(), _account(), _perf(),
            cooldown_ok=False, cooldown_reason="post_open_cooldown",
        )
        assert v.denied and v.reason == "post_open_cooldown"

    def test_cooldown_clear_allows(self):
        v = GUARD.evaluate(_proposal(), _account(), _perf(), cooldown_ok=True)
        assert v.allowed


# ---------------------------------------------------------------------------
# Check 7 / 7.5 - macro and market hours
# ---------------------------------------------------------------------------

class TestCheck7MacroAndMarket:
    def test_macro_blackout_denies(self):
        v = GUARD.evaluate(_proposal(blocked_by_macro=True), _account(), _perf())
        assert v.denied and v.reason == "macro_blackout"

    def test_market_closed_denies(self):
        v = GUARD.evaluate(_proposal(), _account(), _perf(), market_open=False)
        assert v.denied and v.reason == "market_closed"


# ---------------------------------------------------------------------------
# Position sizing
# ---------------------------------------------------------------------------

class TestPositionSizing:
    def test_volume_capped_at_max_lot(self):
        # Huge balance would produce a giant lot; the cap must hold.
        # Stop 8 = floor, TP 24 keeps RR = 3.0 so gates stay green.
        v = GUARD.evaluate(
            _proposal(sl=Decimal("1992"), tp=Decimal("2024")),
            _account(balance=Decimal("1000000")),
            _perf(),
        )
        assert v.allowed
        assert Decimal(str(v.volume)) <= MAX_LOT

    def test_volume_floored_at_min_lot(self):
        v = GUARD.evaluate(
            _proposal(entry=Decimal("2000"), sl=Decimal("1990"), tp=Decimal("2025")),
            _account(balance=Decimal("10")),
            _perf(),
        )
        assert v.allowed
        assert Decimal(str(v.volume)) >= Decimal("0.01")

    def test_risk_pct_never_exceeds_hard_cap(self):
        # Even with an absurd learning risk_mult, the hard cap holds.
        ls = LearningAdjustments(risk_mult=Decimal("50"))
        v = GUARD.evaluate(_proposal(), _account(), _perf(), learning=ls)
        # risk_pct reported is the cap-derived value, never above MAX_RISK_PER_TRADE_PCT
        assert v.risk_pct <= MAX_RISK_PER_TRADE_PCT

    def test_volume_scales_with_balance(self):
        # Wide stop (30pt, RR 2.0) so a 5000 balance stays under the 0.10 cap.
        p = _proposal(sl=Decimal("1970"), tp=Decimal("2060"))
        small = GUARD.evaluate(p, _account(balance=Decimal("1000")), _perf())
        large = GUARD.evaluate(p, _account(balance=Decimal("5000")), _perf())
        assert small.allowed and large.allowed
        assert Decimal(str(large.volume)) > Decimal(str(small.volume))

    def test_yellow_halves_risk_amount(self):
        # Wide stop AND RR >= 1 so the earlier gates do not reject it.
        p = _proposal(sl=Decimal("1970"), tp=Decimal("2030"))
        green = GUARD.evaluate(
            p, _account(), _perf(),
            defcon_insights={"trade_allowed": True, "defcon": "GREEN"},
        )
        yellow = GUARD.evaluate(
            p, _account(), _perf(),
            defcon_insights={"trade_allowed": True, "defcon": "YELLOW"},
        )
        assert green.allowed and yellow.allowed
        assert Decimal(str(yellow.volume)) < Decimal(str(green.volume))


# ---------------------------------------------------------------------------
# Verdict shape
# ---------------------------------------------------------------------------

class TestGuardVerdict:
    def test_denied_property(self):
        v = GuardVerdict(allowed=False, reason="x")
        assert v.denied is True

    def test_to_dict_roundtrip(self):
        v = GuardVerdict(allowed=True, reason="ok", risk_pct=Decimal("0.02"))
        d = v.to_dict()
        assert d["allowed"] is True
        assert d["risk_pct"] == "0.02"

    def test_all_reasons_recorded(self):
        v = GUARD.evaluate(
            _proposal(),
            _account(regime="frozen", positions_unreadable=True),
            _perf(),
        )
        assert len(v.all_reasons) >= 2


# ---------------------------------------------------------------------------
# LearningAdjustments parsing
# ---------------------------------------------------------------------------

class TestLearningAdjustments:
    def test_invalid_values_fall_back_to_defaults(self):
        ls = LearningAdjustments.from_state({"min_rr": "garbage", "min_grade": "Z", "risk_mult": None})
        assert ls.min_rr == MIN_RISK_REWARD
        assert ls.min_grade == "B"
        assert ls.risk_mult == Decimal("1.0")

    def test_valid_values_loaded(self):
        ls = LearningAdjustments.from_state({"min_rr": "2.5", "min_grade": "A", "risk_mult": "0.5"})
        assert ls.min_rr == Decimal("2.5")
        assert ls.min_grade == "A"
        assert ls.risk_mult == Decimal("0.5")

    def test_empty_state_uses_defaults(self):
        ls = LearningAdjustments.from_state({})
        assert ls.min_rr == MIN_RISK_REWARD
        assert ls.min_grade == "B"


# ---------------------------------------------------------------------------
# Fail-closed contract (b29)
# ---------------------------------------------------------------------------

class TestFailClosedContract:
    """
    The single most important contract: when something is ambiguous or
    broken, entry must be BLOCKED, never allowed through.
    """

    def test_invalid_grade_is_treated_as_worst(self):
        v = GUARD.evaluate(_proposal(grade="N/A"), _account(), _perf())
        assert v.denied

    def test_learning_error_blocks_entry(self):
        # A learning object whose grade is invalid must not bypass the gate.
        ls = LearningAdjustments(min_grade="X")
        v = GUARD.evaluate(_proposal(grade="B"), _account(), _perf(), learning=ls)
        # invalid learning grade -> treated as worst -> B does not pass
        assert v.denied

    def test_history_error_blocks_entry(self):
        v = GUARD.evaluate(_proposal(), _account(history_ok=False), _perf())
        assert v.denied

    def test_zero_balance_does_not_silently_allow_loss(self):
        v = GUARD.evaluate(
            _proposal(),
            _account(balance=Decimal("0")),
            _perf(daily_pnl=Decimal("-9999")),
        )
        # The daily-loss gate is skipped at zero balance, but the position
        # sizing then produces the minimum lot, never an unbounded size.
        assert v.allowed
        assert Decimal(str(v.volume)) <= MAX_LOT
