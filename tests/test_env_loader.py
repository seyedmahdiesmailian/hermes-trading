"""Tests for env_loader — the python-dotenv fallback (2026-08-30 outage fix).

Background: python-dotenv is not installed on this box, and every entrypoint
guarded `from dotenv import load_dotenv` with a silent no-op lambda. Direct
runs of hermes_master.py therefore had no HERMES_BRIDGE_TOKEN → bridge 401 →
'insufficient_market_data' on every cycle. These tests lock the fallback's
behaviour (offline, temp files only — never reads the real .env).
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, '/home/ai/hermes-trading')

from env_loader import load_dotenv


class TestEnvLoader(unittest.TestCase):
    def _write(self, text: str) -> str:
        fd, path = tempfile.mkstemp(suffix=".env")
        os.close(fd)
        Path(path).write_text(text, encoding="utf-8")
        self.addCleanup(lambda: os.path.exists(path) and os.unlink(path))
        return path

    def test_loads_plain_pairs(self):
        p = self._write("HERMES_T_A=1\nHERMES_T_B=two words\n")
        load_dotenv(p)
        self.assertEqual(os.environ.get("HERMES_T_A"), "1")
        self.assertEqual(os.environ.get("HERMES_T_B"), "two words")

    def test_strips_matching_quotes(self):
        p = self._write('HERMES_T_Q="quoted val"\nHERMES_T_S=\'single\'\nHERMES_T_D=mixed"\n')
        load_dotenv(p)
        self.assertEqual(os.environ.get("HERMES_T_Q"), "quoted val")
        self.assertEqual(os.environ.get("HERMES_T_S"), "single")
        self.assertEqual(os.environ.get("HERMES_T_D"), 'mixed"')

    def test_never_overrides_existing_env(self):
        os.environ["HERMES_T_EXIST"] = "orig"
        self.addCleanup(os.environ.pop, "HERMES_T_EXIST", None)
        p = self._write("HERMES_T_EXIST=new\n")
        load_dotenv(p)
        self.assertEqual(os.environ["HERMES_T_EXIST"], "orig")

    def test_ignores_comments_and_junk(self):
        p = self._write("# comment\n\n  \nNOEQUALS\n=noname\nHERMES_T_OK=y\n")
        load_dotenv(p)
        self.assertEqual(os.environ.get("HERMES_T_OK"), "y")
        self.assertNotIn("NOEQUALS", os.environ)
        self.assertNotIn("", os.environ)

    def test_missing_file_is_noop(self):
        load_dotenv("/nonexistent/path/.env")  # must not raise

    def test_value_with_equals_keeps_rest(self):
        p = self._write("HERMES_T_EQ=a=b=c\n")
        load_dotenv(p)
        self.assertEqual(os.environ.get("HERMES_T_EQ"), "a=b=c")

    def test_entrypoints_use_fallback_not_noop(self):
        """The silent no-op lambda must not come back in core entrypoints."""
        for rel in ("hermes_master.py", "signal_monitor.py", "backtest_runner.py",
                    "engines/signal_listener.py"):
            src = Path("/home/ai/hermes-trading", rel).read_text(encoding="utf-8")
            self.assertNotIn("load_dotenv = lambda", src,
                             f"{rel} still silently no-ops .env loading")
            self.assertIn("env_loader", src, f"{rel} missing env_loader fallback")

    def test_every_dotenv_user_has_fallback(self):
        """Any repo .py that imports dotenv must guard it with the env_loader
        fallback (python-dotenv is NOT installed on this box — a bare import
        crashes the script; a silent no-op starves it of the bridge token).
        Also bans hand-parsed .env reads outside env_loader itself."""
        root = Path("/home/ai/hermes-trading")
        checked = 0
        for py in sorted(root.rglob("*.py")):
            if "__pycache__" in py.parts or ".git" in py.parts:
                continue
            if py.parent == root / "tests":  # this file quotes the banned patterns
                continue
            if py == root / "env_loader.py":
                continue
            src = py.read_text(encoding="utf-8", errors="replace")
            uses_dotenv = "from dotenv import" in src or "import dotenv" in src
            hand_parses = (".env'" in src or '.env"' in src) and "load_dotenv" not in src
            if uses_dotenv or hand_parses:
                checked += 1
                self.assertIn("env_loader", src,
                              f"{py.relative_to(root)} loads .env without the "
                              "env_loader fallback (bare dotenv import or "
                              "hand-parsed .env)")
                self.assertNotIn("load_dotenv = lambda", src,
                                 f"{py.relative_to(root)} silently no-ops .env loading")
        # sanity: the scan actually finds the known consumers
        self.assertGreaterEqual(checked, 8,
                                "dotenv-consumer scan found too few files — glob broken?")


if __name__ == "__main__":
    unittest.main()
