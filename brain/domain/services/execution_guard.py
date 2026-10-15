"""
Execution Guard - the safety core of the system.

All fail-closed gates that lived in V1's auto_executor.py are reimplemented
here as clean-architecture domain code.

Golden rule (b29): every gate is fail-closed.
A gate error blocks entry, never allows it through.

Extracted from: docs/V1_LOGIC_EXTRACTION.md
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Hard safety constants (fail-closed ceilings)
# ---------------------------------------------------------------------------

MAX_RISK_PER_TRADE_PCT = Decimal("0.02")   # 2% of balance per trade - hard cap
MAX_DAILY_LOSS_PCT = Decimal("0.05")       # 5% daily loss -> stop trading
MAX_DAILY_TRADES = 5                       # max trades per day
MAX_OPEN_POSITIONS = 1                     # only 1 simultaneous position
MIN_RISK_REWARD = Decimal("1.0")           # minimum RR floor
MIN_SETUP_GRADE = "B"                      # A > B > C
MAX_LOT = Decimal("0.10")                  # hard volume cap
MIN_STOP_BALANCE = Decimal("1000")         # below this, stop filter is looser
MIN_STOP_DISTANCE = Decimal("8.0")         # gold noise floor (points)
MIN_STOP_ATR_MULT = Decimal("2.0")         # stop must be >= 2x ATR
GRADE_ORDER = ("A", "B", "C")              # A is the best grade

# Regimes where trading is blocked entirely
STOP_TRADING_REGIMES = frozenset({"drawdown_lock", "margin_call", "frozen"})

# Styles exempt from the RR floor (b233d: only strong styles may carry low RR)
RR_FLOOR_EXEMPT_STYLES = frozenset({
    "aggressive_value_entry",
    "value_entry",
    "discount_entry",
    "ob_entry",
    "fvg_entry",
})


# ---------------------------------------------------------------------------
# Value objects
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class GuardVerdict:
    """Result of evaluating every gate."""
    allowed: bool
    reason: str                          # primary reason (ticket)
    all_reasons: tuple[str, ...] = ()    # every reason (observability)
    defcon: Optional[str] = None         # GREEN / YELLOW / RED
    risk_pct: Decimal = Decimal("0")     # final risk percentage
    volume: Decimal = Decimal("0")       # computed volume
    gate_errors: int = 0                 # gates that raised an exception

    @property
    def denied(self) -> bool:
        return not self.allowed

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "reason": self.reason,
            "all_reasons": list(self.all_reasons),
            "defcon": self.defcon,
            "risk_pct": str(self.risk_pct),
            "volume": str(self.volume),
            "gate_errors": self.gate_errors,
        }


@dataclass
class ProposalInput:
    """Guard input - equivalent of the V1 proposal."""
    side: str                      # BUY / SELL
    entry: Decimal
    sl: Decimal
    tp: Decimal
    symbol: str = "XAUUSD"
    grade: str = "B"               # required: A/B/C
    execution_style: str = ""
    blocked_by_macro: bool = False
    # Contract size: for XAUUSD 1 lot = 100 oz, so a 1.0 price move on 1 lot
    # is $100. Sizing must divide by contract size or the volume explodes.
    contract_size: Decimal = Decimal("100")

    @classmethod
    def from_blueprint(cls, blueprint: dict, **extra: Any) -> "ProposalInput":
        return cls(
            side=str(blueprint.get("side", "")).upper(),
            entry=Decimal(str(blueprint.get("entry_price", 0))),
            sl=Decimal(str(blueprint.get("sl", 0))),
            tp=Decimal(str(blueprint.get("tp", 0))),
            symbol=str(blueprint.get("symbol", "XAUUSD")),
            **extra,
        )


@dataclass
class AccountState:
    """Account state - equivalent of the V1 account_policy."""
    balance: Decimal = Decimal("0")
    regime: str = "normal"
    trade_allowed: bool = True
    open_positions: int = 0
    positions_unreadable: bool = False   # b219: bridge went dark
    history_ok: Optional[bool] = None    # None = unknown, False = error

    @classmethod
    def from_policy(cls, policy: dict) -> "AccountState":
        return cls(
            balance=Decimal(str(policy.get("balance", 0) or 0)),
            regime=str(policy.get("regime", "normal")),
            trade_allowed=bool(policy.get("trade_allowed", True)),
            open_positions=int(policy.get("open_positions", 0) or 0),
            positions_unreadable=bool(policy.get("positions_unreadable", False)),
            history_ok=policy.get("history_ok"),
        )


@dataclass
class PerformanceState:
    """Performance state - equivalent of the V1 performance_state."""
    daily_pnl: Decimal = Decimal("0")
    trades_today: int = 0
    loss_streak: int = 0
    recent_closed: list = field(default_factory=list)


@dataclass
class LearningAdjustments:
    """Learning tweaks - learning may only tighten."""
    min_rr: Decimal = MIN_RISK_REWARD
    min_grade: str = "B"
    risk_mult: Decimal = Decimal("1.0")

    @classmethod
    def from_state(cls, ls: dict) -> "LearningAdjustments":
        """Load from learning_state; invalid values fall back to the default."""
        def _dec(key: str, default: Decimal) -> Decimal:
            # FAIL-CLOSED: an invalid value keeps the default (strictest).
            try:
                val = Decimal(str(ls.get(key, default)))
            except Exception:
                return default
            return val

        def _grade(key: str, default: str) -> str:
            v = str(ls.get(key, default)).strip().upper()
            return v if v in GRADE_ORDER else default

        return cls(
            min_rr=_dec("min_rr", MIN_RISK_REWARD),
            min_grade=_grade("min_grade", "B"),
            risk_mult=_dec("risk_mult", Decimal("1.0")),
        )


# ---------------------------------------------------------------------------
# ExecutionGuard - the gate engine
# ---------------------------------------------------------------------------

class ExecutionGuard:
    """
    All fail-closed gates in one evaluation.

    Evaluation order matches V1 auto_executor.evaluate_proposal exactly:
      1   proposal validity
      2   account policy
      2.5 closed-trade history readable
      3   daily loss
      4   daily trades
      5   open positions
      5.5 TP/SL geometry
      5.6 risk:reward floor
      5.65 gold noise floor
      6   setup grade
      6.5 learning grade gate (fail-closed)
      6.6 DEFCON feedback (fail-closed)
      6.7 cooldown (fail-closed)
      7   macro blackout
      7.5 market session
    """

    def evaluate(
        self,
        proposal: ProposalInput,
        account: AccountState,
        performance: PerformanceState,
        plan: Optional[dict] = None,
        learning: Optional[LearningAdjustments] = None,
        defcon_insights: Optional[dict] = None,
        cooldown_ok: bool = True,
        cooldown_reason: str = "",
        market_open: bool = True,
        now: Optional[datetime] = None,
    ) -> GuardVerdict:
        reasons: list[str] = []
        gate_errors = 0

        # -- Check 1: valid proposal --------------------------------------
        if proposal is None:
            return self._deny("no_proposal", ["no_proposal"])
        if proposal.side not in {"BUY", "SELL"}:
            return self._deny("invalid_blueprint", ["invalid_side"])
        if proposal.entry <= 0 or proposal.sl <= 0 or proposal.tp <= 0:
            return self._deny("invalid_blueprint", ["invalid_price"])

        # -- Check 2: account policy --------------------------------------
        if not account.trade_allowed or account.regime in STOP_TRADING_REGIMES:
            if account.positions_unreadable:
                reasons.append("bridge_dark_positions_unreadable")  # b219
            reasons.append(f"account_{account.regime}")
            return self._deny(f"account_policy_{account.regime}", reasons)

        # -- Check 2.5: history readable ----------------------------------
        if account.history_ok is False:
            return self._deny("history_unavailable", reasons + ["history_unavailable"])

        # -- Check 3: daily loss limit ------------------------------------
        if account.balance > 0:
            daily_loss_pct = abs(min(Decimal(0), performance.daily_pnl)) / account.balance
            if daily_loss_pct >= MAX_DAILY_LOSS_PCT:
                return self._deny(
                    "daily_loss_limit",
                    reasons + [f"daily_loss_{daily_loss_pct:.1%}"],
                )

        # -- Check 4: daily trade count -----------------------------------
        if performance.trades_today >= MAX_DAILY_TRADES:
            return self._deny(
                "daily_trade_limit",
                reasons + [f"max_daily_trades_{performance.trades_today}"],
            )

        # -- Check 5: open positions limit --------------------------------
        if account.open_positions >= MAX_OPEN_POSITIONS:
            return self._deny(
                "position_limit",
                reasons + [f"max_positions_{account.open_positions}"],
            )

        # -- Check 5.5: TP/SL geometry ------------------------------------
        if proposal.side == "SELL" and (proposal.tp >= proposal.entry or proposal.sl <= proposal.entry):
            return self._deny("invalid_geometry", reasons + ["invalid_geometry_sell"])
        if proposal.side == "BUY" and (proposal.tp <= proposal.entry or proposal.sl >= proposal.entry):
            return self._deny("invalid_geometry", reasons + ["invalid_geometry_buy"])

        # -- Check 5.6: risk:reward floor ---------------------------------
        sl_dist = abs(proposal.entry - proposal.sl)
        tp_dist = abs(proposal.tp - proposal.entry)
        rr = tp_dist / sl_dist if sl_dist > 0 else Decimal("0")
        eff_min_rr = learning.min_rr if learning else MIN_RISK_REWARD
        floor = max(MIN_RISK_REWARD, eff_min_rr)
        if proposal.execution_style in RR_FLOOR_EXEMPT_STYLES:
            floor = Decimal("0")   # b233d
        if rr < floor:
            return self._deny(f"poor_rr_{rr:.2f}", reasons + [f"poor_rr_{rr:.2f}"])

        # -- Check 5.65: gold noise floor ---------------------------------
        atr = Decimal(str((plan or {}).get("atr") or 0))
        min_stop = MIN_STOP_DISTANCE
        if atr > 0:
            min_stop = min(MIN_STOP_ATR_MULT * atr, MIN_STOP_DISTANCE)
        if sl_dist < min_stop and account.balance >= MIN_STOP_BALANCE:
            return self._deny("stop_too_tight", reasons + [f"stop_too_tight_{sl_dist:.2f}"])

        # -- Check 6: setup grade -----------------------------------------
        grade = proposal.grade or "B"
        if self._grade_idx(grade) > self._grade_idx(MIN_SETUP_GRADE):
            return self._deny(
                f"setup_grade_{grade}",
                reasons + [f"grade_{grade}_below_minimum"],
            )

        # -- Check 6.5: learning grade gate (FAIL-CLOSED) -----------------
        if learning is not None:
            try:
                # V1 parity: GRADES.index() raised on an invalid grade and the
                # except branch denied entry. Mirror that here instead of
                # silently treating an invalid floor as the most permissive.
                if learning.min_grade not in GRADE_ORDER:
                    raise ValueError(f"invalid min_grade:{learning.min_grade}")
                if self._grade_idx(grade) > self._grade_idx(learning.min_grade):
                    return self._deny(
                        f"learned_min_grade_{learning.min_grade}",
                        reasons + [f"learned_grade_{learning.min_grade}"],
                    )
            except Exception as e:
                gate_errors += 1
                logger.error("learning_gate_error: %s", e)
                return self._deny(
                    "learning_gate_error",
                    reasons + [f"learning_error:{e}"],
                    gate_errors=gate_errors,
                )

        # -- Check 6.6: DEFCON feedback (FAIL-CLOSED) ---------------------
        if defcon_insights is not None:
            try:
                if not defcon_insights.get("trade_allowed", True):
                    lvl = str(defcon_insights.get("defcon", "UNKNOWN")).upper()
                    return self._deny(
                        f"defcon_{lvl.lower()}_entry_blocked",
                        reasons + [f"defcon_{lvl}"],
                        defcon=lvl,
                        gate_errors=gate_errors,
                    )
            except Exception as e:
                gate_errors += 1
                logger.error("defcon_gate_error: %s", e)
                return self._deny(
                    "defcon_gate_error",
                    reasons + [f"defcon_error:{e}"],
                    gate_errors=gate_errors,
                )

        # -- Check 6.7: cooldown (FAIL-CLOSED) ----------------------------
        if not cooldown_ok:
            return self._deny(
                cooldown_reason or "cooldown",
                reasons + [cooldown_reason or "cooldown"],
                gate_errors=gate_errors,
            )

        # -- Check 7: macro blackout --------------------------------------
        if proposal.blocked_by_macro:
            return self._deny("macro_blackout", reasons + ["macro_blackout"])

        # -- Check 7.5: market open ---------------------------------------
        if not market_open:
            return self._deny("market_closed", reasons + ["market_closed"])

        # -- All gates passed -> size the position ------------------------
        sizing = self._size_position(
            account=account,
            defcon_insights=defcon_insights,
            learning=learning,
            sl_dist=sl_dist,
            contract_size=proposal.contract_size,
        )
        return GuardVerdict(
            allowed=True,
            reason="ok",
            all_reasons=tuple(reasons),
            defcon=sizing.get("defcon"),
            risk_pct=sizing.get("risk_pct", Decimal("0")),
            volume=sizing.get("volume", Decimal("0")),
            gate_errors=gate_errors,
        )

    # ------------------------------------------------------------------
    # Position sizing - V1 principles (b196)
    # ------------------------------------------------------------------
    def _size_position(
        self,
        account: AccountState,
        defcon_insights: Optional[dict],
        learning: Optional[LearningAdjustments],
        sl_dist: Decimal,
        contract_size: Decimal = Decimal("100"),
    ) -> dict:
        """
        b196: size from the account's balance tier, never flat 2%.
        Hard cap: MAX_RISK_PER_TRADE_PCT (2%) is never breached.
        DEFCON YELLOW halves the risk.
        Contract size: for XAUUSD, 1 lot = 100 oz, so risk per lot on a
        stop of D points is D * contract_size. Without this divisor the
        computed volume is 100x too large.
        """
        try:
            risk_amount = account.balance * MAX_RISK_PER_TRADE_PCT

            # DEFCON YELLOW -> half risk
            defcon_level = None
            if defcon_insights:
                defcon_level = str(defcon_insights.get("defcon", "")).upper()
            if defcon_level == "YELLOW":
                risk_amount = risk_amount / 2

            # learning risk_mult (clamped - may only tighten)
            if learning and learning.risk_mult > 0:
                risk_amount = risk_amount * learning.risk_mult

            # volume from the stop distance, normalised by contract size
            per_lot_risk = sl_dist * contract_size if sl_dist > 0 else Decimal("0")
            volume = risk_amount / per_lot_risk if per_lot_risk > 0 else Decimal("0")

            # volume floor / cap
            volume = max(Decimal("0.01"), min(volume, MAX_LOT))

            risk_pct = MAX_RISK_PER_TRADE_PCT
            if defcon_level == "YELLOW":
                risk_pct = MAX_RISK_PER_TRADE_PCT / 2
            return {"risk_pct": risk_pct, "volume": volume, "defcon": defcon_level}
        except Exception as e:
            logger.error("sizing_error: %s", e)
            return {"risk_pct": Decimal("0"), "volume": Decimal("0")}

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    def _grade_idx(self, grade: str) -> int:
        """A=0 (best), B=1, C=2. Invalid = worst (fail-closed)."""
        return GRADE_ORDER.index(grade) if grade in GRADE_ORDER else len(GRADE_ORDER)

    def _deny(
        self,
        reason: str,
        reasons: list[str],
        defcon: Optional[str] = None,
        gate_errors: int = 0,
    ) -> GuardVerdict:
        return GuardVerdict(
            allowed=False,
            reason=reason,
            all_reasons=tuple(reasons),
            defcon=defcon,
            gate_errors=gate_errors,
        )
