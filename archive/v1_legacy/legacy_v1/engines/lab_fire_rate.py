#!/usr/bin/env python3
"""b79 — GATE FIRE-RATE STABILITY PRE-FLIGHT: measure the oracle's PASS RATE
per window BEFORE spending any R on the arm it gates.

Why this exists (b68 round 16, todo b79): the weekly-runway gate's pass rate
swung 36%-68% across four independent windows (measured from the shipped
b68p ledger: 0.676/0.491/0.628/0.362) and its median room-to-weekly-extreme
swung from +6.46 ATR (W1) to -0.79 ATR (W4). An oracle whose fire rate is
itself regime-gifted cannot produce a regime-independent selection — round 16
could have been closed on that 5-line probe alone, without the four-window
draw.

ROUND 17 CALIBRATION (the other half of the rule): the H4 trend gate's pass
rate is the loop's MOST stable (0.433/0.451/0.461/0.462, swing 2.9 points)
and its selection ordering is the loop's cleanest (4-of-4 agree>cut) — and
the arm it gated STILL failed the merit bar 1-of-4 windows. So this screen is
NECESSARY-not-sufficient: a stable fire rate rules out regime-gifted
selection, it does NOT promise a replicating LIFT. b74's lift-vs-control and
all-windows tests stay the binding checks. This module must never be used to
promote anything — only to STOP a round early.

PASS-RATE DEFINITIONS (extracted from the probe blocks the rounds already
ship — no re-measurement, no new fetch):
  - b68m/b68q/b68n4 shape: gate_share directly (agree / fireable signals).
  - b68p (runway) shape: (runway_buy+runway_sell)/(pdh_signals -
    no_week_level) — kept over fireable, same denominator convention.
  - b68o (geometry) shape: signals/weeks_with_level — how often the level
    breaks per week; a geometry whose fire rate swings is the same disease
    one level down (round 15's regime fingerprint).
  - median threshold-crossing age (b79's second clause):
    agree_state_age_median_htf_bars (m/q/n4), room_median (p).

Verdicts (mirrors engines/lab_decay.py's vocabulary):
  STABLE     — swing <= SWING_FAIL_POINTS and no median-age flip of sign
               across windows: fire rate is regime-independent enough that a
               draw can be spent; the lift question stays open.
  UNSTABLE   — swing > SWING_FAIL_POINTS (or median-age sign flip): the
               oracle's SELECTION is regime-gifted; b79 says close the round
               on the probe alone. Necessary-not-sufficient: UNSTABLE is a
               stop, STABLE is only a permission to proceed.
  INSUFFICIENT — fewer than 3 legs with a parseable pass rate: no swing can
               be read (a 2-point line is not a curve, b77 lesson).

Read-only research code: nothing here is imported by the live trading path
(same contract as engines/lab_harness.py and engines/lab_decay.py).
"""
from __future__ import annotations

SWING_FAIL_POINTS = 20.0   # percentage points of pass-rate spread that kills


def _num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def pass_rate(probe: dict):
    """Extract the oracle's pass rate from one leg's probe block.

    Returns (rate, kind) or (None, reason). Handles every probe shape the
    loop has shipped (see module docstring); unknown shapes return None so
    they can never silently count as a 0.0 rate.
    """
    if not isinstance(probe, dict):
        return None, "no probe block"
    # b68m / b68q / b68n4: explicit gate_share (b68n4 nests per-oracle)
    if _num(probe.get("gate_share")):
        return float(probe["gate_share"]), "gate_share"
    # b68p runway shape: kept / fireable (fireable excludes no-week-level)
    if all(_num(probe.get(k)) for k in
           ("runway_buy", "runway_sell", "pdh_signals", "no_week_level")):
        fireable = probe["pdh_signals"] - probe["no_week_level"]
        if fireable <= 0:
            return None, "no fireable signals"
        return (probe["runway_buy"] + probe["runway_sell"]) / fireable, "runway"
    # b68o geometry shape: signals per week that HAD a level
    if all(_num(probe.get(k)) for k in ("signals", "weeks_with_level")):
        if probe["weeks_with_level"] <= 0:
            return None, "no weeks with level"
        return probe["signals"] / probe["weeks_with_level"], "signals_per_week"
    return None, "unrecognised probe shape"


def median_age(probe: dict):
    """Median threshold-crossing age of the kept subset, if the probe carries
    one (b79's second clause: an oracle whose kept-subset state age flips
    sign or order of magnitude across regimes is not a stable STATE)."""
    if not isinstance(probe, dict):
        return None
    for k in ("agree_state_age_median_htf_bars", "room_median"):
        if _num(probe.get(k)):
            return float(probe[k]), k
    return None


def _walk_legs(led: dict, windows):
    """Yield (leg, probe_dict) for every requested leg that carries a probe.

    Legs are the top-level window names of a confirm ledger; a leg's probe is
    under '_probe'. Legs without '_probe' (rounds 1-11 predate it) are
    skipped and reported, never guessed.
    """
    for w in windows or [k for k in led if not k.startswith("_")]:
        v = led.get(w)
        if isinstance(v, dict) and isinstance(v.get("_probe"), dict):
            yield w, v["_probe"]


