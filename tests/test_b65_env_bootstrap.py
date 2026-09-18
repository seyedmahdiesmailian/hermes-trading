"""b65 — every bridge consumer must BOOTSTRAP its own env (found by the b64 audit).

The b64 scan asks "does this file write a host literal down?". The b64 run
found a sibling shape it could not see: a file that resolves the bridge
through bridge_client (so NO literal, NO env read of its own) but never
loads .env. bridge_client reads HERMES_WIN_IP/HERMES_BRIDGE_URL at IMPORT
time and BridgeClient.__init__ reads HERMES_BRIDGE_TOKEN at construction —
if the process started without the env (no cron wrapper, no systemd
Environment=), every call goes out tokenless and the consumer never notices.

Two LIVE cases were found and healed this run:
  * cli.py `status` — imported bridge_client, never loaded .env:
    'Bridge: OK' next to 'Account: HTTP_401', and worse, the positions line
    read positions.get('data', []) WITHOUT the ok-check, so a 401 printed
    'Open Positions: 0' — an auth failure rendered as an empty account.
    (The b51 harvest note already caught this bug class on two probe
    scripts via a dead NAME; this is the same failure via a MISSING
    bootstrap — invisible to b52/b61/b62/b63/b64, all of which look at
    env READS, and a file that reads no env has nothing to flag.)
  * cli.py `run` — `os.environ['HERMES_DRY_RUN'] = str(args.live).lower()`
    with a store_true flag: bare `cli.py run` wrote 'false' (= LIVE) and
    `cli.py run --live` wrote 'true' (= dry-run). The flag was INVERTED —
    the safe-looking default command was the one that could send a real
    order. Fixed: dry-run is the default, only --live flips it.
  * hermes_runtime.main() — read NO env and called cycle() with its
    default dry_run=False, so a bare `python3 hermes_runtime.py` was a
    LIVE-order path with a tokenless bridge (401s would have blocked the
    entry, but the DEFAULT must be safe, not saved by an accident). Now it
    loads .env and honours HERMES_DRY_RUN exactly like hermes_master
    (default: dry-run). hermes_master — the production entry — always
    passed dry_run=DRY_RUN and is unchanged.

RULE enforced mechanically: every production file (.py at root, scripts/,
engines/, notifier/) that CONSTRUCTS BridgeClient must also CALL
load_dotenv — AST-checked, replayed against the pre-b65 shapes, floored so
a broken scan cannot pass by finding nothing.
"""
from __future__ import annotations

import ast
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

PRODUCTION_GLOBS = ("*.py", "scripts/*.py", "engines/*.py", "notifier/*.py")


def _calls_named(tree: ast.AST, name: str) -> list[int]:
    """linenos of Call sites whose func is `name` or `x.name`."""
    out = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Call):
            f = n.func
            if (isinstance(f, ast.Name) and f.id == name) or (
                    isinstance(f, ast.Attribute) and f.attr == name):
                out.append(n.lineno)
    return out


def bridge_consumers_without_bootstrap(files=None) -> list[dict]:
    """Production files that construct BridgeClient but never call
    load_dotenv — they will run tokenless unless someone else exported .env."""
    bad = []
    paths = files
    if paths is None:
        s: set[Path] = set()
        for pat in PRODUCTION_GLOBS:
            s.update(REPO.glob(pat))
        paths = sorted(p for p in s
                       if "__pycache__" not in p.parts and ".git" not in p.parts)
    for p in paths:
        src = p.read_text(encoding="utf-8", errors="replace")
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue          # b52's universe tripwire already reports it
        ctor = _calls_named(tree, "BridgeClient")
        if not ctor:
            continue
        if not _calls_named(tree, "load_dotenv"):
            bad.append({"file": str(p.relative_to(REPO)), "ctor_lines": ctor})
    return bad


def _scan_one(src: str, name: str) -> list[dict]:
    tree = ast.parse(src)
    ctor = _calls_named(tree, "BridgeClient")
    if ctor and not _calls_named(tree, "load_dotenv"):
        return [{"file": name, "ctor_lines": ctor}]
    return []


