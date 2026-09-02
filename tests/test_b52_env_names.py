"""b52 — dead-env-var-name tripwire.

The incident (found by the b51 harvest): two probe scripts read
os.getenv('BRIDGE_TOKEN') — a name that exists in NO .env, no .env.example,
no systemd unit, no crontab. The failure mode was a confusing tokenless 401,
not a loud KeyError. This run's audit found the class was NOT dead:

  * scripts/ab_b55_meta.py still had os.getenv('BRIDGE_TOKEN') (masked only
    because BridgeClient falls back to the real key internally);
  * scripts/weekly_report.py read os.getenv('BRIDGE_URL', <hardcoded>) —
    the WRONG name WITH a default, so the default silently won even though
    HERMES_BRIDGE_URL is configured in .env. A bridge host change would have
    left the Friday cron report pointing at the old IP forever, with no error
    anywhere. This is the sharper lesson: an inline default does NOT make a
    dead name safe — it makes it SILENT. So the rule below flags every
    unknown name, default or not.

RULE enforced mechanically (AST, same family as b41/b42/b44/b48 tripwires):
  Every constant env name READ (os.getenv / os.environ.get / os.environ[...]
  with Load context) by production code (root *.py, scripts/, engines/,
  notifier/) must live in the known universe:
    1. .env.example keys (tracked; the deploy contract — .env itself is
       gitignored and ABSENT in the b50 clean worktree, so it can never be
       the source of truth);
    2. OS-standard names (PATH, HOME, XDG_RUNTIME_DIR, ...) — set by the
       kernel/login/systemd, never by us;
    3. DOCUMENTED_KNOBS — operational tunables and test seams that are
       deliberately NOT in .env because they carry safe inline defaults;
       each entry must name a real reader (liveness test below, b40/b41
       lesson: a dead exemption must not linger as a silent hole).

Pinned here:
  * the REAL repo is violation-free (the two dead names above were fixed in
    the same commit that added this tripwire);
  * anti-vacuity: minimum findings count (the scan must see a floor of
    distinct names across a floor of files, so a broken glob/parse can't
    pass by finding nothing);
  * DOCUMENTED_KNOBS liveness: every knob must actually be read by some
    production file;
  * BEHAVIOURAL replay: the exact pre-b52 shapes (dead BRIDGE_TOKEN, and
    dead BRIDGE_URL-WITH-a-default) are flagged through the real analyzer,
    while the fixed shapes are clean — proving the default does not buy
    immunity;
  * .env drift: if a real .env exists, every key in it must be documented
    in .env.example (a secret that exists only on one box is a dead name
    waiting for the next server rebuild — docs/DEPLOY.md restores from
    .env.example).
"""
from __future__ import annotations

import ast
import os
import re
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

# Production scope: everything that ships and runs on cron/systemd.
# tests/ and legacy_* are deliberately out of scope (test files create
# throwaway seams all the time; legacy trees are dead code).
PRODUCTION_GLOBS = ("*.py", "scripts/*.py", "engines/*.py", "notifier/*.py")

# OS-standard names: set by the kernel, login, or systemd — never by .env.
OS_KEYS = {
    "PATH", "HOME", "USER", "SHELL", "LANG", "LC_ALL", "TZ", "TMPDIR",
    "XDG_RUNTIME_DIR", "PYTHONPATH", "PYTHONUNBUFFERED", "DISPLAY",
}

