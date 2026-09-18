from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path

from engines import paths  # resolved at CALL time so tests can redirect the tree
# NOTE: functions below bind a LOCAL variable named `paths` (the dir dict), so
# the durable-JSON helpers are imported by name, not via the module.
from engines.paths import read_json_safe, write_json_atomic

DEFAULT_BASE_DIR = None  # None → paths.plan_dir() (production default)


def xau_plan_paths(base_dir: str | Path | None = None) -> dict:
    """Pure path computation for the plan tree — NO mkdir, ever.

    review-fix A1 (2026-09-17): every READ used to go through
    ensure_xau_plan_dirs, so its mkdir ran on the read path — and on any
    box where the production root (/home/ai/hermes-trading) is absent (DR
    checkout, CI, a moved install) read_json_safe never got a chance to
    honestly return None: the mkdir raised PermissionError first and every
    signal was rejected with policy_error. Reads must never need to create
    anything; writers keep the mkdir via ensure_xau_plan_dirs below.
    """
    root = Path(base_dir) if base_dir else paths.plan_dir()
    return {
        "base_dir": root,
        "plan_history_dir": root / "plan_history",
        "current_plan_path": root / "current_plan.json",
        "runtime_state_path": root / "runtime_state.json",
        "performance_state_path": root / "performance_state.json",
        "execution_log_path": root / "execution_log.csv",
        "reassessment_log_path": root / "reassessment_log.csv",
        "risk_ledger_path": root / "risk_ledger.csv",
        "pending_orders_path": root / "pending_orders.json",
    }


def ensure_xau_plan_dirs(base_dir: str | Path | None = None) -> dict:
    """Compute the plan-tree paths AND create plan_history/ (writers only)."""
    dirs = xau_plan_paths(base_dir)
    dirs["plan_history_dir"].mkdir(parents=True, exist_ok=True)
    return dirs


def load_current_plan(base_dir: str | Path | None = None):
    paths = xau_plan_paths(base_dir)  # A1: read-only, never mkdir
    return read_json_safe(paths["current_plan_path"], None, label="current_plan")


PLAN_HISTORY_KEEP = 1500   # ≈ 3 weeks at ~7 archives/day; learning only joins 48h back


def _prune_plan_history(history_dir: Path):
    """Keep plan_history bounded — it grows every save (~7/day) and learning
    only needs the last 48h of plans. Delete oldest beyond PLAN_HISTORY_KEEP,
    but only when comfortably over the cap (amortized, no per-save scan)."""
    try:
        files = sorted(history_dir.glob("*.json"))
        if len(files) <= PLAN_HISTORY_KEEP * 1.1:
            return
        for f in files[:len(files) - PLAN_HISTORY_KEEP]:
            f.unlink(missing_ok=True)
    except OSError:
        pass


def save_current_plan(base_dir: str | Path | None, plan: dict) -> Path:
    paths = ensure_xau_plan_dirs(base_dir)
    current_path = paths["current_plan_path"]
    existing = read_json_safe(current_path, None, label="current_plan")
    if existing is not None:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        archive_path = paths["plan_history_dir"] / f"{stamp}_{existing.get('plan_id', 'plan')}.json"
        write_json_atomic(archive_path, existing, indent=2)
        _prune_plan_history(paths["plan_history_dir"])
    write_json_atomic(current_path, plan, indent=2)
    return current_path


