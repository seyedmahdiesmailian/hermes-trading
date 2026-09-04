#!/usr/bin/env python3
"""b77 — CHRONOLOGICAL-DECAY PRE-FLIGHT: check the margin SHAPE before
spending another window draw on a candidate.

Why this exists (b68 round 14, todo b77): the fourth draw killed
funnel_h4t_agree, and the shape of the kill was the lesson. Margins quoted
in WINDOW order (W1→W4, labels are NEWEST-FIRST) looked like a slow decay
toward the bar (+0.093/+0.032/+0.008/−0.015); read in CHRONOLOGICAL order
(W4 oldest → W1 newest) they are MONOTONIC INCREASING — the edge grows with
recency, i.e. it is a gift of the recent regime, not a property of the
market. No further draw can rescue a candidate like that, and spending one
to find out is exactly what this pre-flight prevents.

RULE (b77): given an arm's per-window margins (arm exp_R − funnel exp_R on
the SAME bars), sorted by TIME:
  REGIME_GIFTED — margins strictly increase with recency and the average
      per-step slope >= SLOPE_MIN_R: the edge is a recent-regime artefact;
      STOP, do not burn a draw, record the curve as the verdict.
  DECAYING     — margins strictly decrease with recency: the edge is real
      but fading; a draw is only worth it if the OLDEST surviving margin
      still clears the promotion bar (b74).
  MIXED        — no monotone order: regime interaction unknown; the draw
      question is open and b74's all-windows rule decides.
  INSUFFICIENT — fewer than 3 windows: no shape can be read (a 2-point
      line is monotone by construction — never call it a curve).

None margins (an arm that traded 0 times on a window) never silently count
as 0: they make the series INSUFFICIENT for that arm and are reported.

Read-only research code: nothing here is imported by the live trading path
(same contract as engines/lab_harness.py, pinned by its tests).
"""
from __future__ import annotations

SLOPE_MIN_R = 0.02   # R per window-step that makes a monotone ramp material


def margins_by_window(led: dict, arm: str,
                      windows: list[str],
                      funnel_key: str = "CURRENT_FUNNEL",
                      mode: str = "ladder_ts") -> dict[str, float | None]:
    """arm exp_R − funnel exp_R per window, from a shipped round ledger.

    `led` maps window name -> {arm: {mode: {exp_R}}}. A None exp_R on either
    side yields a None margin (never a fake 0.0).
    """
    out: dict[str, float | None] = {}
    for w in windows:
        win = led.get(w) or {}
        f = (win.get(funnel_key) or {}).get(mode, {}).get("exp_R")
        a = (win.get(arm) or {}).get(mode, {}).get("exp_R")
        out[w] = None if (f is None or a is None) else round(a - f, 3)
    return out


def chrono_windows(window_meta: dict, windows: list[str]) -> list[str]:
    """Sort window names oldest→newest by their own last-bar timestamp.

    `window_meta` maps name -> {"last": <epoch>} (the facts the windows
    ledger already records). Window LABELS are newest-first by convention
    (W1 = most recent) — reading a "decay W1→W4" series is reading time
    BACKWARDS, the round-14 near-miss. Never trust labels; trust timestamps.
    """
    def last_ts(w: str) -> int:
        meta = window_meta.get(w)
        if meta is None or "last" not in meta:
            raise KeyError(f"window {w} has no '_last' timestamp in meta — "
                           "chronological order cannot be established")
        return int(meta["last"])
    return sorted(windows, key=last_ts)


def decay_verdict(margins: dict[str, float | None],
                  chrono_order: list[str]) -> dict:
    """b77 pre-flight verdict on one arm's margin series.

    `chrono_order` must be oldest→newest (see chrono_windows). Returns a
    dict with verdict/series/slope so the caller can ship it in a ledger.
    """
    series = [margins.get(w) for w in chrono_order]
    if any(s is None for s in series):
        return {"verdict": "INSUFFICIENT",
                "reason": "a window has no measurable margin (None)",
                "chrono_order": chrono_order, "series": series,
                "slope_R_per_step": None}
    if len(series) < 3:
        return {"verdict": "INSUFFICIENT",
                "reason": f"{len(series)} windows — a 2-point line is "
                          "monotone by construction, not a curve",
                "chrono_order": chrono_order, "series": series,
                "slope_R_per_step": None}
    diffs = [series[i + 1] - series[i] for i in range(len(series) - 1)]
    slope = round((series[-1] - series[0]) / (len(series) - 1), 4)
    mono_up = all(d > 0 for d in diffs)
    mono_down = all(d < 0 for d in diffs)
    if mono_up and abs(slope) >= SLOPE_MIN_R:
        v = "REGIME_GIFTED"
    elif mono_down:
        v = "DECAYING"
    else:
        v = "MIXED"
    return {"verdict": v, "chrono_order": chrono_order, "series": series,
            "slope_R_per_step": slope,
            "monotone_increasing": mono_up,
            "monotone_decreasing": mono_down}


def preflight(led: dict, arms: list[str], windows: list[str],
              window_meta: dict, funnel_key: str = "CURRENT_FUNNEL",
              mode: str = "ladder_ts") -> dict:
    """Run the b77 check for a set of arms on one round ledger."""
    order = chrono_windows(window_meta, windows)
    out: dict = {"_chrono_order_oldest_first": order,
                 "_slope_min_R": SLOPE_MIN_R}
    for arm in arms:
        if arm == funnel_key:
            continue
        m = margins_by_window(led, arm, windows, funnel_key, mode)
        out[arm] = decay_verdict(m, order)
    return out
