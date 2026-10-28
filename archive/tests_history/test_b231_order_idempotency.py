"""b231 — order idempotency (roadmap 4.1).

The gap this closes: bridge_client.send_order posted a request and the LAN
reply was lost. The daemon retries, and the retry opened a SECOND position
against MAX_OPEN_POSITIONS=1. Two layers are tested here:

  1. key derivation — deterministic for one intent, distinct across intents.
     Determinism is what makes a replay recognisable to the bridge; distinctness
     is what keeps two genuinely different orders from colliding.
  2. client wire shape — the key travels in `comment`, and a call made without
     a key sends no comment at all (back-compat with the deployed bridge, which
     would otherwise treat every keyless order as a replay and refuse to trade).
"""
import unittest
from unittest.mock import patch, MagicMock

from bridge_client import (make_idempotency_key, _idempotency_comment,
                           BridgeClient, IDEMPOTENCY_PREFIX)


class TestKeyDerivation(unittest.TestCase):
    """The key must be a pure function of the order intent."""

    def test_same_intent_same_key(self):
        a = make_idempotency_key("chat:123", "BUY", 0.02, 4410.0, 4400.0)
        b = make_idempotency_key("chat:123", "BUY", 0.02, 4410.0, 4400.0)
        self.assertEqual(a, b)

    def test_different_intent_different_key(self):
        a = make_idempotency_key("chat:123", "BUY", 0.02, 4410.0, 4400.0)
        b = make_idempotency_key("chat:124", "BUY", 0.02, 4410.0, 4400.0)
        self.assertNotEqual(a, b)

    def test_different_geometry_different_key(self):
        """A re-sized or re-priced order is a DIFFERENT order."""
        base = ("chat:123", "BUY", 0.02, 4410.0, 4400.0)
        self.assertNotEqual(make_idempotency_key(*base),
                            make_idempotency_key("chat:123", "BUY", 0.04, 4410.0, 4400.0))
        self.assertNotEqual(make_idempotency_key(*base),
                            make_idempotency_key("chat:123", "BUY", 0.02, 4420.0, 4400.0))
        self.assertNotEqual(make_idempotency_key(*base),
                            make_idempotency_key("chat:123", "SELL", 0.02, 4410.0, 4400.0))

    def test_no_sl_tp_is_still_deterministic(self):
        a = make_idempotency_key("plan:7", "SELL", 0.01)
        b = make_idempotency_key("plan:7", "SELL", 0.01)
        self.assertEqual(a, b)

    def test_none_sl_tp_distinguishable_from_zero(self):
        """None and 0.0 must not map to the same key — None means 'unset'."""
        k_none = make_idempotency_key("plan:7", "BUY", 0.01)
        k_zero = make_idempotency_key("plan:7", "BUY", 0.01, sl=0.0, tp=0.0)
        self.assertNotEqual(k_none, k_zero)

    def test_key_length_is_bounded(self):
        self.assertEqual(len(make_idempotency_key("x", "BUY", 0.01)), 16)

    def test_comment_is_mt5_safe(self):
        """MT5 truncates comment to 31 chars — the carrier must fit."""
        key = make_idempotency_key("chat:9999999999", "BUY", 0.10, 4400.0, 4350.0)
        c = _idempotency_comment(key)
        self.assertLessEqual(len(c), 31)
        self.assertTrue(c.startswith(IDEMPOTENCY_PREFIX))

    def test_comment_rejects_foreign_shape(self):
        """The bridge recognises replay candidates by the prefix."""
        self.assertTrue(_idempotency_comment(
            make_idempotency_key("a", "BUY", 0.01)).startswith("hms"))
        # a plain human comment must look different from a key carrier
        self.assertFalse("Hermes".startswith(IDEMPOTENCY_PREFIX))


class TestSendOrderWire(unittest.TestCase):
    """The key rides in `comment`; keyless callers send no comment."""

    def _client(self):
        bc = BridgeClient()
        bc._post = MagicMock()
        return bc

    def test_key_is_sent_as_comment(self):
        bc = self._client()
        key = make_idempotency_key("chat:1", "BUY", 0.02, 4410.0, 4400.0)
        bc.send_order("BUY", 0.02, sl=4410.0, tp=4400.0, idempotency_key=key)
        payload = bc._post.call_args[0][1]
        self.assertEqual(payload["comment"], _idempotency_comment(key))

    def test_no_key_sends_no_comment(self):
        """Back-compat: the deployed bridge must keep serving keyless orders.

        Without this, a not-yet-redeployed Windows bridge would treat every
        normal order as an unrecognised replay and refuse to trade at all.
        """
        bc = self._client()
        bc.send_order("BUY", 0.02, sl=4410.0, tp=4400.0)
        payload = bc._post.call_args[0][1]
        self.assertNotIn("comment", payload)

    def test_side_is_lowercased_on_the_wire(self):
        bc = self._client()
        bc.send_order("SELL", 0.01)
        payload = bc._post.call_args[0][1]
        self.assertEqual(payload["type"], "sell")

    def test_lot_is_a_number_on_the_wire(self):
        bc = self._client()
        bc.send_order("BUY", 0.02)
        payload = bc._post.call_args[0][1]
        self.assertEqual(payload["volume"], 0.02)


class TestReplayGuarantee(unittest.TestCase):
    """The client-side half of the contract: retries carry the SAME comment."""

    @staticmethod
    def _client():
        bc = BridgeClient()
        bc._post = MagicMock()
        return bc

    def test_retried_request_carries_identical_comment(self):
        """A daemon retry of the same intent must send the same comment, or the
        bridge cannot recognise it as a replay."""
        bc = self._client()
        key = make_idempotency_key("chat:42", "BUY", 0.03, 4420.0, 4390.0)
        for _ in range(3):
            bc.send_order("BUY", 0.03, sl=4420.0, tp=4390.0,
                          idempotency_key=key)
        payloads = [args[0][1] for args in bc._post.call_args_list]
        comments = {p["comment"] for p in payloads}
        self.assertEqual(len(comments), 1, "retries must share one comment")

    def test_two_intents_never_share_comment(self):
        bc = self._client()
        k1 = make_idempotency_key("chat:1", "BUY", 0.02, 4410.0, 4400.0)
        k2 = make_idempotency_key("chat:2", "BUY", 0.02, 4410.0, 4400.0)
        bc.send_order("BUY", 0.02, sl=4410.0, tp=4400.0, idempotency_key=k1)
        bc.send_order("BUY", 0.02, sl=4410.0, tp=4400.0, idempotency_key=k2)
        payloads = [args[0][1] for args in bc._post.call_args_list]
        self.assertNotEqual(payloads[0]["comment"], payloads[1]["comment"])


if __name__ == "__main__":
    unittest.main()
