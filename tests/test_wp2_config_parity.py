#!/usr/bin/env python3
"""WP2 — config centralization parity + no-stray-literals ratchet.

engines/config.py is the ONE canonical reader of infrastructure identity
(bridge host/URL, LAN addrs, Telegram ids/tokens, DRY_RUN parse). These
tests pin that every accessor returns EXACTLY what the pre-WP2 literals
did — including the documented precedence chains — and that no identity
literal survives anywhere else in production code.

The two DOCUMENTED normalizations (see engines/config.py) are pinned as
behavior, not smuggled: empty-string HERMES_BRIDGE_URL falls back to the
derived URL, and ops_chat_id() uses the nested chain everywhere.
"""
from __future__ import annotations

import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engines import config as C  # noqa: E402

CHAT = "194015957"
WIN = "192.168.10.51"
LAN = "192.168.10.18"

_PINNED_KEYS = (
    "HERMES_WIN_IP", "HERMES_BRIDGE_URL", "HERMES_BRIDGE_TOKEN",
    "HERMES_LAN_IP", "HERMES_DRY_RUN", "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_CHAT_ID", "TELEGRAM_SIGNAL_GROUP",
    "AUTOPILOT_REPORT_BOT_TOKEN", "AUTOPILOT_REPORT_CHAT_ID",
    "WIN_HOST", "WIN_USER", "WIN_PASS", "WIN_BACKUP_DIR",
)


def _scrubbed(**over):
    """Env with every pinned key removed, then overrides applied."""
    env = {k: v for k, v in os.environ.items() if k not in _PINNED_KEYS}
    env.update(over)
    return env


class TestWp2Defaults(unittest.TestCase):
    def test_defaults_match_pre_wp2_literals(self):
        with mock.patch.dict(os.environ, _scrubbed(), clear=True):
            self.assertEqual(C.win_ip(), WIN)
            self.assertEqual(C.bridge_url(), f"http://{WIN}:5050")
            self.assertEqual(C.lan_ip(), LAN)
            self.assertEqual(C.telegram_chat_id(), CHAT)
            self.assertEqual(C.ops_chat_id(), CHAT)
            self.assertEqual(C.telegram_bot_token(), "")
            self.assertEqual(C.ops_bot_token(), "")
            self.assertIsNone(C.bridge_token())
            self.assertEqual(C.signal_group(), "")
            self.assertEqual(C.win_user(), "Administrator")
            self.assertEqual(C.win_pass(), "")
            # byte-for-byte: the shipped default carries TWO literal
            # backslashes (PowerShell tolerates it; WP2 preserves it).
            self.assertEqual(C.win_backup_dir(), "C:\\\\HermesBackups")
            self.assertTrue(C.dry_run())

    def test_bridge_timeout_values_unchanged(self):
        self.assertEqual(C.BRIDGE_TIMEOUT_GET, 8)
        self.assertEqual(C.BRIDGE_TIMEOUT_POST, 12)
        self.assertEqual(C.BRIDGE_TIMEOUT_HEALTH, 5)


class TestWp2Precedence(unittest.TestCase):
    def test_explicit_url_wins_over_win_ip(self):
        with mock.patch.dict(os.environ,
                             _scrubbed(HERMES_WIN_IP="10.0.0.9",
                                       HERMES_BRIDGE_URL="http://10.0.0.9:9999"),
                             clear=True):
            self.assertEqual(C.bridge_url(), "http://10.0.0.9:9999")

    def test_url_derives_from_win_ip(self):
        with mock.patch.dict(os.environ,
                             _scrubbed(HERMES_WIN_IP="10.0.0.9"), clear=True):
            self.assertEqual(C.bridge_url(), "http://10.0.0.9:5050")

    def test_empty_url_falls_back_to_derived(self):
        # NORMALIZATION (pinned): pre-WP2 bridge_client honored "" via
        # getenv-default and broke downstream; weekly/health already used
        # the or-form. One coherent rule now.
        with mock.patch.dict(os.environ,
                             _scrubbed(HERMES_WIN_IP="10.0.0.9",
                                       HERMES_BRIDGE_URL=""), clear=True):
            self.assertEqual(C.bridge_url(), "http://10.0.0.9:5050")

    def test_win_host_override_chain(self):
        with mock.patch.dict(os.environ, _scrubbed(), clear=True):
            self.assertEqual(C.win_host(), WIN)
        with mock.patch.dict(os.environ,
                             _scrubbed(HERMES_WIN_IP="10.0.0.9"), clear=True):
            self.assertEqual(C.win_host(), "10.0.0.9")
        with mock.patch.dict(os.environ,
                             _scrubbed(HERMES_WIN_IP="10.0.0.9",
                                       WIN_HOST="10.0.0.7"), clear=True):
            self.assertEqual(C.win_host(), "10.0.0.7")

    def test_ops_token_falsy_fallback(self):
        # ``or``-form preserved: emptied ops token falls back, never mutes.
        with mock.patch.dict(os.environ,
                             _scrubbed(TELEGRAM_BOT_TOKEN="t",
                                       AUTOPILOT_REPORT_BOT_TOKEN="o"),
                             clear=True):
            self.assertEqual(C.ops_bot_token(), "o")
        with mock.patch.dict(os.environ,
                             _scrubbed(TELEGRAM_BOT_TOKEN="t",
                                       AUTOPILOT_REPORT_BOT_TOKEN=""),
                             clear=True):
            self.assertEqual(C.ops_bot_token(), "t")

    def test_ops_chat_nested_chain(self):
        # NORMALIZATION (pinned): nested everywhere (was flat in daemons).
        with mock.patch.dict(os.environ, _scrubbed(), clear=True):
            self.assertEqual(C.ops_chat_id(), CHAT)
        with mock.patch.dict(os.environ,
                             _scrubbed(TELEGRAM_CHAT_ID="111"), clear=True):
            self.assertEqual(C.ops_chat_id(), "111")
        with mock.patch.dict(os.environ,
                             _scrubbed(TELEGRAM_CHAT_ID="111",
                                       AUTOPILOT_REPORT_CHAT_ID="222"),
                             clear=True):
            self.assertEqual(C.ops_chat_id(), "222")

    def test_dry_run_parse_table(self):
        cases = [("true", True), ("True", True), ("1", True), ("yes", True),
                 ("anything", True), ("false", False), ("FALSE", False),
                 ("0", False), ("no", False), ("NO", False)]
        for raw, want in cases:
            with mock.patch.dict(os.environ,
                                 _scrubbed(HERMES_DRY_RUN=raw), clear=True):
                self.assertEqual(C.dry_run(), want, f"DRY_RUN={raw!r}")


