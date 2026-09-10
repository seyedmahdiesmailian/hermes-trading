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
LEDGER_124 = os.path.join(BT, "b124_gate_exemption_census.json")
LEDGER_129 = os.path.join(BT, "b129_timestop_reprice.json")
LEDGER_130 = os.path.join(BT, "b130_wall_clock_parity.json")
LEDGER_132 = os.path.join(BT, "b132_news_veto_real_calendar.json")
LEDGER_131 = os.path.join(BT, "b131_news_veto_pricing.json")
LEDGER_160 = os.path.join(BT, "b160_reanchor_symmetry.json")
LEDGER_161 = os.path.join(BT, "b161_reanchor_symmetry_verdict.json")
LEDGER_161_W = os.path.join(BT, "b161_w1_divergence.json")
LEDGER_163 = os.path.join(BT, "b163_plan_age_census.json")
LEDGER_136 = os.path.join(BT, "b136_regime_wiring_census.json")


def _load(path: str) -> dict:
    with open(path) as fh:
        return json.load(fh)


def _load_probe():
    """b114's drift probe is not a package module (scripts/ has no __init__
    guarantee for it); load it by path the way its own test does."""
    return _load_probe_by_name("b114_daemon_code_drift.py")


def _load_probe_by_name(fname: str):
    spec = importlib.util.spec_from_file_location(
        fname[:-3], os.path.join(_ROOT, "scripts", fname))
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


def check_b124_derived_blocks() -> str:
    """b128's ship-time rule applied to the b124 ledger: the exemption census
    (re-executed from the stored `_off_rows`, the same shape b130 uses for its
    `_ages_off`), the gate gap on every metric, the neutrality rows, the
    parity decomposition, the verdict and the integrity claims are pure
    functions of the shipped grid + rows, re-run here. The measurement half
    (2 gates x 7 legs of funnel replay at live's wall limit) is NOT re-run —
    it is pinned by the ledger's own integrity block, which byte-compares both
    wall cells against b130's shipped grid and chains the bar incumbent to
    b129 through b130's claim."""
    from scripts import b124_gate_exemption_census as b124
    led = _load(LEDGER_124)
    assert {k: all(v.values()) for k, v in led["_integrity"].items()} == \
           {k: True for k in led["_legs"]}, \
        "b124 integrity fails on the shipped ledger — the wall cells no longer " \
        "match b130, so the gate gap is a splice of two funnels"
    for leg in led["_legs"]:
        got = b124.exemption_census(led[leg]["_off_rows"],
                                    led[leg]["_live_hours"],
                                    b124.INCUMBENT_STOP)
        assert got == led[leg]["_census"], \
            f"b124 census {leg} no longer reproduces from its stored rows"
    for fn, key in ((b124.gate_gap, "_gate_gap_R"),
                    (b124.neutrality, "_neutrality"),
                    (b124.parity_decomposition, "_parity_decomposition"),
                    (b124.verdict, "_verdict")):
        got = fn(led)
        assert got == led[key], f"b124 producer {key} no longer reproduces"
    for metric, rows in led["_gate_gap_other_metrics"].items():
        assert rows == b124.gate_gap(led, metric), \
            f"b124 gate gap ({metric}) no longer reproduces"
    return (f"b124 integrity + census(7 legs) + 4 derived blocks + "
            f"{len(led['_gate_gap_other_metrics'])} metric gaps")


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


