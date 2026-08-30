"""b29 — safety gates must FAIL CLOSED.

evaluate_proposal() wraps three safety gates (learned grade, DEFCON,
cooldown) in try/except. The old code did `except Exception: pass`, i.e.
a corrupted state file or a broken gate silently BYPASSED the gate and
let the trade through. Now any gate error returns execute=False with a
*_gate_error reason. These tests pin that behaviour: if anyone reverts
to fail-open, they go red.
"""
import unittest
from datetime import datetime, timezone


class FailClosedGateTests(unittest.TestCase):
    """Each gate-error path must refuse the trade, never bypass it."""

    def _pol(self):
        return {'trade_allowed': True, 'regime': 'normal',
                'open_positions': 0, 'balance': 5000.0}

    def _prop(self):
        return {'blueprint': {'side': 'SELL', 'entry_price': 4450,
                              'sl': 4460, 'tp': 4435, 'symbol': 'XAUUSD'},
                'grade': 'B'}

    def _perf(self):
        from engines.risk import compute_performance_state
        now = datetime.now(timezone.utc)
        return compute_performance_state({}, now.date().isoformat(), 5000.0, [])

    def _base_patches(self):
        """Neutralise market-hours + cooldown so we can isolate one gate."""
        import engines.auto_executor as ae
        import engines.cooldown as cd
        self.addCleanup(lambda: setattr(ae, 'is_market_open', self._real_ae_mk))
        self.addCleanup(lambda: setattr(cd, 'check_entry_cooldown', self._real_cd))
        self._real_ae_mk = ae.is_market_open
        self._real_cd = cd.check_entry_cooldown
        ae.is_market_open = lambda *a, **k: True
        cd.check_entry_cooldown = lambda now=None: {'allowed': True}

    def test_defcon_gate_error_blocks_entry(self):
        self._base_patches()
        import engines.defcon as dc
        real = dc.compute_insights
        self.addCleanup(lambda: setattr(dc, 'compute_insights', real))

        def boom(**kw):
            raise RuntimeError('corrupted defcon state')

        dc.compute_insights = boom
        from engines.auto_executor import evaluate_proposal
        r = evaluate_proposal(self._prop(), self._pol(), self._perf(), {}, None)
        self.assertFalse(r.get('execute'),
                         f"DEFCON gate error must block, got {r}")
        self.assertEqual(r.get('reason'), 'defcon_gate_error')

    def test_cooldown_gate_error_blocks_entry(self):
        import engines.auto_executor as ae
        import engines.cooldown as cd
        self._real_ae_mk = ae.is_market_open
        self._real_cd = cd.check_entry_cooldown
        self.addCleanup(lambda: setattr(ae, 'is_market_open', self._real_ae_mk))
        self.addCleanup(lambda: setattr(cd, 'check_entry_cooldown', self._real_cd))
        ae.is_market_open = lambda *a, **k: True

        def boom(now=None):
            raise RuntimeError('corrupted cooldown state')

        cd.check_entry_cooldown = boom
        from engines.auto_executor import evaluate_proposal
        r = evaluate_proposal(self._prop(), self._pol(), self._perf(), {}, None)
        self.assertFalse(r.get('execute'),
                         f"cooldown gate error must block, got {r}")
        self.assertEqual(r.get('reason'), 'cooldown_gate_error')

    def test_learning_grade_gate_error_blocks_entry(self):
        self._base_patches()
        import engines.learning as lm
        real = lm.GRADES
        self.addCleanup(lambda: setattr(lm, 'GRADES', real))
        lm.GRADES = []  # GRADES.index('B') -> ValueError inside the gate
        from engines.auto_executor import evaluate_proposal
        r = evaluate_proposal(self._prop(), self._pol(), self._perf(), {}, None)
        self.assertFalse(r.get('execute'),
                         f"learning gate error must block, got {r}")
        self.assertEqual(r.get('reason'), 'learning_gate_error')

    def test_healthy_gates_still_allow_entry(self):
        """Control: fail-closed must not become fail-everything."""
        self._base_patches()
        from engines.auto_executor import evaluate_proposal
        r = evaluate_proposal(self._prop(), self._pol(), self._perf(), {}, None)
        if not r.get('execute'):
            self.fail(f'expected execute with healthy gates, got {r.get("reason")}')


if __name__ == '__main__':
    unittest.main()