# Env names deliberately NOT in .env: runtime knobs with safe inline
# defaults, and test-isolation seams. Every entry MUST have a real reader
# (test_documented_knobs_are_still_read) and a written reason.
DOCUMENTED_KNOBS = {
    "HERMES_DATA_ROOT": "test/staging seam redirecting the data dir (engines/paths.py, b39)",
    "HERMES_REPO_ROOT": "test seam redirecting what digest/harvest SCAN, never CODE (b47/b48)",
    "HERMES_SELFCHECK": "b49 fail-safe loud mode (engines/selfcheck.py)",
    "HERMES_STAMP": "verify_head.sh → head_verify stamping opt-in (b45)",
    "HERMES_VERIFY_TIMEOUT": "head_verify suite timeout knob (b50)",
    "HERMES_PUSH_GATE_MAX_AGE": "push-gate fail-open age knob (b45)",
    # HERMES_B50_NESTED is deliberately NOT listed: production (head_verify)
    # only WRITES it into the child env; the sole reader is a test file, which
    # is out of scope. The liveness test below would (rightly) reject it.
    "HERMES_MAX_SPREAD": "live entry spread gate tunable, default 0.60 (hermes_runtime, spread-gate item)",
    "WIN_HOST": "backup target host, default = the only bridge (offsite_backup)",
    "WIN_BACKUP_DIR": "backup dir on Windows, default C:\\HermesBackups (offsite_backup)",
    "HERMES_LAN_IP": "local IP for the WinRM pull URL, default = this box (offsite_backup)",
}


def _env_doc_keys() -> set[str]:
    """Keys declared in .env.example (tracked deploy contract). Names only —
    this test NEVER reads values, and never requires .env to exist."""
    p = REPO / ".env.example"
    keys = set()
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            keys.add(line.split("=", 1)[0].strip())
    return keys


def env_reads(src: str, name: str = "<memory>") -> list[tuple[str, bool, int]]:
    """All CONSTANT env-name reads: (key, has_inline_default, lineno).

    Covers os.getenv(X), os.environ.get(X), environ.get(X) (bare `from os
    import environ` shape), and os.environ[X] / environ[X] subscript READS
    (Store context — e.g. head_verify setting HERMES_SELFCHECK for a child —
    is not a read). Dynamic (non-constant) keys like env_loader's loop are
    unresolvable by design and skipped."""
    tree = ast.parse(src, filename=name)
    bare_environ = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom) and n.module == "os":
            for a in n.names:
                if a.name == "environ":
                    bare_environ.add(a.asname or a.name)

    def is_env_base(node) -> bool:
        # os.environ  /  environ (bare import)
        if isinstance(node, ast.Attribute) and node.attr == "environ" \
                and isinstance(node.value, ast.Name) and node.value.id == "os":
            return True
        return isinstance(node, ast.Name) and node.id in bare_environ

    reads: list[tuple[str, bool, int]] = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) \
                and n.func.attr in ("getenv", "get"):
            base = n.func.value
            ok = (isinstance(base, ast.Name) and base.id in ({"os"} | bare_environ)) \
                or is_env_base(base)
            if ok and n.args and isinstance(n.args[0], ast.Constant) \
                    and isinstance(n.args[0].value, str):
                reads.append((n.args[0].value, len(n.args) > 1, n.lineno))
        elif isinstance(n, ast.Subscript) and isinstance(n.ctx, ast.Load) \
                and isinstance(n.slice, ast.Constant) \
                and isinstance(n.slice.value, str) and is_env_base(n.value):
            reads.append((n.slice.value, False, n.lineno))
    return reads


def production_files() -> list[Path]:
    files = set()
    for pat in PRODUCTION_GLOBS:
        files.update(REPO.glob(pat))
    return sorted(f for f in files
                  if "__pycache__" not in f.parts and ".git" not in f.parts)


# ---------------------------------------------------------------------------
# b61 — REVERSE direction: documented keys with no reader.
# b52's rule above pins "every READ name exists in the universe". The inverse
# was never pinned: a key in .env.example that production never reads is a
# stale deploy contract — a fresh server gets a documented knob that does
# nothing (measured 2026-09-02: GIT_TOKEN_FILE was read by NOTHING while
# git_sync.sh hardcoded `cat .git_token`). Readers count in BOTH languages:
# Python via env_reads() above, shell via $KEY / ${KEY...} expansion — a key
# consumed by a cron .sh is just as "live" as one consumed by Python.
# ---------------------------------------------------------------------------

SHELL_GLOBS = ("*.sh", "scripts/*.sh")

