"""Bridge configuration contract.

BridgeClient is used by daemons, cron jobs, tests, and one-shot tools. Its
network target must be resolved when a client is constructed, not frozen when
bridge_client.py is first imported by another module.
"""
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bridge_client import BridgeClient, bridge_token, bridge_url  # noqa: E402


class TestBridgeConfiguration(unittest.TestCase):
    def setUp(self):
        self.original = {
            key: os.environ.get(key)
            for key in ("HERMES_BRIDGE_URL", "HERMES_WIN_IP", "HERMES_BRIDGE_TOKEN")
        }

    def tearDown(self):
        for key, value in self.original.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def test_url_is_resolved_at_client_construction(self):
        os.environ.pop("HERMES_BRIDGE_URL", None)
        os.environ["HERMES_WIN_IP"] = "10.10.10.20"
        first = BridgeClient()
        self.assertEqual(first.url, "http://10.10.10.20:5050")

        os.environ["HERMES_WIN_IP"] = "10.10.10.21"
        second = BridgeClient()
        self.assertEqual(second.url, "http://10.10.10.21:5050")
        self.assertNotEqual(first.url, second.url)

    def test_explicit_url_wins_over_derived_host(self):
        os.environ["HERMES_BRIDGE_URL"] = "http://bridge.example:6060/"
        os.environ["HERMES_WIN_IP"] = "10.10.10.22"
        self.assertEqual(bridge_url(), "http://bridge.example:6060")
        self.assertEqual(BridgeClient().url, "http://bridge.example:6060")

    def test_token_is_resolved_without_replacing_an_explicit_empty_value(self):
        os.environ["HERMES_BRIDGE_TOKEN"] = "secret-a"
        self.assertEqual(bridge_token(), "secret-a")
        self.assertEqual(BridgeClient().token, "secret-a")

        self.assertEqual(BridgeClient(token="").token, "")

    def test_no_network_request_is_needed_to_construct_a_client(self):
        client = BridgeClient(url="http://offline.invalid", token="test")
        self.assertEqual(client.url, "http://offline.invalid")
        self.assertFalse(client.connected)


if __name__ == "__main__":
    unittest.main()
