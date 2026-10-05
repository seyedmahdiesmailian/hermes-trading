"""b238: the in-zone pullback entry must reanchor, like every other style.

Before b238 the pullback returned build_trade_blueprint RAW: sl = whole-zone
invalidation, tp = tp_levels[0] (== the zone boundary). Entering near the
top of the long zone produced a sub-0.2R trade — live ticket 111572408
carried a $30.59 stop against a $1.67 target (0.05R).

The fix applies _reanchor_blueprint to both pullback sites. This test pins
it on a synthetic plan shaped like the live one, and checks the RR floor
exemption no longer covers pullback_continuation.
"""
import sys
sys.path.insert(0, '.'); sys.path.insert(0, 'engines')
from datetime import datetime, timezone
from engines.plan import decide_execution_action

# shaped after live plan xau-eac6936b (ticket 111572408)
PLAN = {
    "symbol": "XAUUSD",
    "bias": "bullish",
    "invalidation": 4123.51,
    "targets": [],
    "zones": {
        "long_entry_low": 4124.81,
        "long_entry_high": 4155.77,
        "short_entry_low": 4155.77,
        "short_entry_high": 4197.04,
        "value_low": 4155.77,
        "value_high": 4197.04,
    },
    "execution": {
        "tp_levels": [4155.77, 4197.04],
        "tp_shares": [0.5, 0.5],
    },
    "quality": {"setup_grade": "B", "smc_confidence": 0.9},
    "plan_id": "test-b238",
}

now = datetime(2026, 10, 5, 6, 30, tzinfo=timezone.utc)

# entry near the TOP of the long zone — the degenerate case
d = decide_execution_action(PLAN, price=4154.10, trigger_ok=True, now=now)
assert d["action"] == "market_entry_now", d
bp = d["blueprint"]
entry = 4154.10
risk = abs(entry - float(bp["sl"]))
reward = abs(float(bp["tp"]) - entry)
rr = reward / risk
print(f"pullback BUY: sl={bp['sl']} (${risk:.2f}) tp={bp['tp']} (${reward:.2f}) RR={rr:.2f}")
assert rr >= 1.0, f"reanchor failed: RR={rr:.2f} (was 0.05 before b238)"

# sanity: the raw structural geometry was degenerate
raw_rr = abs(4155.77 - entry) / abs(entry - 4123.51)
assert raw_rr < 0.2, f"test premise wrong, raw RR={raw_rr:.2f}"
print(f"raw (pre-b238) RR was {raw_rr:.2f} -> now {rr:.2f}")

# sell side mirror
PLAN_S = {
    "symbol": "XAUUSD", "bias": "bearish", "invalidation": 4197.04, "targets": [],
    "zones": {
        "long_entry_low": 4124.81, "long_entry_high": 4155.77,
        "short_entry_low": 4155.77, "short_entry_high": 4197.04,
        "value_low": 4124.81, "value_high": 4155.77,
    },
    "execution": {"tp_levels": [4155.77, 4124.81], "tp_shares": [0.5, 0.5]},
    "quality": {"setup_grade": "B", "smc_confidence": 0.9},
    "plan_id": "test-b238-s",
}
ds = decide_execution_action(PLAN_S, price=4156.50, trigger_ok=True, now=now)
assert ds["action"] == "market_entry_now", ds
bps = ds["blueprint"]
entry_s = 4156.50
rr_s = abs(float(bps["tp"]) - entry_s) / abs(entry_s - float(bps["sl"]))
print(f"pullback SELL: sl={bps['sl']} tp={bps['tp']} RR={rr_s:.2f}")
assert rr_s >= 1.0, f"sell reanchor failed: RR={rr_s:.2f}"

# RR floor exemption must no longer cover pullback_continuation
from engines.auto_executor import RR_FLOOR_EXEMPT_STYLES
assert "pullback_continuation" not in RR_FLOOR_EXEMPT_STYLES, \
    "pullback_continuation must be gated by the RR floor (b238)"
assert "aggressive_value_entry" in RR_FLOOR_EXEMPT_STYLES, "b233d exemption intact"
print("RR floor exemption: pullback_continuation removed, aggressive_value_entry kept")

print("\nOK b238: pullback reanchor + RR floor gating")