def check_b131_derived_blocks() -> str:
    """b128's ship-time rule applied to the b131 ledger (b133's correction of
    b131's own ship: the ledger went out with no check at all).

    The census, the three delta tables, the neutrality rows and the verdict
    are pure functions of the shipped grid + windows + off_rows and are
    re-executed here. The measurement half (7 arms x 7 legs of funnel replay)
    is NOT re-run — it is pinned by the ledger's integrity block instead,
    which demands the OFF arm still equal b129's frozen incumbent cell: that
    equality is what makes a veto delta a delta on ONE funnel rather than two
    spliced ones.

    `veto_windows()` is deliberately NOT re-probed here: it asks the live
    evaluate_macro_filter once per bar over a calendar built from `git show`
    of committed economic_calendar.json versions, so re-running it would make
    this check depend on the git history of a data file (and on the network
    for nothing). The windows are pinned transitively instead — the census
    reads led[leg]["windows"] verbatim, so a moved window moves the census and
    fails the equality below."""
    from scripts import b131_news_veto_pricing as b131
    led = _load(LEDGER_131)
    l129 = _load(LEDGER_129)
    assert b131.integrity(led, l129) == led["_integrity"], \
        "b131 integrity fails on the shipped ledger — the OFF arm no longer " \
        "reproduces b129, so the veto deltas are two spliced funnels"
    for fn, key in ((b131.vetoed_census, "_census"),
                    (b131.deltas, "_delta_exp_R"),
                    (lambda l: b131.deltas(l, "net_R", 1), "_delta_net_R"),
                    (lambda l: b131.deltas(l, "maxDD_R", 1), "_delta_maxDD_R"),
                    (b131.neutrality, "_neutrality"),
                    (b131.verdict, "_verdict")):
        got = fn(led)
        assert got == led[key], f"b131 producer {key} no longer reproduces"
    return (f"b131 integrity + census(7 legs) + 6 derived blocks "
            f"({len(led['_neutrality'])} arms)")


def check_b161_verdict_and_census() -> str:
    """b161's ship-time rule: the merged 5-leg verdict is a PURE function of
    the five per-leg b160 ledgers and is re-executed here via the producer's
    own merge() (scripts/b161_merge_verdict.py). The measurement half (2 arms
    x 5 legs of funnel replay) is NOT re-run — each leg file's internal
    self-consistency (delta == symmetric - incumbent) is asserted inside
    merge() itself, and the W1 divergence probe ledger is pinned by shape
    arithmetic below (only_in_A + common == n_A etc), not by replaying W1.
    """
    from scripts import b161_merge_verdict as b161
    led = _load(LEDGER_161)
    got = b161.merge()
    for key in ("legs", "verdict"):
        assert got[key] == led[key], f"b161 producer no longer reproduces {key}"
    # cross-leg provenance: the merge reads the cached leg from b160's own
    # ledger — if that file moved under the merge, the pin below catches it.
    cached_src = _load(LEDGER_160)["legs"]["cached"]
    for arm in ("incumbent", "symmetric"):
        assert cached_src[arm]["exp_R"] == led["legs"]["cached"][arm]["exp_R"], \
            "b161 cached leg diverged from b160's own ledger"
    w1 = _load(LEDGER_161_W)
    assert (w1["n_incumbent"] - len(w1["only_in_incumbent"]) ==
            w1["n_symmetric"] - len(w1["only_in_symmetric"])), \
        "b161 W1 divergence probe book arithmetic is inconsistent"
    assert w1["n_incumbent"] == led["legs"]["W1"]["incumbent"]["trades"] \
        and w1["n_symmetric"] == led["legs"]["W1"]["symmetric"]["trades"], \
        "b161 W1 divergence probe disagrees with the verdict's W1 trade counts"
    return ("b161 verdict re-merged from 5 leg files + W1 probe book "
            "arithmetic (181/182 trades, 1 differing common)")


