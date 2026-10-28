"""b49 — the self-verification seam for FAIL-SAFE observability scripts.

Why this module exists: autopilot_harvest.py, autopilot_digest.py and the
dirty_work reader swallow every error on purpose (`except Exception: pass`)
so a broken check can never block the autopilot run. Correct posture — but
it has a blind side: BROKEN and CLEAN produce byte-identical output. b48
only caught the harvester's silent death because a shadow package happened
to RAISE; a NameError, a moved function, a typo inside any swallow block
would have printed nothing forever and every dashboard would have read that
silence as "all good". The observability layer must never be the thing that
goes unnoticed.

The seam: inside a swallow block, call `fail(section, exc)` before returning
the sentinel. In normal operation `fail()` does exactly nothing (behaviour
is byte-identical to `pass` — production posture is unchanged). When the
script runs with `--self-check` or HERMES_SELFCHECK=1, `fail()` re-raises as
RuntimeError, the script dies with a traceback and a non-zero exit — so
"printed nothing because broken" can no longer masquerade as "printed
nothing because clean".

Self-check mode ALSO suppresses outbound side effects (the digest must not
page Telegram when it is being probed) — see `enabled()` consumers.

This module never swallows, never trades, never touches state: it is a
two-function switch. Fail-safe scripts keep being fail-safe; they just gain
a mode where they can be proven alive.
"""
from __future__ import annotations

import os
import sys

_TRUTHY = ('1', 'true', 'yes', 'on')


def enabled(argv: list[str] | None = None) -> bool:
    """True when running as a self-check: HERMES_SELFCHECK=1 (or true/yes/on)
    or a --self-check flag in argv. Read at CALL time (b39 convention) — a
    test may flip the env var after import."""
    if (os.environ.get('HERMES_SELFCHECK') or '').strip().lower() in _TRUTHY:
        return True
    return '--self-check' in (sys.argv[1:] if argv is None else argv)


def fail(section: str, exc: BaseException | None = None) -> None:
    """Call from inside a swallow block, right before returning the sentinel.

    Normal mode: returns None — the caller's swallow posture is unchanged.
    Self-check mode: raises RuntimeError naming the section, so the script
    exits non-zero with a traceback that says WHICH block broke.
    """
    if enabled():
        raise RuntimeError(
            f'selfcheck: fail-safe section "{section}" raised — '
            f'in normal mode this is silently swallowed and indistinguishable '
            f'from a clean run: {exc!r}'
        ) from exc
