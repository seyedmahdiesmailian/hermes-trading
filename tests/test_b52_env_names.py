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

b62 adds the THIRD failure shape neither direction could see: an
undocumented-but-exempted KNOB whose inline default duplicates the VALUE of
a documented key — two names, one fact. WIN_HOST (knob, default
'192.168.10.51') shadowed HERMES_WIN_IP (.env.example): a bridge host
change moved the trading path while the daily off-box backup silently kept
pushing to the OLD IP, because the knob's own default won and the liveness
test only asked "does anyone read WIN_HOST" — yes, its own default. Fix:
offsite_backup resolves WIN_HOST = explicit override > HERMES_WIN_IP >
last-known default; tripwire: scan_knob_default_shadows() must stay empty,
with a behavioural replay of the exact pre-b62 shape through the real
analyzer.

b63 closes the LAST shape in this family: TWO DOCUMENTED keys encoding one
fact. .env.example sets HERMES_WIN_IP=192.168.10.51 AND
HERMES_BRIDGE_URL=http://192.168.10.51:5050 — the same host written twice.
bridge_client's precedence is BRIDGE_URL-wins-when-set, so an operator who
moves the bridge and updates only HERMES_WIN_IP keeps trading against the
OLD host. The b62 knob-scope scan deliberately cannot see this
(documented↔documented value sharing can be legitimate — e.g. the two
Telegram chat ids both point at the ops chat), so b63 adds a TARGETED
check: parse_host_drift() compares the host inside HERMES_BRIDGE_URL's
value against HERMES_WIN_IP, in .env.example and in the real .env when
present (skipped in clean worktrees); on mismatch the failure names the
precedence that makes it silent. Plus a consumer-side tripwire
(scan_literal_bridge_url_defaults): a production read of
HERMES_BRIDGE_URL may not carry ANY inline literal default — the default
must DERIVE from HERMES_WIN_IP (bridge_client parity) or be absent, else a
missing key silently pins the old URL (the exact weekly_report shape b52
healed the NAME of but left the VALUE duplicated).
"""
from __future__ import annotations

import ast
import os
import re
import subprocess
import sys
import unittest
from pathlib import Path
from urllib.parse import urlparse

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
    "HERMES_STALE_WORKTREE_AFTER": "b91 orphan-worktree sweep age budget, default = outer timeout + slack (head_verify)",
    # HERMES_B50_NESTED is deliberately NOT listed: production (head_verify)
    # only WRITES it into the child env; the sole reader is a test file, which
    # is out of scope. The liveness test below would (rightly) reject it.
    "HERMES_MAX_SPREAD": "live entry spread gate tunable, default 0.60 (hermes_runtime, spread-gate item)",
    "WIN_HOST": "backup target host override; falls back to documented HERMES_WIN_IP, last-resort default = the only bridge (offsite_backup, b62)",
    "WIN_BACKUP_DIR": "backup dir on Windows, default C:\\HermesBackups (offsite_backup)",
    "HERMES_LAN_IP": "local IP for the WinRM pull URL, default = this box (offsite_backup)",
    "B77_PREFLIGHT_OUT": "b77 pre-flight OUTPUT-FILE redirect (state only, never code) so tests can regenerate the ledger into a temp dir (scripts/b77_decay_preflight.py, b48)",
    "B79_PREFLIGHT_OUT": "b79 fire-rate pre-flight OUTPUT-FILE redirect (state only, never code) so tests can regenerate the ledger into a temp dir (scripts/b79_fire_rate_preflight.py, b48)",
    "B157_OUT": "b157 window-funnel OUTPUT-FILE redirect (state only, never code) so each measured leg writes its own ledger (scripts/b157_window_funnel.py, same shape as B77/B79, b48)",
    "B160_OUT": "b160 reanchor-symmetry A/B OUTPUT-FILE redirect (state only, never code) so each measured leg writes its own ledger (scripts/b160_reanchor_symmetry_ab.py, same shape as B157_OUT; registration landed in b161 — b160 shipped the knob unregistered and its run predated this tripwire catching scripts/)",
    "B163_OUT": "b163 plan-age-census OUTPUT-FILE redirect (state only, never code) so tests can regenerate the ledger into a temp dir (scripts/b163_plan_age_census.py, same shape as B160_OUT; registered in the SAME run that shipped the knob, per b162's rule)",
    "B198_OUT": "b198 reassess-flip-census ledger redirect (state only, never code) so a test can re-run the census into a temp dir (scripts/b198_reassess_flip_census.py, same shape as B163_OUT; registered the run b52 caught it unregistered)",
    "B198_LOG": "b198 reassess-flip-census INPUT-log redirect (read-only source, the rolling reassessment CSV) so a test can replay the census on a frozen fixture instead of the mutating live log (scripts/b198_reassess_flip_census.py)",
    "HERMES_SIGNAL_PENDING_DISABLE": "b71 kill-switch for signal LIMIT parking: '1' disables, default off = enabled (engines/signal_pending.py)",
    "HERMES_PENDING_TTL_MIN": "b70 pending-order lifetime in minutes, default 240, engines/signal_pending.py",
    "HERMES_PENDING_MAX": "b70 max simultaneous parked signal limits, default 2, engines/signal_pending.py",
}


def _env_doc_keys() -> set[str]:
    """Keys declared in .env.example (tracked deploy contract). Names only —
    the b52 universe check never requires .env to exist; the b62 shadow
    check compares against _env_doc_values() below."""
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
    return [(key, has_default, node.lineno)
            for key, has_default, _lit, node in _env_read_nodes(src, name)[1]]


def env_reads_with_literal_defaults(src: str,
                                    name: str = "<memory>"
                                    ) -> list[tuple[str, str | None, int]]:
    """(key, literal_default_or_None, lineno) — the inline default kept as a
    VALUE when it is a plain string constant (None for no default OR a
    computed default like an f-string). b62's shadow check needs the value,
    not just the presence flag."""
    return [(key, lit, node.lineno)
            for key, _hd, lit, node in _env_read_nodes(src, name)[1]]


def _env_read_nodes(src: str, name: str = "<memory>"):
    """Shared walker: (key, has_default_arg, literal_default, node)."""
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

    reads = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) \
                and n.func.attr in ("getenv", "get"):
            base = n.func.value
            ok = (isinstance(base, ast.Name) and base.id in ({"os"} | bare_environ)) \
                or is_env_base(base)
            if ok and n.args and isinstance(n.args[0], ast.Constant) \
                    and isinstance(n.args[0].value, str):
                lit = None
                if len(n.args) > 1 and isinstance(n.args[1], ast.Constant) \
                        and isinstance(n.args[1].value, str):
                    lit = n.args[1].value
                reads.append((n.args[0].value, len(n.args) > 1, lit, n))
        elif isinstance(n, ast.Subscript) and isinstance(n.ctx, ast.Load) \
                and isinstance(n.slice, ast.Constant) \
                and isinstance(n.slice.value, str) and is_env_base(n.value):
            reads.append((n.slice.value, False, None, n))
    return tree, reads


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


# ---------------------------------------------------------------------------
# b62 — knob defaults that shadow a documented key's VALUE.
# The b52 universe check asks "does this NAME exist"; b61's reverse check
# asks "does this documented NAME have a reader". Neither sees the THIRD
# failure shape: an UNdocumented knob (legal in DOCUMENTED_KNOBS, invisible
# to the reverse scan) whose inline default duplicates the VALUE of a
# documented key — a second name for one fact. Measured 2026-09-02:
# WIN_HOST default '192.168.10.51' == HERMES_WIN_IP's value; a bridge host
# change moved the trading path while the daily off-box backup silently kept
# pushing to the OLD IP (the knob's own default won, no error anywhere).
# The knob's liveness test could never catch it: "does anyone read WIN_HOST?"
# — yes, its own default.
#
# RULE: a DOCUMENTED_KNOBS read whose literal default equals the
# .env.example VALUE of a DIFFERENT documented key is a shadow. (Scope is
# knobs only: two documented keys may legitimately share a value — e.g.
# TELEGRAM_CHAT_ID and AUTOPILOT_REPORT_CHAT_ID both point at the ops chat —
# but an undocumented knob mirroring a documented value is exactly the
# two-names-one-fact trap. Empty defaults ('') are never shadows.)
# ---------------------------------------------------------------------------

def _env_doc_values() -> dict[str, str]:
    """key -> value from .env.example, for the b62 shadow comparison ONLY.
    .env.example is tracked and carries placeholder values (the deploy
    contract); real secrets live in .env, which this never reads."""
    vals = {}
    for line in (REPO / ".env.example").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            if v.strip():
                vals[k.strip()] = v.strip()
    return vals


def knob_shadow_hits(src: str) -> list[dict]:
    """Shadow hits in ONE source (kept per-source so the behavioural replay
    can run the REAL analyzer over synthetic shapes)."""
    doc_vals = _env_doc_values()
    hits = []
    for key, lit, line in env_reads_with_literal_defaults(src):
        if key not in DOCUMENTED_KNOBS or not lit:
            continue
        for doc_key, doc_val in doc_vals.items():
            if doc_key != key and lit == doc_val:
                hits.append({"knob": key, "default": lit,
                             "shadows": doc_key, "line": line})
    return hits


def scan_knob_default_shadows() -> list[dict]:
    hits = []
    for p in production_files():
        src = p.read_text(encoding="utf-8", errors="replace")
        try:
            file_hits = knob_shadow_hits(src)
        except SyntaxError:
            continue  # the main universe tripwire already reports the file
        for h in file_hits:
            h["file"] = str(p.relative_to(REPO))
        hits.extend(file_hits)
    return hits


# ---------------------------------------------------------------------------
# b63 — two DOCUMENTED keys, one fact: HERMES_WIN_IP vs the host inside
# HERMES_BRIDGE_URL. The b62 shadow scan is knob-scope on purpose (two
# documented keys MAY share a value legitimately — TELEGRAM_CHAT_ID and
# AUTOPILOT_REPORT_CHAT_ID both point at the ops chat), so this family's
# LAST shape needs its own targeted check: the host embedded in the URL
# must equal the host key, in .env.example AND in the real .env. Why it
# matters: bridge_client resolves BRIDGE_URL = getenv('HERMES_BRIDGE_URL',
# derived-from-WIN_IP) — the URL wins whenever it is set, so a half-done
# host migration (IP updated, URL left behind) silently keeps EVERY trading
# consumer on the old host. No runtime error, no log line: the b62
# silent-stale shape one level up.
# ---------------------------------------------------------------------------

def _host_of(url: str) -> str | None:
    """Hostname part of a URL value (port stripped); None if unparseable."""
    try:
        h = urlparse(url).hostname
    except ValueError:
        return None
    return h or None


def parse_host_drift(values: dict[str, str], source: str) -> list[dict]:
    """Drift hits in ONE key->value map: HERMES_BRIDGE_URL's embedded host
    != HERMES_WIN_IP. Missing either key, or an unparseable URL, is NOT a
    drift hit (the b61 reader scan and the doc parser own those shapes);
    this check only fires when both facts are present and DISAGREE."""
    ip = (values.get("HERMES_WIN_IP") or "").strip()
    url = (values.get("HERMES_BRIDGE_URL") or "").strip()
    if not ip or not url:
        return []
    host = _host_of(url)
    if host is None or host == ip:
        return []
    return [{"source": source, "win_ip": ip, "bridge_url": url,
             "url_host": host,
             "why": "HERMES_BRIDGE_URL wins over HERMES_WIN_IP in "
                    "bridge_client (getenv default only when unset) — "
                    "updating just the IP leaves every consumer on the "
                    "URL's host, silently"}]


def env_file_values(path: Path) -> dict[str, str]:
    """key -> value from an env file (same parse shape as _env_doc_values)."""
    vals = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            if v.strip():
                vals[k.strip()] = v.strip()
    return vals


# ---------------------------------------------------------------------------
# b63 consumer side: an inline literal default on a HERMES_BRIDGE_URL read
# duplicates the host a SECOND time inside code. The default must DERIVE
# from HERMES_WIN_IP (bridge_client parity: f"http://{WIN_IP}:5050") or be
# absent — a literal default means a missing/renamed key silently pins the
# old URL, the exact shape b52 healed the NAME of in weekly_report while
# the VALUE stayed duplicated. (Any literal default on the URL read is a
# violation, not just the known IP: a stale literal is the bug, and which
# IP it hardcodes is forensic detail.)
# ---------------------------------------------------------------------------

def literal_bridge_url_defaults(src: str) -> list[dict]:
    return [{"key": key, "default": lit, "line": line}
            for key, lit, line in env_reads_with_literal_defaults(src)
            if key == "HERMES_BRIDGE_URL" and lit is not None]


def scan_literal_bridge_url_defaults() -> list[dict]:
    hits = []
    for p in production_files():
        src = p.read_text(encoding="utf-8", errors="replace")
        try:
            file_hits = literal_bridge_url_defaults(src)
        except SyntaxError:
            continue  # the main universe tripwire already reports the file
        for h in file_hits:
            h["file"] = str(p.relative_to(REPO))
        hits.extend(file_hits)
    return hits


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

    # ------------------------------------------------------------------ b62

    def test_no_knob_default_shadows_a_documented_value(self):
        """MAIN TRIPWIRE (b62): no DOCUMENTED_KNOBS read may carry an inline
        literal default equal to the .env.example VALUE of a different
        documented key — that is two names for one fact, and the knob's own
        default silently wins when the documented key changes (the WIN_HOST
        vs HERMES_WIN_IP shape the b61 audit found)."""
        hits = scan_knob_default_shadows()
        self.assertEqual(
            hits, [],
            f"knob defaults shadowing documented values — the documented key "
            f"can change while these readers silently keep the old value: {hits}")

    def test_offsite_backup_follows_the_documented_host(self):
        """The b62 deliverable named concretely: WIN_HOST must fall back to
        HERMES_WIN_IP (explicit override still possible), not carry its own
        copy of the IP as a first-resort default."""
        src = (REPO / "scripts" / "offsite_backup.py").read_text(encoding="utf-8")
        self.assertRegex(
            src, r"os\.getenv\(['\"]WIN_HOST['\"]\)\s*or\s*os\.getenv\(['\"]HERMES_WIN_IP['\"]",
            "offsite_backup no longer chains WIN_HOST -> HERMES_WIN_IP (b62)")
        self.assertNotIn("os.getenv('WIN_HOST', ", src,
                         "WIN_HOST regained a standalone inline default — "
                         "the exact shadow shape b62 exists to kill")
        # the shadow scan must see the read itself (chain form, no literal)
        self.assertIn("WIN_HOST", {k for k, _d, _l in env_reads(src, "offsite_backup.py")})

    def test_win_host_resolution_is_behavioural(self):
        """Not just source text: run the REAL module resolution in a fresh
        subprocess (env_loader never overrides an existing env var, so the
        injected values win over .env) and check the precedence:
        explicit WIN_HOST > documented HERMES_WIN_IP > last-known default."""
        script = ("import sys; sys.path.insert(0, 'scripts');"
                  "import offsite_backup as o; print(o.WIN_HOST)")
        base_env = {k: v for k, v in os.environ.items() if k not in
                    ("WIN_HOST", "HERMES_WIN_IP")}
        cases = [
            ({"HERMES_WIN_IP": "10.0.0.9"}, "10.0.0.9",
             "documented HERMES_WIN_IP must drive the backup host"),
            ({"WIN_HOST": "10.0.0.5", "HERMES_WIN_IP": "10.0.0.9"}, "10.0.0.5",
             "explicit WIN_HOST override must still win"),
            ({}, "192.168.10.51",
             "nothing set -> last-known default (or .env's HERMES_WIN_IP)"),
        ]
        for inject, expect, why in cases:
            r = subprocess.run([sys.executable, "-c", script], cwd=str(REPO),
                               env={**base_env, **inject},
                               capture_output=True, text=True, timeout=60)
            self.assertEqual(r.returncode, 0, f"import failed: {r.stderr[:300]}")
            self.assertEqual(r.stdout.strip(), expect, why)

    def test_knob_shadow_replay_is_flagged(self):
        """BEHAVIOURAL proof through the REAL analyzer: the exact pre-b62
        shape must fire, the fixed shape must be clean, and a knob default
        that matches NO documented value stays clean (no false-positive
        drift toward 'no knob may have any default')."""
        pre_b62 = ("import os\n"
                   "WIN_HOST = os.getenv('WIN_HOST', '192.168.10.51')\n")
        hits = knob_shadow_hits(pre_b62)
        self.assertEqual(len(hits), 1, f"pre-b62 shape not flagged: {hits}")
        self.assertEqual(hits[0]["knob"], "WIN_HOST")
        self.assertEqual(hits[0]["shadows"], "HERMES_WIN_IP")
        healed = ("import os\n"
                  "WIN_HOST = (os.getenv('WIN_HOST')\n"
                  "            or os.getenv('HERMES_WIN_IP', '192.168.10.51'))\n")
        self.assertEqual(knob_shadow_hits(healed), [],
                         "fixed chain falsely flagged")
        innocent = "import os\nS = float(os.getenv('HERMES_MAX_SPREAD', '0.60'))\n"
        self.assertEqual(knob_shadow_hits(innocent), [],
                         "knob default unrelated to any documented value flagged")

    def test_shadow_scan_is_not_vacuous(self):
        """The doc-value parser must actually see the values the shadow rule
        compares against — an empty map would pass every shadow test by
        finding nothing (b41/b48 anti-vacuity lesson)."""
        vals = _env_doc_values()
        self.assertGreaterEqual(len(vals), 8,
                                ".env.example values vanished — parser broken?")
        self.assertEqual(vals.get("HERMES_WIN_IP"), "192.168.10.51",
                         "the exact fact b62 is about must be in the map")
        # and the knob universe must be visible to the scan
        self.assertIn("WIN_HOST", DOCUMENTED_KNOBS)

    # ------------------------------------------------------------------ b63

    def test_no_documented_host_drift_in_env_example(self):
        """MAIN TRIPWIRE (b63): the host embedded in HERMES_BRIDGE_URL must
        equal HERMES_WIN_IP in the tracked deploy contract. These two keys
        encode ONE fact; bridge_client lets the URL win whenever it is set,
        so a half-done host migration (IP updated, URL left behind) keeps
        every trading consumer on the OLD host with no error anywhere."""
        hits = parse_host_drift(_env_doc_values(), ".env.example")
        self.assertEqual(hits, [], f".env.example host drift: {hits}")

    def test_no_documented_host_drift_in_real_env(self):
        """The same check against the REAL .env when present — that is where
        drift actually bites (the clean b50 worktree has no .env, so it
        skips there; the .env.example check above always runs)."""
        env = REPO / ".env"
        if not env.exists():
            self.skipTest("no .env on this checkout (clean worktree)")
        hits = parse_host_drift(env_file_values(env), ".env")
        self.assertEqual(
            hits, [],
            ".env documents two different bridge hosts — bridge_client "
            f"follows HERMES_BRIDGE_URL, so HERMES_WIN_IP is a lie: {hits}")

    def test_no_literal_bridge_url_default_in_production(self):
        """Consumer side (b63): no production read of HERMES_BRIDGE_URL may
        carry an inline literal default — the fallback must DERIVE from
        HERMES_WIN_IP (bridge_client parity) or be absent. A literal default
        duplicates the host a third time and silently wins when the key is
        missing (the pre-b63 weekly_report shape)."""
        hits = scan_literal_bridge_url_defaults()
        self.assertEqual(
            hits, [],
            f"HERMES_BRIDGE_URL reads with a literal default: {hits} — "
            "derive from HERMES_WIN_IP instead (bridge_client parity)")

    def test_host_drift_replay_is_flagged(self):
        """BEHAVIOURAL proof through the REAL analyzer: the exact drift
        shape must fire and name the precedence; matching hosts, a missing
        key, and an unparseable URL must stay clean (the check owns ONLY
        the both-present-and-disagree shape)."""
        drifted = parse_host_drift(
            {"HERMES_WIN_IP": "10.0.0.7",
             "HERMES_BRIDGE_URL": "http://192.168.10.51:5050"}, ".env.test")
        self.assertEqual(len(drifted), 1, f"drift not flagged: {drifted}")
        self.assertEqual(drifted[0]["url_host"], "192.168.10.51")
        self.assertIn("HERMES_BRIDGE_URL wins", drifted[0]["why"],
                      "failure must name the precedence that makes it silent")
        clean = [
            {"HERMES_WIN_IP": "10.0.0.7",
             "HERMES_BRIDGE_URL": "http://10.0.0.7:5050"},   # migrated both
            {"HERMES_WIN_IP": "10.0.0.7"},                   # URL unset: derived
            {"HERMES_BRIDGE_URL": "http://10.0.0.7:5050"},   # IP unset: doc check
            {"HERMES_WIN_IP": "10.0.0.7",
             "HERMES_BRIDGE_URL": "not a url"},              # parser owns that
        ]
        for vals in clean:
            self.assertEqual(parse_host_drift(vals, ".env.test"), [],
                             f"falsely flagged: {vals}")

    def test_literal_default_replay_is_flagged(self):
        """BEHAVIOURAL proof of the consumer tripwire: the pre-b63
        weekly_report shape fires; the healed derivation shape and
        bridge_client's f-string default are clean — proving DERIVATION is
        the legal fallback, a literal is not."""
        pre_b63 = ("import os\n"
                   "BRIDGE_URL = os.getenv('HERMES_BRIDGE_URL', "
                   "'http://192.168.10.51:5050')\n")
        hits = literal_bridge_url_defaults(pre_b63)
        self.assertEqual(len(hits), 1, f"pre-b63 shape not flagged: {hits}")
        self.assertEqual(hits[0]["line"], 2)
        healed = ("import os\n"
                  "BRIDGE_URL = (os.getenv('HERMES_BRIDGE_URL')\n"
                  "              or f\"http://{os.getenv('HERMES_WIN_IP', "
                  "'192.168.10.51')}:5050\")\n")
        self.assertEqual(literal_bridge_url_defaults(healed), [],
                         "derived fallback falsely flagged")
        bare = "import os\nBRIDGE_URL = os.getenv('HERMES_BRIDGE_URL')\n"
        self.assertEqual(literal_bridge_url_defaults(bare), [],
                         "no-default read falsely flagged")

    def test_drift_scans_are_not_vacuous(self):
        """Anti-vacuity (b41/b48): the host parser must actually extract
        hosts (a parser returning None for everything passes every drift
        test by finding nothing), and the doc map must carry BOTH keys of
        the fact pair for the check to have anything to compare."""
        self.assertEqual(_host_of("http://192.168.10.51:5050"), "192.168.10.51")
        self.assertEqual(_host_of("https://example.com:8443/x"), "example.com")
        self.assertIsNone(_host_of("not a url"))
        self.assertIsNone(_host_of("http://"))
        vals = _env_doc_values()
        self.assertIn("HERMES_WIN_IP", vals)
        self.assertIn("HERMES_BRIDGE_URL", vals)
        # the pair must be in the scan's view AND agree, or the main
        # tripwire above is certifying nothing
        self.assertEqual(_host_of(vals["HERMES_BRIDGE_URL"]),
                         vals["HERMES_WIN_IP"])
        # and the literal-default scan must see the healed consumers
        files = {str(p.relative_to(REPO)) for p in production_files()}
        self.assertIn("scripts/weekly_report.py", files)
        self.assertIn("bridge_client.py", files)

    def test_healed_consumers_follow_the_documented_host(self):
        """The two live consumers this item healed must stay healed, by
        NAME and by BEHAVIOUR (fresh subprocess, real precedence):
        explicit HERMES_BRIDGE_URL > derived from HERMES_WIN_IP >
        last-known default. The health monitor is the dangerous one — it
        used to read NO env at all while paging ops every 5 minutes."""
        for rel in ("scripts/bridge_health_monitor.py",
                    "scripts/weekly_report.py"):
            src = (REPO / rel).read_text(encoding="utf-8")
            self.assertNotIn("http://192.168.10.51", src,
                             f"{rel} hardcodes a bridge URL again (b63)")
            self.assertIn("HERMES_BRIDGE_URL", src,
                          f"{rel} lost the documented URL read")
            self.assertIn("HERMES_WIN_IP", src,
                          f"{rel} lost the derivation from the host key")
        script = ("import sys; sys.path.insert(0, 'scripts');"
                  "import bridge_health_monitor as m;"
                  "print(' '.join(m.bridge_urls()))")
        base_env = {k: v for k, v in os.environ.items()
                    if k not in ("HERMES_BRIDGE_URL", "HERMES_WIN_IP")}
        cases = [
            ({"HERMES_WIN_IP": "10.0.0.9"},
             "http://10.0.0.9:5050/health http://10.0.0.9:5050/",
             "documented HERMES_WIN_IP must drive the watchdog (derived)"),
            ({"HERMES_BRIDGE_URL": "http://10.0.0.5:6060",
              "HERMES_WIN_IP": "10.0.0.9"},
             "http://10.0.0.5:6060/health http://10.0.0.5:6060/",
             "explicit HERMES_BRIDGE_URL must win (bridge_client parity)"),
            ({},
             "http://192.168.10.51:5050/health http://192.168.10.51:5050/",
             "nothing set -> last-known default (or .env's values)"),
        ]
        for inject, expect, why in cases:
            r = subprocess.run([sys.executable, "-c", script], cwd=str(REPO),
                               env={**base_env, **inject},
                               capture_output=True, text=True, timeout=60)
            self.assertEqual(r.returncode, 0, f"import failed: {r.stderr[:300]}")
            self.assertEqual(r.stdout.strip(), expect, why)
        # weekly_report resolves BRIDGE_URL at module level (import is safe:
        # main() is guarded) — same precedence must hold there.
        wr_script = ("import sys; sys.path.insert(0, 'scripts');"
                     "import weekly_report as w; print(w.BRIDGE_URL)")
        for inject, expect, why in [
            ({"HERMES_WIN_IP": "10.0.0.9"}, "http://10.0.0.9:5050",
             "weekly_report must derive from the documented host"),
            ({"HERMES_BRIDGE_URL": "http://10.0.0.5:6060"},
             "http://10.0.0.5:6060",
             "explicit HERMES_BRIDGE_URL must win in weekly_report"),
        ]:
            r = subprocess.run([sys.executable, "-c", wr_script],
                               cwd=str(REPO),
                               env={**base_env, "HERMES_BRIDGE_URL": "",
                                    "HERMES_WIN_IP": "", **inject},
                               capture_output=True, text=True, timeout=60)
            self.assertEqual(r.returncode, 0, f"import failed: {r.stderr[:300]}")
            self.assertEqual(r.stdout.strip(), expect, why)


if __name__ == "__main__":
    unittest.main()