def check_b163_derived_blocks() -> str:
    """b163's ship-time rule: the plan-age census summary (per-source
    buckets, stale counts, verdict) is a PURE function of the frozen
    per-decision rows embedded in the ledger, re-executed through the
    producer's own derive() (scripts/b163_plan_age_census.py). The join half
    (reading plan_history/signals_log) is NOT re-run: those files keep
    growing and the log rotates at 200, so re-joining would certify a
    different dataset than the one measured; the rows ARE the evidence.
    Cross-check: the ledger's own row arithmetic (n_decisions per source ==
    row counts, max_age matches the rows) must be self-consistent."""
    from scripts import b163_plan_age_census as b163
    led = _load(LEDGER_163)
    got = b163.derive(led["rows"])
    for key in ("decisions_on_timeline", "decisions_on_reassess_bound",
                "stale_alignment_scores", "bound_over_cadence_pre_history",
                "stale_decisive_for_verdict", "verdict"):
        assert got[key] == led[key], f"b163 producer no longer reproduces {key}"
    cov = [r for r in led["rows"] if r["source"] == "timeline"]
    assert led["decisions_on_timeline"]["n_decisions"] == len(cov), \
        "b163 timeline-bucket count disagrees with its own rows"
    ages = [r["age_h"] for r in cov if r["age_h"] is not None]
    assert abs(max(ages) - led["decisions_on_timeline"]["max_age_h"]) < 1e-9, \
        "b163 max_age disagrees with its own rows"
    assert led["verdict"] == "FRESH_ALWAYS_KEEP_PIN_TRIPWIRE" \
        and led["stale_alignment_scores"] == 0, \
        "b163 verdict no longer matches its own stale census"
    return ("b163 census re-derived from frozen rows (52 decisions, "
            "46 timeline-joined, max age 0.2787h, 0 stale)")


def check_b143_derived_blocks() -> str:
    """b128's rule applied to the risk-lane ledger, which b127 shipped WITHOUT
    covering. b143 wrote its post-processing inline in main(), but it embeds
    the raw journal rows in the artifact, so the aggregation half is
    re-executable from the file alone — b164 extracted aggregate_journal
    into a pure function for exactly this. The PINNED half is the
    aggregation; the measurement half (bridge history, MFE recompute) is NOT
    re-run here and stays pinned by this check's own row arithmetic.

    Field-for-field equality with the frozen journal_positions is NOT
    expected: the artifact predates b152, so its rows lack the
    entry_commission column the current aggregator emits (0.0 vs absent).
    The load-bearing assertion is that realized_net — the number every
    derived block is computed from — is identical per position."""
    from scripts import b143_risk_ledger_reader as b143
    led = _load(os.path.join(BT, "b143_risk_ledger_reader.json"))
    rec = b143.aggregate_journal(led["journal_rows"])
    rec.pop("_index", None)
    frozen = {e["position_id"]: e for e in led["journal_positions"]}
    net_mismatch = sum(
        1 for k in rec
        if abs((rec[k]["realized_net"] or 0.0)
               - (frozen.get(k, {}).get("realized_net") or 0.0)) > 1e-9)
    assert set(rec) == set(frozen), (
        f"b143 aggregation covers {set(rec) ^ set(frozen)} differently")
    assert net_mismatch == 0, (
        f"b143 realized_net disagrees on {net_mismatch} positions — the "
        "frozen ledger was NOT produced by the shipped aggregator")
    d = led["_derived"]
    for key in ("rows", "status_counts", "defect_rows", "damper_mix",
                "ticket_join", "verdict", "sizing_epoch"):
        assert key in d, f"b143 _derived lost block {key}"
    # the join is re-runnable too (pure over artifact inputs): every
    # execution_log row that carries its own ticket must resolve through the
    # re-aggregated journal exactly as the shipped code does
    joined = b143.join_to_tickets(led["rows"], led["execution_log"], rec)
    assert sum(1 for j in joined if j["joinable"]) \
        == sum(1 for j in led["_derived"]["ticket_join"] if j["joinable"]), \
        "b143 ticket join no longer reproduces from its own inputs"
    return (f"b143 journal aggregation re-run from frozen rows "
            f"({len(rec)} positions, 0 realized_net mismatches)")


# ── b128 (2026-09-10): COVERAGE RATCHET — unregistered producers are DEBT ──
# b128's rule: a script that WRITES a frozen ledger under data/backtest|data/ops
# must have a reproduction check registered in CHECKS, or its name sits in the
# BASELINE below. The baseline is the burned-down debt list, so the ratchet is
# mechanical: a NEW producer script not in the baseline and not registered turns
# test_b128 red; burning the debt down means registering a check AND removing
# the token from the baseline in the SAME commit. Ownership rule: a script owns
# an artifact only if the artifact's leading bNNN[token] equals the script's own
# token, so a script that merely READS b68l_independent_windows.json (b77, b92,
# ...) is not counted as its producer.

