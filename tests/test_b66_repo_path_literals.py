"""b66 — absolute REPO-PATH literals: the b64 bug class one level down.

Why this file exists: b64 pinned hardcoded HOST literals, but the same
"works on this box, silently wrong anywhere else" shape sat in hardcoded
FILESYSTEM paths. A literal '/home/ai/hermes-trading' in production code
either breaks LOUDLY when the repo moves (fine) or — the b46/b48 disease
from the filesystem side — reads/writes the WRONG tree while reporting
success: a digest pointed at an old checkout summarizes stale state, a
verifier pointed at an old checkout stamps OK on the wrong tree, a cron
wrapper pointed at an old checkout runs old code forever.

RULE enforced mechanically (same family as b41/b42/b44/b48/b52/b64): no
production file (root/scripts/engines/notifier, .py AND .sh — b44 lesson:
shell carries real machinery) may contain an absolute path literal whose
repo segment is `hermes-trading` under ANY home directory (/home/<user>/
hermes-trading, /root/hermes-trading, and anything under them) unless it
sits on the allowlist with a written reason.

Docstrings and shell comments are exempt (b64 rule): the bug is a path
being RESOLVED from a literal, not a sentence describing one. Python
comments are invisible to the AST anyway; shell comments are stripped by
the shared b64 line walker.

THE ALLOWLIST is one entry deep: engines/paths.PRODUCTION_ROOT — the ONE
canonical default every state accessor falls back to (documented in the
module itself, liveness-checked here exactly like b40/b64: an exemption
that matches no real hit is a hole, not a pass).

Out of scope by decision: other absolute home-dir paths that are NOT the
repo root — scripts/autopilot.sh's `/home/ai/.local/bin/hermes` fallback
is the AGENT BINARY location behind `command -v hermes`, and the
crontab/systemd files under ops/ are the BOOTSTRAP layer: the one place
the OS must learn where the repo lives (a crontab cannot discover itself).
The scripts they launch now derive everything else from their own
location, so the install path is written down exactly once per layer.

HEALED this item (b39 pattern — Path(__file__)-derived roots):
  * 20 scripts/*.py + notifier/dashboards.py + scripts/autopilot_harvest.py
    (sys.path inserts, load_dotenv targets, data/report caches);
  * engines/paths.py gained repo_root()/repo_file() — the accessor every
    consumer should reach for instead of re-deriving;
  * the four cron-critical .sh (hermes_cron, git_sync, verify_head,
    autopilot) now derive REPO_ROOT from BASH_SOURCE, and the two quoted
    python heredocs inside them receive the root through exported seams
    (HERMES_AUTOPILOT_REPO_ROOT / HERMES_VERIFY_REPO_ROOT) because shell
    expansion cannot reach inside a quoted heredoc;
  * autopilot.sh's agent PROMPT interpolates REPO_ROOT, so a relocated
    repo sends the agent to ITS OWN backlog, not to the old checkout.

Pinned here:
  * the real repo is violation-free (scan + allowlist, both languages);
  * allowlist liveness + file existence (no dead exemption);
  * anti-vacuity: the scan must FIND the known engines/paths.py literal
    (a scan that saw nothing would pass every test above) and must see a
    floor of production files (b64 floors);
  * BEHAVIOURAL replays: the bash derivation idiom resolves from the
    SCRIPT location against a moved throwaway tree; the real PROMPT
    assignment from autopilot.sh is extracted and evaluated in bash with
    REPO_ROOT pointed at a fake root (the interpolated prompt must name
    the fake root and contain no install literal); the real state-stamp
    heredoc is extracted and run against a throwaway git repo (it must
    write its state THERE, proving the seam redirects, not the literal);
  * the healed consumers resolve their root from __file__ (positive
    proof, not just absence of the literal — b50 lesson).
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tests"))

# One shared analyzer family with b64: python_string_literals (AST
# constants, docstrings excluded) and shell_code_lines (comments stripped)
# plus the production file scopes. Re-importing instead of re-implementing
# is deliberate — two copies of the same walker is the bug class this file
# is about, wearing a different hat.
from test_b64_literal_hosts import (  # noqa: E402
    PRODUCTION_PY_GLOBS,
    PRODUCTION_SH_GLOBS,
    production_py_files,
    production_sh_files,
    python_string_literals,
    shell_code_lines,
)

# The install-literal family: the repo directory under ANY home dir, plus
# anything under it. /home/<user>/ catches a user rename; the repo segment
# itself is the fact ("this checkout"), which is what must never be
# repeated outside the canonical default.
REPO_PATH_RE = re.compile(r"(?:/home/[^/\s'\"]+|/root)/hermes-trading(?:/[^\s'\"]*)?")

# --------------------------------------------------------------------------
# THE ALLOWLIST — one entry: the canonical default, with a written reason.
# --------------------------------------------------------------------------
REPO_PATH_ALLOWLIST: dict[str, dict[str, str]] = {
    "engines/paths.py": {
        "/home/ai/hermes-trading":
            "the ONE canonical install default: PRODUCTION_ROOT is the "
            "fallback every state accessor resolves through when neither "
            "$HERMES_DATA_ROOT nor set_data_root() redirects it (b39 "
            "design). Consumers must use repo_root()/repo_file() or the "
            "accessors instead of repeating the literal — pinned by "
            "test_canonical_default_and_accessor.",
    },
}

# Files whose root binding must now derive from __file__ (positive proof of
# the heal, b50 style — absence of the literal alone could mean the scan
# simply missed the file).
HEALED_PY = (
    "scripts/probe_gates.py",
    "scripts/measure_neutral.py",
    "scripts/gen_backtest_report.py",
    "scripts/offsite_backup.py",
    "scripts/autopilot_digest.py",
    "scripts/autopilot_harvest.py",
    "scripts/bridge_health_monitor.py",
    "notifier/dashboards.py",
)
HEALED_SH = (
    "scripts/hermes_cron.sh",
    "scripts/git_sync.sh",
    "scripts/verify_head.sh",
    "scripts/autopilot.sh",
)


# --------------------------------------------------------------------------
# Scanners (thin wrappers over the shared b64 walkers)
# --------------------------------------------------------------------------
def repo_path_hits_py(src: str, name: str) -> list[dict]:
    # sorted by line: ast.walk is BFS, so a constant nested deeper (e.g.
    # inside an f-string's JoinedStr) is yielded after later top-level
    # statements — deterministic order is needed for replay assertions
    hits = [{"file": name, "line": lineno, "literal": s.strip()}
            for s, lineno in python_string_literals(src, name)
            if REPO_PATH_RE.search(s)]
    return sorted(hits, key=lambda h: h["line"])


def repo_path_hits_sh(src: str, name: str) -> list[dict]:
    return [{"file": name, "line": lineno, "literal": line.strip()}
            for line, lineno in shell_code_lines(src)
            if REPO_PATH_RE.search(line)]


def all_repo_path_hits() -> list[dict]:
    hits: list[dict] = []
    for f in production_py_files():
        rel = str(f.relative_to(REPO))
        hits += repo_path_hits_py(f.read_text(encoding="utf-8"), rel)
    for f in production_sh_files():
        rel = str(f.relative_to(REPO))
        hits += repo_path_hits_sh(f.read_text(encoding="utf-8"), rel)
    return hits


def scan_repo_path_literals() -> list[dict]:
    """Violations: hits whose (file, matched install root) is not covered
    by a written allowlist reason. Keyed on the ROOT (/home/x/hermes-trading),
    not the full literal, so '/home/ai/hermes-trading/.env' cannot slip past
    an entry written for the bare root."""
    bad = []
    for h in all_repo_path_hits():
        m = REPO_PATH_RE.search(h["literal"])
        root = m.group(0)
        if root.endswith("/"):
            root = root[:-1]
        # trim to the repo segment itself for the allowlist key
        seg = re.match(r"(?:/home/[^/]+|/root)/hermes-trading", root)
        key = seg.group(0)
        reason = REPO_PATH_ALLOWLIST.get(h["file"], {}).get(key)
        if not reason:
            h = dict(h)
            h["root"] = key
            h["why"] = ("absolute repo-path literal outside the allowlist — "
                        "derive from Path(__file__)/BASH_SOURCE or use "
                        "engines.paths.repo_root()/repo_file()")
            bad.append(h)
    return bad


class TestB66RepoPathLiterals(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # shared scratch dir for the bash-render replays (cheap, per-class)
        cls._tmp = tempfile.TemporaryDirectory()

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def setUp(self):
        self.hits = all_repo_path_hits()

    # ---------------------------------------------------------- main rules

    def test_no_unallowlisted_repo_path_literals_in_production(self):
        bad = scan_repo_path_literals()
        self.assertEqual(
            bad, [],
            "production files resolve the repo from an absolute literal — "
            "a moved repo/second checkout then reads or writes the WRONG "
            "tree while reporting success (b46/b48 from the filesystem "
            "side). Heal to __file__/BASH_SOURCE derivation: "
            + "; ".join(f"{b['file']}:{b['line']}: {b['literal'][:70]}"
                        for b in bad))

    def test_allowlist_entries_are_live(self):
        """b40 rule: an exemption that matches no real hit is a hole."""
        for rel, roots in REPO_PATH_ALLOWLIST.items():
            p = REPO / rel
            self.assertTrue(p.exists(), f"allowlisted file gone: {rel}")
            for root, reason in roots.items():
                self.assertTrue(reason.strip(), f"empty reason for {rel}")
                covered = [h for h in self.hits
                           if h["file"] == rel and root in h["literal"]]
                self.assertTrue(
                    covered,
                    f"DEAD allowlist entry {rel}:{root} — the literal is "
                    "no longer there; remove the exemption (or the scan "
                    "broke, which the floors below would catch)")

    def test_canonical_default_and_accessor(self):
        """engines/paths: the ONE literal stays, and the accessor that
        replaces every other copy of it works from the code location."""
        from engines import paths
        self.assertEqual(str(paths.PRODUCTION_ROOT), "/home/ai/hermes-trading",
                         "the canonical default moved — update the allowlist "
                         "reason AND .env.example expectations deliberately")
        self.assertEqual(paths.repo_root(), REPO,
                         "repo_root() must resolve the tree UNDER TEST from "
                         "__file__ (b50 location-independence), never the "
                         "hardcoded default")
        self.assertEqual(paths.repo_file("data", "ops"), REPO / "data" / "ops")

    # ---------------------------------------------------------- anti-vacuity

    def test_scan_actually_sees_the_literal_it_certifies(self):
        """A scan that found nothing would pass every rule above."""
        self.assertTrue(any(h["file"] == "engines/paths.py" for h in self.hits),
                        "the scan does not even see the ONE known literal — "
                        "it is broken, not the repo clean")

    def test_scan_scope_is_wide_enough(self):
        self.assertGreaterEqual(len(production_py_files()), 90,
                                "production .py scope shrank — glob broken?")
        self.assertGreaterEqual(len(production_sh_files()), 4,
                                "production .sh scope shrank — glob broken?")

    # ------------------------------------------------------------- replays

    def test_pre_b66_shapes_are_flagged(self):
        """The exact shapes this run healed, replayed through the REAL
        analyzer: they must fire, naming the file."""
        py = ("import sys\n"
              "sys.path.insert(0, '/home/ai/hermes-trading')\n"
              "from engines import paths\n")
        hits = repo_path_hits_py(py, "synthetic_probe.py")
        self.assertEqual(len(hits), 1, hits)
        self.assertEqual(hits[0]["line"], 2)

        sh = ("#!/usr/bin/env bash\n"
              "# cd /home/ai/hermes-trading  <- comment, exempt\n"
              "cd /home/ai/hermes-trading || exit 1\n")
        hits = repo_path_hits_sh(sh, "synthetic_cron.sh")
        self.assertEqual(len(hits), 1, hits)
        self.assertEqual(hits[0]["line"], 3)

        # f-strings and subpaths fire too (the constant lives inside a
        # JoinedStr; the AST walker still sees it)
        f = ("root = '/home/ai/hermes-trading'\n"
             "p = f'/home/ai/hermes-trading/reports/x.docx'\n"
             "q = '/home/otheruser/hermes-trading/.env'\n")
        hits = repo_path_hits_py(f, "synthetic_paths.py")
        self.assertEqual([h["line"] for h in hits], [1, 2, 3],
                         "bare root, f-string subpath and a DIFFERENT user's "
                         "checkout must all fire")

    def test_prose_and_comments_stay_clean(self):
        py = ('"""The old bug: Path(\'/home/ai/hermes-trading/data\') at import."""\n'
              "x = 1  # not /home/ai/hermes-trading either\n")
        self.assertEqual(repo_path_hits_py(py, "doc.py"), [])
        sh = "# a relocated /home/ai/hermes-trading used to break this\nx=1\n"
        self.assertEqual(repo_path_hits_sh(sh, "doc.sh"), [])

    def test_allowlist_cannot_hide_a_new_file(self):
        """The allowlist is keyed per-file: engines/paths.py being exempt
        grants nothing to any other file."""
        fresh = repo_path_hits_py(
            "BASE = '/home/ai/hermes-trading'\n", "scripts/new_tool.py")
        self.assertEqual(len(fresh), 1)
        self.assertNotIn("scripts/new_tool.py", REPO_PATH_ALLOWLIST)

    def test_healed_consumers_derive_root_from_code_location(self):
        """Positive proof (b50 lesson): the healed files bind their root to
        __file__, not merely stop containing the literal."""
        for rel in HEALED_PY:
            src = (REPO / rel).read_text(encoding="utf-8")
            self.assertIn("__file__", src,
                          f"{rel} lost its literal but never learned the "
                          "__file__ derivation — the scan may be missing it")
        for rel in HEALED_SH:
            src = (REPO / rel).read_text(encoding="utf-8")
            code = "\n".join(l for l, _ in shell_code_lines(src))
            self.assertIn('SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"',
                          code, f"{rel} must derive its root from its own location")
            self.assertIn('REPO_ROOT="$(dirname "$SCRIPT_DIR")"', code, rel)
            self.assertIn('cd "$REPO_ROOT"', code, rel)

    # --------------------------------------------------- behavioural (bash)

    def test_derivation_idiom_resolves_from_script_location(self):
        """The idiom the four cron scripts now use, replayed for real in a
        MOVED throwaway tree: run from an unrelated cwd, it must print the
        temp repo root — proving location-independence, not just text."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "moved-checkout"
            (root / "scripts").mkdir(parents=True)
            script = root / "scripts" / "idiom.sh"
            src = (REPO / "scripts" / "hermes_cron.sh").read_text(encoding="utf-8")
            lines = [l for l, _ in shell_code_lines(src)]
            idiom = [l for l in lines if "SCRIPT_DIR=" in l
                     or 'REPO_ROOT="$(dirname' in l]
            self.assertEqual(len(idiom), 2, idiom)
            script.write_text("#!/usr/bin/env bash\nset -u\n"
                              + "\n".join(idiom) + "\necho \"$REPO_ROOT\"\n")
            r = subprocess.run(["bash", str(script)], cwd=td,
                               capture_output=True, text=True, timeout=30)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(r.stdout.strip(), str(root),
                             "the derivation resolved to the wrong tree")

    def test_autopilot_prompt_interpolates_repo_root(self):
        """The REAL PROMPT assignment from autopilot.sh, evaluated in bash
        with REPO_ROOT pointed at a fake root: the agent must be sent to
        the fake tree's backlog, and the rendered prompt must carry NO
        install literal (a stale one would send every future run to the
        old checkout — the digest-summarizes-stale-state shape)."""
        src = (REPO / "scripts" / "autopilot.sh").read_text(encoding="utf-8")
        start = src.index("PROMPT='You are")
        end = src.index("why.'\n", start) + len("why.'\n")
        block = src[start:end]
        self.assertIn('\'"$REPO_ROOT"\'', block,
                      "the prompt must interpolate REPO_ROOT (b66)")
        script = Path(self._tmp.name) / "render.sh"
        script.write_text("#!/usr/bin/env bash\nset -u\n"
                          'REPO_ROOT="/tmp/fake-relocated-repo"\n'
                          + block + 'printf "%s" "$PROMPT"\n')
        r = subprocess.run(["bash", str(script)], capture_output=True,
                           text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("/tmp/fake-relocated-repo/data/ops/autopilot_backlog.md",
                      r.stdout, "rendered prompt must name the CALLER's tree")
        self.assertNotIn("/home/ai/hermes-trading", r.stdout,
                         "the rendered prompt still carries the install "
                         "literal — a relocated repo would send the agent "
                         "to the OLD backlog")

    def test_autopilot_state_heredoc_follows_the_env_seam(self):
        """The REAL state-stamp heredoc from autopilot.sh, run against a
        throwaway git repo through HERMES_AUTOPILOT_REPO_ROOT: it must
        write its state INTO the throwaway tree and report the throwaway
        repo's commits — proof the seam redirects, not a leftover literal."""
        src = (REPO / "scripts" / "autopilot.sh").read_text(encoding="utf-8")
        start = src.index("python3 - <<'PY'\nimport json, os")
        end = src.index("\nPY\n", start) + len("\nPY\n")
        body = src[start + len("python3 - <<'PY'\n"):end - len("\nPY\n")]
        self.assertIn("HERMES_AUTOPILOT_REPO_ROOT", body)
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "repo"
            (root / "data" / "ops").mkdir(parents=True)
            env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
                       GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t",
                       HERMES_AUTOPILOT_REPO_ROOT=str(root))
            subprocess.run(["git", "init", "-q", "-b", "master", str(root)],
                           check=True, env=env, capture_output=True)
            (root / "a.txt").write_text("1")
            subprocess.run(["git", "-C", str(root), "add", "-A"], check=True,
                           env=env, capture_output=True)
            subprocess.run(["git", "-C", str(root), "commit", "-qm",
                            "throwaway head"], check=True, env=env,
                           capture_output=True)
            r = subprocess.run([sys.executable, "-c", body], cwd=td, env=env,
                               capture_output=True, text=True, timeout=60)
            self.assertEqual(r.returncode, 0, r.stderr[-400:])
            state = root / "data" / "ops" / "autopilot_state.json"
            self.assertTrue(state.exists(),
                            "the heredoc wrote somewhere else — the seam is "
                            "not what actually resolves the root")
            import json as _json
            data = _json.loads(state.read_text())
            self.assertIn("throwaway head", "\n".join(data["recent_commits"]),
                          "git log ran against the wrong repo")

    def test_verify_head_alert_reads_root_from_exported_seam(self):
        """The BROKEN-path alert heredoc cannot be executed here (it pages
        Telegram), so pin its shape: the root arrives through the exported
        seam and the script exports it; no literal survives in code."""
        src = (REPO / "scripts" / "verify_head.sh").read_text(encoding="utf-8")
        self.assertIn('export HERMES_VERIFY_REPO_ROOT="$REPO_ROOT"', src)
        alert = src[src.index('python3 - "$HEAD" <<\'PY\''):]
        self.assertIn("os.environ['HERMES_VERIFY_REPO_ROOT']", alert)
        for b in repo_path_hits_sh(src, "scripts/verify_head.sh"):
            self.fail(f"verify_head.sh still resolves a literal: {b}")


