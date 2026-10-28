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


# ── b217: the wall clock is an ambient input too ──────────────────────────
# use_temp_data_root() removed the filesystem's influence on a test run. The
# CLOCK was still ambient: engines.market_hours.is_market_open() defaults to
# datetime.now(), so every gate downstream of it flips with the real weekday
# and the suite went RED every weekend (6 tests). A red weekend suite is
# worse than a slow one — it trains the operator to ignore failures, which is
# exactly how a real regression gets shipped on a Monday.
#
# is_market_open(now) already accepts an injected time; nothing in production
# needs to change. What was missing is ONE switch the tests can share, so a
# new market-dependent test cannot forget it the way the old per-module path
# patches were forgotten.
#
# It patches the MODULE ATTRIBUTE on each importer, not the function itself:
# auto_executor does `from engines.market_hours import is_market_open`, which
# binds a local name at import time, so patching only engines.market_hours
# would silently miss it (the b41 binding lesson).

_MARKET_PATCH_TARGETS = (
    ('engines.market_hours', 'is_market_open'),
    ('engines.auto_executor', 'is_market_open'),
)
_orig_market: list = []


def force_market_open(is_open: bool = True) -> None:
    """Make every execution path see the market as open (or closed).

    Call release_market() in tearDown. Safe to call when a module has not
    been imported yet — that importer is simply skipped.
    """
    import importlib
    global _orig_market
    release_market()
    for mod_name, attr in _MARKET_PATCH_TARGETS:
        try:
            mod = importlib.import_module(mod_name)
        except Exception:
            continue
        if not hasattr(mod, attr):
            continue
        _orig_market.append((mod, attr, getattr(mod, attr)))
        setattr(mod, attr, lambda *a, **k: is_open)


def release_market() -> None:
    global _orig_market
    for mod, attr, fn in _orig_market:
        setattr(mod, attr, fn)
    _orig_market = []