def _registered_tokens(root: str = _ROOT) -> set[str]:
    """Tokens of the check functions actually LISTED in CHECKS — parsed with
    ast from the real top-level assignment (a text slice would pick up prose
    mentions in docstrings and comments)."""
    import ast as _ast
    import re as _re
    with open(os.path.join(root, "scripts",
                           "b127_producer_reproduction.py")) as fh:
        src = fh.read()
    tree = _ast.parse(src)
    names: list[str] = []
    for node in tree.body:
        if (isinstance(node, _ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], _ast.Name)
                and node.targets[0].id == "CHECKS"
                and isinstance(node.value, (_ast.Tuple, _ast.List))):
            names = [e.id for e in node.value.elts
                     if isinstance(e, _ast.Name)]
    return set(m.group(1) for n in names
               if (m := _re.match(r"check_(b\d+[a-z]*?)_", n + "_")))


def uncovered_writers(root: str = _ROOT) -> list[str]:
    """Deterministic coverage scan: tokens of scripts/bNNN*.py that json.dump
    an OWNED artifact existing on disk, minus tokens registered in CHECKS."""
    import glob as _glob
    import re as _re
    registered = _registered_tokens(root)
    writers: set[str] = set()
    for path in _glob.glob(os.path.join(root, "scripts", "b*_*.py")):
        with open(path) as fh:
            text = fh.read()
        if "json.dump" not in text:
            continue
        m = _re.match(r"(b\d+[a-z]*)_", os.path.basename(path))
        if not m:
            continue
        tok = m.group(1)
        for art in _re.findall(r"([A-Za-z0-9_\-]+\.json)", text):
            am = _re.match(r"(b\d+[a-z]*?)_", art)
            if not am or am.group(1) != tok:
                continue                     # read-only reference, not owned
            if (os.path.exists(os.path.join(root, "data", "backtest", art))
                    or os.path.exists(os.path.join(root, "data", "ops", art))):
                writers.add(tok)
                break
    return sorted(writers - registered,
                  key=lambda t: (int(_re.sub(r"\D", "", t)), len(t), t))


BASELINE_UNCOVERED: tuple[str, ...] = (
    "b61", "b62", "b63", "b63b", "b64", "b65", "b65b", "b66", "b66b", "b68",
    "b68b", "b68c", "b68d", "b68e", "b68f", "b68g", "b68h", "b68i", "b68j",
    "b68k", "b68l", "b68m", "b68n", "b68o", "b68p", "b68q", "b68r", "b70",
    "b71", "b77", "b79", "b80", "b89", "b92", "b93", "b109", "b111", "b112",
    "b117", "b149", "b150", "b152", "b157", "b158", "b160", "b182", "b184",
    "b185", "b186", "b187", "b189", "b193",
)


def check_b128_coverage_ratchet(root: str = _ROOT) -> str:
    """The scan must equal the baseline: nothing new unregistered (hard fail),
    and nothing registered-but-still-listed (burn-down hygiene — remove the
    token from BASELINE_UNCOVERED in the commit that adds the check)."""
    got = uncovered_writers(root)
    new = [t for t in got if t not in BASELINE_UNCOVERED]
    assert not new, (
        f"unregistered ledger producer(s) {new}: a script that writes a frozen "
        f"ledger must register a check_bNNN_* reproduction in CHECKS in the "
        f"same commit (b128 rule), or be added to BASELINE_UNCOVERED with a "
        f"reason")
    stale = [t for t in BASELINE_UNCOVERED if t not in got]
    assert not stale, (
        f"BASELINE_UNCOVERED still lists {stale} which the scan no longer "
        f"reports — drop the token(s) from the baseline (burn-down)")
    return (f"b128 coverage ratchet ({len(BASELINE_UNCOVERED)} debt tokens, "
            f"scan matches exactly)")