class TestWp2Delegation(unittest.TestCase):
    """The old import shapes still resolve — through config now."""

    def _run(self, code: str, env: dict) -> str:
        base = {k: v for k, v in os.environ.items() if k not in _PINNED_KEYS}
        base.update(env)
        r = subprocess.run([sys.executable, "-c", code], cwd=str(ROOT),
                           env=base, capture_output=True, text=True,
                           timeout=90)
        self.assertEqual(r.returncode, 0, f"stderr: {r.stderr[-800:]}")
        return r.stdout.strip()

    def test_bridge_client_constants_derive_from_config(self):
        out = self._run(
            "from bridge_client import WIN_IP, BRIDGE_URL;"
            "from engines.config import win_ip, bridge_url;"
            "print(WIN_IP == win_ip(), BRIDGE_URL == bridge_url(), BRIDGE_URL)",
            {"HERMES_WIN_IP": "10.0.0.9"})
        self.assertTrue(out.startswith("True True http://10.0.0.9:5050"), out)

    def test_daemon_dry_run_constants_follow_config(self):
        out = self._run(
            "import hermes_master, signal_monitor;"
            "from engines.config import dry_run;"
            "print(hermes_master.DRY_RUN, signal_monitor.DRY_RUN, dry_run())",
            {"HERMES_DRY_RUN": "false"})
        self.assertEqual(out, "False False False", out)


class TestWp2NoStrayLiterals(unittest.TestCase):
    """Ratchet: identity literals live ONLY in engines/config.py (+3 named
    exceptions with written reasons). A new literal anywhere else fails."""

    ALLOW = {
        "engines/config.py": "the ONE canonical home of every default",
        "scripts/_deploy_bridge.py": "manual SecOps tool: hard-require "
            "WIN_PASS + explicit host chain, deliberately not rewired",
        "scripts/_deploy_pending_bridge.py": "same as _deploy_bridge.py",
        "scripts/build_full_report.py": "report CONTENT string (admin chat "
            "label), not a config read",
    }

    def _prod_py(self):
        for p in sorted(ROOT.rglob("*.py")):
            rel = str(p.relative_to(ROOT))
            if rel.startswith((".git/", "tests/", "legacy_backup/",
                               "legacy_removed/", "data/", "logs/")):
                continue
            if "__pycache__" in p.parts:
                continue
            yield rel, p

    def test_no_stray_identity_literals(self):
        bad = []
        for rel, p in self._prod_py():
            if rel in self.ALLOW:
                continue
            src = p.read_text(encoding="utf-8", errors="replace")
            for lit in (CHAT, WIN, LAN):
                if lit in src:
                    bad.append(f"{rel}: {lit}")
        self.assertEqual(bad, [], "identity literal outside engines/config.py"
                         " (rewire through config or extend ALLOW with a "
                         f"written reason): {bad}")

    def test_allowlist_entries_are_live(self):
        for rel, why in self.ALLOW.items():
            p = ROOT / rel
            self.assertTrue(p.exists(), f"allowlisted file gone: {rel}")
            src = p.read_text(encoding="utf-8", errors="replace")
            self.assertTrue(any(lit in src for lit in (CHAT, WIN, LAN)),
                            f"DEAD allowlist entry {rel} ({why}) — the "
                            "literal is gone, drop the exemption")

    def test_scan_is_not_vacuous(self):
        src = (ROOT / "engines/config.py").read_text(encoding="utf-8")
        for lit in (CHAT, WIN, LAN):
            self.assertIn(lit, src, "scan lost sight of the canonical "
                          f"literal {lit} — scope broken?")
        n = sum(1 for _ in self._prod_py())
        self.assertGreater(n, 50, f"only {n} prod files scanned — glob broken?")


if __name__ == "__main__":
    unittest.main()