def _append_csv_row(path: Path, row: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    exists = path.exists()
    fieldnames = list(row.keys())
    with path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if not exists:
            writer.writeheader()
        writer.writerow(row)


def append_execution_log(base_dir: str | Path | None, row: dict):
    paths = ensure_xau_plan_dirs(base_dir)
    _append_csv_row(paths["execution_log_path"], row)


def append_reassessment_log(base_dir: str | Path | None, row: dict):
    paths = ensure_xau_plan_dirs(base_dir)
    _append_csv_row(paths["reassessment_log_path"], row)


# b139: the per-trade risk-shrink stack lives in its OWN ledger, not in
# execution_log.csv. Why a sidecar (b142's rule): _append_csv_row writes a
# header only when the file is new, so adding a 13th key to the existing
# 12-column execution_log would write values under a column name nobody ever
# writes — csv.DictReader folds them into the None restkey and every consumer
# (learning's join, dashboards, weekly_report) reads the file as if the field
# never existed. A new file gets its header on creation, and the fieldnames
# below are FIXED so a future row can never silently redefine the schema.
# b144: `ticket` is the last column. It is what makes a sidecar row joinable
# to realized P&L on its OWN key — without it every signal-lane row carries
# plan_id='signal' and the b138 question ("did the 0.25x double-charge trade
# actually lose less money?") is unanswerable for the lane that trades most.
# Appending it to the END of the tuple keeps the old 18-column header a strict
# prefix of the new one, so _migrate_risk_ledger_header can widen existing rows
# losslessly (b142's rule: adding a column is a schema migration).
RISK_LEDGER_FIELDS = (
    "at", "lane", "plan_id", "side", "lot", "entry", "sl", "tp",
    "grade", "base_risk_pct", "learning_risk_mult", "execution_style",
    "style_mult", "defcon_override", "regime", "regime_mult",
    "final_risk_pct", "risk_usd", "ticket",
)


def _risk_ledger_header(path: Path) -> list[str] | None:
    """The header line of an existing ledger, or None if absent/empty."""
    if not path.exists() or path.stat().st_size == 0:
        return None
    with path.open(newline="", encoding="utf-8") as f:
        line = f.readline().strip()
    return next(csv.reader([line])) if line else None


def _migrate_risk_ledger_header(path: Path) -> None:
    """Widen an existing ledger to RISK_LEDGER_FIELDS without losing a row.

    learning.py's _migrate_journal is the precedent: DictWriter appends BY
    POSITION, so writing a 19-wide row under an 18-wide header silently
    misaligns nothing but simply hides the extra value under csv's None
    restkey (b142's no-op trap). Rewrite the file instead.

    Refuses (raises) rather than destroying data when the on-disk header is
    not a strict prefix of the shipped schema — an unknown column means an
    unknown writer, and guessing is worse than not auditing. The caller
    swallows the exception: a missing audit row is honest, a corrupt ledger
    is not.
    """
    header = _risk_ledger_header(path)
    if header is None or tuple(header) == RISK_LEDGER_FIELDS:
        return
    want = list(RISK_LEDGER_FIELDS)
    if header != want[:len(header)]:
        raise RuntimeError(
            f"risk_ledger header {header} is not a prefix of {want}")
    size_before = path.stat().st_size
    with path.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    tmp = path.with_suffix(".csv.tmp")
    with tmp.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=want, extrasaction="ignore")
        writer.writeheader()
        for r in rows:
            writer.writerow({k: r.get(k, "") for k in want})
    # Race guard: the live daemons still run pre-b144 code and append to this
    # same file. If a row landed while we were rewriting, replacing would
    # silently drop it — an audit ledger that loses a trade is worse than one
    # that gains none. Bail out (the caller swallows it) and let the next
    # entry retry.
    if path.stat().st_size != size_before:
        tmp.unlink(missing_ok=True)
        raise RuntimeError("risk_ledger changed during migration; retry later")
    tmp.replace(path)


def append_risk_ledger(base_dir: str | Path | None, row: dict):
    """Append one per-trade risk-stack audit row (b139). Additive, read-only
    for every gate: nothing on the entry path consumes this file."""
    paths = ensure_xau_plan_dirs(base_dir)
    path = paths["risk_ledger_path"]
    path.parent.mkdir(parents=True, exist_ok=True)
    _migrate_risk_ledger_header(path)
    with path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(RISK_LEDGER_FIELDS),
                                extrasaction="ignore")
        if not path.exists() or path.stat().st_size == 0:
            writer.writeheader()
        writer.writerow({k: row.get(k, "") for k in RISK_LEDGER_FIELDS})


def load_runtime_state(base_dir: str | Path | None = None) -> dict:
    paths = xau_plan_paths(base_dir)  # A1: read-only
    return read_json_safe(paths["runtime_state_path"], {}, label="runtime_state")


def save_runtime_state(base_dir: str | Path | None, state: dict) -> Path:
    paths = ensure_xau_plan_dirs(base_dir)
    return write_json_atomic(paths["runtime_state_path"], state, indent=2)


def load_performance_state(base_dir: str | Path | None = None) -> dict:
    paths = xau_plan_paths(base_dir)  # A1: read-only
    return read_json_safe(paths["performance_state_path"], {}, label="performance_state")


def save_performance_state(base_dir: str | Path | None, state: dict) -> Path:
    paths = ensure_xau_plan_dirs(base_dir)
    return write_json_atomic(paths["performance_state_path"], state, indent=2)
