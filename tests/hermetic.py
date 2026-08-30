"""Shared test helper: redirect the ENTIRE state tree into a temp dir.

Why (2026-08-30 audit): tests used to patch one module's path at a time
(cd.STATE_FILE, ks.STATE_FILE, hermes_runtime.PLAN_DIR...). Every module that
was forgotten wrote straight into live production state — a test run replaced
the real current_plan.json with synthetic 4600-price data and reset
performance_state.json to a stale day, which silently re-based the daily loss
cap. One switch, covering everything, cannot be forgotten.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

_orig_root: str | None = None
_tmp = None


def use_temp_data_root() -> Path:
    """Point all state at a fresh temp dir. Call release() in tearDown."""
    global _orig_root, _tmp
    _orig_root = os.environ.get('HERMES_DATA_ROOT')
    _tmp = tempfile.TemporaryDirectory(prefix='hermes_test_')
    root = Path(_tmp.name)
    (root / 'data' / 'xau_plan').mkdir(parents=True, exist_ok=True)
    os.environ['HERMES_DATA_ROOT'] = str(root)
    return root


def release() -> None:
    global _orig_root, _tmp
    if _orig_root is None:
        os.environ.pop('HERMES_DATA_ROOT', None)
    else:
        os.environ['HERMES_DATA_ROOT'] = _orig_root
    _orig_root = None
    if _tmp:
        _tmp.cleanup()
        _tmp = None
