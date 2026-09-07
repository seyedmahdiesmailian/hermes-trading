#!/usr/bin/env python3
"""b127 — DOES EACH FROZEN LEDGER'S OWN PRODUCER STILL REPRODUCE IT?

WHY THIS EXISTS (the b108 lesson, generalised)
==============================================
`scripts/b108_rescore_corrected.py` shipped a NameError in the LAST statement of
`main()` and no test noticed for a day, because every b108 test reads the JSON
artifact and none touches the code that makes it (b118b found it while trying to
follow b108's own method note, which said "re-run this script"). That is the
b114/b116 disease — an artifact certifying a number instead of the code
producing it — in a new costume: not a stale process, a stale producer.

b126's static scan catches only UNBOUND NAMES. It cannot see a KeyError after a
dict-shape change, a wrong constant, or a producer whose arithmetic quietly
stopped matching the block it wrote. The missing defence is the one this script
is: EXECUTE the producer's own pure functions against the shipped JSON and
require EXACT reproduction.

WHAT IS CHECKED (24 reproductions, all pure post-processing — no funnel replay)
==============================================================================
  b81   verdict(led) == led["_verdict"], and delta() re-applied to every stored
        lane/leg/convention cell (40 cells)
  b118  attribution(led) == led["_attribution"]
  b119  _neutrality on both grids, _frame_summary, the funnel-baseline and
        arm-identity blocks
  b121  verdict(led) == led["_verdict"]
  b121b _merge(step1, own rows) == led["_merged"] and _curve(merged) ==
        led["_curve"]  (the merge-integrity check, re-run rather than trusted)
  b121c ratios(led) == led["_ratio"]
  b123  integrity(), decomposition(), neutrality(), all four share_curve()
        blocks and arm_identity_live_share()
  b129  integrity() + deltas/neutrality/best_per_gate/gate_gap/verdict
        (b128's ship-time rule applied to the newest frozen ledger)
  b130  integrity() + census(per leg) + deltas/neutrality/clock_gap/verdict
        (the bar incumbent == b129's frozen cell is the proof the engine's new
        time_stop_hours dial is inert at its default)
  b114  import_closure() and changed_files() re-derived from the ledger's OWN
        recorded boot commit and head (so the drift claim is arithmetic on git,
        not prose)
  b118b redecide(led) == stored block and margin_table() == stored margins

NO LIVE CHANGE: this script only reads JSON files and runs `git log/diff`. It
imports no bridge client, calls no order endpoint, and writes nothing — the
reproduction is a CHECK, not a re-run. Producers whose measurement half needs
the ~7-minute funnel replay are pinned on their PURE half only, and each check
says which half it is (b127's own rule: say what you did not test).

Run standalone for a diagnostic printout:  python3 scripts/b127_producer_reproduction.py
The suite runs the same list: tests/test_b127_producer_reproduction.py
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
os.chdir(_ROOT)

BT = os.path.join(_ROOT, "data", "backtest")
OPS = os.path.join(_ROOT, "data", "ops")

LEDGER_81 = os.path.join(BT, "b81_lane_rescore.json")
LEDGER_108 = os.path.join(BT, "b108_rescore_corrected.json")
LEDGER_114 = os.path.join(OPS, "daemon_code_drift.json")
LEDGER_118 = os.path.join(BT, "b118_merit_bar_rebaseline.json")
LEDGER_118B = os.path.join(BT, "b118b_lane_redecision_live_parity.json")
LEDGER_119 = os.path.join(BT, "b119_exit_grid_reprice.json")
LEDGER_121 = os.path.join(BT, "b121_flat_share_replication.json")
LEDGER_121B = os.path.join(BT, "b121b_share_sweep.json")
LEDGER_121C = os.path.join(BT, "b121c_partial_call_census.json")
LEDGER_123 = os.path.join(BT, "b123_protection_share_decomposition.json")
LEDGER_129 = os.path.join(BT, "b129_timestop_reprice.json")
LEDGER_130 = os.path.join(BT, "b130_wall_clock_parity.json")
LEDGER_132 = os.path.join(BT, "b132_news_veto_real_calendar.json")


def _load(path: str) -> dict:
    with open(path) as fh:
        return json.load(fh)


def _load_probe():
    """b114's drift probe is not a package module (scripts/ has no __init__
    guarantee for it); load it by path the way its own test does."""
    spec = importlib.util.spec_from_file_location(
        "b114_probe", os.path.join(_ROOT, "scripts",
                                   "b114_daemon_code_drift.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ── the checks ─────────────────────────────────────────────────────────────
# Each returns None on success or raises AssertionError with the diff. Names
# carry the producer AND the block, so a failure says which ledger rotted.

def check_b81_verdict() -> str:
    from scripts import b81_lane_rescore as b81
    led = _load(LEDGER_81)
    got = b81.verdict(led)
    assert got == led["_verdict"], "b81.verdict() no longer reproduces _verdict"
    return f"b81 verdict ({len(got)} lanes)"


def check_b81_delta_cells() -> str:
    from scripts import b81_lane_rescore as b81
    led = _load(LEDGER_81)
    bad = []
    n = 0
    for leg in b81.LEGS:
        L = led[leg]
        for lane in b81.PROVENANCE:
            for conv, base, key in (("graded", "funnel_graded",
                                     "graded_vs_graded_funnel"),
                                    ("ungraded", "funnel_ungraded",
                                     "ungraded_vs_ungraded_funnel")):
                n += 1
                got = b81.delta(L[lane][conv], L[base])
                if got != L[lane][key]:
                    bad.append((leg, lane, conv))
    assert not bad, f"b81.delta() disagrees with {len(bad)} stored cells: {bad}"
    return f"b81 delta ({n} lane/leg/convention cells)"


def check_b118_attribution() -> str:
    from scripts import b118_merit_bar_rebaseline as b118
    led = _load(LEDGER_118)
    got = b118.attribution(led)
    assert got == led["_attribution"], ("b118.attribution() no longer "
                                        "reproduces _attribution — the drift "
                                        "decomposition behind the re-quoted "
                                        "merit bar has moved")
    return f"b118 attribution ({len(got)} legs)"


def _b119_neutrality(grid_key, arms, incumbent, block):
    from scripts import b119_exit_grid_reprice as b119
    led = _load(LEDGER_119)
    got = b119._neutrality(led, grid_key, arms, incumbent)
    assert got == led[block], f"b119._neutrality({grid_key}) != {block}"


def check_b119_tp1_neutrality() -> str:
    from scripts import b119_exit_grid_reprice as b119
    _b119_neutrality("tp1_grid", b119.TP1_ARMS, "incumbent_tp1_0.50",
                     "_tp1_neutrality")
    return "b119 tp1 neutrality"


def check_b119_share_neutrality() -> str:
    from scripts import b119_exit_grid_reprice as b119
    _b119_neutrality("share_grid", b119.SHARE_ARMS,
                     "incumbent_live_grade_fn", "_share_neutrality")
    return "b119 share neutrality"


def check_b119_frame_probe() -> str:
    from scripts import b119_exit_grid_reprice as b119
    led = _load(LEDGER_119)
    got = {leg: b119._frame_summary(led[leg]["frame_probe"]) for leg in b119.LEGS}
    assert got == led["_frame_probe"], "b119._frame_summary != _frame_probe"
    return f"b119 frame probe ({len(got)} legs)"


def check_b119_derived_blocks() -> str:
    from scripts import b119_exit_grid_reprice as b119
    led = _load(LEDGER_119)
    base = {leg: {k: led[leg]["funnel_baseline"][k] for k in
                  ("trades", "exp_R", "net_R", "maxDD_R")}
            for leg in b119.LEGS}
    assert base == led["_funnel_baseline"], "b119 _funnel_baseline block"
    ident = {leg: led[leg]["arm_identity"] for leg in b119.LEGS}
    assert ident == led["_arm_identity"], "b119 _arm_identity block"
    return "b119 funnel_baseline + arm_identity blocks"


def check_b121_verdict() -> str:
    from scripts import b121_flat_share_replication as b121
    led = _load(LEDGER_121)
    got = b121.verdict(led)
    assert got == led["_verdict"], ("b121.verdict() no longer reproduces "
                                    "_verdict — the replication claim (fresh "
                                    "pair + selection set) has moved")
    return f"b121 verdict ({len(got)} arms)"


def check_b121b_merge_and_curve() -> str:
    from scripts import b121b_share_sweep as b121b
    step1 = _load(LEDGER_121)
    led = _load(LEDGER_121B)
    merged = b121b._merge(step1, led)
    assert merged == led["_merged"], ("b121b._merge() disagrees with _merged — "
                                      "the two rounds no longer share an "
                                      "incumbent row, so the curve is spliced")
    got = b121b._curve(merged)
    assert got == led["_curve"], "b121b._curve() != _curve"
    return f"b121b merge + curve ({len(got)} legs)"


def check_b121c_ratios() -> str:
    from scripts import b121c_partial_call_census as b121c
    led = _load(LEDGER_121C)
    got = b121c.ratios(led)
    assert got == led["_ratio"], ("b121c.ratios() != _ratio — the ~3x "
                                  "multi-call cost of the share candidate has "
                                  "moved")
    return f"b121c call ratios ({len(got)} legs)"


def _b123_ledgers():
    from scripts import b123_protection_share_decomposition as b123
    return (b123, _load(LEDGER_123), _load(LEDGER_121), _load(LEDGER_121B))


def check_b123_integrity() -> str:
    b123, led, step1, step2 = _b123_ledgers()
    got = b123.integrity(led, step1, step2)
    want = led["_integrity"]
    assert {k: all(v.values()) for k, v in got.items()} == \
           {k: all(v.values()) for k, v in want.items()}, \
        "b123.integrity() disagrees with _integrity — the coupled family no " \
        "longer reproduces b121/b121b, so the decomposition splices funnels"
    assert all(all(v.values()) for v in got.values()), \
        "b123.integrity() now FAILS on the shipped ledger"
    return f"b123 integrity ({len(got)} legs x 6 checks)"


def check_b123_decomposition() -> str:
    b123, led, _s1, _s2 = _b123_ledgers()
    got = b123.decomposition(led)
    assert got == led["_decomposition"], "b123.decomposition() != _decomposition"
    return f"b123 decomposition ({len(got)} legs)"


def check_b123_neutrality() -> str:
    b123, led, _s1, _s2 = _b123_ledgers()
    got = b123.neutrality(led)
    assert got == led["_neutrality"], ("b123.neutrality() != _neutrality — the "
                                       "one-sidedness verdicts the b125 "
                                       "decision package rests on have moved")
    return f"b123 neutrality ({len(got)} axes)"


def check_b123_curves() -> str:
    b123, led, _s1, _s2 = _b123_ledgers()
    for mode, key, gate in (("partial", "_curve_coupled_live_engine",
                             "no_partial"),
                            ("tp1", "_curve_protection_always", "no_partial"),
                            ("none", "_curve_protection_never", "no_partial"),
                            ("tp1", "_curve_protection_always_age_only",
                             "age_only")):
        got = b123.share_curve(led, mode, gate=gate)
        assert got == led[key], f"b123.share_curve({mode},{gate}) != {key}"
    return "b123 all four share curves"


def check_b123_arm_identity() -> str:
    b123, led, _s1, _s2 = _b123_ledgers()
    got = b123.arm_identity_live_share(led)
    assert got == led["_arm_identity_live_share"], "b123 arm_identity block"
    assert all(v["partial_eq_tp1"] and v["partial_neq_none"]
               for v in got.values()), ("b123's arm-identity check now FAILS — "
                                        "a protection mode is not the dial it "
                                        "is named for (b122)")
    return f"b123 arm identity ({len(got)} legs)"


def check_b118b_redecide_and_margins() -> str:
    """b118b's own derivation, re-executed (b118b's test pinned the STORED
    numbers; this pins the CODE that wrote them)."""
    from scripts import b118b_lane_redecision as b118b
    led = _load(LEDGER_118B)
    got = b118b.redecide(led)
    assert got == led["_b70_redecision_live_parity"], \
        "b118b.redecide() != _b70_redecision_live_parity — b70's re-derived " \
        "answer no longer reproduces its own margins"
    stored = _load(b118b.STORED)
    bad = [leg for leg in b118b.LEGS
           if b118b.margin_table(led[leg], stored[leg])
           != led[leg]["_margins"]]
    assert not bad, f"b118b.margin_table() disagrees on {bad}"
    return f"b118b redecide + margin_table ({len(b118b.LEGS)} legs)"


def check_b108_producer_still_alive() -> str:
    """The defect that started this item, kept as a live check rather than only
    a story: b108's two pure functions must still reproduce its frozen ledger,
    and main() must still call a name the file defines."""
    import ast
    from scripts import b108_rescore_corrected as b108
    led = _load(LEDGER_108)
    assert b108.merit_bar(led) == led["_merit_bar"], \
        "b108.merit_bar() no longer reproduces its own ledger"
    assert {k: r["windows_beaten"] for k, r in
            b108.redecide_b70(led).items()} == \
        {k: r["windows_beaten"] for k, r in led["_b70_redecision"].items()}, \
        "b108.redecide_b70() no longer reproduces its own ledger"
    src = open(os.path.join(_ROOT, "scripts", "b108_rescore_corrected.py")).read()
    tree = ast.parse(src)
    defined = {n.name for n in ast.walk(tree)
               if isinstance(n, ast.FunctionDef)}
    called = {n.func.id for n in ast.walk(tree)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    dead = sorted(called - defined - set(dir(__builtins__)) - _BUILTINS)
    assert not dead, f"b108 calls names it never binds: {dead}"
    return "b108 merit_bar + redecide_b70 + no unbound call in main()"


_BUILTINS = set(dir(__import__("builtins")))


def check_b114_drift_is_arithmetic() -> str:
    """The drift ledger's two derived fields — the import closure and the
    changed-since-boot set — re-computed from the ledger's OWN recorded boot
    commit and head. If either stops matching, the drift claim is prose."""
    probe = _load_probe()
    led = _load(LEDGER_114)
    n = 0
    for name, entry in led["daemons"].items():
        if not entry.get("running"):
            continue
        n += 1
        got_closure = probe.import_closure(probe.DAEMONS[name]["entry"],
                                           probe.DAEMONS[name]["extra"])
        assert got_closure == entry["closure"], (
            f"b114 import_closure({name}) != stored closure — the probe's "
            "import walk changed shape, so 'no drift' would read as vacuous")
        got_changed = probe.changed_files(entry["boot_commit"]["sha"],
                                          entry["closure"], ref=led["head"])
        assert got_changed == entry["changed_since_boot"], (
            f"b114 changed_files({name}) != stored changed_since_boot — the "
            "drift set is not reproducible from the ledger's own commits")
    assert n, "no daemon in the ledger is marked running — the check is vacuous"
    return f"b114 closure + drift set ({n} daemons)"


def check_b129_derived_blocks() -> str:
    """b128's ship-time rule applied to the b129 ledger: every DERIVED block
    (integrity, deltas, neutrality, best_per_gate, gate_gap, verdict) is
    re-computed from the ledger's own grid by the producer's pure functions.
    The measurement half (14 arms x 7 legs of funnel replay) is NOT re-run —
    pinned by its own cross-ledger integrity check instead (b127's rule: say
    which half a check pins)."""
    from scripts import b129_timestop_reprice as b129
    led = _load(LEDGER_129)
    step1 = _load(LEDGER_121)
    step3 = _load(LEDGER_123)
    integ = b129.integrity(led, step1, step3)
    assert {k: all(v.values()) for k, v in integ.items()} == \
           {k: all(v.values()) for k, v in led["_integrity"].items()}, \
        "b129.integrity() disagrees with _integrity — the incumbent no longer " \
        "reproduces b121/b123, so every delta in this ledger is a splice"
    assert all(all(v.values()) for v in integ.values()), \
        "b129.integrity() now FAILS on the shipped ledger"
    for fn, key in ((b129.deltas, "_delta_exp_R"),
                    (lambda l: b129.deltas(l, "net_R"), "_delta_net_R"),
                    (lambda l: b129.deltas(l, "maxDD_R"), "_delta_maxDD_R"),
                    (b129.neutrality, "_neutrality"),
                    (b129.best_per_gate, "_best_per_gate"),
                    (b129.gate_gap, "_gate_gap"),
                    (b129.verdict, "_verdict")):
        got = fn(led)
        assert got == led[key], f"b129 producer {key} no longer reproduces"
    return f"b129 integrity + 6 derived blocks ({len(led['_neutrality'])} arms)"


def check_b130_derived_blocks() -> str:
    """b128's ship-time rule applied to the b130 ledger: the census, the
    clock-gap, the deltas, the neutrality rows and the verdict are pure
    functions of the shipped grid + ages, re-executed here. The measurement
    half (28 arms x 7 legs x 2 clocks of funnel replay) is NOT re-run — it is
    pinned instead by the ledger's own integrity block, which requires the BAR
    incumbent to still equal b129's frozen cell (the engine gained a dial this
    round; that equality is the proof the dial is inert at its default)."""
    from scripts import b130_wall_clock_parity as b130
    led = _load(LEDGER_130)
    assert {k: all(v.values()) for k, v in led["_integrity"].items()} == \
           {k: True for k in led["_legs"]}, \
        "b130 integrity fails on the shipped ledger — the bar incumbent no " \
        "longer reproduces b129, so the two clocks are two spliced funnels"
    for leg in led["_legs"]:
        got = b130.census(led[leg]["_ages_off"], led[leg]["_time_stop_bars"],
                          b130.LIVE_HOURS)
        assert got == led[leg]["_census"], f"b130 census {leg} no longer reproduces"
    for fn, key in ((b130.deltas, "_delta_exp_R"),
                    (b130.neutrality, "_neutrality"),
                    (b130.clock_gap, "_clock_gap"),
                    (b130.verdict, "_verdict")):
        got = fn(led)
        assert got == led[key], f"b130 producer {key} no longer reproduces"
    return (f"b130 integrity + census(7 legs) + 4 derived blocks "
            f"({len(led['_neutrality'])} arms)")


def check_b132_derived_blocks() -> str:
    """b128's ship-time rule applied to the b132 ledger: coverage, census,
    deltas, neutrality, verdict and the lever test are pure functions of the
    shipped grid + the committed event archive, re-executed here. The funnel
    half (5 arms x 7 legs) is pinned by the integrity block: the OFF arm must
    still equal b129's frozen incumbent, which is what makes the veto deltas
    comparable instead of two spliced funnels."""
    from scripts import b132_news_veto_real_calendar as b132
    led = _load(LEDGER_132)
    l129 = _load(LEDGER_129)
    assert b132.integrity(led, l129) == led["_integrity"], \
        "b132 integrity fails on the shipped ledger — the OFF arm no longer " \
        "reproduces b129, so the veto deltas are two spliced funnels"
    cal = b132.load_archive()
    for leg in b132.LEGS:
        got = b132.coverage(cal, led[leg]["_first"], led[leg]["_last"])
        assert got == led[leg]["_coverage"], f"b132 coverage {leg} moved"
    for fn, key in ((b132.vetoed_census, "_census"),
                    (b132.deltas, "_delta_exp_R"),
                    (b132.neutrality, "_neutrality"),
                    (b132.verdict, "_verdict"),
                    (b132.lever_test, "_lever")):
        got = fn(led)
        assert got == led[key], f"b132 producer {key} no longer reproduces"
    assert all(not v["is_lever"] for v in led["_lever"].values()), \
        "a b132 veto arm now reads as a lever — re-open the human-gate call"
    return (f"b132 integrity + coverage(7 legs) + census + 5 derived blocks "
            f"({len(led['_neutrality'])} arms, archive {cal['n_events']} ev)")


CHECKS = (
    check_b81_verdict,
    check_b81_delta_cells,
    check_b118_attribution,
    check_b119_tp1_neutrality,
    check_b119_share_neutrality,
    check_b119_frame_probe,
    check_b119_derived_blocks,
    check_b121_verdict,
    check_b121b_merge_and_curve,
    check_b121c_ratios,
    check_b123_integrity,
    check_b123_decomposition,
    check_b123_neutrality,
    check_b123_curves,
    check_b123_arm_identity,
    check_b118b_redecide_and_margins,
    check_b108_producer_still_alive,
    check_b114_drift_is_arithmetic,
    check_b129_derived_blocks,
    check_b130_derived_blocks,
    check_b132_derived_blocks,
)


def run() -> list[tuple[str, str | None]]:
    """Execute every check. Returns (label, error_or_None) pairs — the caller
    decides whether a failure is a printout (here) or a red test (the suite)."""
    out = []
    for fn in CHECKS:
        try:
            out.append((fn(), None))
        except Exception as exc:                      # noqa: BLE001
            out.append((fn.__name__, f"{type(exc).__name__}: {exc}"))
    return out


def main() -> int:
    results = run()
    bad = [(n, e) for n, e in results if e]
    for name, err in results:
        print(f"{'OK  ' if not err else 'FAIL'} {name}")
        if err:
            print(f"     {err}")
    print(f"\n{len(results) - len(bad)}/{len(results)} producer "
          f"reproductions exact")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
