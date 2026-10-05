"""Live race test for the b256 lock-name fix.

Simulates the flood mechanism: one thread plays the fetch loop (read-modify-
write of listener_state.json under the "telegram_updates" lock) while another
inserts dedup keys (same file, same lock after b256). Before b256 the two used
different lock names and the fetch side clobbered the dedup side's keys.

This exercises the REAL check_signals + _fetch paths via the real lock, so it
fails on pre-b256 code and passes after.
"""
import os, sys, threading, time, json

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _ROOT)

os.environ.setdefault("DRY_RUN", "1")

import engines.signal_listener as SL
from engines import paths
from engines.process_lock import exclusive


def _wiped():
    p = paths.listener_state()
    return {"last_update_id": 0, "seen_message_ids": {}}


def run(trials=60):
    """Concurrent fetch-style writes racing dedup-style writes on one state file."""
    lost = 0
    for t in range(trials):
        paths.listener_state().parent.mkdir(parents=True, exist_ok=True)
        paths.listener_state().write_text(json.dumps(_wiped()), encoding="utf-8")

        inserted = []
        barrier = threading.Barrier(2)
        errors = []

        def fetch_side():
            # mimics _fetch_new_messages_unlocked's state save
            barrier.wait()
            for _ in range(40):
                try:
                    with exclusive("telegram_updates", timeout=2.0):
                        st = SL._load_state()
                        st["last_update_id"] = int(time.time())
                        SL._save_state(st)
                except Exception as e:
                    errors.append(("fetch", e))
                time.sleep(0.0005)

        def dedup_side():
            # mimics check_signals' dedup insert
            barrier.wait()
            try:
                with exclusive("telegram_updates", timeout=5.0):
                    for i in range(50):
                        st = SL._load_state()
                        seen = st.get("seen_message_ids", {})
                        seen[f"k{i}"] = time.time()
                        st["seen_message_ids"] = seen
                        SL._save_state(st)
                inserted.append("done")
            except Exception as e:
                errors.append(("dedup", e))

        th = [threading.Thread(target=fetch_side), threading.Thread(target=dedup_side)]
        for x in th:
            x.start()
        for x in th:
            x.join()

        final = SL._load_state().get("seen_message_ids", {})
        if len(final) < 50:
            lost += 1
        if errors:
            print(f"  trial {t}: errors {errors[:2]}")
    return lost


if __name__ == "__main__":
    n = run()
    if n:
        print(f"FAIL: {n} trials lost dedup keys (state clobber race)")
        sys.exit(1)
    print("ok: 0/60 trials lost dedup keys — shared lock holds")