def fire_rate_series(led: dict, windows=None, oracle: str | None = None):
    """Per-leg pass rates from a shipped confirm ledger.

    `oracle` selects a nested probe group (b68n4 shape: "h4_pdh"/"h4_funnel");
    None means the leg's probe is flat. Returns (series, skipped) where
    series maps leg -> {"rate","kind"} and skipped lists legs with no
    parseable rate (with reason).
    """
    series, skipped = {}, []
    for leg, probe in _walk_legs(led, windows):
        p = probe
        if oracle is not None:
            if not isinstance(p.get(oracle), dict):
                skipped.append({"leg": leg, "reason": f"no '{oracle}' group"})
                continue
            p = p[oracle]
        rate, kind = pass_rate(p)
        if rate is None:
            skipped.append({"leg": leg, "reason": kind})
            continue
        row = {"rate": round(rate, 4), "kind": kind}
        ma = median_age(p)
        if ma:
            row["median_age"], row["median_age_field"] = ma
        series[leg] = row
    return series, skipped


def fire_rate_verdict(series: dict, chrono_order: list[str]) -> dict:
    """b79 verdict on one oracle's pass-rate series, ordered by TIME.

    `chrono_order` must be oldest→newest (use engines.lab_decay.chrono_windows
    with the ledger's own '_last' stamps — b77 lesson: window LABELS are
    newest-first, reading them as time reads history backwards).
    Swing is max-min across the series; the median-age clause fires only when
    EVERY leg carries the SAME age field and its sign flips across windows
    (round 16's room_median +6.46→-0.79 shape).
    """
    legs = [w for w in chrono_order if w in series]
    out: dict = {"_chrono_order_oldest_first": chrono_order,
                 "_swing_fail_points": SWING_FAIL_POINTS,
                 "series": {w: series[w] for w in legs}}
    if len(legs) < 3:
        out["verdict"] = "INSUFFICIENT"
        out["reason"] = (f"{len(legs)} legs with a parseable pass rate — "
                         "a 2-point line is not a curve (b77 lesson)")
        return out
    rates = [series[w]["rate"] for w in legs]
    kinds = {series[w]["kind"] for w in legs}
    if kinds == {"signals_per_week"}:
        # a COUNT rate (breaks per week): percentage points are meaningless,
        # use swing relative to the mean — 20% relative is the same bar.
        mean = sum(rates) / len(rates)
        swing = round((max(rates) - min(rates)) / mean * 100.0, 1) if mean else None
        out["swing_basis"] = "relative % of mean (count rate)"
    else:
        swing = round((max(rates) - min(rates)) * 100.0, 1)
        out["swing_basis"] = "percentage points (probability rate)"
    out["swing_points"] = swing
    out["min_rate"], out["max_rate"] = min(rates), max(rates)
    ages = [series[w].get("median_age") for w in legs]
    fields = {series[w].get("median_age_field") for w in legs}
    age_flip = False
    if len(fields) == 1 and None not in fields and all(a is not None for a in ages):
        age_flip = any(a > 0 for a in ages) and any(a < 0 for a in ages)
        out["median_age_series"] = dict(zip(legs, ages))
        out["median_age_field"] = next(iter(fields))
    out["median_age_sign_flip"] = age_flip
    if swing > SWING_FAIL_POINTS or age_flip:
        out["verdict"] = "UNSTABLE"
        out["reason"] = ("pass-rate swing %.1f pts%s — the oracle's fire rate "
                         "is itself regime-gifted; b79 says close the round on "
                         "the probe alone (do NOT spend a draw)" % (
                             swing, ", plus median-age sign flip" if age_flip else ""))
    else:
        out["verdict"] = "STABLE"
        out["reason"] = ("fire rate regime-independent enough to spend a draw; "
                         "round 17 proved this is NECESSARY-not-sufficient — "
                         "the lift-vs-control test (b74) still decides")
    return out


def preflight(led: dict, windows: list[str], oracle: str | None = None,
              window_meta: dict | None = None) -> dict:
    """One-call b79 pre-flight over a shipped confirm ledger.

    `window_meta` maps window name -> {"last": epoch} (same shape
    lab_decay.preflight takes); when omitted it is built from each leg's own
    "_last" stamp, which every b76-era confirm ledger records. Returns the
    verdict dict plus any skipped legs so nothing is silently dropped.
    """
    from engines.lab_decay import chrono_windows
    if window_meta is None:
        window_meta = {w: {"last": led[w]["_last"]} for w in windows
                       if isinstance(led.get(w), dict) and "_last" in led[w]}
    order = chrono_windows(window_meta, windows)
    series, skipped = fire_rate_series(led, windows, oracle)
    v = fire_rate_verdict(series, order)
    if skipped:
        v["_skipped_legs"] = skipped
    return v