def check_b136_derived_blocks() -> str:
    """b136's census (the regime-wiring fix evidence) is pure arithmetic on the
    rows IT EMBEDDED in the ledger: derive(journal_walk + live_walk, size_probe,
    ...) must reproduce _derived exactly, and the row arithmetic must be
    self-consistent (fire counts sum to sample_cycles). The bridge/journal
    collection half is NOT re-run: the deal feed keeps growing, so re-collecting
    would certify a different dataset (b128's rule, same shape as b141)."""
    from scripts import b136_regime_wiring_census as b136
    led = _load(LEDGER_136)
    d = led["_derived"]
    rows = led["journal_walk"] + led["live_walk"]
    got = b136.derive(rows, led["size_probe"], d["regimes_emittable"],
                      d["regimes_wired_into_entry"])
    assert got == d, ("b136.derive() no longer reproduces _derived — the "
                      "regime-wiring verdict behind the risk.py fix moved")
    assert sum(d["regime_fire_counts"].values()) == d["sample_cycles"] == len(rows), \
        "b136 fire counts disagree with its own embedded rows"
    return (f"b136 derive + row arithmetic ({len(rows)} walk rows, "
            f"verdict {d['verdict']})")


# ── b128 (2026-09-09): the producers b127 did not cover, now registered ─────
# b128's rule: every frozen ledger with PURE post-processing gets a CHECKS
# entry in the same commit that ships it, and a producer whose derived blocks
# are re-runnable but UNREGISTERED is a silent hole. The coverage scan filed
# as MISSING by b127's own diff: b136/b137/b140/b141 (censuses feeding gate
# decisions) and b84/b86/b88 (the books ledgers behind the min_rr,
# range-kill and DEFCON decisions). Each check below pins the half that is
# pure arithmetic on the ledger's OWN embedded inputs; where a producer's
# measurement half needs a live bridge or the funnel replay, the check says
# so and pins only the re-derivable half.

LEDGER_141 = os.path.join(BT, "b141_rollover_blind_window_census.json")
LEDGER_190 = os.path.join(BT, "b190_merit_bar_live_trigger.json")
LEDGER_191 = os.path.join(BT, "b191_m5_window_lab.json")
LEDGER_194 = os.path.join(BT, "b194_veto_fire_census.json")
LEDGER_84 = os.path.join(BT, "b84_rr_gate_books.json")
LEDGER_86 = os.path.join(BT, "b86_range_kill_books.json")
LEDGER_88 = os.path.join(BT, "b88_defcon_books.json")


def check_b141_rollover_blocks() -> str:
    """The b141 census behind the pending A-vs-B human decision: its three
    derived blocks must still follow from the deals it embedded. Option A is
    decision-blocking, so a number that silently rotted here would mis-price
    a risk-gate change."""
    from scripts import b141_rollover_blind_window_census as b141
    led = _load(LEDGER_141)
    bal = float(led["_balance_used"])
    got = b141.derive(led["_deals_embedded"], bal)
    assert got == led["derived"], ("b141.derive() no longer reproduces the "
                                   "boundary rows — the rollover replay "
                                   "changed shape")
    sweep = b141.synthetic_arms(bal)
    assert sweep == led["synthetic_sweep"], ("b141.synthetic_arms() moved the "
                                             "28-step threshold sweep (the "
                                             "kill-leg arming evidence)")
    v = b141.verdict(led["derived"], led["_thresholds"])
    assert v == led["verdict"], f"b141.verdict() no longer {led['verdict']!r}"
    return (f"b141 derive + synthetic sweep + verdict "
            f"({led['_deal_count']} embedded deals, "
            f"{led['derived']['blind_count']} blind boundaries)")


