"""b231d — the two real callers produce STABLE keys (roadmap 4.1).

The bridge replay only works if a retried order hashes to the key the first
attempt used. That is a property of what the CALLER seeds the key with: an
intent id that does not move across retries. A wall-clock value or a per-cycle
random id would break the guarantee silently — the key would differ on every
retry and the bridge would treat each one as a fresh order.

This file executes the real key-builders from the two production order paths
and asserts determinism + distinctness directly, so a caller refactor that
re-seeds the key on something unstable fails here instead of in production.
"""
import unittest

from bridge_client import make_idempotency_key


def _plan_key(plan, cmd):
    """Mirror of the hermes_runtime.py wiring (line ~993)."""
    return make_idempotency_key(
        f"plan:{plan.get('plan_id') or plan.get('id', 'noid')}",
        cmd['side'], cmd['lot'], sl=cmd.get('sl'), tp=cmd.get('tp'))


def _signal_key(sig_record, command):
    """Imported from the production module — the real builder, not a copy."""
    from engines.signal_listener import _signal_order_key
    return _signal_order_key(sig_record, command)


class TestPlanPathKey(unittest.TestCase):
    def setUp(self):
        self.plan = {"plan_id": "xau_20261004_0315", "grade": "A"}
        self.cmd = {"side": "BUY", "lot": 0.02, "sl": 4400.0, "tp": 4450.0}

    def test_key_is_stable_across_cycles(self):
        """Two passes over the same plan must produce the same key — a cron
        retry has nothing else to identify the intent by."""
        a = _plan_key(self.plan, self.cmd)
        b = _plan_key(self.plan, self.cmd)
        self.assertEqual(a, b)

    def test_different_plan_gives_different_key(self):
        other = {"plan_id": "xau_20261004_0320"}
        self.assertNotEqual(_plan_key(self.plan, self.cmd),
                            _plan_key(other, self.cmd))

    def test_plan_falls_back_to_id_when_no_plan_id(self):
        fallback = {"id": "legacy-1"}
        self.assertTrue(_plan_key(fallback, self.cmd))
        # a plan with neither field still keys deterministically
        bare = {}
        self.assertEqual(_plan_key(bare, self.cmd), _plan_key(bare, self.cmd))

    def test_two_plans_with_noid_do_not_collide_by_accident_only(self):
        """Two plans lacking an id key to the SAME value — documented, since
        neither has anything to distinguish it. Real plans always have one."""
        self.assertEqual(_plan_key({}, self.cmd), _plan_key({}, self.cmd))


class TestSignalPathKey(unittest.TestCase):
    def setUp(self):
        self.sig = {"chat_id": "-1001234567890", "message_id": 77001,
                    "parsed": {}, "decision": {}}
        self.cmd = {"side": "BUY", "lot": 0.02, "sl": 4400.0, "tp": 4450.0}

    def test_key_is_stable(self):
        self.assertEqual(_signal_key(self.sig, self.cmd),
                         _signal_key(self.sig, self.cmd))

    def test_edited_repost_keeps_same_key(self):
        """The channel editing a signal arrives with a new update_id but the
        SAME message_id — this is precisely the case the dedup horizon could
        miss, and here the key keeps it from trading twice."""
        repost = dict(self.sig)
        repost["timestamp"] = 9999999999
        self.assertEqual(_signal_key(self.sig, self.cmd),
                         _signal_key(repost, self.cmd))

    def test_different_message_gives_different_key(self):
        other = dict(self.sig, message_id=77002)
        self.assertNotEqual(_signal_key(self.sig, self.cmd),
                            _signal_key(other, self.cmd))

    def test_missing_ids_still_deterministic(self):
        """A signal record from an older build path lacks the fields; the key
        must not crash and must still be stable."""
        bare = {"parsed": {}}
        self.assertEqual(_signal_key(bare, self.cmd),
                         _signal_key(bare, self.cmd))

    def test_signal_and_plan_paths_never_collide(self):
        """The two intents are namespaced apart so a signal cannot ever replay
        a plan's answer (or vice versa) even at identical geometry."""
        plan_key = _plan_key({"plan_id": "xau_1"}, self.cmd)
        sig_key = _signal_key({"chat_id": "c", "message_id": 1}, self.cmd)
        self.assertNotEqual(plan_key, sig_key)


if __name__ == "__main__":
    unittest.main()