# Keys legitimately outside the repo's reader scope (consumed by systemd
# units, the operator shell, or other repos). Same b40 discipline as
# DOCUMENTED_KNOBS: every entry must have a real reader somewhere, pinned
# by test_external_allowlist_is_still_used — a dead exemption is a hole.
EXTERNAL_READERS = {
    # (kept empty on purpose for now; if a key must live in .env.example
    # without a repo reader, name it here WITH a written reason)
}

_SHELL_VAR_RE = re.compile(r"\$\{?([A-Za-z_][A-Za-z0-9_]*)")


def shell_reads(src: str) -> set[str]:
    """Env names referenced by bash parameter expansion: $KEY, ${KEY},
    ${KEY:-default}, ${KEY:?msg}. Braces are optional in bash, so both
    shapes count; the word-boundary regex cannot over-match prefixes."""
    return set(_SHELL_VAR_RE.findall(src))


def production_shell_files() -> list[Path]:
    files = set()
    for pat in SHELL_GLOBS:
        files.update(REPO.glob(pat))
    return sorted(f for f in files
                  if "__pycache__" not in f.parts and ".git" not in f.parts)


def documented_key_readers() -> dict[str, list[str]]:
    """key -> files that read it (Python or shell). Built once per call;
    only .env.example keys are looked up, so OS/knob noise is irrelevant."""
    doc = _env_doc_keys()
    readers: dict[str, list[str]] = {k: [] for k in doc}
    for p in production_files():
        names = {k for k, _d, _l in env_reads(
            p.read_text(encoding="utf-8", errors="replace"), str(p))}
        for k in names & doc:
            readers[k].append(str(p.relative_to(REPO)))
    for p in production_shell_files():
        names = shell_reads(p.read_text(encoding="utf-8", errors="replace"))
        for k in names & doc:
            readers[k].append(str(p.relative_to(REPO)))
    return readers


def scan_dead_documented_keys() -> list[str]:
    readers = documented_key_readers()
    exempt = set(EXTERNAL_READERS)
    return sorted(k for k, files in readers.items()
                  if not files and k not in exempt)


def scan_universe_violations() -> list[dict]:
    universe = _env_doc_keys() | OS_KEYS | set(DOCUMENTED_KNOBS)
    violations = []
    for p in production_files():
        src = p.read_text(encoding="utf-8", errors="replace")
        try:
            reads = env_reads(src, str(p))
        except SyntaxError:
            self_fail = f"unparseable production file: {p}"
            violations.append({"file": str(p.relative_to(REPO)),
                               "key": self_fail, "default": False, "line": 0})
            continue
        for key, has_default, line in reads:
            if key not in universe:
                violations.append({"file": str(p.relative_to(REPO)),
                                   "key": key, "default": has_default,
                                   "line": line})
    return violations


