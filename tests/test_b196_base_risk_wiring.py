"""b196 — the entry sizer must read the account's OWN base risk (2026-09-09).

Root cause this test locks: engines/risk.assess_account_policy emits a
balance-tiered base_risk_pct (<800 1% / <1500 1.5% / <5000 2% / >=5000 1.5%)
every cycle and hermes_runtime hands that dict to evaluate_proposal — but the
executor sized from the flat MAX_RISK_PER_TRADE_PCT and recorded THAT as the
stack's base. The policy's base had ZERO readers in the sizing path: the b136
"computed, reported, never wired" class, this time on the BASE leg. At
balance >= 5000 (live crossed 5k before) every entry risked 2% where the
shipped account-health doc says 1.5% — 33% LOOSER than the policy.

Contract pinned here (tightening-only, fail-closed):
  * base = min(policy base_risk_pct, MAX) — the tier can only SHRINK the lot;
  * a policy dict WITHOUT the key (legacy/test callers) falls back to MAX,
    i.e. exactly the pre-fix behaviour — never a silent 0-lot;
  * risk_stack["base_risk_pct"] records the base that ACTUALLY sized the lot
    (b139 ledger product stays true).
"""
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engines import auto_executor as AE                        # noqa: E402
from engines import cooldown as CD                             # noqa: E402
from engines.risk import _base_risk_pct, assess_account_policy  # noqa: E402


def _blueprint():
    return {"side": "SELL", "entry_price": 4450.0, "sl": 4460.0,
            "tp": 4425.0, "symbol": "XAUUSD"}


def _perf():
    from engines.risk import compute_performance_state
    return compute_performance_state(
        {}, datetime.now(timezone.utc).date().isoformat(), 5000.0, [])


def _eval(policy: dict) -> dict:
    real_open, real_cd = AE.is_market_open, CD.check_entry_cooldown
    AE.is_market_open = lambda *a, **k: True
    CD.check_entry_cooldown = lambda now=None: {"allowed": True}
    try:
        return AE.evaluate_proposal({"blueprint": dict(_blueprint()),
                                     "grade": "B"}, policy, _perf(), {}, None)
    finally:
        AE.is_market_open = real_open
        CD.check_entry_cooldown = real_cd


