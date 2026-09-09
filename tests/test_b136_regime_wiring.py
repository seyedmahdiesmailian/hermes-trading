"""b136 — every regime the account-health policy can emit must be WIRED.

Root cause this test locks: engines/risk.assess_account_policy returns a
risk_multiplier (normal 1.0 / defensive 0.75 / recovery 0.5 / locked 0.0), but
the entry path never reads that field — sizing is gated off the literal sets
STOP_TRADING_REGIMES and TIGHT_REGIMES in engines/auto_executor.py alone.
"recovery" was in neither, so at >=2.5% drawdown the bot sized entries at FULL
risk — larger than the more urgent-looking "defensive" state.

These tests assert the WIRING (each non-normal regime must block or shrink vs
normal), not a specific multiplier, so they stay true if numbers are retuned.
They must NOT be weakened if a regime is added: add it to the emitter here AND
wire it in auto_executor in the same change.
"""
import unittest
from datetime import datetime, timezone

from engines import auto_executor as AE
from engines import cooldown as CD
from engines.auto_executor import STOP_TRADING_REGIMES, TIGHT_REGIMES
from engines.risk import assess_account_policy, compute_performance_state


def _emitted_regimes() -> dict:
    """regime -> risk_multiplier, discovered from the real policy function."""
    probes = [(0.0, 0, 0.0), (0.0, 2, 0.0), (-60.0, 0, 0.0),
              (0.0, 0, 0.026), (0.0, 0, 0.051)]
    out = {}
    for pnl, streak, dd in probes:
        pol = assess_account_policy(balance=5000.0,
                                    equity=round(5000 * (1 - dd), 2),
                                    free_margin=5000.0, margin=0.0,
                                    daily_pnl=pnl, loss_streak=streak,
                                    open_positions=0)
        out[pol["regime"]] = pol["risk_multiplier"]
    return out


def _blueprint():
    # Same gate-passing SELL the census uses: 10.00 stop, 25.00 target (RR 2.5).
    return {"side": "SELL", "entry_price": 4450.0, "sl": 4460.0,
            "tp": 4425.0, "symbol": "XAUUSD"}


def _result_for(regime: str):
    """Real evaluate_proposal, time gates stubbed OPEN; nothing else stubbed."""
    mult = _emitted_regimes().get(regime, 1.0)
    real_open, real_cd = AE.is_market_open, CD.check_entry_cooldown
    AE.is_market_open = lambda *a, **k: True
    CD.check_entry_cooldown = lambda now=None: {"allowed": True}
    try:
        pol = {"trade_allowed": regime not in STOP_TRADING_REGIMES,
               "regime": regime, "open_positions": 0, "balance": 5000.0,
               "risk_multiplier": mult}
        # b196 (2026-09-09, edited not deleted — b88 rule): the real policy
        # carries a balance-tiered base_risk_pct and the executor now SIZES
        # FROM IT (clamped under MAX). A hand-built pol without the key would
        # silently test only the fallback, so carry the true base in — the
        # same one assess_account_policy emits at this balance.
        pol["base_risk_pct"] = assess_account_policy(
            balance=5000.0, equity=5000.0, free_margin=5000.0, margin=0.0,
            daily_pnl=0.0, loss_streak=0, open_positions=0)["base_risk_pct"]
        perf = compute_performance_state(
            {}, datetime.now(timezone.utc).date().isoformat(), 5000.0, [])
        return AE.evaluate_proposal({"blueprint": dict(_blueprint()),
                                     "grade": "B"}, pol, perf, {}, None)
    finally:
        AE.is_market_open = real_open
        CD.check_entry_cooldown = real_cd


def _lot(regime: str):
    res = _result_for(regime)
    assert res.get("execute"), f"{regime} did not execute: {res.get('reason')}"
    return float(res["command"]["lot"])


class B136RegimeWiring(unittest.TestCase):

    def test_policy_emits_the_four_expected_regimes(self):
        self.assertEqual(set(_emitted_regimes()),
                         {"normal", "defensive", "recovery", "locked"})

    def test_every_non_normal_regime_is_wired(self):
        """A regime the policy can emit must block or shrink — never be inert."""
        emitted = set(_emitted_regimes()) - {"normal"}
        wired = STOP_TRADING_REGIMES | TIGHT_REGIMES
        self.assertEqual(emitted - wired, set(),
                         f"regimes the policy emits but sizing ignores: "
                         f"{sorted(emitted - wired)}")

    def test_recovery_shrinks_size_vs_normal(self):
        """The bug: recovery used to size identically to normal."""
        self.assertLess(_lot("recovery"), _lot("normal"))

    def test_recovery_is_not_looser_than_defensive(self):
        """Ordering guard: deeper drawdown must never size LARGER."""
        self.assertLessEqual(_lot("recovery"), _lot("defensive"))

    def test_locked_still_blocks(self):
        res = _result_for("locked")
        self.assertFalse(res["execute"])
        self.assertIn("account_policy_locked", res["reason"])

    def test_normal_path_untouched_by_this_fix(self):
        """Regression: the tightening must not have shrunk the normal path."""
        res = _result_for("normal")
        self.assertTrue(res["execute"])
        # b196 (2026-09-09, edited not deleted — b88 rule): this pin used to
        # demand MAX (0.02). That WAS the b136 defect on the BASE leg: the
        # policy's balance-tiered base had no reader. Post-fix the normal path
        # sizes at the POLICY's own base — min(0.015 tier at 5k, MAX 0.02) =
        # 0.015. The test's meaning survives intact: no regime damper fires.
        self.assertAlmostEqual(res["risk_pct"], 0.015, places=9)


if __name__ == "__main__":
    unittest.main()
