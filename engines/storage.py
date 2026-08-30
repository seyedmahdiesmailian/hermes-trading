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


def ensure_xau_plan_dirs(base_dir: str | Path | None = None) -> dict:
    root = Path(base_dir) if base_dir else paths.plan_dir()
    plan_history_dir = root / "plan_history"
    current_plan_path = root / "current_plan.json"
    runtime_state_path = root / "runtime_state.json"
    performance_state_path = root / "performance_state.json"
    execution_log_path = root / "execution_log.csv"
    reassessment_log_path = root / "reassessment_log.csv"
    pending_orders_path = root / "pending_orders.json"
    plan_history_dir.mkdir(parents=True, exist_ok=True)
    return {
        "base_dir": root,
        "plan_history_dir": plan_history_dir,
        "current_plan_path": current_plan_path,
        "runtime_state_path": runtime_state_path,
        "performance_state_path": performance_state_path,
        "execution_log_path": execution_log_path,
        "reassessment_log_path": reassessment_log_path,
        "pending_orders_path": pending_orders_path,
    }


def load_current_plan(base_dir: str | Path | None = None):
    paths = ensure_xau_plan_dirs(base_dir)
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


def load_runtime_state(base_dir: str | Path | None = None) -> dict:
    paths = ensure_xau_plan_dirs(base_dir)
    return read_json_safe(paths["runtime_state_path"], {}, label="runtime_state")


def save_runtime_state(base_dir: str | Path | None, state: dict) -> Path:
    paths = ensure_xau_plan_dirs(base_dir)
    return write_json_atomic(paths["runtime_state_path"], state, indent=2)


def load_performance_state(base_dir: str | Path | None = None) -> dict:
    paths = ensure_xau_plan_dirs(base_dir)
    return read_json_safe(paths["performance_state_path"], {}, label="performance_state")


def save_performance_state(base_dir: str | Path | None, state: dict) -> Path:
    paths = ensure_xau_plan_dirs(base_dir)
    return write_json_atomic(paths["performance_state_path"], state, indent=2)