def check_b190_merit_bar_blocks() -> str:
    """b190's post-processing (the coverage-gated bar + per-leg trigger delta)
    is pure arithmetic on the frozen leg rows; the funnel replay itself is NOT
    re-run (b127's rule: pin the pure half, say so). This is the ledger behind
    the CURRENT merit-bar citation, so a rot here mis-prices every future
    lab-vs-funnel comparison."""
    from scripts import b190_merit_bar_live_trigger as b190
    led = _load(LEDGER_190)
    got_bar = b190.bar(led)
    assert got_bar == led["_merit_bar_live_wired"], (
        "b190.bar() no longer reproduces _merit_bar_live_wired — the "
        "coverage gate or the leg rows moved under the shipped bar")
    got_delta = b190.trigger_delta(led)
    assert got_delta == led["_trigger_delta"], (
        "b190.trigger_delta() moved the stored wired-minus-control deltas")
    n_quotable = sum(1 for k in led["_legs"]
                     if isinstance(got_bar.get(k), float))
    return (f"b190 coverage-gated bar + trigger delta "
            f"({n_quotable}/{len(led['_legs'])} legs quotable, "
            f"mixed-sign delta intact)")


def check_b191_m5_window_blocks() -> str:
    """b191's post-processing (the M5-entry coverage-gated bar, trigger
    delta, and the b190 cross-read band) is pure arithmetic on the frozen leg
    rows; the funnel replay itself is NOT re-run (b127's rule). This is the
    ledger behind the CURRENT live-entry-TF bar citation."""
    from scripts import b191_m5_window_lab as b191
    led = _load(LEDGER_191)
    got_bar = b191.bar(led)
    assert got_bar == led["_merit_bar_m5_entry"], (
        "b191.bar() no longer reproduces _merit_bar_m5_entry — the "
        "coverage gate or the leg rows moved under the shipped M5 bar")
    got_delta = b191.trigger_delta(led)
    assert got_delta == led["_trigger_delta"], (
        "b191.trigger_delta() moved the stored wired-minus-control deltas")
    got_band = b191.band_comparison(led)
    assert got_band == led["_band_vs_b190_m15_bar"], (
        "b191.band_comparison() no longer reproduces the stored cross-read "
        "of the b190 bar")
    n_quotable = sum(1 for k in led["_legs"]
                     if isinstance(got_bar.get(k), float))
    return (f"b191 M5-entry bar + trigger delta + b190 cross-band "
            f"({n_quotable}/{len(led['_legs'])} legs quotable, "
            f"anchor {led['M5W0_anchor']['anchor_ok']})")


def check_b194_veto_fire_verdict() -> str:
    """b194's verdict block (the ALIVE_AND_INERT reading of the byte-
    identical re-price) is pure arithmetic on the censused arms plus the
    two current ledgers; the funnel replay itself is NOT re-run (b127's
    rule). This is the proof behind the CURRENT merit-bar citation — a rot
    here means the bar was re-priced on an unproven seam."""
    from scripts import b194_veto_fire_census as b194
    led = _load(LEDGER_194)
    led190 = _load(LEDGER_190)
    led191 = _load(LEDGER_191)
    got = b194.compare_to_stored(led, led190, led191)
    assert got == led["_compare"], ("b194.compare_to_stored() no longer "
                                    "reproduces the stored verdict — the "
                                    "census rows or the cited ledgers moved")
    assert got["_verdict"] == "ALIVE_AND_INERT", (
        f"b194's verdict flipped to {got['_verdict']!r}: the byte-identical "
        "merit bar is no longer proven inert-but-alive")
    return (f"b194 veto-fire verdict ALIVE_AND_INERT "
            f"({got['_total_vetoes']} vetoes, "
            f"{len(led['_arms'])} arms all row-matched)")


def _books_verdict_check(mod_name: str, script: str, ledger: str) -> str:
    """b84/b86/b88 share a shape: verdict(led) re-derives the decision cells
    from the stored leg blocks (the funnel replay itself is NOT re-run —
    b127's rule: pin the pure half, say so)."""
    mod = _load_probe_by_name(script)
    led = _load(ledger)
    got = mod.verdict(led)
    assert got == led["_verdict"], (
        f"{mod_name}.verdict() no longer reproduces its frozen ledger — the "
        "arm-vs-incumbent decision cells moved under the stored legs")
    return f"{mod_name} verdict ({len(got)} legs) exact on stored blocks"


def check_b84_rr_gate_verdict() -> str:
    return _books_verdict_check("b84", "b84_rr_gate_books.py", LEDGER_84)


