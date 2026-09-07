#!/usr/bin/env python3
"""b114 — WHICH CODE IS THE LIVE WATCHDOG ACTUALLY RUNNING?

position_daemon.py is a long-lived systemd service (Restart=always). Python
binds its modules at import, so a commit that changes the exit path does NOT
take effect until the process restarts. Nothing in the repo records which
commit a running daemon booted from, so a committed change to the live ladder
can sit unapplied indefinitely and every audit that reads the working tree
will describe behaviour production does not have.

This probe measures the gap WITHOUT touching anything: it reads the process
start time from `ps`, finds the last commit at or before that time, computes
the daemon's transitive import closure, and asks which closure files changed
between that commit and HEAD. Read-only: no signals, no bridge call, no
restart, no order endpoint.

Writes data/ops/daemon_code_drift.json.
"""
from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
from datetime import datetime, timezone

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

OUT = os.path.join(_ROOT, "data", "ops", "daemon_code_drift.json")

# The two long-lived trading processes (systemd services). hermes_master runs
# from cron every 15 min, so it always boots from current code and is NOT a
# drift risk — only the daemons are.
DAEMONS = {
    "position_daemon.py": {"entry": "position_daemon.py",
                           "extra": ["engines/trade_management.py",
                                     "engines/auto_executor.py",
                                     "engines/legacy_guards.py"]},
    "signal_daemon.py": {"entry": "signal_daemon.py",
                         "extra": ["engines/signal_parser.py",
                                   "engines/signal_decision.py",
                                   "engines/signal_listener.py"]},
}


def _git(*args: str) -> str:
    return subprocess.run(["git", "-C", _ROOT, *args],
                          capture_output=True, text=True).stdout.strip()


def process_start_utc(pattern: str) -> datetime | None:
    """Wall-clock start of the running process matching `pattern`, in UTC.
    None when no such process is running (then there is no drift to measure —
    the code runs fresh every boot)."""
    try:
        out = subprocess.run(
            ["ps", "-eo", "lstart=,cmd="], capture_output=True, text=True,
            check=True).stdout
    except Exception:
        return None
    for line in out.splitlines():
        if pattern not in line or "ps -eo" in line:
            continue
        stamp = line[:24].strip()
        try:
            # `ps lstart` prints LOCAL wall-clock time; the naive datetime must
            # be resolved through the host timezone or the boot commit lands
            # hours off (this box is +03:30, so a naive-as-UTC read shifted the
            # whole measurement by 3.5h on the first draft).
            return datetime.strptime(stamp, "%a %b %d %H:%M:%S %Y").astimezone(
                timezone.utc)
        except ValueError:
            continue
    return None


def commit_at_or_before(when: datetime) -> dict:
    sha = _git("log", "-1", "--format=%H", f"--before={when.isoformat()}")
    when_s = _git("log", "-1", "--format=%cI", sha) if sha else ""
    return {"sha": sha or None, "committed_at": when_s or None}


def import_closure(entry: str, extra: list[str]) -> list[str]:
    """Transitive repo-local import closure of one entry module (stdlib and
    third-party names dropped), plus the explicitly listed runtime deps."""
    seen: set[str] = set()
    queue = [entry]
    while queue:
        rel = queue.pop()
        if rel in seen or not os.path.exists(os.path.join(_ROOT, rel)):
            continue
        seen.add(rel)
        try:
            tree = ast.parse(open(os.path.join(_ROOT, rel)).read(),
                             filename=rel)
        except Exception:
            continue
        for node in ast.walk(tree):
            mods: list[str] = []
            if isinstance(node, ast.Import):
                mods = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                if node.level:  # relative import inside a package
                    pkg = os.path.dirname(rel)
                    mods = [os.path.normpath(os.path.join(
                        pkg, *[""] * (node.level - 1), node.module))]
                else:
                    mods = [node.module]
            for m in mods:
                parts = m.split(".")
                cand = os.path.join(*parts) + ".py"
                cand_pkg = os.path.join(*parts, "__init__.py")
                for c in (cand, cand_pkg):
                    if os.path.exists(os.path.join(_ROOT, c)) and c not in seen:
                        queue.append(c)
    for e in extra:
        if os.path.exists(os.path.join(_ROOT, e)):
            seen.add(e)
    return sorted(seen)


def changed_files(sha: str, paths: list[str],
                  ref: str = "HEAD") -> list[dict]:
    """Which closure files changed between `sha` and `ref`.

    b127: `ref` defaults to HEAD (the live question), but the reproduction test
    must be able to re-derive a FROZEN ledger against the head it recorded, so
    the reference is a parameter instead of a hardcoded string. Additive: the
    default keeps every existing call byte-identical.
    """
    if not sha:
        return []
    out = _git("diff", "--name-only", sha, ref, "--", *paths)
    names = [n for n in out.splitlines() if n.strip()]
    detail = []
    for n in names:
        c = _git("log", "--format=%h %cI", f"{sha}..{ref}", "--", n)
        detail.append({"file": n,
                       "commits_since_boot": [l for l in c.splitlines() if l]})
    return detail


def measure() -> dict:
    head = _git("rev-parse", "HEAD")
    led = {"_note": "b114: does each long-lived trading daemon run the code at "
                    "HEAD? Python binds at import, so a committed change to the "
                    "live ladder is inert until the service restarts.",
           "_generated_at": datetime.now(timezone.utc).isoformat(),
           "head": head,
           "daemons": {}}
    for name, spec in DAEMONS.items():
        start = process_start_utc(name)
        if start is None:
            led["daemons"][name] = {"running": False}
            continue
        boot = commit_at_or_before(start)
        closure = import_closure(spec["entry"], spec["extra"])
        changed = changed_files(boot["sha"], closure)
        led["daemons"][name] = {
            "running": True,
            "started_utc": start.isoformat(),
            "stale_hours": round(
                (datetime.now(timezone.utc) - start).total_seconds() / 3600.0,
                1),
            "boot_commit": boot,
            "closure_files": len(closure),
            "closure": closure,
            "changed_since_boot": changed,
            "drift": bool(changed),
        }
    return led


def main() -> int:
    led = measure()
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as fh:
        json.dump(led, fh, indent=2, ensure_ascii=False)
    for name, d in led["daemons"].items():
        if not d.get("running"):
            print(f"{name}: not running")
            continue
        print(f"{name}: started {d['started_utc']} ({d['stale_hours']}h ago) "
              f"boot={str(d['boot_commit']['sha'])[:9]} "
              f"closure={d['closure_files']} files, "
              f"{len(d['changed_since_boot'])} changed since boot")
        for c in d["changed_since_boot"]:
            print("   ", c["file"], "<-", c["commits_since_boot"])
    print("wrote", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