class TestB66BootstrapBoundary(unittest.TestCase):
    """The deliberate scope line: the install path may live in the
    BOOTSTRAP layer (crontab/systemd — where the OS learns about the repo)
    but the scripts it launches must not repeat it."""

    def test_ops_bootstrap_files_still_document_the_install_path(self):
        """Liveness of the boundary: if these ever lose the path, the
        boundary itself moved and this file's reasoning must be revisited
        (they are outside the scan scope on purpose — a dead scope claim
        is as bad as a dead allowlist)."""
        crons = (REPO / "ops" / "cron" / "crontab.backup.txt").read_text()
        self.assertIn("/home/ai/hermes-trading", crons)
        units = list((REPO / "ops" / "systemd").glob("*.service"))
        self.assertTrue(units, "ops/systemd vanished — update the boundary")
        self.assertTrue(any("/home/ai/hermes-trading" in u.read_text()
                            for u in units))

    def test_agent_binary_fallback_is_out_of_scope_by_rule(self):
        """/home/ai/.local/bin/hermes is the AGENT BINARY behind
        `command -v hermes`, not the repo root — the scan must not fire on
        it (documents why the regex keys on the repo segment, not /home/*)."""
        hits = repo_path_hits_sh(
            'HERMES_BIN="$(command -v hermes || echo /home/ai/.local/bin/hermes)"\n',
            "x.sh")
        self.assertEqual(hits, [])


if __name__ == "__main__":
    unittest.main()