class BaseRiskWiring(unittest.TestCase):

    def _normal_pol(self, balance, **over):
        pol = assess_account_policy(balance=balance, equity=balance,
                                    free_margin=balance, margin=0.0,
                                    daily_pnl=0.0, loss_streak=0,
                                    open_positions=0)
        pol.update(over)
        return pol

    def test_real_policy_at_5k_sizes_at_1_5_pct(self):
        """The headline defect: >=5000 used to size 0.02, policy says 0.015."""
        res = _eval(self._normal_pol(5000.0))
        self.assertTrue(res["execute"], res["reason"])
        self.assertAlmostEqual(res["risk_pct"], 0.015, places=9)
        self.assertAlmostEqual(res["risk_usd"], 75.0, places=0)

    def test_low_balance_tier_halves_the_old_flat_base(self):
        """<800 -> 1%: the pre-fix flat 2% was sizing 2x the policy. NOTE
        (measured while writing this test): at 1% base a 10pt stop wants
        0.008 lots < the broker's 0.01 min — the tightening converts into a
        sizing_below_min_meaningful_lot SKIP at that stop width, which is
        fail-closed behaviour, so risk_pct is pinned on the stack, not the
        lot."""
        pol = self._normal_pol(799.0)
        self.assertAlmostEqual(pol["base_risk_pct"], 0.01, places=9)
        res = _eval(pol)
        self.assertFalse(res["execute"])
        self.assertEqual(res["reason"], "sizing_below_min_meaningful_lot")
        # the sizing branch carries no risk_pct key; the returned sizing dict
        # holds the lot math, and the tier is visible via risk_usd/balance.
        self.assertAlmostEqual(res["sizing"]["risk_usd"] / 799.0, 0.01,
                               places=6)
        # a narrow stop (5pt) still fits the min lot at 1%:
        bp = _blueprint()
        bp["sl"] = bp["entry_price"] + 5.0
        real_open, real_cd = AE.is_market_open, CD.check_entry_cooldown
        AE.is_market_open = lambda *a, **k: True
        CD.check_entry_cooldown = lambda now=None: {"allowed": True}
        try:
            res2 = AE.evaluate_proposal({"blueprint": bp, "grade": "B"},
                                        pol, _perf(), {}, None)
        finally:
            AE.is_market_open = real_open
            CD.check_entry_cooldown = real_cd
        self.assertTrue(res2["execute"], res2["reason"])
        self.assertAlmostEqual(res2["command"]["lot"], 0.01, places=2)

    def test_mid_tier_unchanged_vs_pre_fix(self):
        """800..4999 -> the tier IS 2%, so behaviour is byte-identical."""
        pol = self._normal_pol(4897.79)   # the live balance at filing time
        self.assertAlmostEqual(pol["base_risk_pct"], 0.02, places=9)
        res = _eval(pol)
        self.assertAlmostEqual(res["risk_pct"], AE.MAX_RISK_PER_TRADE_PCT,
                               places=9)

    def test_max_is_a_ceiling_not_a_floor(self):
        """A hypothetical looser policy base must NEVER raise the lot."""
        pol = self._normal_pol(5000.0)
        pol["base_risk_pct"] = 0.05      # nonsense tier, must be clamped
        res = _eval(pol)
        self.assertTrue(res["execute"], res["reason"])
        self.assertAlmostEqual(res["risk_pct"], AE.MAX_RISK_PER_TRADE_PCT,
                               places=9)

    def test_missing_key_falls_back_to_max_not_zero(self):
        """Fail-CLOSED means the legacy contract, not a silent 0-lot: a
        minimal hand-built policy (test_b53 shape) keeps pre-fix sizing."""
        pol = {"trade_allowed": True, "regime": "normal",
               "open_positions": 0, "balance": 5000.0}   # NO base_risk_pct
        res = _eval(pol)
        self.assertTrue(res["execute"], res["reason"])
        self.assertAlmostEqual(res["risk_pct"], AE.MAX_RISK_PER_TRADE_PCT,
                               places=9)
        self.assertAlmostEqual(res["risk_stack"]["base_risk_pct"],
                               AE.MAX_RISK_PER_TRADE_PCT, places=9)

    def test_garbage_base_falls_back_to_max(self):
        for junk in ("", "abc", None, 0, -1):
            pol = self._normal_pol(5000.0)
            pol["base_risk_pct"] = junk
            res = _eval(pol)
            self.assertTrue(res["execute"], f"{junk!r}: {res['reason']}")
            self.assertAlmostEqual(res["risk_pct"],
                                   AE.MAX_RISK_PER_TRADE_PCT, places=9,
                                   msg=f"junk base {junk!r} must fall back")

    def test_stack_records_the_base_that_sized_the_lot(self):
        """b139 ledger integrity: product of the recorded legs reproduces
        final_risk_pct even when the base is tiered, not MAX."""
        res = _eval(self._normal_pol(5000.0))
        st = res["risk_stack"]
        self.assertAlmostEqual(st["base_risk_pct"], 0.015, places=9)
        product = (st["base_risk_pct"] * st["learning_risk_mult"]
                   * st["style_mult"] * st["regime_mult"]
                   * st.get("session_mult", 1.0))
        self.assertAlmostEqual(product, res["risk_pct"], places=10)

    def test_tiered_base_composes_with_every_damper(self):
        """Style 0.5 x defensive-regime 0.5 on top of the 1.5% base."""
        pol = self._normal_pol(5000.0)
        res = _eval(dict(pol, regime="defensive"))
        # defensive shrinks via TIGHT_REGIMES 0.5 (policy risk_multiplier is
        # still unread by sizing — that is b138's open human decision).
        self.assertTrue(res["execute"], res["reason"])
        self.assertAlmostEqual(res["risk_pct"], 0.015 * 0.5, places=9)

    def test_tiers_are_never_looser_than_max(self):
        """The clamp proof for every tier boundary: min(tier, MAX)==tier."""
        for b in (1.0, 799.0, 800.0, 1499.0, 1500.0, 4999.0, 5000.0, 99999.0):
            self.assertLessEqual(_base_risk_pct(b), AE.MAX_RISK_PER_TRADE_PCT,
                                 f"tier at {b} exceeds the ceiling")


if __name__ == "__main__":
    unittest.main()
