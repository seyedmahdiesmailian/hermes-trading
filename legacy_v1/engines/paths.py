"""Single source of truth for on-disk state locations.

Why this exists (2026-08-30 audit): every module used to hardcode
Path('/home/ai/hermes-trading/data/...') at IMPORT time. The test suite
therefore wrote straight into live production state — running the tests
overwrote current_plan.json with synthetic 4600-price plans, reset
performance_state.json to a stale day (which silently re-based the daily
loss cap), and rewrote kill_switch_state.json with a fake last_check.
A test run was a production incident.

Fix: resolve paths at CALL time through this module, and let a test (or a
staging box) redirect the whole tree with set_data_root() / $HERMES_DATA_ROOT.
Production default is unchanged.
"""
from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path

PRODUCTION_ROOT = Path("/home/ai/hermes-trading")   # b66 allowlist: the ONE
# canonical default, pinned by tests/test_b66_repo_path_literals.py.

_override: Path | None = None


def repo_root() -> Path:
    """CODE location — derived from this file, never from an env var.

    b66: engines/paths.PRODUCTION_ROOT is the single sanctioned place the
    install directory is written down (the default every state accessor
    falls back to). Everything else that needs to find the repo — a script
    inserting itself into sys.path, loading .env, reading a sibling file —
    must call THIS instead of repeating the literal: a moved repo or another
    user then follows automatically, and a stale copy can never read or
    write the wrong tree while reporting success (the b46/b48 disease from
    the filesystem side).

    Deliberately NOT env-driven: HERMES_DATA_ROOT redirects STATE only.
    Letting any env var redirect the code root re-opens the b48 hole — a
    shadowing engines/ package in the seam root would be imported while the
    fail-safe swallows the crash.
    """
    return Path(__file__).resolve().parent.parent


def repo_file(*parts: str) -> Path:
    """A file inside the repo, resolved from CODE location (b66)."""
    return repo_root().joinpath(*parts)


def set_data_root(root: str | Path | None) -> None:
    """Redirect all state paths. Pass None to return to production."""
    global _override
    _override = Path(root) if root else None


def get_data_root() -> Path:
    """Active project root (env var wins, then test override)."""
    env = os.environ.get("HERMES_DATA_ROOT")
    if env:
        return Path(env)
    return _override or PRODUCTION_ROOT


def data_dir() -> Path:
    return get_data_root() / "data"


def plan_dir() -> Path:
    return data_dir() / "xau_plan"


def signals_dir() -> Path:
    return data_dir() / "signals"


def calendar_dir() -> Path:
    return data_dir() / "calendar"


def logs_dir() -> Path:
    return get_data_root() / "logs"


def kill_switch_state() -> Path:
    return data_dir() / "kill_switch_state.json"


def cooldown_state() -> Path:
    return data_dir() / "cooldown_state.json"


def listener_state() -> Path:
    return signals_dir() / "listener_state.json"


def signals_log() -> Path:
    return signals_dir() / "signals_log.json"


def pending_state() -> Path:
    """b70 — tracked signal LIMIT orders awaiting their entry price."""
    return signals_dir() / "pending_orders.json"


def watchdog_state() -> Path:
    return plan_dir() / "watchdog_state.json"


def broker_clock_state() -> Path:
    # b35: watchdog-published broker-clock calibration, read by the runtime
    # fallback time_exit (see engines/broker_clock.py).
    return plan_dir() / "broker_clock.json"


def current_plan() -> Path:
    return plan_dir() / "current_plan.json"


def learning_state() -> Path:
    return plan_dir() / "learning_state.json"


def trade_journal() -> Path:
    return plan_dir() / "trade_journal.csv"


def calendar_cache() -> Path:
    return calendar_dir() / "economic_calendar.json"


# ── durable JSON I/O ────────────────────────────────────────────────────
# Why (2026-08-30 audit): state files were written with a bare
# path.write_text(). A crash or power loss mid-write leaves a truncated JSON
# file, and the readers had no try/except — so the NEXT trading cycle died on
# an unhandled JSONDecodeError and stayed dead until a human noticed. Writes
# now go temp-file + os.replace (atomic on POSIX); reads degrade to "no
# state" and quarantine the bad file instead of taking the system down.

def write_json_atomic(path, payload, *, indent: int | None = None, **dumps_kw) -> Path:
    """Persist JSON so a crash can never leave a half-written file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    dumps_kw.setdefault("default", str)      # datetimes/Paths → str, never crash
    text = json.dumps(payload, ensure_ascii=False, indent=indent, **dumps_kw)
    # A fixed `<name>.tmp` is not safe with two daemons: writer A can replace
    # the temp file while writer B still has it open, causing B's replace to
    # fail or publish the wrong payload. A unique temp in the same directory
    # preserves same-filesystem atomic rename without pretending to serialize
    # read-modify-write state updates.
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            fd = None
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)          # atomic rename, same directory
        return path
    finally:
        if fd is not None:
            os.close(fd)
        tmp.unlink(missing_ok=True)


def read_json_safe(path, default=None, *, label: str | None = None):
    """Load JSON; on missing/corrupt input return `default` and warn.

    A corrupt state file must degrade to 'no state', never crash the cycle.
    The unreadable file is kept aside as <name>.corrupt.<ts> for forensics.
    """
    path = Path(path)
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        tag = label or path.name
        try:
            kept = path.with_name(f"{path.name}.corrupt.{int(time.time())}")
            path.replace(kept)
            print(f"[paths] WARN {tag} unreadable ({exc}); moved to "
                  f"{kept.name}, continuing with default", flush=True)
        except Exception:
            print(f"[paths] WARN {tag} unreadable ({exc}); using default",
                  flush=True)
        return default