def check_b86_range_kill_verdict() -> str:
    return _books_verdict_check("b86", "b86_range_kill_books.py", LEDGER_86)


def check_b88_defcon_verdict() -> str:
    return _books_verdict_check("b88", "b88_defcon_books.py", LEDGER_88)


def check_b137_self_check_still_clean() -> str:
    """b137's derive() consumes live-discovered inputs (learning floor,
    style map, DEFCON overrides) that the ledger does NOT embed, so the
    re-runnable pure half is self_check(ledger['_derived']) — the b122
    invariant set a census that cannot fail will silently rot. It must still
    return zero problems, AND the double-count it documented must still
    reproduce: if b138 dedups it, this check is the tripwire that says the
    census was retired, not drifted."""
    from scripts import b137_shrink_stack_census as b137
    led = _load(os.path.join(BT, "b137_shrink_stack_census.json"))
    problems = b137.self_check(led["_derived"])
    assert problems == [], f"b137 self_check fires: {problems}"
    return "b137 self_check clean (4 dampers, double-count reproduces)"


def check_b140_derive_and_self_check() -> str:
    """b140 embedded its full collected arms, so BOTH halves are re-runnable:
    derive() must reproduce the sizing/scoring blocks exactly and self_check()
    must still find no problems (locked regimes block, tight regimes shrink,
    scorer sees the real regime). This census is the evidence that the signal
    lane sees drawdown regimes (b140's wiring fix); drift here means the
    wiring claim rotted."""
    from scripts import b140_signal_lane_regime_census as b140
    led = _load(os.path.join(BT, "b140_signal_lane_regime_census.json"))
    got = b140.derive(led)
    assert got == led["derived"], ("b140.derive() no longer reproduces the "
                                   "frozen arms — lane sizing/scoring moved")
    problems = b140.self_check(led)
    assert problems == [], f"b140 self_check fires: {problems}"
    return (f"b140 derive + self_check ({len(got['sizing'])} arms, "
            f"0 problems)")


def check_b198_derived_blocks() -> str:
    """b198 (b188(c) census) ships rows+derive per b164: the transition
    matrix, episode-reversal count and verdict are re-executed from the
    frozen rows embedded in the ledger — the rolling reassessment_log.csv is
    NOT re-read, so the backlog number can never drift with new log rows.
    Cross-check: episode and row arithmetic must agree with the rows."""
    from scripts import b198_reassess_flip_census as b198
    led = _load(os.path.join(BT, "b198_reassess_flip_census.json"))
    got = b198.derive(led["rows"])
    for key in ("n_events", "transition_matrix", "noop_pct", "direct_flips",
                "n_episodes", "episode_reversals_via_neutral",
                "sticky_per_b188c", "flickering"):
        assert got[key] == led[key], f"b198 producer no longer reproduces {key}"
    assert sum(got["transition_matrix"].values()) == got["n_events"] == len(led["rows"]), \
        "b198 matrix/row arithmetic disagrees"
    assert led["sticky_per_b188c"] is False \
        and led["episode_reversals_via_neutral"] >= 10, \
        "b198 verdict no longer matches its own rows"
    return (f"b198 reassess census re-derived from frozen rows "
            f"({got['n_events']} events, {got['episode_reversals_via_neutral']} "
            f"episode reversals, 1 direct flip)")


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
    check_b124_derived_blocks,
    check_b131_derived_blocks,
    check_b132_derived_blocks,
    check_b161_verdict_and_census,
    check_b163_derived_blocks,
    check_b143_derived_blocks,
    check_b141_rollover_blocks,
    check_b190_merit_bar_blocks,
    check_b191_m5_window_blocks,
    check_b194_veto_fire_verdict,
    check_b84_rr_gate_verdict,
    check_b86_range_kill_verdict,
    check_b88_defcon_verdict,
    check_b137_self_check_still_clean,
    check_b140_derive_and_self_check,
    check_b198_derived_blocks,
    check_b136_derived_blocks,
    check_b128_coverage_ratchet,
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
