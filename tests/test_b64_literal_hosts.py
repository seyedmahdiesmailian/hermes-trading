"""b64 — hardcoded HOST literals: the shape every env-read scan is blind to.

Why this file exists (found by the b63 audit): b52 (does the NAME exist),
b61 (does the documented NAME have a reader), b62 (does a knob default
shadow a documented VALUE) and b63 (do two documented keys encode one host)
all work by looking at env READS. A file that never reads env is invisible
to every one of them — and that is exactly what the b63 audit found in
scripts/bridge_health_monitor.py: the watchdog that pages ops when the
bridge dies had the bridge URL hardcoded in two module-level literals and
read NO env at all. b63 healed that one file; the same shape still sat in
the probe/deploy scripts (hardcoded 192.168.10.51 in winrm.Session(...) and
in http://... URL strings).

RULE enforced mechanically (AST + line scan, same family as b41/b42/b44/
b48/b52): no production file (root/scripts/engines/notifier, .py AND .sh —
b44 lesson: a .py-only scan was blind to the untracked .sh that carried the
verifier itself) may contain a literal that IDENTIFIES ONE OF OUR OWN
MACHINES unless it sits on the allowlist with a written reason.

What counts as "one of our own machines" (the sensitive-host set), derived
from the deploy contract rather than from a hand-maintained list:
  1. any RFC1918 (private/LAN) IPv4 literal — private space is by
     definition our infrastructure, and it is the address that MOVES when a
     box is rebuilt or the bridge is relocated;
  2. any host that appears in a .env.example VALUE — either as an IP, as
     the host inside a URL value (HERMES_BRIDGE_URL), or as the value of a
     *_IP / *_HOST key (so a future named host is covered too).
Public service hosts (api.telegram.org, nfs.faireconomy.media,
economic-calendar.tradingview.com) are NOT in the set: there is no env key
for them and nothing to drift against — hardcoding the canonical endpoint
of a public API is not the bug class. Loopback (127.x) and the bind-all
wildcard (0.0.0.0) are excluded by rule, not by allowlist: they are not the
identity of a remote machine (the probe scripts' http://127.0.0.1:5050
health checks run ON the Windows box itself, where 127.0.0.1 is correct and
must NOT be replaced by HERMES_WIN_IP).

Docstrings and shell comments are exempt: the bug is a host being RESOLVED
from a literal, not a sentence mentioning one.

THE ALLOWLIST is for justified last-resort defaults only — the ONE place a
host may legitimately be written down is the fallback of a chain that
prefers the documented key (bridge_client's WIN_IP, offsite_backup's
WIN_HOST chain, the b63 bridge_urls()/weekly_report derivations, the b64
healed _deploy_bridge chain). Every entry carries a written reason and is
LIVENESS-CHECKED (b40/b41/b61 lesson: an exemption that matches no real hit
is a hole, not a pass).

DECISIONS on the five probe/deploy scripts the b63 audit named:
  * scripts/_check_bridge.py — HEALED onto bridge_client.BridgeClient. It is
    NOT a dead one-off: docs/DEPLOY.md step 5 tells the operator to run it
    as the bridge smoke test on a fresh server, so it must follow the
    documented host. The rewrite also deletes a second copy of the
    precedence logic (one canonical resolver instead of two).
  * scripts/_deploy_bridge.py — HEALED with the offsite_backup chain
    (explicit WIN_HOST > documented HERMES_WIN_IP > last-known default) and
    WIN_USER from .env. Also documented in DEPLOY.md as the bridge redeploy
    tool, so it is a live deploy path that used to pin the old box.
  * scripts/_probe_win.py, scripts/_check_bridge_patch.py,
    scripts/_patch_bridge_position_id.py — MOVED to
    legacy_removed/scripts_old/. Dead one-off surgery scripts from the b44
    incident (patch the live bridge for position_id, disable the MT5Trader
    scheduled task). They are not referenced by cron, docs or tests; two of
    them MUTATE the Windows box, so keeping them out of the production tree
    is a safety gain, not just tidiness. The item's own rule: "probes are
    dead one-offs — healing them is optional, hiding them from the scan is
    not" — they are not hidden, they are retired, and any NEW probe that
    hardcodes a host still fails this scan.

Pinned here:
  * the real repo is violation-free (scan + allowlist, both languages);
  * anti-vacuity: the sensitive-host derivation must be non-empty and must
    contain the documented bridge host, the scan must see a floor of files,
    and it must actually FIND the known literals (a scan that saw nothing
    would pass every test above);
  * allowlist liveness + file existence (no dead exemption, no stale path);
  * BEHAVIOURAL replays through the REAL analyzer: the exact pre-b64 shapes
    (the old _check_bridge URL string, the old winrm.Session literal) fire;
    private-IP, URL-host, documented-non-IP-hostname and shell shapes fire;
    public hosts, loopback, bind-all, docstrings and comments stay clean;
  * the healed consumers resolve by BEHAVIOUR (fresh subprocess, real
    bridge_client precedence), never by hitting the network.
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
sys.path.insert(0, str(REPO / "tests"))

from test_b52_env_names import _env_doc_values  # one shared .env.example parser

# Same production scope as b52, plus shell (b44 lesson: .sh carries real
# machinery — verify_head.sh, git_sync.sh — and is never "imported").
PRODUCTION_PY_GLOBS = ("*.py", "scripts/*.py", "engines/*.py", "notifier/*.py")
PRODUCTION_SH_GLOBS = ("*.sh", "scripts/*.sh")

# --------------------------------------------------------------------------
# THE ALLOWLIST — justified last-resort defaults, one entry per (file, host).
# --------------------------------------------------------------------------
# WP2 (2026-09-18): the five chain-tail literals that lived in
# bridge_client.py, scripts/bridge_health_monitor.py, scripts/offsite_backup.py
# and scripts/weekly_report.py are now derived from the ONE canonical holder
# below (engines.config). Their allowlist entries were dropped WITH the
# literals (b40 rule: a dead exemption is a silent hole, and the liveness
# check in test_scan_actually_sees_the_literals_it_certifies enforces it).
# Exempted surface shrank 7 files -> 4; the scan still pins every remaining
# literal by (file, host).
LITERAL_HOST_ALLOWLIST: dict[str, dict[str, str]] = {
    "engines/config.py": {
        "192.168.10.51":
            "WP2: the ONE canonical last-resort bridge host (DEFAULT_WIN_IP). "
            "Every consumer chain prefers the documented key first "
            "(HERMES_BRIDGE_URL > HERMES_WIN_IP > this); the literal only "
            "bites on a box with no .env at all, exactly the b63/b64 design",
        "192.168.10.18":
            "WP2: DEFAULT_LAN_IP = THIS Linux box's own address as seen by "
            "the Windows VM (offsite_backup tarball-pull URL tail); moved "
            "here verbatim from offsite_backup.py, same chain shape",
    },
    "scripts/_deploy_pending_bridge.py": {
        "192.168.10.51":
            "b71 one-off deploy helper, same chain shape as offsite_backup: "
            "WIN_HOST = getenv('WIN_HOST') or getenv('HERMES_WIN_IP', <this>) "
            "— documented key wins; literal is the last-resort tail for the "
            "WinRM target of the /api/pending bridge deploy",
    },
    "scripts/_deploy_bridge.py": {
        "192.168.10.51":
            "b64 heal: same offsite_backup chain (WIN_HOST > HERMES_WIN_IP > "
            "<this>) for the documented bridge-redeploy tool — was a bare "
            "winrm.Session('192.168.10.51') with NO env read at all",
    },
    "scripts/autopilot.sh": {
        "192.168.10.51":
            "prose inside the agent PROMPT ('never touch anything on "
            "192.168.10.51') — an instruction naming the forbidden box, not a "
            "host resolution; no shell script in this repo resolves a host "
            "from a literal (verified by the scan's own hit list)",
    },
}

# The three retired probes must stay retired (pins the b64 decision).
RETIRED_PROBES = ("scripts/_probe_win.py",
                  "scripts/_check_bridge_patch.py",
                  "scripts/_patch_bridge_position_id.py")
RETIRE_DIR = "legacy_removed/scripts_old"


# --------------------------------------------------------------------------
# Host extraction primitives
# --------------------------------------------------------------------------
_IPV4_RE = re.compile(r"(?<![\w.])(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})"
                      r"(?!\w)(?!\.\d)")
_URL_RE = re.compile(r"https?://([^/\s'\"<>()]+)")


def _valid_ipv4(s: str) -> bool:
    parts = s.split(".")
    return len(parts) == 4 and all(p.isdigit() and int(p) <= 255 for p in parts)


def is_private_ipv4(ip: str) -> bool:
    """RFC1918 — our own LAN space, the address that moves with a rebuild."""
    o = [int(p) for p in ip.split(".")]
    return (o[0] == 10
            or (o[0] == 172 and 16 <= o[1] <= 31)
            or (o[0] == 192 and o[1] == 168))


def is_non_host_literal(ip: str) -> bool:
    """Not the identity of a remote machine: bind-all wildcard or loopback.

    The probe scripts health-check the bridge at http://127.0.0.1:5050 from
    INSIDE the Windows box — there 127.0.0.1 is correct and replacing it with
    HERMES_WIN_IP would break it. Exempt by rule, not by allowlist.
    """
    return ip == "0.0.0.0" or ip.startswith("127.")


def ipv4_literals(s: str) -> list[str]:
    return [m for m in _IPV4_RE.findall(s) if _valid_ipv4(m)]


def _authority_host(authority: str) -> str | None:
    """host from a URL authority: strips userinfo and port, keeps IPv6."""
    if "@" in authority:
        authority = authority.rsplit("@", 1)[1]
    if authority.startswith("["):                      # IPv6 literal
        return authority.split("]")[0] + "]"
    return authority.split(":")[0] or None


def url_hosts(s: str) -> list[str]:
    out = []
    for authority in _URL_RE.findall(s):
        h = _authority_host(authority)
        if h:
            out.append(h)
    return out


def documented_hosts() -> dict[str, str]:
    """host -> which documented key states it. Derived from .env.example so
    the sensitive set follows the deploy contract instead of a hand-kept
    list: an operator who documents HERMES_BRIDGE_HOST=hermes-box.local gets
    that hostname protected automatically."""
    hosts: dict[str, str] = {}
    for key, val in _env_doc_values().items():
        v = val.strip().strip("'\"")
        if not v:
            continue
        for ip in ipv4_literals(v):
            hosts.setdefault(ip, key)
        for h in url_hosts(v):
            hosts.setdefault(h, key)
        if (key.endswith("_IP") or key.endswith("_HOST")) and not re.search(
                r"\s", v):
            hosts.setdefault(v, key)
    return hosts


# --------------------------------------------------------------------------
# Source scanners
# --------------------------------------------------------------------------
def _docstring_nodes(tree: ast.AST) -> set[int]:
    """ids of docstring Constant nodes (module/class/function) — prose, not
    resolution, so mentioning an IP in a docstring is not a violation."""
    skip = set()
    holders = [tree] + [n for n in ast.walk(tree) if isinstance(
        n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))]
    for node in holders:
        body = getattr(node, "body", None)
        if body and isinstance(body[0], ast.Expr):
            val = body[0].value
            if isinstance(val, ast.Constant) and isinstance(val.value, str):
                skip.add(id(val))
    return skip


def python_string_literals(src: str, name: str) -> list[tuple[str, int]]:
    tree = ast.parse(src, filename=name)
    skip = _docstring_nodes(tree)
    return [(n.value, n.lineno) for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)
            and id(n) not in skip]


def _hits_in(strings: list[tuple[str, int]],
             doc_hosts: dict[str, str]) -> list[dict]:
    """(host, line, kind, why) for every literal that identifies our own
    machine. Deduped per (line, host) — an IP inside a URL is ONE fact."""
    found: dict[tuple[int, str], dict] = {}
    for s, line in strings:
        # (1) every IPv4 literal, wherever it sits (bare or inside a URL)
        for ip in ipv4_literals(s):
            if is_non_host_literal(ip):
                continue
            if is_private_ipv4(ip):
                kind = "private IPv4 literal"
                why = ("RFC1918 address is our own infrastructure — it "
                       "changes on a rebuild/relocation and must resolve "
                       "from HERMES_WIN_IP (or the documented URL key)")
            elif ip in doc_hosts:
                kind = "documented host as IP literal"
                why = f"stated in .env.example by {doc_hosts[ip]}"
            else:
                continue          # a public IP is not one of our machines
            found.setdefault((line, ip), {"host": ip, "line": line,
                                          "kind": kind, "why": why})
        # (2) non-IP URL hosts: only documented ones are ours (a public API
        #     endpoint has no env key to drift against — not this bug class)
        for h in url_hosts(s):
            if _valid_ipv4(h) or h in doc_hosts:
                if _valid_ipv4(h):
                    continue
                found.setdefault((line, h), {
                    "host": h, "line": line,
                    "kind": "documented hostname as URL literal",
                    "why": f"host of documented key {doc_hosts[h]}"})
    return [found[k] for k in sorted(found)]


def literal_host_hits_py(src: str, name: str,
                         doc_hosts: dict[str, str] | None = None) -> list[dict]:
    doc_hosts = documented_hosts() if doc_hosts is None else doc_hosts
    return _hits_in(python_string_literals(src, name), doc_hosts)


def shell_code_lines(src: str) -> list[tuple[str, int]]:
    """Non-comment lines of a shell script (whole-line and trailing comments
    stripped; a # inside quotes on a comment-only line is irrelevant)."""
    out = []
    for i, line in enumerate(src.splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "#" in stripped:                     # trailing comment
            before = re.split(r"\s#", stripped, 1)[0]
            if before.strip():
                out.append((before, i))
            continue
        out.append((stripped, i))
    return out


def literal_host_hits_sh(src: str, name: str,
                         doc_hosts: dict[str, str] | None = None) -> list[dict]:
    doc_hosts = documented_hosts() if doc_hosts is None else doc_hosts
    return _hits_in(shell_code_lines(src), doc_hosts)


# --------------------------------------------------------------------------
# Repo-wide scans
# --------------------------------------------------------------------------
def production_py_files() -> list[Path]:
    files: set[Path] = set()
    for pat in PRODUCTION_PY_GLOBS:
        files.update(REPO.glob(pat))
    return sorted(f for f in files
                  if "__pycache__" not in f.parts and ".git" not in f.parts)


def production_sh_files() -> list[Path]:
    files: set[Path] = set()
    for pat in PRODUCTION_SH_GLOBS:
        files.update(REPO.glob(pat))
    return sorted(f for f in files
                  if "__pycache__" not in f.parts and ".git" not in f.parts)


def all_literal_hits() -> list[dict]:
    doc_hosts = documented_hosts()
    hits = []
    for p in production_py_files():
        rel = str(p.relative_to(REPO))
        try:
            file_hits = literal_host_hits_py(
                p.read_text(encoding="utf-8", errors="replace"), rel, doc_hosts)
        except SyntaxError:
            continue          # b52's universe tripwire already reports it
        for h in file_hits:
            h["file"] = rel
        hits.extend(file_hits)
    for p in production_sh_files():
        rel = str(p.relative_to(REPO))
        file_hits = literal_host_hits_sh(
            p.read_text(encoding="utf-8", errors="replace"), rel, doc_hosts)
        for h in file_hits:
            h["file"] = rel
        hits.extend(file_hits)
    return hits


def scan_literal_hosts() -> list[dict]:
    """Every literal host hit NOT covered by the allowlist, with the reason
    an operator would need to fix it."""
    violations = []
    for h in all_literal_hits():
        reason = LITERAL_HOST_ALLOWLIST.get(h["file"], {}).get(h["host"])
        if reason:
            continue
        violations.append(h)
    return violations


class TestB64LiteralHosts(unittest.TestCase):
    # ---------------------------------------------------------- tripwires

    def test_no_unallowlisted_literal_hosts_in_production(self):
        """MAIN TRIPWIRE: production code must resolve our own hosts from
        env, not write them down. This is the check b52/b61/b62/b63 could
        never make — they all look at env READS, and a file that reads no
        env is invisible to them."""
        v = scan_literal_hosts()
        self.assertEqual(
            v, [],
            "hardcoded host literals outside the allowlist — move the box "
            "and these silently keep the OLD address (the b63 "
            "bridge_health_monitor shape): "
            f"{[(x['file'], x['line'], x['host'], x['kind']) for x in v]}")

    def test_retired_probes_are_out_of_the_production_tree(self):
        """The b64 decision, pinned: the three dead surgery scripts are
        retired, not hidden — they still exist (history preserved) but no
        longer sit in scripts/ where an operator could re-run a box-mutating
        one-off, and no longer need an allowlist exemption."""
        for rel in RETIRED_PROBES:
            self.assertFalse((REPO / rel).exists(),
                             f"{rel} is back in the production tree — either "
                             "heal it to env resolution or re-retire it")
            self.assertTrue((REPO / RETIRE_DIR / Path(rel).name).exists(),
                            f"{Path(rel).name} vanished from {RETIRE_DIR}/ — "
                            "retired code must stay retrievable")

    def test_healed_probes_resolve_through_the_documented_host(self):
        """The two DEPLOY-CONTRACT scripts (docs/DEPLOY.md tells the operator
        to run them on a fresh server) must follow the documented host:
        _check_bridge delegates to bridge_client (one canonical resolver),
        _deploy_bridge uses the b62 chain."""
        cb_src = (REPO / "scripts" / "_check_bridge.py").read_text(encoding="utf-8")
        self.assertIn("BridgeClient", cb_src,
                      "_check_bridge.py no longer resolves the bridge through "
                      "bridge_client (the single canonical resolver)")
        # through the REAL analyzer (docstrings exempt): zero hits means the
        # file needs no allowlist entry at all — it resolves everything
        self.assertEqual(literal_host_hits_py(cb_src, "scripts/_check_bridge.py"),
                         [], "_check_bridge.py has a host literal in CODE (b64)")
        db = (REPO / "scripts" / "_deploy_bridge.py").read_text(encoding="utf-8")
        self.assertRegex(
            db, r"os\.getenv\(['\"]WIN_HOST['\"]\)\s*or\s*os\.getenv\(['\"]HERMES_WIN_IP['\"]",
            "_deploy_bridge.py no longer chains WIN_HOST -> HERMES_WIN_IP "
            "(the b62 shape, on the documented redeploy path)")
        self.assertIn("os.getenv('WIN_USER'", db,
                      "_deploy_bridge.py hardcoded 'Administrator' again")

    def test_check_bridge_inherits_the_documented_precedence(self):
        """BEHAVIOUR, not source text: the resolver _check_bridge now leans
        on must actually follow HERMES_WIN_IP (fresh subprocess, constructor
        only — no network call)."""
        script = ("import bridge_client as b; "
                  "print(b.BridgeClient().url)")
        base_env = {k: v for k, v in os.environ.items()
                    if k not in ("HERMES_BRIDGE_URL", "HERMES_WIN_IP")}
        r = subprocess.run([sys.executable, "-c", script], cwd=str(REPO),
                           env={**base_env, "HERMES_WIN_IP": "10.0.0.44"},
                           capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, f"import failed: {r.stderr[:300]}")
        self.assertEqual(r.stdout.strip(), "http://10.0.0.44:5050",
                         "bridge_client stopped deriving from the documented "
                         "host — every consumer that leans on it is stale")

    # ------------------------------------------------------- anti-vacuity

    def test_sensitive_host_set_is_derived_and_non_empty(self):
        """The scan's target set comes from .env.example, so it must actually
        contain the fact this whole family is about — an empty set would pass
        every test above by finding nothing (b41/b48 lesson)."""
        hosts = documented_hosts()
        self.assertGreaterEqual(len(hosts), 1)
        vals = _env_doc_values()
        self.assertIn(vals["HERMES_WIN_IP"], hosts,
                      "the documented bridge host is not in the sensitive set")
        self.assertEqual(hosts[vals["HERMES_WIN_IP"]], "HERMES_WIN_IP")
        # the URL value's embedded host resolves to the same fact (b63 pair)
        self.assertIn("192.168.10.51", hosts)

    def test_scan_actually_sees_the_literals_it_certifies(self):
        """Anti-vacuity on the other end: the scan must FIND the known
        literals in the real tree (allowlisted or not). If the AST walk or
        the glob broke, scan_literal_hosts() would return [] and the main
        tripwire would certify nothing."""
        hits = all_literal_hits()
        files = {h["file"] for h in hits}
        # WP2 (2026-09-18): floor 5 -> 4 — the centralization DELETED literals
        # (four chain tails folded into engines.config), so a scan that still
        # saw 5 files would be the broken one. Both languages stay pinned.
        self.assertGreaterEqual(len(files), 4,
                                f"literal-host scan saw only {files} — broken?")
        self.assertIn("engines/config.py", files)
        self.assertIn("scripts/_deploy_bridge.py", files)
        self.assertIn("scripts/_deploy_pending_bridge.py", files)
        self.assertIn("scripts/autopilot.sh", files,
                      "the shell half of the scan found nothing — glob broken?")
        kinds = {h["kind"] for h in hits}
        self.assertIn("private IPv4 literal", kinds)
        # every allowlisted (file, host) pair must correspond to a real hit
        by_file: dict[str, set[str]] = {}
        for h in hits:
            by_file.setdefault(h["file"], set()).add(h["host"])
        for rel, hosts in LITERAL_HOST_ALLOWLIST.items():
            self.assertTrue((REPO / rel).exists(),
                            f"allowlist names a file that no longer exists: {rel}")
            for host in hosts:
                self.assertIn(host, by_file.get(rel, set()),
                              f"DEAD EXEMPTION: {rel} no longer contains a "
                              f"literal {host} — drop the allowlist entry "
                              "(b40: an unused exemption is a silent hole)")
        for reason in (r for hosts in LITERAL_HOST_ALLOWLIST.values()
                       for r in hosts.values()):
            self.assertGreaterEqual(len(reason), 40,
                                    "allowlist reason must be a written reason")

    def test_scan_scope_is_wide_enough(self):
        self.assertGreaterEqual(len(production_py_files()), 90,
                                "production .py scope shrank — glob broken?")
        self.assertGreaterEqual(len(production_sh_files()), 4,
                                "production .sh scope shrank — glob broken?")

    # --------------------------------------------------- behavioural replays

    def test_pre_b64_probe_shapes_are_flagged(self):
        """The EXACT lines the b63 audit named, replayed through the real
        analyzer: the hardcoded URL in a probe and the hardcoded host in a
        winrm.Session must both fire."""
        old_check_bridge = ('import urllib.request\n'
                            'def get(ep):\n'
                            '    req = urllib.request.Request(\n'
                            '        f"http://192.168.10.51:5050{ep}", '
                            'headers=H)\n')
        hits = literal_host_hits_py(old_check_bridge, "scripts/_check_bridge.py")
        self.assertEqual([h["host"] for h in hits], ["192.168.10.51"],
                         f"pre-b64 _check_bridge shape not flagged: {hits}")
        old_deploy = ("s = winrm.Session('192.168.10.51',\n"
                      "                  auth=('Administrator', pw))\n")
        hits = literal_host_hits_py(old_deploy, "scripts/_deploy_bridge.py")
        self.assertEqual([h["host"] for h in hits], ["192.168.10.51"],
                         f"pre-b64 winrm.Session shape not flagged: {hits}")
        # and the healed shapes are clean
        healed = ("WIN_HOST = (os.getenv('WIN_HOST')\n"
                  "            or os.getenv('HERMES_WIN_IP'))\n"
                  "s = winrm.Session(WIN_HOST, auth=(WIN_USER, pw))\n")
        self.assertEqual(literal_host_hits_py(healed, "x.py"), [],
                         "healed chain falsely flagged")

    def test_private_ip_and_documented_hostname_both_fire(self):
        """Two independent paths into the sensitive set: RFC1918 by rule,
        and a documented NON-IP hostname by contract. The second one is what
        keeps the scan alive if the lab ever moves to named hosts — replayed
        by injecting a fake documented key, never by editing .env.example."""
        doc = {"hermes-box.local": "HERMES_BRIDGE_HOST"}
        src = 'U = "http://hermes-box.local:5050/health"\n'
        hits = literal_host_hits_py(src, "x.py", doc)
        self.assertEqual(len(hits), 1, f"documented hostname not flagged: {hits}")
        self.assertEqual(hits[0]["kind"], "documented hostname as URL literal")
        # a private IP that is NOT documented still fires (10/8 is ours)
        self.assertEqual(
            [h["host"] for h in literal_host_hits_py(
                "H = '10.1.2.3'\n", "x.py", {})], ["10.1.2.3"])
        # a public, undocumented host never fires
        self.assertEqual(literal_host_hits_py(
            'U = "https://api.telegram.org/bot%s/sendMessage"\n', "x.py", {}), [])
        self.assertEqual(literal_host_hits_py(
            'U = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"\n',
            "x.py", {}), [])

    def test_loopback_bindall_and_prose_are_clean(self):
        """The rule-based exemptions (NOT allowlist entries): loopback and
        the bind-all wildcard are not remote-machine identities, and a
        docstring is prose."""
        self.assertEqual(literal_host_hits_py(
            'H = "http://127.0.0.1:5050/health"\n', "x.py"), [],
            "loopback falsely flagged (the probes health-check FROM the VM)")
        self.assertEqual(literal_host_hits_py(
            "app.run(host='0.0.0.0', port=5050)\n", "x.py"), [],
            "bind-all wildcard falsely flagged")
        doc_only = '"""Restore from C:\\\\HermesBackups on 192.168.10.18."""\nX = 1\n'
        self.assertEqual(literal_host_hits_py(doc_only, "x.py"), [],
                         "docstring prose falsely flagged")
        # ...but the same sentence as CODE fires
        self.assertEqual(
            [h["host"] for h in literal_host_hits_py(
                'X = "192.168.10.18"\n', "x.py")], ["192.168.10.18"])

    def test_shell_shapes_fire_and_comments_stay_clean(self):
        """b44 lesson applied to literals: shell carries real machinery, so
        a hardcoded host in a .sh must fail; a comment naming one must not."""
        hits = literal_host_hits_sh('BRIDGE="http://192.168.10.51:5050"\n',
                                    "scripts/x.sh")
        self.assertEqual([h["host"] for h in hits], ["192.168.10.51"],
                         f"hardcoded host in shell not flagged: {hits}")
        self.assertEqual(literal_host_hits_sh(
            "# the old bridge lived at 192.168.10.51\nX=1\n", "x.sh"), [],
            "shell comment falsely flagged")
        trailing = literal_host_hits_sh(
            'U=http://10.0.0.9:5050   # derived above\n', "x.sh")
        self.assertEqual([h["host"] for h in trailing], ["10.0.0.9"],
                         "a trailing comment must not hide code on the same "
                         "line — the literal still has to fire")

    def test_allowlist_cannot_hide_a_new_file(self):
        """The allowlist is keyed by file, so a NEW script that hardcodes the
        host is a violation even though the same IP is allowlisted elsewhere
        — the exemption buys the ONE canonical default, not the whole repo."""
        hosts = documented_hosts()
        self.assertIn("192.168.10.51", hosts)
        # simulate: a fresh file with the literal is NOT in the allowlist
        fresh = "scripts/_new_probe.py"
        self.assertNotIn(fresh, LITERAL_HOST_ALLOWLIST)
        hits = literal_host_hits_py("B = 'http://192.168.10.51:5050'\n", fresh)
        self.assertEqual(len(hits), 1)
        covered = LITERAL_HOST_ALLOWLIST.get(fresh, {}).get(hits[0]["host"])
        self.assertIsNone(covered,
                          "a new file must not inherit an exemption")


if __name__ == "__main__":
    unittest.main()