class TestB52EnvNames(unittest.TestCase):
    def test_production_env_reads_all_known(self):
        v = scan_universe_violations()
        self.assertEqual(
            v, [],
            "production code reads env names that exist NOWHERE (.env.example/"
            f"OS/knobs) — dead names fail as silent defaults or tokenless 401s: {v}")

    def test_scan_is_not_vacuous(self):
        """A broken glob or parse must not pass by finding nothing."""
        seen_names, seen_files = set(), set()
        for p in production_files():
            for key, _d, _l in env_reads(p.read_text(encoding="utf-8",
                                                     errors="replace"), str(p)):
                seen_names.add(key)
                seen_files.add(p)
        self.assertGreaterEqual(len(seen_files), 15,
                                "env-read scan saw too few files — glob broken?")
        self.assertGreaterEqual(len(seen_names), 12,
                                "env-read scan saw too few names — parse broken?")
        # the specific names the class is about must be in the scan's view
        for must_see in ("HERMES_BRIDGE_TOKEN", "HERMES_DRY_RUN",
                         "TELEGRAM_BOT_TOKEN"):
            self.assertIn(must_see, seen_names,
                          f"scan lost sight of {must_see} — scope broken?")

    def test_documented_knobs_are_still_read(self):
        """b40/b41 lesson: an exemption nobody uses is a hole, not a pass."""
        read_names = set()
        for p in production_files():
            for key, _d, _l in env_reads(p.read_text(encoding="utf-8",
                                                     errors="replace"), str(p)):
                read_names.add(key)
        dead = [k for k in DOCUMENTED_KNOBS if k not in read_names]
        self.assertEqual(dead, [],
                         f"DOCUMENTED_KNOBS entries with no real reader: {dead}")

    def test_dead_name_replay_is_flagged(self):
        """BEHAVIOURAL proof through the real analyzer: the exact pre-b52
        shapes must be violations, the fixed shapes must be clean. The
        BRIDGE_URL case pins the core decision — an inline default does NOT
        grant immunity, it only makes the dead name silent."""
        universe = _env_doc_keys() | OS_KEYS | set(DOCUMENTED_KNOBS)
        dead_shapes = [
            "import os\nb = os.getenv('BRIDGE_TOKEN')\n",          # no default
            "import os\nU = os.getenv('BRIDGE_URL', 'http://x')\n",  # WITH default
            "import os\nT = os.environ.get('TELEGRAM_TOKEN')\n",   # near-miss name
            "from os import environ\nT = environ['HERMES_BRIDGE_TOKN']\n",
        ]
        for src in dead_shapes:
            bad = [k for k, _d, _l in env_reads(src) if k not in universe]
            self.assertEqual(len(bad), 1, f"not flagged: {src!r} -> {bad}")
        clean_shapes = [
            "import os\nb = os.getenv('HERMES_BRIDGE_TOKEN')\n",
            "import os\nU = os.getenv('HERMES_BRIDGE_URL', 'http://x')\n",
            "import os\ns = os.getenv('HERMES_MAX_SPREAD', '0.60')\n",  # knob
            "import os\nenv = dict(os.environ); p = env.get('PATH')\n",  # dynamic+OS
            "import os\nos.environ['HERMES_SELFCHECK'] = '1'\n",        # WRITE, not read
        ]
        for src in clean_shapes:
            bad = [k for k, _d, _l in env_reads(src) if k not in universe]
            self.assertEqual(bad, [], f"falsely flagged: {src!r} -> {bad}")

    def test_fixed_files_no_longer_read_dead_names(self):
        """The two files this item healed must stay healed (the main tripwire
        covers this too — this names the regression explicitly)."""
        for rel, dead in (("scripts/ab_b55_meta.py", "BRIDGE_TOKEN"),
                          ("scripts/weekly_report.py", "BRIDGE_URL")):
            src = (REPO / rel).read_text(encoding="utf-8")
            names = {k for k, _d, _l in env_reads(src, rel)}
            self.assertNotIn(dead, names, f"{rel} reads dead '{dead}' again")
            self.assertIn("HERMES_BRIDGE_TOKEN" if dead == "BRIDGE_TOKEN"
                          else "HERMES_BRIDGE_URL", names,
                          f"{rel} lost the real bridge env read entirely")

    def test_dotenv_keys_are_documented(self):
        """If a real .env exists on this box, every key in it must appear in
        .env.example — a secret that lives on one machine only is a dead name
        waiting for the next server rebuild (restore follows .env.example)."""
        env = REPO / ".env"
        if not env.exists():
            self.skipTest("no .env on this checkout (clean worktree)")
        doc = _env_doc_keys()
        keys = {l.split("=", 1)[0].strip() for l in
                env.read_text(encoding="utf-8").splitlines()
                if l.strip() and not l.strip().startswith("#") and "=" in l}
        self.assertEqual(sorted(keys - doc), [],
                         ".env keys missing from .env.example (undocumented):")

    # ------------------------------------------------------------------ b61

    def test_documented_keys_have_readers(self):
        """REVERSE liveness (b61): every .env.example key must be READ by
        production code — Python (env_reads) or shell ($KEY expansion). A
        documented knob nobody reads is a stale deploy contract: the fresh
        server sets it and nothing happens."""
        dead = scan_dead_documented_keys()
        self.assertEqual(
            dead, [],
            f".env.example keys with NO production reader: {dead} — wire a "
            "reader or drop the key (and remove it from .env too, else the "
            "drift test above goes RED)")

    def test_git_token_file_is_wired_into_git_sync(self):
        """The b61 deliverable named concretely: git_sync.sh must honor
        GIT_TOKEN_FILE (not hardcode .git_token), and the fallback default
        must keep the old path so behaviour is unchanged when unset."""
        src = (REPO / "scripts" / "git_sync.sh").read_text(encoding="utf-8")
        self.assertIn("${GIT_TOKEN_FILE:-.git_token}", src,
                      "git_sync.sh no longer honors GIT_TOKEN_FILE with the "
                      ".git_token fallback")
        self.assertIn("GIT_TOKEN_FILE", _env_doc_keys(),
                      "key dropped from .env.example but still wired — "
                      "reverse the git_sync change too or re-document it")

    def test_reverse_scan_is_not_vacuous(self):
        """The reader map must actually see the keys it certifies alive:
        a broken glob/regex that finds NO readers would pass the dead-key
        test only if the doc list were empty — pin both floors, and pin
        GIT_TOKEN_FILE's reader by name (the shell half of the scan is the
        new machinery; a Python-only scan was the blind spot b61 fixes)."""
        readers = documented_key_readers()
        self.assertGreaterEqual(len(readers), 10,
                                ".env.example shrank unexpectedly — is the "
                                "doc parser broken?")
        self.assertGreaterEqual(sum(1 for f in readers.values() if f), 10,
                                "reader map found almost nothing — scan broken")
        self.assertIn("scripts/git_sync.sh", readers["GIT_TOKEN_FILE"],
                      "GIT_TOKEN_FILE must be read by git_sync.sh")
        self.assertTrue(all(f.endswith(".sh") for f in readers["GIT_TOKEN_FILE"]),
                        "GIT_TOKEN_FILE liveness must come from the SHELL scan "
                        "(a Python-only scan was the b61 blind spot)")

    def test_external_allowlist_is_still_used(self):
        """b40 lesson on the reverse side: an allowlist entry that exempts a
        key nobody could otherwise see is dead weight — every entry must
        name a real .env.example key."""
        doc = _env_doc_keys()
        stale = sorted(set(EXTERNAL_READERS) - doc)
        self.assertEqual(stale, [],
                         f"EXTERNAL_READERS entries not in .env.example: {stale}")

    def test_dead_documented_key_replay_is_flagged(self):
        """BEHAVIOURAL proof the reverse scan bites: a key that appears in
        .env.example but in no reader source must be flagged; adding a shell
        reader heals it. Replayed through the REAL functions by temporarily
        injecting a fake key into the doc parser's output."""
        import sys as _sys
        mod = _sys.modules[__name__]  # the instance discovery actually ran
        orig = mod._env_doc_keys
        try:
            mod._env_doc_keys = lambda: orig() | {"BOGUS_UNREAD_KEY",
                                                  "HERMES_BRIDGE_TOKEN"}
            dead = scan_dead_documented_keys()
            self.assertIn("BOGUS_UNREAD_KEY", dead,
                          "reverse scan passed a key with zero readers")
            self.assertNotIn("HERMES_BRIDGE_TOKEN", dead,
                             "reverse scan flagged a key Python clearly reads")
            # shell reader heals it: pretend a .sh references the key
            orig_shell = mod.production_shell_files
            mod.production_shell_files = lambda: orig_shell() + [
                type("P", (), {
                    "read_text": lambda self=None, **k: 'X="${BOGUS_UNREAD_KEY:-y}"',
                    "relative_to": lambda self, o: "scripts/fake.sh"})()]
            self.assertNotIn("BOGUS_UNREAD_KEY", scan_dead_documented_keys(),
                             "shell reader did not heal the key")
        finally:
            mod._env_doc_keys = orig
            mod.production_shell_files = orig_shell


if __name__ == "__main__":
    unittest.main()
