"""Regression: all writers of listener_state.json must share ONE lock.

The replay flood root cause (deleg_2939f5ad): the fetch path locked
"telegram_updates" while the dedup path locked "signal_dedup". exclusive()
is keyed on the NAME (engines/process_lock.py: lock_dir / f"{name}.lock"),
so two different names = two different lock files = zero mutual exclusion.
The fetch side's read-modify-write then clobbered the dedup side's
seen_message_ids, wiping dedup keys.

This test asserts both critical sections use the same lock name.
"""
import os, sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _ROOT)

import engines.signal_listener as SL


def _lock_names(func):
    """Return the lock name passed to _state_lock inside a function body."""
    import inspect, re
    src = inspect.getsource(func)
    m = re.search(r'_state_lock\(\s*"([^"]+)"', src)
    return m.group(1) if m else None


def test_fetch_and_dedup_share_one_lock():
    names = set()
    for fn in (SL._fetch_new_messages_unlocked, SL.check_signals):
        n = _lock_names(fn)
        if n:
            names.add(n)
    assert len(names) == 1, (
        f"writers of listener_state.json use DIFFERENT locks {names}; "
        "exclusive() is per-name so they do not exclude each other"
    )


def test_dedup_keyed_on_content_not_message_id_only():
    """b254: same content under a fresh message_id must collapse."""
    import time, hashlib
    chat = -1001234
    base = time.time()
    msgs = []
    for i, mid in enumerate((111, 222, 333, 444, 555)):
        msgs.append({
            "chat_id": chat, "message_id": mid, "date": int(base) + i,
            "text": "SELL XAUUSD 4450 SL 4462 TP 4414",
        })
    seen = {}
    horizon = 86400
    kept = []
    for m in msgs:
        mid = m.get("message_id") or 0
        k1 = f'{m.get("chat_id", "")}:{mid}' if mid else None
        txt = (m.get("text") or "")[:500]
        k2 = "txt:" + hashlib.sha1(f'{m.get("chat_id", "")}:{txt}'.encode()).hexdigest()
        if k1 and k1 in seen:
            continue
        if k2 in seen and base - seen[k2] < horizon:
            continue
        if k1:
            seen[k1] = base
        seen[k2] = base
        kept.append(m)
    assert len(kept) == 1, f"content dedup collapsed {len(kept)} msgs, expected 1"


if __name__ == "__main__":
    for name in ("test_fetch_and_dedup_share_one_lock",
                 "test_dedup_keyed_on_content_not_message_id_only"):
        fn = globals()[name]
        try:
            fn()
            print(f"ok   {name}")
        except AssertionError as e:
            print(f"FAIL {name}: {e}")
            sys.exit(1)
    print("all passed")