class TestB65EnvBootstrap(unittest.TestCase):
    # ---------------------------------------------------------- tripwires

    def test_every_bridge_client_constructor_loads_dotenv(self):
        """MAIN TRIPWIRE: a file that builds a BridgeClient owns its env
        bootstrap. The pre-b65 cli.py and hermes_runtime.main() are exactly
        what this catches."""
        bad = bridge_consumers_without_bootstrap()
        self.assertEqual(
            bad, [],
            "BridgeClient constructed without load_dotenv — tokenless bridge "
            "calls on any entrypoint that did not export .env (the b65 "
            f"cli.py shape): {bad}")

    def test_scan_scope_floor(self):
        """Anti-vacuity: the scan must see the real population of bridge
        consumers — a broken glob/parse would pass the tripwire above by
        finding nothing (b41/b48 lesson)."""
        seen = 0
        for pat in PRODUCTION_GLOBS:
            for p in REPO.glob(pat):
                if "__pycache__" in p.parts:
                    continue
                src = p.read_text(encoding="utf-8", errors="replace")
                try:
                    tree = ast.parse(src)
                except SyntaxError:
                    continue
                seen += len(_calls_named(tree, "BridgeClient"))
        self.assertGreaterEqual(
            seen, 40,
            f"only {seen} BridgeClient() sites found — scan broken?")

    def test_tripwire_bites_on_the_pre_b65_shape(self):
        """Replay: the old cli.py import block (constructs, never loads) is
        flagged; the healed block is clean; a file that never touches the
        bridge is irrelevant."""
        pre_b65 = ("from bridge_client import BridgeClient\n"
                   "def go():\n"
                   "    b = BridgeClient()\n"
                   "    return b.get_account()\n")
        hits = _scan_one(pre_b65, "cli.py")
        self.assertEqual(len(hits), 1, "pre-b65 cli.py shape not flagged")
        healed = ("try:\n"
                  "    from dotenv import load_dotenv\n"
                  "except ImportError:\n"
                  "    from env_loader import load_dotenv\n"
                  "load_dotenv('.env')\n"
                  "from bridge_client import BridgeClient\n"
                  "b = BridgeClient()\n")
        self.assertEqual(_scan_one(healed, "cli.py"), [],
                         "healed bootstrap shape falsely flagged")
        innocent = "import json\nprint(json.dumps({}))\n"
        self.assertEqual(_scan_one(innocent, "x.py"), [])

    # ------------------------------------------------- cli.py behavioural

    def _subp(self, code: str, env_extra=None, argv=None):
        base = {k: v for k, v in os.environ.items()
                if k not in ("HERMES_BRIDGE_TOKEN", "HERMES_WIN_IP",
                             "HERMES_BRIDGE_URL", "HERMES_DRY_RUN")}
        base.update(env_extra or {})
        r = subprocess.run([sys.executable, "-c", code] + (argv or []),
                           cwd=str(REPO), env=base,
                           capture_output=True, text=True, timeout=90)
        return r

    def test_cli_import_loads_the_bridge_token(self):
        """BEHAVIOUR: importing cli.py in a tokenless environment must
        restore HERMES_BRIDGE_TOKEN from .env (skipped where .env is absent
        — clean worktrees)."""
        if not (REPO / ".env").exists():
            self.skipTest("no .env in this checkout")
        r = self._subp("import cli, os; "
                       "print(bool(os.environ.get('HERMES_BRIDGE_TOKEN')))")
        self.assertEqual(r.returncode, 0, f"import failed: {r.stderr[:300]}")
        self.assertEqual(r.stdout.strip(), "True",
                         "cli.py no longer bootstraps .env — status panel "
                         "is back to tokenless 401s")

    def test_cli_run_defaults_to_dry_run(self):
        """The inverted flag, replayed for real: a bare `cli.py run` must
        set HERMES_DRY_RUN=true (the pre-b65 line set 'false' = LIVE), and
        `cli.py run --live` must set false. hermes_master is STUBBED — no
        cycle ever runs."""
        code = (
            "import sys, os, types\n"
            "sys.argv = ['cli'] + __import__('json').loads(sys.argv[1])\n"
            "fake = types.ModuleType('hermes_master')\n"
            "fake.main = lambda: (print('DRY=' + os.environ.get("
            "'HERMES_DRY_RUN', '<unset>')), 0)[1]\n"
            "sys.modules['hermes_master'] = fake\n"
            "import cli\n"
            "try:\n"
            "    cli.main()\n"
            "except SystemExit:\n"
            "    pass\n")
        import json as _json
        r = self._subp(code, argv=[_json.dumps(["run"])])
        self.assertIn("DRY=true", r.stdout,
                      f"`cli.py run` (no flag) is not dry-run: {r.stdout!r} "
                      f"{r.stderr[:200]!r}")
        r2 = self._subp(code, argv=[_json.dumps(["run", "--live"])])
        self.assertIn("DRY=false", r2.stdout,
                      f"`cli.py run --live` did not flip to live: {r2.stdout!r}")

    def test_cli_status_surfaces_auth_failure_not_zero(self):
        """The silent-zero positions line, replayed through the REAL
        cmd_status with a fake 401 bridge (HERMES_DATA_ROOT redirected to a
        temp dir — no production state read): every failed section must
        print ❌, and 'Open Positions: 0' must NOT appear."""
        code = (
            "import sys, os, tempfile\n"
            "os.environ['HERMES_DATA_ROOT'] = tempfile.mkdtemp()\n"
            "class Fake:\n"
            "    url = 'http://fake'\n"
            "    def health(self): return {'ok': True}\n"
            "    def get_account(self): return {'ok': False, "
            "'error': 'HTTP_401'}\n"
            "    def get_tick(self, s): return {'ok': False, "
            "'error': 'HTTP_401'}\n"
            "    def get_positions(self, s): return {'ok': False, "
            "'error': 'HTTP_401'}\n"
            "import bridge_client\n"
            "bridge_client.BridgeClient = Fake\n"
            "import cli\n"
            "sys.argv = ['cli', 'status']\n"
            "cli.main()\n")
        r = self._subp(code)
        self.assertEqual(r.returncode, 0, f"cmd_status crashed: {r.stderr[:300]}")
        out = r.stdout
        self.assertIn("Open Positions: ❌", out,
                      f"401 positions payload not surfaced: {out!r}")
        self.assertNotIn("Open Positions: 0", out,
                         "auth failure still renders as an empty account")
        self.assertIn("Account: ❌", out)

    # ------------------------------------------- hermes_runtime.main()

    def test_runtime_main_honours_dry_run_knob(self):
        """BEHAVIOUR: hermes_runtime.main() with cycle() and BridgeClient
        stubbed. The knob must be WIRED (injected true/false reach cycle as
        dry_run True/False — env_loader never overrides an existing value,
        so the injection wins over .env), main() must bootstrap .env (token
        present), and the SOURCE must keep the safe default: unset resolves
        through os.getenv('HERMES_DRY_RUN', 'true') — pre-b65 the default
        was cycle()'s dry_run=False, a live-by-accident path. (The unset
        case is not asserted behaviourally: this box's .env deliberately
        says false — the live system — so 'unset' cannot be observed here.)
        """
        code = (
            "import sys, os\n"
            "sys.argv = ['hermes_runtime.py']\n"
            "import hermes_runtime as hr, bridge_client\n"
            "captured = {}\n"
            "class Fake:\n"
            "    url = 'http://fake'\n"
            "    def health(self): return {'ok': True}\n"
            "bridge_client.BridgeClient = Fake\n"
            "def fake_cycle(bridge, dry_run=None, **kw):\n"
            "    captured['dry'] = dry_run\n"
            "    captured['token'] = bool(os.environ.get("
            "'HERMES_BRIDGE_TOKEN'))\n"
            "    return {'ok': True}\n"
            "hr.cycle = fake_cycle\n"
            "hr.main()\n"
            "print('DRY=%r TOKEN=%r' % (captured['dry'], "
            "captured['token']))\n")
        r = self._subp(code, env_extra={"HERMES_DRY_RUN": "true"})
        self.assertEqual(r.returncode, 0, f"main() crashed: {r.stderr[:400]}")
        self.assertIn("DRY=True", r.stdout,
                      f"HERMES_DRY_RUN=true did not reach cycle(): {r.stdout!r}")
        r2 = self._subp(code, env_extra={"HERMES_DRY_RUN": "false"})
        self.assertEqual(r2.returncode, 0, f"main() crashed: {r2.stderr[:400]}")
        self.assertIn("DRY=False", r2.stdout,
                      f"HERMES_DRY_RUN=false did not reach cycle(): {r2.stdout!r}")
        if (REPO / ".env").exists():
            self.assertIn("TOKEN=True", r.stdout + r2.stdout,
                          "hermes_runtime.main() no longer loads .env")
        src = (REPO / "hermes_runtime.py").read_text(encoding="utf-8")
        # WP2 (2026-09-18, edited not deleted per b102): the safe default
        # moved to engines.config.dry_run() (default-true pinned by
        # tests/test_wp2_config_parity.py); main() must still resolve
        # through it (the behavioural halves above prove the wiring).
        self.assertIn("engines.config", src)
        self.assertIn("dry_run", src,
                      "hermes_runtime.main() lost its safe default — unset "
                      "HERMES_DRY_RUN must mean dry-run (b65)")

    def test_production_entry_still_owns_the_live_knob(self):
        """Pin the contract this fix leans on: hermes_master parses
        HERMES_DRY_RUN with default-true and passes it to cycle() — if that
        ever changes, the 'safe default' reasoning above is stale."""
        src = (REPO / "hermes_master.py").read_text(encoding="utf-8")
        # WP2 (2026-09-18, edited not deleted per b102): the knob moved to
        # engines.config.dry_run() (default-true pinned by
        # tests/test_wp2_config_parity.py); the entry still OWNS it by
        # resolving DRY_RUN at import and passing it to cycle().
        self.assertIn("engines.config", src)
        self.assertIn("dry_run", src)
        self.assertRegex(src, r"(?m)^DRY_RUN\s*=",
                         "hermes_master no longer resolves DRY_RUN")
        self.assertIn("cycle(bridge, dry_run=DRY_RUN)", src)


if __name__ == "__main__":
    unittest.main()
