"""Root conftest — restore importability of archived V1 modules.

Phase 1 moved the legacy V1 root-level modules into ``legacy_archive/`` and
the old engine package lives at ``legacy_v1/engines/``. A number of legacy
test files still ``import bridge_client`` / ``hermes_runtime`` / ``engines``
by their old top-level names. This shim puts those directories back on
``sys.path`` during test collection only, so the baseline collection state
is preserved. It changes no production import.

Order matters: the repository root stays first (pytest.ini ``pythonpath``),
so current ``brain/`` / ``adapters/`` packages always win over legacy ones.
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent

for _legacy in ("legacy_archive", "legacy_v1"):
    _p = _ROOT / _legacy
    if _p.is_dir() and str(_p) not in sys.path:
        sys.path.append(str(_p))
