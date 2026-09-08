# Hermes Trading — Autopilot Backlog

Rules for every autopilot run: pick ONE item (top of list with status `todo`),
finish it, verify (tests + live cycle), move it to `done` with a dated note.
If nothing left: audit a new area, add findings here, pick the highest-value one.

**Commit discipline (b42):** ALWAYS `git add -A` then `git commit` — NEVER
`git commit -am`. `-am` stages modifications to tracked files and silently
skips NEW untracked files, so HEAD ships an import of a module that is not in
the repo (88cac1e did exactly this; every cron tick died on a fresh checkout).
tests/test_b42_tracked_imports.py now makes that loud: it scans BOTH the
working tree and the HEAD tree, plus fails on any untracked .py/.sh in the
repo (b44: shell scripts are never imported, so a .py-only scan was blind to
the untracked verify_head.sh itself).

**Post-commit verification (b44/b50, step 4b):** immediately AFTER the commit,
run `bash scripts/verify_head.sh`. It re-checks the FRESH HEAD: import checks
first, then the FULL suite inside a clean detached worktree of HEAD
(b50 — `git archive` was not enough: no .git dir, so the git-integrity tests
certified the wrong tree). It appends the verdict to logs/verify_head.log,
stamps data/ops/head_verified.json, and pages ops via Telegram if HEAD is
broken. It logs and alerts, never blocks. Since b45 that stamp is also the
PUSH GATE: cron's git_sync.sh refuses to push a HEAD the verifier called
BROKEN (or that was never verified), and fail-opens only when the stamp is
older than ~1h. The pre-commit suite can only see the working tree; only
step 4b sees what the commit actually shipped.

**Hard limits:** never execute trades, never touch DRY_RUN/positions/bridge/Windows,
never weaken risk gates. Code quality & analysis only. All changes must keep
`python3 -m unittest discover -s tests` green and pass a real `hermes_master.py` cycle.

**TRADER FOCUS (user standing order 2026-09-06):** the autopilot's job is the
AUTO-TRADER, not the harness. Priority order for picking a todo:
1. Read the trader's own code (engines/signal_parser.py, signal_decision.py,
   plan.py, defcon.py, risk.py, trade_management.py, auto_executor.py,
   orchestrator.py, smc.py, market_hours.py, cooldown.py, kill_switch.py,
   macro_filter.py, learning.py) for real defects, dead paths, contradictions
   between modules — and FIX what is found, with a backtest or live-parity
   proof where possible.
2. Research (web/literature) methods that could RAISE the funnel's exp_R or
   cut its DD; measure them in the lab (b68 protocol); wire in ONLY what
   beats the funnel on cached AND fresh sets without weakening gates.
3. Audit the ARCHITECTURE end-to-end (signal -> plan -> gate -> entry ->
   management -> exit) against backtests and the live journal; propose and
   implement structural fixes.
4. Meta/harness/tripwire/report items (b94-b104 family, report-builder fixes):
   do them ONLY when no trader item applies. Tag such todos [META].

## Active
- [x] b140 TRADER WIRING — SIGNAL LANE NEVER SEES DRAWDOWN REGIMES (b137's
      second leftover, 2026-09-08): signal_listener builds account_policy with
      regime hardcoded "normal" (or "halted" from the kill-switch) — so
      defensive/recovery sizing and STOP_TRADING_REGIMES only bite the PLAN
      lane; a signal arriving at 3% drawdown trades at full size. Wiring the
      real assess_account_policy regime into the signal lane is a TIGHTENING
      (allowed), but must ship census-style: probe each regime through the
      real evaluate_signal/executor path and assert the observable moves
      (b136/b137 template), not a hand-typed literal.
      DONE 2026-09-08 (scripts/b140_signal_lane_regime_census.py +
      tests/test_b140_signal_lane_regime.py, 13 tests). FINDING THAT CORRECTS
      b137'S PREMISE: the lane builds TWO policies — run_signal_check already
      feeds the REAL assess_account_policy regime to the SIZER (locked blocked,
      defensive/recovery shrank the lot through the real path BEFORE this
      change), so "trades at full size at 3% drawdown" was false; only the
      SCORER (check_signals -> evaluate_signal) was blind (hardcoded normal).
      FIX (tightening only): check_signals now ANDs the real policy's
      trade_allowed with the kill-switch verdict and passes the real regime
      name through (kill-switch halt still wins the name); emitter failure is
      fail-CLOSED to policy_error, never silent normal. Post-fix census: 0
      blind arms, scorer sees real regime on all 6. SIDE FINDING (filed b141):
      the first cycle of every UTC day classifies the account "normal" no
      matter what yesterday did — compute_performance_state's day-rollover
      zeroes daily_pnl/loss_streak (cold-start column in the census ledger).
- [ ] b141 TRADER WIRING — DAY-ROLLOVER BLIND WINDOW: FIRST CYCLE OF EVERY UTC
      DAY CLASSIFIES THE ACCOUNT "normal" (filed by b140, 2026-09-08):
      compute_performance_state returns daily_pnl=0.0/loss_streak=0 whenever
      the stored day != today (b88 carried only recent_closed through the
      rollover, deliberately NOT the two regime inputs), so for ONE cycle per
      day both lanes see regime "normal" no matter what yesterday did — a
      signal arriving in that window after a -3% day sizes at full risk.
      Measured: b140 census ledger `arms[].lane.cold_start_regime` (every
      deal-derived arm reads "cold"=normal, steady=defensive). FIX OPTIONS
      (tightening-neutral, needs a census first): recompute yesterday's
      daily_pnl from the 7-day deal feed on rollover instead of zeroing it,
      or keep the zero but treat "cold state" as its own regime for sizing.
      Do NOT simply widen the window to 24h — that changes DEFCON semantics.
      b102 line: shipping this must EDIT b88's pins
      (tests/test_b88_defcon_books.py::test_loss_streak_still_resets_on_rollover
      and ::test_red_cannot_fire_on_a_rollover_cycle), edited not deleted — the
      reset is a live boundary either way, so the flip has to be dated.
- [ ] b139 TRADER OBSERVABILITY — execution_style IS NOT PERSISTED ANYWHERE
      (filed by b137, 2026-09-08): the style leg is the ONLY per-trade risk
      damper (STYLE_RISK_MULT 0.5 on aggressive_* entries), yet neither
      execution_log.csv nor trade_journal.csv nor plan_history/*.json carries
      the field — b137 proved this by scanning all three ledgers (0 hits).
      Consequence: the realized shrink stack can never be audited per trade,
      and any future "was the 0.5x style damper actually applied?" question is
      unanswerable from history. FIX (small, additive, no gate change): append
      an execution_style column to the execution_log row at proposal time
      (hermes_runtime._build_proposal already has the plan in hand). Must not
      rewrite existing rows; old rows stay NULL.
      PROGRESS 2026-09-08 (b142 finding, item stays todo): the fix AS WRITTEN
      IS A NO-OP TRAP. engines/storage._append_csv_row writes the header ONLY
      when the file does not exist, and the live execution_log.csv exists with
      12 columns (pinned: every one of its 27 rows is exactly 12 fields, CRLF,
      header at git 8fbde21). Appending a 13th key therefore writes the VALUE
      but never the COLUMN NAME: csv.DictReader — the reader used by every
      consumer (learning.py's exec join, notifier/dashboards,
      scripts/weekly_report, b70, b111, b137) — folds the extra field under the
      None restkey, so the audit question stays unanswerable while the CSV
      LOOKS fixed. Measured in /tmp with the real _append_csv_row (probe
      output: row 2 -> {..., None: ['aggressive_discount_entry']}). The fix
      must therefore be a SCHEMA MIGRATION, not an extra key: either (a) teach
      _append_csv_row to rewrite the header when a row carries keys the header
      lacks (touches the shared writer used by BOTH lanes and rewrites the live
      header line — needs its own test + a b42-style pin that old rows keep
      NULL), or (b) record the damper stack per trade in a NEW sidecar ledger
      (e.g. data/xau_plan/risk_ledger.csv) written at the same call sites,
      leaving execution_log.csv byte-stable. (b) is smaller and cannot break a
      reader; pick (b) unless a consumer must see the field inline. Also note
      the signal lane's rows carry plan_id='signal' and are SKIPPED by
      learning.py's join, so a per-trade style audit needs both call sites
      (hermes_runtime ~709 and signal_listener ~589/624), not just the plan
      lane _build_proposal mentions here.
- [ ] b142 REUSABLE PROCEDURE — "ADD A COLUMN TO THE CSV LOG" IS A SCHEMA
      MIGRATION, NOT AN EXTRA KEY (filed by the b139 probe, 2026-09-08):
      engines/storage._append_csv_row writes the header ONLY when the file does
      not exist, so appending a row with a NEW key to an existing ledger writes
      the value without the column name, and csv.DictReader folds it under the
      None restkey — every consumer (learning, dashboards, weekly_report, the
      bNN censuses) then reads the file as if the field were never added. The
      CSV LOOKS fixed and the audit question stays unanswerable: the worst kind
      of observability fix. RULE: before adding a field to any existing CSV
      ledger, (1) check whether the writer can migrate the header at all,
      (2) if not, choose a sidecar ledger or a real migration with its own
      test, and (3) prove the field is READABLE by a DictReader round-trip on
      a file seeded with an OLD-schema row — never prove it by asserting the
      dict you passed to the writer. Name-carrier:
      tests/test_b142_csv_schema.py::test_b142_a_new_key_on_an_existing_ledger
      _is_invisible_to_DictReader.
- [ ] b138 [HUMAN DECISION] — loss_streak>=2 DOUBLE-COUNT: one fact, two
      modules (filed by b137, 2026-09-08): the same streak turns DEFCON YELLOW
      (risk_override 0.5) AND pushes account regime to defensive (TIGHT_REGIMES
      0.5), so entry risk lands at 0.25x from ONE condition — measured through
      the real evaluate_proposal (tight_defensive_streak probe). Removing or
      clamping either leg would LOOSEN a risk gate, which autopilot may not do
      unilaterally (hard rule). Needs mahdi's call: keep 0.25x (conservative,
      current) or deduplicate to 0.5x. b137's census + test pin the CURRENT
      behavior either way, so the ledger re-runs will show if it changed.
- [x] b137 REUSABLE PROCEDURE — WIRING CENSUS: EVERY VALUE A POLICY MODULE EMITS
      MUST BE CONSUMED BY THE PATH IT CLAIMS TO CONTROL (from b136, 2026-09-08).
      DONE 2026-09-08: shrink-stack census shipped (scripts/b137_shrink_stack_
      census.py + tests/test_b137_shrink_stack.py, 12 tests). FINDINGS: all 4
      dampers ARE wired (each moves the lot through real evaluate_proposal);
      loss_streak>=2 DOUBLE-COUNTS one fact at 0.25x (filed b138); combined
      floor 0.0625x = 0.00125 risk_pct is DEAD (silent skip) at every stop
      distance ever traded (median 10.16); execution_style un-persisted so the
      style leg is unauditable from history (filed b139); signal-lane regime
      leftover filed b140.
      b136 found "recovery" because risk.py computes a risk_multiplier that
      auto_executor never reads — the two modules agreed on a VOCABULARY
      (regime names) but not on a CONTRACT (who consumes which field). RULE:
      for each policy/decision module pair on the live path (risk->sizing,
      defcon->risk_override, learning->min_rr/risk_mult, calendar->blackout),
      run a census that (a) DISCOVERS the emitter's output range by calling the
      real function over branch-hitting probes — never by restating literals
      (b109/b122), (b) feeds each emitted value through the real consumer and
      asserts the observable (lot, gate verdict) actually MOVES, and (c) walks
      real history to report how often each state fires, so an unwired state is
      ranked by exposure, not just existence. Template:
      scripts/b136_regime_wiring_census.py + tests/test_b136_regime_wiring.py.
      Next un-censused pair by b136's own ledger: learning.py's risk_mult vs
      STYLE_RISK_MULT vs the new TIGHT_REGIMES multiplier — three independent
      shrink factors multiply into one risk_pct with no test pinning the
      COMBINED floor; check they can't stack below the broker's
      min_meaningful_lot and silently zero out the lane (sizing_too_small is a
      skip, not a trade — but a permanently-too-small lane is dead code that
      looks alive). SECOND b136 leftover, same class: signal_listener builds
      its account_policy with regime hardcoded to "normal" (or "halted" from
      the kill-switch) — so the SIGNAL lane never sees defensive/recovery at
      all and b136's tightening only bites the plan lane. Wiring drawdown
      regimes into the signal lane is a TIGHTENING and allowed; do it with a
      census-style test, not by hand.
- [ ] b135 MEASUREMENT PROCEDURE — A DECISION TRIGGER MUST NOT OR A SIGN TEST
      WITH A MAGNITUDE TEST (reusable rule from b124, 2026-09-07): b124's
      wording was "the pin fires if the exemption moves the bar ONE-SIDED **or**
      past 0.010R". An OR of a sign predicate and a size predicate is satisfied
      by a one-sided 0.003R — a directional nothing — so the round would have
      had to print "RE-BASELINE DECISION" for a gap no stored number can see.
      RULE: any trigger that gates a re-baseline/wiring decision over N legs
      must be a CONJUNCTION (one_sided AND past_tripwire) for the decision,
      with both axes REPORTED separately so a one-sided-but-tiny gap is
      disclosed as a bias direction, not escalated. This is the third variant
      of the same bug class in three days: b123 fixed the n=7 tautology
      (majority over a fixed denominator), b129's one_sided_strict fixed the
      DENOMINATOR (inert legs must not count as evidence), b124's verdict
      fixed the MAGNITUDE half (a sign test alone is not a decision trigger).
      When writing a new grid round, grep your own trigger wording for " or "
      between a sign word and a number word; if it's there, split the states
      like scripts/b124_gate_exemption_census.py::verdict does (four named
      states, pinned on synthetic axes, not just on the shipped ledger).
      Name-carrier: tests/test_b124_gate_exemption_census.py::
      TestB124TriggerIsAConjunction::
      test_b124_the_conjunction_shape_is_pinned_on_synthetic_axes.
- [ ] b134 [META] TRIAGE RULE — WHEN ONLY b50'S SUITE-INSIDE-HEAD FAILS, THE
      TREE IS RIGHT AND HEAD IS WRONG (reusable procedure from b47,
      2026-09-07): the b47 harvest found the full suite red on exactly one
      test — test_b50_suite_is_location_independent::
      test_head_passes_the_full_suite_in_a_clean_worktree — whose failure
      message quoted a b104 phantom citation living in the COMMITTED tree
      (engines/backtest.py cited test_b131_news_veto_pricing; the file
      shipped as _dial). b50 runs the suite inside a detached worktree of
      HEAD, so it is the only test that can fail while the working tree is
      green — and its failure is therefore a statement about HEAD, not about
      uncommitted work. RULE: if b50 is the ONLY failure, (1) read its
      embedded inner-suite output (it prints the real failing test), (2) run
      that test module against the working tree, (3) if it is green there,
      the defect is already fixed in the tree — commit the fix FIRST and
      re-run verify_head before touching anything else; never revert good
      tree work because HEAD is stale. Cheap version: `bash
      scripts/verify_head.sh` after every commit is exactly this check
      automated; the suite-embedded copy only exists so a forgotten step 4b
      cannot ship silently.
- [x] b118 TRADER MEASUREMENT — THE LAB BAR STILL SCORES THE FUNNEL AT A TRAIL
      LIVE DOES NOT RUN (decision opened by b117, 2026-09-07). DONE 2026-09-07:
      option (a) taken — `lab_harness.LADDER` no longer restates the trail, it
      PROBES it (`live_runner_trail()` derives multiplier AND $ floor from
      `_trail_params` in the RUNNER frame: grade A ⇒ volatility_state high ⇒
      the branch a trail can actually reach), and `trail_floor` is ON in the
      harness (measured cost: 0.000R on 4/5 legs, +0.005R on W4 — live-parity
      is practically free). UNPLANNED FINDING, BIGGER THAN THE ITEM: the quoted
      merit bar (b108's 0.285/0.202/0.206/0.227/0.222) DOES NOT REPRODUCE on
      today's engine — 0.270/107 at the identical call. Cause: b109 shipped
      LADDER_FIELDS into the backtest trade dict, measured its own delta at
      -0.015/+0.003/+0.021/-0.004/-0.001, declared the numbers "STAND" (true:
      noise-level) and never re-quoted the HEADLINE, so every document since
      2026-09-06 carried a pre-b109 bar. Proved by EXACT REPRODUCTION:
      stripping the ladder fields (the pre-b109 trade dict) reproduces b108's
      exp_R AND trade count on all five legs. NEW BAR (live-parity): cached
      0.278 | W1 0.211 | W2 0.230 | W3 0.232 | W4 0.233; total drift vs stored
      -0.007..+0.024R, all under 0.025R = an order of magnitude below the lane
      margins b70/b81/b108 decided on, so no stored ranking rots (b110's rule
      applied to the bar itself). scripts/b118_merit_bar_rebaseline.py + ledger
      data/backtest/b118_merit_bar_rebaseline.json; 12 tests in
      tests/test_b118_merit_bar_rebaseline.py (AST-pin: LADDER's trail keys must
      be NAMES not numbers; anti-vacuity: the strip MUST change at least one
      leg; the harness default MUST reproduce the ledger's parity row). b117's
      two drift pins were FLIPPED with named edits, not deleted, and b117's
      probe now pins its unfloored grid explicitly (`dict(LADDER,
      trail_floor=0.0)`) so the two ledgers cannot silently disagree about what
      "the lab bar" means. NO live change: engines/trade_management.py
      untouched. Filed b120 (the reusable rule: "the delta is noise" is NOT
      "the headline stands" — an engine change that moves a stored bar must
      re-quote it, not just certify its size).
      ORIGINAL NOTE follows.
      engines/lab_harness.LADDER.trail_after_partial = 0.50 while live HEAD's
      _trail_params balanced lane = 0.30 and live RUNNING = 0.45 (b114). Every
      funnel number in this repo — the 0.285 cached bar, the ~0.20-0.23R merit
      bar, b109's deltas — was scored at 0.50. b117 measured the trail grid is
      FLAT (max spread ~0.02R on exp_R per leg), so the drift is currently
      harmless to the RANKINGS, but it is exactly the b82 class: a harness that
      re-declares its own exit constants instead of deriving them from live.
      DECISION for a measured round: (a) re-baseline LADDER to the live value
      (import the multiplier out of _trail_params the way b117's trail_floor()
      probes the floor — one probe, no restated literal) and re-quote the merit
      bar, or (b) keep 0.50 as a documented conservative bar. Either way the
      test_b116_boot_commit_frame drift pin in tests/test_b117_trail_reprice.py
      fires when the harness is aligned — EDIT it with a named note, never
      delete it (b102's rule). Also decide whether trail_floor should default
      ON in the harness (live-parity says yes; the whole stored ledger says no —
      b110's neutrality test must run before the bar moves).
- [x] b129 TRADER RESEARCH (b107 exit side) — THE LIVE 36h TIME EXIT HAS NEVER
      BOUND ON THE FUNNEL'S OWN TRADES, AND TIGHTENING IT IS ONE-SIDEDLY WORSE
      (the b57 grid re-priced on the corrected engine, 2026-09-07). DONE
      2026-09-07: scripts/b129_timestop_reprice.py + ledger data/backtest/
      b129_timestop_reprice.json — 7 stops (0/8/16/24/48/96/144 M15 bars, 144
      DERIVED from live's 36h via lh.live_time_stop_bars, never a literal) x the
      TWO b123 time-exit gates, on cached + W1..W6, one harness, share dial
      HELD at live's grade fn. Integrity: the ts_144 @ no_partial cell is
      byte-identical to b121's and b123's incumbent rows on all seven legs
      (raises otherwise). FINDINGS: (1) THE GUARD IS INERT — ts_0 (no time exit
      at all) differs from the live 144 by EXACTLY 0.000R on all seven legs and
      holds_over_time_exit is 0 everywhere (max hold 49..112 bars vs a 144-bar
      exit, mean 8.0-11.2): across ~33,000 bars of live-parity replay the 36h
      exit has never once closed a funnel trade. That is NOT an argument to
      delete it — it is a stuck-position safety net, and the lab counts BAR age
      while live counts WALL-CLK age (weekend gaps make those different rules) →
      filed b130. Anti-vacuity pinned: the same grid DOES bite (96 bars moves
      W4 by +0.006R, 8 bars moves 5/6 windows), so the zeros are a property of
      the population, not of the code. (2) B57'S DIRECTION SURVIVES THE ENGINE
      FIX — a 2h exit loses on 5 of 6 real windows (-0.024..-0.057R, mean
      -0.031R), one-sided under b123's rule AND with both fresh windows
      agreeing. (3) The only one-sidedly BETTER arm is ts_48 (12h) at +0.003R
      mean / 0.009R max — an order of magnitude under b119's 0.10R ceiling: NO
      LEVER, the incumbent stays. (4) THE RUNNER EXEMPTION IS INERT ACROSS THE
      WHOLE GRID, not just at 144 as b123 measured at one arm: the two gates
      never disagree about where the optimum sits on any leg and the largest
      age_only-minus-no_partial gap anywhere is 0.006R — b124's parity question
      is now measured at 14 stops instead of one. TOOLING FINDING (b130's
      carrier): b123's one_sided() is a >=3/4 majority with <=1 dissent, which
      is right when every leg produces a non-zero delta, but neutrality() can
      only count non-zero legs, so on an INERT grid a single +0.006 with five
      exact zeros passes as unanimous — ts_96 is flagged one_sided on precisely
      that shape. b123's shipped flags are UNTOUCHED (b127 reproduces them;
      editing the predicate would move a frozen ledger), so the corrected rule
      lives here as one_sided_strict()/the "unanimous" flag — proportion PLUS a
      minimum-evidence floor (>= half the windows, never fewer than 3, non-zero)
      — and is pinned BOTH ways: ts_96 loses its flag, ts_8 and ts_48 keep
      theirs. b128's ship-time rule applied to this round's own ledger:
      check_b129_derived_blocks registers integrity + all six derived blocks in
      scripts/b127_producer_reproduction.py::CHECKS (19/19 reproductions exact;
      the measurement half is pinned by cross-ledger integrity, not re-run —
      b127's "say which half you pin"). NOTHING WIRED: engines/legacy_guards.py
      and engines/backtest.py untouched; a live time-stop retune is an
      exit-behaviour change = human gate (b89 class). 14 tests in
      tests/test_b129_timestop_reprice.py. HARVEST NOTE (this run): the round
      was left UNCOMMITTED by a dead run — 2 tests red (b42 untracked
      scripts/b129_timestop_reprice.py + tests/test_b129_timestop_reprice.py;
      b103 phantom: the prose filed "b130" which existed nowhere), and b128's
      registration was missing. Fixed by landing the files, filing b130 with
      its name-carrier (test_b130_a_single_non_zero_leg_is_not_one_sided_evidence)
      and adding the b129 check. No measurement re-run, no live change.
- [x] b130 TRADER PARITY NOTE — THE LAB'S TIME EXIT COUNTS BAR AGE, LIVE'S
      COUNTS WALL-CLK AGE, AND THE NEUTRALITY PREDICATE NEEDS A DENOMINATOR
      (filed by b129, 2026-09-07): two halves. (a) PARITY: b129 found the live
      36h exit is inert on the funnel's trades measured in BARS (max hold 112
      vs 144), but engines/legacy_guards.evaluate_time_exit measures
      wall-clock hours, and XAUUSD is closed Sunday night and over holiday
      gaps, so a position held across a weekend accrues age the lab cannot see
      — the two rules coincide only because the funnel's holds are short, not
      because they are the same guard. Before ANY retune of
      MAX_POSITION_AGE_HOURS, re-run the grid on a bar series with the weekend
      gap modelled (or measure live's own journal holds) and state which clock
      the decision rests on. (b) PREDICATE: b123's one_sided() fixed the n=7
      tautology but says nothing about the DENOMINATOR — on a grid where most
      arms are byte-identical to the incumbent, one non-zero leg is a 100%
      majority with zero dissent. b129's one_sided_strict() (proportion PLUS
      >= max(3, half the windows) non-zero legs) is the corrected shape and
      lives in scripts/b129_timestop_reprice.py; the generalisation is that any
      future grid whose arms can be INERT must report n_nonzero next to the
      flag, not just pos/neg. b123's shipped predicate is deliberately NOT
      edited (b127 reproduces its frozen ledger's flags), so when this ships,
      the b123 ledger's _neutrality block must be re-derived in the same commit
      and its pins EDITED, not deleted. Name-carrier:
      tests/test_b129_timestop_reprice.py::
      TestB130OneSidedNeedsNonZeroEvidence::
      test_b130_a_single_non_zero_leg_is_not_one_sided_evidence.
      DONE 2026-09-07 (this run): scripts/b130_wall_clock_parity.py + ledger
      data/backtest/b130_wall_clock_parity.json — the SAME 28-arm grid (2 b123
      gates x 7 stops x both clocks, bar incumbent DERIVED via
      lh.live_time_stop_bars, wall arm DERIVED from MAX_POSITION_AGE_HOURS,
      never literals) replayed on cached + W1..W6 with engines/backtest.py
      gaining one additive dial (time_stop_hours, default 0.0 = OFF; every
      pre-b130 call site byte-identical, pinned by re-running b129's frozen
      incumbent cell through the patched engine on all 7 legs). FINDING (a):
      B129'S "INERT" WAS AN ARTEFACT OF THE CLOCK, NOT A PROPERTY OF THE GUARD
      — the off-arm census finds 32 trades across the 7 legs at/over 36 WALL
      hours (max 54.25..78.00h) while NONE reaches 144 BARS (max bar age
      49..112): live's guard touches ~2.6% of funnel trades and b129's zero
      holds only in bar time. The VALUE still stands: wall-36h minus bar-144
      is -0.014..+0.007R per leg (mean +0.002R), far under b119's 0.10R
      ceiling, and b57's direction survives the clock change (2h loses
      one-sidedly on 5/6 real windows, mean -0.030R vs the bar clock's
      -0.031R); no wall arm earns a lever, so NO live change and the retune
      stays a human gate (b89 class). Mechanism pinned: the wall clock bites
      by FREEING THE SLOT, not by repricing — trade counts go 109→111 (cached),
      205→206 (W3), 177→178 (W4) while the cut trades' own pnl is unchanged.
      FINDING (b): every neutrality row now carries n_nonzero NEXT TO the flag
      (ts_0h: 0 non-zero legs, both predicates silent; wall ts_36h: its
      one_sided flag rests on 5/6), and b123's shipped predicate was NOT
      touched — this round ships its own grid with the denominator, so the
      "re-derive the b123 ledger" precondition is moot. b128's ship-time rule:
      check_b130_derived_blocks registers integrity + census(7 legs) + 4
      derived blocks in scripts/b127_producer_reproduction.py::CHECKS
      (20/20 reproductions exact). NOTHING WIRED: engines/legacy_guards.py
      untouched, MAX_POSITION_AGE_HOURS still 36. 19 tests in
      tests/test_b130_wall_clock_parity.py.
- [ ] b120 MEASUREMENT PROCEDURE — "THE DELTA IS NOISE" IS NOT "THE HEADLINE
      STANDS" (reusable rule from b118, 2026-09-07): b109 shipped a backtest
      engine change (LADDER_FIELDS into the trade dict), measured its own effect
      on the funnel at -0.015..+0.021R per leg, concluded the old numbers
      "STAND", and left every stored ledger and backlog note quoting the
      pre-change bar. The conclusion was right about the RANKINGS and wrong
      about the BOOKKEEPING: 25 rounds later b118 found the repo's headline
      (0.285 cached) no longer reproducible, and had to reconstruct the gap
      from scratch. RULE: whenever an engine/harness change moves a stored
      headline number, (1) re-QUOTE the headline in the same round, not just
      size the delta, (2) record the reproduction recipe (what convention
      produces the old number — b118's `quoted_pre_b109` arm is exactly that),
      and (3) state the new bar in the ledger, not only in prose. Cheap
      version: after any change to engines/backtest*.py or lab_harness.LADDER,
      re-run the funnel baseline and diff it against the stored merit bar
      before writing "stands". Name-carrier:
      tests/test_b118_merit_bar_rebaseline.py::
      TestB120StaleHeadlineRule::test_b120_* (b102's discipline: a filed item
      lives in a test name, not only in this file).
- [x] b121 TRADER MEASUREMENT — flat_0.30 REPLICATES ON TWO WINDOWS IT WAS
      NEVER RANKED ON, AND LIVE'S GRADE-GATED SHARE FINISHES LAST OR
      SECOND-LAST ON BOTH (candidate round from b119, 2026-09-07). DONE
      2026-09-07: precondition 1 (fresh draw) — scripts/b121_fresh_windows.py
      cut W5 (2025-04-07..07-09) and W6 (2025-01-06..04-07) out of the broker's
      deep history, 6000 M15 bars each, strictly before W4, overlap with
      cached/W1..W4/each other MEASURED zero, bar count and fetch depth
      IMPORTED from b68l. scripts/b121_flat_share_replication.py scored the
      same arms on all seven legs, one harness, live gate/trail/floor imported
      or derived: flat_0.30 REPLICATES (+0.028R W5, +0.035R W6, 2/2 fresh;
      still 4/4 on the selection set), stays under b119's 0.10R magnitude
      ceiling, and b66b's crowned constant-1.0 arm loses BOTH fresh windows too
      (-0.005/-0.014) — the reversal holds out of sample. THE BIGGER FINDING
      (scripts/b121b_share_sweep.py, the five share points step 1 skipped,
      merged into one curve per leg with a CHECKED merge — the incumbent row
      must be byte-identical across the two ledgers or the curve is two spliced
      funnels): the curve is monotone in the RIDING direction and live's
      grade-gated rule sits at the WRONG END of it — beaten by all nine flat
      alternatives on W1/W4/W5 (rank 9/9) and by eight of nine on W6. b66b's
      "grade-weighted sizing CONFIRMED" is not merely unsupported (b119), its
      opposite replicates. WHAT THIS ROUND REFUSES TO CLAIM: share=0.0 is best
      on cached/W1/W4/W5 (+0.066..+0.099R) and WORST on W2/W3/W6
      (-0.016..-0.051R) — mixed sign across seven windows = b110 says NO LEVER,
      and the reason is a CONFOUND, not noise: in engines/backtest.py the BE
      move and the runner trail are both gated on partial_taken > 0, so
      share=0.0 is not "more riding", it is a different TRADE (no BE, no trail,
      time-exit-eligible). Decomposition filed as b123. PRECONDITION 2 (the
      cost side) shipped as b121c below. b122's rule caught a defect in THIS
      round's own first draft: step 1's exit_reason census reported an
      IDENTICAL runner-path share for flat_0.1..0.9 and its LARGEST for the
      arm that never takes a partial — exit_reason is structurally blind to the
      share (which exit a runner reaches is the price path's business), so the
      column was void. engines/backtest.py's trade_log now carries
      partial_taken (additive; every pre-b121 row unchanged, pinned by
      TestB121CensusIsBlind so the void number can never be re-quoted).
      b121c's honest census: the candidate does NOT multiply partial calls
      (0.96-0.98x — the same trades reach TP1 either way); it multiplies the
      MULTI-CALL tail 2.8-3.2x (live closes 46/77/87 winners in ONE call at
      TP1; flat_0.30 closes zero). So the operational price is ~3x the trades
      that need trail modifies plus a final close, not the 5x the founding note
      guessed. NO live change: engines/trade_management.py untouched, a live
      exit-behaviour change is a human gate (b89 class). 25 tests in
      tests/test_b121_flat_share_replication.py (freshness of the new windows,
      exact reproduction of b119's selection rows, replication on the fresh
      pair, the magnitude ceiling, the incumbent's last-place rank, the
      merge-integrity check, the share=0.0 confound pinned in BOTH directions,
      the void-census pin, the engine-field pin, the call-ratio bands, and the
      unwired state). b119's carrier pin was EDITED with a named note (it rode
      "- [ ] b121", which this round closed — the same trap b119 fell into once)
      and now rides b123. HARVEST 2026-09-07 (d6d8891): the whole round was
      left UNCOMMITTED by a dead run — 6 tests red (b42 untracked, b50 broken
      HEAD, b102 x3: b121/b122/b123 had no name-carrier). Fixed by renaming
      three methods to carry their item (test_b121_flat_0_30_replicates...,
      test_b122_pre_b109_trade_dict..., test_b123_the_breakeven_and_trail...);
      no measurement re-run, no live change. ORIGINAL NOTE follows.
      keeping a
      0.3 runner on EVERY trade (flat share) rather than only on grade A beat
      live's rule on exp_R in 4/4 independent windows (+0.002..+0.046R), on
      net_R in 3/4, on maxDD in 3/4, with mean hold +0.8 bars and zero holds
      past the live time exit. That is NOT a claim of edge — the margins are
      b109/b110 noise-level (max 0.046R, ~1.5R per 6000 bars) and the ONLY
      reason it is worth a round is that b66b's stored verdict ("grade-weighted
      sizing CONFIRMED as real edge", 2x total R) is now known to have been the
      double-count, so the incumbent has no evidence behind it either. Before
      any wiring decision: (1) re-measure with the b68 protocol on a FRESH draw
      (b119's windows are the same bars the incumbent was chosen on — a
      one-sided delta on the selection set is not replication), (2) price the
      COST SIDE the lab cannot see: a 0.7 runner on every trade means 70% of
      every position rides past TP1, so the live partial-close path runs 5x
      more often (bridge calls, MT5 10026 rejection handling, the
      `_tp1_exit_closes_all` branch) — an operational-risk change, not just an
      R change, (3) it is a live EXIT-BEHAVIOUR change = human gate (b89 class),
      and per the standing rule the autopilot does not restart or re-wire the
      live path. Name-carrier:
      tests/test_b119_exit_grid_reprice.py::
      TestB119ShareRankingInverted::test_flat_30_percent_beats_the_grade_weighted_incumbent_one_sided
      (b102's discipline: the pin fires if the delta moves, so the round starts
      from a number that still reproduces).
- [x] b121c TRADER MEASUREMENT — THE OPERATIONAL COST OF THE SHARE CANDIDATE,
      COUNTED OFF A FIELD THAT CAN SEE IT (precondition 2 of b121, 2026-09-07).
      DONE 2026-09-07: scripts/b121c_partial_call_census.py + ledger
      data/backtest/b121c_partial_call_census.json, on the three
      decision-relevant legs (cached, W5, W6). ANSWER: the candidate's cost is
      NOT in call COUNT (partial calls 0.96-0.98x the incumbent — the same
      trades reach TP1 under either rule) but in the multi-call TAIL: trades
      that survive TP1 and so need trail modifies plus a final close go from
      24/38/38 to 67/111/123, i.e. 2.79x/2.92x/3.24x. Live today closes 46/77/87
      winners in ONE call at TP1 (share>=1.0 -> tp1_full); flat_0.30 closes
      ZERO that way. That is the honest size of the MT5 10026 /
      `_tp1_exit_closes_all` / watchdog-retry surface a wiring decision buys —
      ~3x, not the 5x b121's founding note guessed. The lab cannot see
      rejections or retries; it counts paths, and the ledger says so. Pinned by
      tests/test_b121_flat_share_replication.py::TestB121cHonestCallCensus
      (bands both ways: >2.0 and <5.0, plus exp_R rows must reproduce step 1's
      ledger exactly, so a moved engine cannot splice two funnels).
- [x] b123 TRADER MEASUREMENT — THE SHARE AXIS IS DECOMPOSED: THE PROTECTION
      CONFOUND IS REAL AND MIXED-SIGN, BUT THE SHARE EFFECT SURVIVES IT AT
      ~+0.03R WITH FRESH REPLICATION (found by b121b, 2026-09-07). DONE
      2026-09-07: engines/backtest.py gained TWO additive dials —
      `protection_mode` ("partial" = today's coupling, the default and what
      every stored number means; "tp1" = a TP1 touch arms SL->entry + trail
      whatever the share; "none" = never arms) and `time_stop_gate`
      ("no_partial" = today's exemption, "age_only" = live's actual
      age-based rule) — plus a `prot_armed` trade flag. Defaults preserve the
      coupled path EXACTLY: all six b121/b121b rows (incumbent + flat 0.0/0.3/
      0.5/0.7/1.0) reproduce byte-identically on all seven legs, dict-to-dict
      (integrity() raises otherwise). scripts/
      b123_protection_share_decomposition.py scored 18 arms x 2 gates on
      cached+W1..W6; ledger data/backtest/
      b123_protection_share_decomposition.json. FINDINGS: (1) THE CONFOUND IS
      CONFIRMED — the coupled curve's left end (share=0.0) beats the incumbent
      on 4/7 legs (+0.072..+0.094R) and loses on 3 (-0.016..-0.029R), and the
      PURE protection effect there is mixed-sign (3 pos/4 neg, mean -0.006R,
      max 0.072R): b121b's "monotone in the riding direction" curve really was
      several dials and the protection dial alone is no lever. (2) THE SHARE
      DIAL SURVIVES — with protection held constant (tp1 family), 0.3 vs 1.0
      is 6/7 legs positive (only cached -0.007R), BOTH fresh windows positive
      (+0.033/+0.049R), mean +0.030R, max +0.057R, and net_R (6/7) and maxDD
      (5/7) agree with the same trade counts. So b121's candidate is NOT dead:
      it is small, systematic, out-of-sample replicated — and the confound had
      INFLATED its apparent size (the coupled left end looked worth up to
      +0.094R; the pure share effect is ~1/3 of that). (3) THE CHEAP WIRING IS
      A MEASURED NO-OP — for live's `_partial_close_fraction` the "partial"
      and "tp1" families are byte-identical on all 7 legs (non-A tickets
      return 1.0 and close at TP1 before any arming; the A lane returns 0.3
      and arms either way), so decoupling protection while keeping the grade
      gate changes nothing; buying (2) requires changing the SHARE rule, whose
      best arm (`tp1::share_0.3`) runs a protection policy live does NOT run
      (position_daemon arms BE only after a TP FILL) — a live exit-behaviour
      change = human gate (b89 class). (4) THE TIME-EXIT EXEMPTION IS INERT ON
      THIS POPULATION — 0.000R on 15/18 arms, -0.010..+0.003R on the three
      never-protected arms that outride 144 bars, mixed sign: the stored bar
      needs no re-baseline, but the lab/live gap is real in code and is now
      pinned so it fails loudly if a future arm makes it material.
      UNPLANNED FINDING BIGGER THAN THE ITEM — the b110 neutrality test as
      written (`pos >= 3 or neg >= 3`) is a TAUTOLOGY at seven legs: the two
      sides sum to seven so one is always >= 4. The abandoned first draft of
      this round hit it — its own anti-wiring pin asserted `assertFalse` on a
      3/4 split and could never pass, and its docstring concluded "protection
      is the big axis, neither clears the bar", the REVERSE of its own ledger.
      Fixed by `one_sided()` (>=3/4 majority AND <=1 dissent — reproduces
      b110's literal exactly at n=4, where it was written) and pinned BOTH
      ways: against known splits (TestB123OneSidedRule, an independent copy of
      the predicate so the cross-check is not a function comparing itself) and
      against the shipped ledger's own flags. b120's rule applied to this
      round: the headline is re-quoted in the round that moved it. 17 tests in
      tests/test_b123_protection_decomposition.py. NO live change:
      engines/trade_management.py untouched. b121's two carrier pins were
      EDITED with named notes, not deleted (the code-shape pin now asserts the
      new flag AND the share=0.0 equivalence off this ledger; the unwired-state
      carrier moved to b125). b119's sibling carrier moved the same way.
      ORIGINAL NOTE follows.
      (found by b121b, 2026-09-07): in engines/backtest.py the BE move
      (`t["be_moved"] = True; t["sl"] = t["entry"]`) and the runner trail
      (`if trail_after_partial > 0 and t["partial_taken"] > 0`) are BOTH gated
      on a TP1 partial having happened. So sweeping partial_share from 1.0 down
      to 0.0 does not move one dial — at share=0.0 the trade loses its
      breakeven protection and its trail as well, and the curve's left end is a
      DIFFERENT TRADE, not more of the same. Measured consequence: share=0.0 is
      the best arm on cached/W1/W4/W5 (+0.066..+0.099R over the incumbent) and
      the worst on W2/W3/W6 (-0.016..-0.051R) — mixed sign across seven windows,
      which b110 reads as NO LEVER, but the reason is the confound, not noise.
      METHOD for the round that takes this: hold the share at the live
      incumbent's and vary ONLY the exit-protection dial (a BE/trail arm that
      does not require a partial — one parameter at a time, b72's pure-arm
      rule), then vary the share with the protection FIXED, on cached + W1..W6
      with the same harness, and re-run b110's neutrality test on each axis
      separately. Only a share effect that survives with protection held
      constant is a candidate at all; today's flat_0.30 delta (+0.028/+0.035R
      fresh) is small enough that a protection effect of the same size would
      fully explain it. Name-carrier:
      tests/test_b121_flat_share_replication.py::
      TestB121bCurveIsNotALever::test_the_breakeven_and_trail_are_gated_on_the_partial
      (fires the moment live decouples them, which is when this item is done).
- [ ] b125 TRADER DECISION PACKAGE (HUMAN GATE) — WIRE THE SHARE RULE ONLY IF
      THE PROTECTION POLICY CHANGE IS ACCEPTED (filed by b123, 2026-09-07):
      b123's decomposition says the pure share dial (flat 0.3 vs live's
      grade-gated 1.0) is worth ~+0.030R/trade, one-sided 6/7 legs with both
      fresh windows agreeing, net_R and maxDD pointing the same way — but the
      arm that expresses it (`tp1::share_0.3`) runs a protection policy live
      does NOT run: the lab's "tp1" mode arms SL->entry + trail on a TP1 TOUCH
      whatever the share, while position_daemon arms BE only after a TP FILL,
      so a zero-share ticket never arms. Changing the share rule therefore
      IS a live exit-behaviour change (b89 class) and stays human. The cheap
      wiring (decouple protection, keep the grade gate) is a MEASURED NO-OP —
      "partial" and "tp1" are byte-identical for live's
      `_partial_close_fraction` on all 7 legs. DECISION SET for whoever
      decides: (1) accept a BE-at-touch policy in position_daemon and wire
      flat 0.3 for the A lane, or (2) keep the incumbent and record the
      candidate as measured-but-declined. b123's pins
      (test_b123_pure_share_effect_is_one_sided_with_fresh_replication,
      TestB123NoLiveChange) and b119/b121's carrier pins are EDITED, not
      deleted, when this ships. Name-carrier:
      tests/test_b123_protection_decomposition.py::
      TestB125WiringDecision::test_b125_live_share_rule_is_still_grade_gated.
- [x] b124 TRADER PARITY NOTE — THE LAB'S TIME-EXIT PARTIAL EXEMPTION VS
      LIVE'S AGE-BASED RULE (filed by b123, 2026-09-07): engines/backtest.py
      exempts any trade that took a partial from the b57 time exit
      (`time_stop_gate="no_partial"`, the default) while
      engines/legacy_guards.evaluate_time_exit is purely age-based — a real
      parity gap in code. Measured INERT on this population: 0.000R on 15/18
      arms, -0.010..+0.003R mixed-sign on the three never-protected arms whose
      max_hold crosses 144 bars, so the stored funnel bar needs no re-baseline
      TODAY. The gap is pinned in both directions
      (test_b124_the_time_exit_exemption_costs_nothing_on_the_stored_arms
      fires if the exemption ever moves the bar one-sided or past 0.010R —
      that is when this becomes a re-baseline decision, b120's rule). When a
      future exit arm holds runners past 144 bars, re-run the b123 grid with
      `time_stop_gate="age_only"` and decide whether the lab should mirror
      live's age rule by default.
      DONE 2026-09-07 (this run): scripts/b124_gate_exemption_census.py +
      ledger data/backtest/b124_gate_exemption_census.json — the cross-tab
      b130's census left out: wall-old trades x `partial_taken`, priced at
      live's OWN limit (LIVE_HOURS imported from MAX_POSITION_AGE_HOURS, never
      restated), both gates, cached + W1..W6. FINDING 1: the exemption is NOT
      vacuous on live's clock — 14 of the 32 wall-old trades (44%) took a
      partial, so the lab's stored default spares them and live would cut them
      at 36h; on the bar clock the same census finds 0 old trades, which is
      exactly why b123/b129 could both honestly measure 0.000R and still not
      answer this. FINDING 2: all 14 spared trades are WINNERS (+$235.41,
      14/14 pnl>0; 10 of them full-close-at-TP1 tickets), so the stored bar's
      bias from this gap is directional and known — the lab keeps a winner
      alive past live's limit — the honest statement is no longer "inert".
      FINDING 3: the cost is still noise: age_only minus no_partial at 36h is
      -0.003..0.000R (mean -0.0012R), trade counts IDENTICAL at both gates on
      every leg (the cut ticket's R is substituted, not harvested), 3x UNDER
      b123's 0.010R tripwire. FINDING 4 (the tooling result): b124's own
      trigger — "one-sided OR past 0.010R" — is an OR of a sign test and a
      magnitude test, so a one-sided 0.003R (a directional nothing) satisfies
      it; the round ships the corrected CONJUNCTION shape (one_sided AND
      past_tripwire = re-baseline; one_sided alone = disclosed bias, pinned
      both ways on synthetic axes) — b129 fixed the denominator of this bug
      class, this fixes its magnitude half, which no predicate here checked.
      FINDING 5: decomposition — the total lab-vs-live time-exit gap splits
      into clock_part (b130's, mean +0.0018R) and gate_part (this, mean
      -0.0012R) with OPPOSITE signs; the total is mixed-sign and smaller than
      either part, the arithmetic reason no re-baseline is owed. Integrity:
      both wall cells byte-equal b130's grid on all 7 legs and the chain to
      b129's bar incumbent re-asserted; census re-executes from stored
      `_off_rows` (b130's shape) — check_b124_derived_blocks registered in
      b127::CHECKS (21/21 reproductions exact). NOTHING WIRED: engine default
      `time_stop_gate="no_partial"` unchanged, MAX_POSITION_AGE_HOURS still
      36, a live retune stays a human gate (b89 class). 24 tests in
      tests/test_b124_gate_exemption_census.py (incl. b123's bar-clock pin
      kept, the tripwire value shared not restated, and the name-carrier
      cross-check). Filed b135 (the reusable trigger-shape rule).
- [ ] b122 MEASUREMENT PROCEDURE — VERIFY AN ARM IS THE RULE IT IS NAMED FOR
      (reusable rule from b119, 2026-09-07): b66b's "live grade-fn share" arm
      was a lambda that called the live share function, so it LOOKED like the
      live rule and was read, quoted and defended as such for four days. It was
      not: the engine fed that function a dict that could not satisfy its
      contract, so it returned a constant. The general shape — an arm whose
      NAME describes a rule the FRAME could not execute — is invisible to every
      neutrality test, because neutrality compares numbers between arms and
      both numbers can come from the same degenerate function. RULE: before
      trusting any stored arm-vs-arm comparison, (1) enumerate the inputs the
      arm's function actually reads, (2) enumerate what the frame at the time
      actually supplied, (3) if the function's output was constant over the
      population it was scored on, the arm measured NOTHING about the rule it
      is named after, and every verdict built on it is void, not shrunk. Cheap
      version: b119's `arm_identity_census()` — replay the arm's function over
      the real signals under the old dict shape and the new one and print both
      histograms; a one-value histogram is the tell. Cross-check the b109
      lesson (a restated constant drifts) and b117's (a deleted population
      invalidates its decisions): this is the third variant, a MISLABELLED arm.
      Name-carrier: tests/test_b119_exit_grid_reprice.py::
      TestB119ArmIdentity (all four tests are the procedure, run on the frozen
      ledger every suite).
- [x] b118b TRADER MEASUREMENT — THE b108/b81/b70 LANE LEDGERS STILL CARRY THE
      PRE-b109 FUNNEL ROW (follow-up to b118, 2026-09-07): b118 re-derived the
      BAR (live-parity cached 0.278 / W1 0.211 / W2 0.230 / W3 0.232 / W4 0.233)
      but the stored lane-vs-funnel DELTAS in data/backtest/
      b108_rescore_corrected.json were computed against the stale row, so every
      `d_exp_R` there is off by b109's mixed-sign component (-0.015..+0.021).
      Max possible effect on a verdict: nr7htf's margin, which b108 already
      calls the largest shift (+0.045..+0.093), so a re-decision is unlikely to
      flip anything — but b70's standing answer should be re-derived from
      numbers that reproduce, not argued from. Method: re-run
      scripts/b108_rescore_corrected.py (it imports b81's measure_leg verbatim,
      so the harness alignment flows through automatically) and diff
      `_b70_redecision` against the stored block. LOW priority until a lane is
      actually up for wiring.
      DONE 2026-09-07: re-derived on live-parity numbers (scripts/
      b118b_lane_redecision.py imports b81.measure_leg verbatim over
      cached+W1..W4; frozen b108 ledger untouched; new ledger data/backtest/
      b118b_lane_redecision_live_parity.json) — b70's answer HOLDS AND FIRMS:
      no lane earns a slot, h4pdh drops 2/4 -> 1/4 (its W2 margin +0.003 turns
      -0.001), best surviving margin +0.051R sits inside b110's noise band.
      THE ROUND'S REAL FINDING IS ELSEWHERE: the script b118b's own method note
      said to re-run had NEVER RUN since it shipped — `redeide_b70` typo at
      b108:168, a NameError on main()'s last statement, after all measurement
      and before the json.dump; fixed, and the frozen artifact vindicated by
      EXECUTING its own merit_bar()/redecide_b70() against the shipped JSON
      (exact reproduction, pinned). Defence ships as scripts/
      b126_dead_path_scan.py (static scan for calls to unbound names, clean on
      repo+tests+bridge, pinned in both directions incl. the defect shape).
- [x] b127 TRADER HYGIENE (reusable procedure from b118b, 2026-09-07) — EVERY
      FROZEN BACKTEST LEDGER NEEDS A REPRODUCTION TEST THAT EXECUTES ITS
      PRODUCER, NOT JUST READS ITS JSON. DONE 2026-09-07: 18 reproductions
      across 9 producers (b81 verdict+40 delta cells, b108 merit_bar/
      redecide_b70/no-unbound-call, b114 closure+drift-as-git-arithmetic for
      both running daemons, b118 attribution, b118b redecide+margin_table,
      b119 both neutrality blocks+frame probe+derived blocks, b121 verdict,
      b121b merge+curve, b121c ratios, b123 integrity/decomposition/
      neutrality/4 curves/arm-identity) — ALL EXACT on the shipped ledgers, so
      no frozen number rotted; four producers needed their post-processing
      lifted verbatim into pure functions (b118 attribution, b121c ratios,
      b123 arm_identity, b114 changed_files ref param) to be executable at all,
      which is itself the finding: the arithmetic was unreachable from a test
      by construction. Pinned by tests/test_b127_producer_reproduction.py
      (checks live in scripts/b127_producer_reproduction.py, one
      implementation; anti-vacuity + missing-artifact guards). Original
      procedure follows.
      FROZEN BACKTEST LEDGER NEEDS A REPRODUCTION TEST THAT EXECUTES ITS
      PRODUCER, NOT JUST READS ITS JSON. b108 shipped a NameError in main()'s
      LAST statement and no test noticed for a day, because every b108 test
      reads the artifact and none touches the code that makes it (b114/b116's
      disease in a new costume: an artifact certifying a number, not the code
      producing it). b126's static scan catches only UNBOUND NAMES; it cannot
      see a KeyError on a dict-shape change or a wrong constant. Procedure:
      for each producer script with a frozen ledger (b81_lane_rescore,
      b118_merit_bar_rebaseline, b119_exit_grid_reprice,
      b123_protection_share_decomposition, b114_daemon_code_drift), add one
      test that imports the script's PURE functions and re-applies them to
      the shipped JSON requiring exact reproduction (pattern:
      tests/test_b118b_lane_redecision_and_b126_dead_scan.py::
      TestB108ProducerPathIsAlive — merit_bar/redecide_b70 vs stored blocks).
      Where a producer's measurement half needs the 7-minute funnel replay,
      pin only the pure post-processing half and say so in the test docstring.
      Do NOT re-run producer mains() in tests (they overwrite frozen ledgers);
      b118b's write-a-new-ledger-import-the-machinery pattern is the way.
- [ ] b128 TRADER HYGIENE (reusable procedure from b127, 2026-09-07) — EVERY
      NEW FROZEN LEDGER MUST REGISTER A CHECK IN scripts/
      b127_producer_reproduction.py::CHECKS AT SHIP TIME, AND THE PRODUCERS
      b127 DID NOT COVER GET ADDED THE SAME WAY. b127 pinned 9 producers / 18
      checks; the coverage scan it shipped (enumerate scripts/*.py that
      json.dump a data/backtest or data/ops artifact, diff against CHECKS)
      lists the rest — mostly producers whose ONLY derived numbers live inline
      in main(). b127's finding generalises into the rule: post-processing
      arithmetic written inline in main() is UNREACHABLE from any test by
      construction, so a new producer must write its derived blocks as a pure
      function of the ledger dict from day one and register it in CHECKS in
      the same commit.
- [x] b119 TRADER RESEARCH — b66's "EXIT GEOMETRY IS LOCALLY OPTIMAL" WAS ALSO
      PRICED ON THE PHANTOM RUNNER (reusable procedure from b117, 2026-09-07).
      DONE 2026-09-07: b66b's load-bearing verdict is not merely smaller under
      the corrected engine, it is INVERTED, and the arm it crowned never
      existed. ARM IDENTITY (measured over the real funnel signals, not argued):
      b66b's "live grade-fn share" passed `_partial_close_fraction` into an
      engine whose trade dict carried none of the four ladder fields, so
      `rr_remaining` defaulted to 0.0 and the function returned the CONSTANT 1.0
      on EVERY call — 306/306 cached, 536/536 W1, 523/523 W2, 737/737 W3,
      578/578 W4. Post-b109 the same function returns 0.3 for the A lane
      (84/306 cached), so live's incumbent is a THIRD rule that had never been
      scored. The frozen b66b ledger carries the phantom-population signature
      itself: four different share rules, IDENTICAL trade counts and IDENTICAL
      win rates (303/62.7% M5, 338/63.6% M15), total_r swinging 91.5->184.3R —
      a sizing rule cannot reprice a closed ticket without changing which
      tickets get taken, so that 2x "edge" WAS the b105 double-count.
      RE-PRICED (scripts/b119_exit_grid_reprice.py, cached+W1..W4, one harness,
      live grade gate/min_rr imported, trail + $ floor derived per b118, ledger
      data/backtest/b119_exit_grid_reprice.json): the constant-1.0 arm b66b
      actually scored now LOSES to the real grade fn on exp_R in 4/4 windows
      (-0.005..-0.024R) — keeping a runner is worth ~0.01R/trade, not 2x total
      R — and `flat_0.30` (keep 70% riding on EVERY trade) BEATS the
      grade-weighted incumbent one-sided: exp_R 4/4 (+0.002..+0.046), net_R 3/4,
      maxDD better on 3/4, mean hold +0.8 bars, zero holds past the time exit
      (so it is not b71's swing-in-disguise). b66's DECISION stands on its OWN
      metric (no looser TP1 arm wins net_R on all four; .70 has a -13.2R W2
      hole) but its evidence is contradicted: tp1=0.60 is positive on exp_R in
      3/4 windows — the opposite direction — bought with trade count (109->95
      cached), and ".45 wins M15 +7.0R" is refuted outright (loses exp_R 3/4,
      net_R 3/4). FRAME, not only engine: b66/b66b ran with no min_grade, so
      they scored every C-grade setup live rejects — same engine, same bars,
      exp_R 0.081..0.161 ungraded vs 0.211..0.278 graded (+0.079..+0.152R),
      while b71's missing time exit cost EXACTLY 0.000R on this family (max
      hold 112 < 144 bars on every leg, pinned with an anti-vacuity arm at a
      24-bar exit so the zero means something). NO live change:
      engines/trade_management.py untouched; flat_0.30 is a CANDIDATE for its
      own measured round + a human gate decision (b89 class), not something a
      probe wires in. 24 tests in tests/test_b119_exit_grid_reprice.py: the
      incumbent arms of BOTH grids must reproduce b118's live-parity bar
      exactly (cross-ledger integrity), the census must stay constant-1.0
      pre-b109 / discriminating post-b109 with the delta equal to the A-grade
      count, the frozen b66b ledger's identical-n/identical-WR signature is
      re-read every run, the reversal is pinned on BOTH metrics with magnitude
      ceilings (a 2x-scale gap reappearing = the double-count is back), the
      probe is pinned read-only, and the UNWIRED state is pinned via b121's
      open marker (the first draft pinned b119's own todo marker and went red
      the moment step 3 marked it done — b114's "a suite that punishes the fix
      trains people to delete the test", caught by verify_head, not by me).
      Filed b121 (the candidate round) + b122 (reusable rule:
      before trusting a stored arm-vs-arm comparison, verify the arms were
      DIFFERENT functions in the frame that ran — an arm named after a rule it
      could not execute is the b109 disease wearing a decision's clothes).
      ORIGINAL NOTE follows.
      b117 re-priced ONE pre-b105 exit decision (b65's trail) and its evidence
      shrank ~15x. The same deletion applies to the whole b55-b66 exit family,
      which ran on the engine where _partial_close_fraction returned a constant
      1.0 AND a phantom full-size runner survived every TP1 close. Specifically
      suspect: b66's TP1-step grid (tp1_position arms — the phantom runner rode
      to the final TP under every step, inflating high-tp1 arms), b66b's
      "grade-weighted partial sizing CONFIRMED as real edge" (flat 30/50/70%
      arms kept a runner post-b105 while the grade fn closes the ticket at
      share>=1.0 — the comparison is now between DIFFERENT position models),
      and b56/b57/b61's arms. RULE (generalising b83): when an engine fix
      deletes a POPULATION rather than shifting a number, every stored decision
      whose evidence was measured ON that population must be re-priced, not
      just re-baselined. Method: reuse scripts/b117_trail_reprice.py's shape —
      import b81.funnel_fn + lh.run_arm, arms differ in ONE exit parameter,
      cached + W1..W4, verdict by b110's neutrality test (one-sided across >=3
      windows = contaminated). Expect the b66b verdict to be the load-bearing
      one: it is the only exit-side finding that claims REAL EDGE rather than
      local optimality.
- [x] b114 TRADER ARCHITECTURE AUDIT — THE LONG-LIVED DAEMONS RUN CODE NO TEST
      CERTIFIES (found by b111's harvest, 2026-09-07). DONE 2026-09-07:
      position_daemon booted 2026-09-03T14:45:01Z, 17 SECONDS before 31c64f7
      (b65 balanced runner trail 0.45R→0.30R), so production has managed every
      position with the looser trail while the funnel, the tests and this file
      quoted 0.30R; signal_daemon booted 2026-09-04T18:44:16Z, 1 SECOND before
      c32f4e8 (b74g non-gold instrument rejection in the LIVE listener). Both
      closures also miss d3a0ba0 (b109 ladder_fields), 1698e7d (b106
      computed_rr), and the watchdog misses 5c17f28 (b89 defcon UNITS note) +
      6b65ef1 (learning journal migration); the signal path misses d0a7122
      (b88 DEFCON rollover blind-cycle fix — a live gate). Python binds at
      import and Restart=always only fires on a crash, so a committed exit-path
      fix is INERT until a restart, and nothing recorded the boot commit: every
      audit reads the working tree and describes behaviour production does not
      have. scripts/b114_daemon_code_drift.py measures it read-only (ps boot
      time → boot commit → transitive import closure → files changed since
      boot); ledger data/ops/daemon_code_drift.json (live) +
      daemon_code_drift_b114_finding.json (frozen evidence). 8 tests in
      tests/test_b114_daemon_code_drift.py: machinery pins re-derive the drift
      from the OS each run (so the ledger cannot be a hand-written claim), and
      the historical pins read the FROZEN artifact so the restart (b115) cannot
      delete the evidence. NO restart performed here: it is a live-path
      operation, filed as b115.
- [x] b117 TRADER CODE REVIEW — THE b65 TRAIL DECISION WAS PRICED ON A
      POPULATION THAT NO LONGER EXISTS (found by b114's drift audit + b110's
      neutrality rule, 2026-09-07). DONE 2026-09-07: THREE runner-trail values
      were in play and nobody had priced them against each other — live HEAD
      0.30 (_trail_params, b65), live RUNNING 0.45 (b114: the watchdog booted
      17s before 31c64f7, so production never ran 0.30 once), and the LAB BAR
      0.50 (engines/lab_harness.LADDER — the value every funnel number in this
      repo was measured with, b80/b81/b108's merit bar included). Worse than
      the drift: b65's sweep ran on the PRE-b105 engine, where
      _partial_close_fraction returned the constant 1.0 and backtest.py kept a
      PHANTOM full-size runner alive after every TP1 fill, so the trail touched
      EVERY trade. Post-b105 a share>=1.0 TP1 close closes the ticket
      (tp1_full) and the only population a trail can act on is the strong-runner
      lane = setup_grade=='A' (b109's collapse), measured here at 20-27% of
      gate-passed signals. scripts/b117_trail_reprice.py (arms differ ONLY in
      trail_after_partial; same bars, same engine, same harness, same live
      grade gate; ledger data/backtest/b117_trail_reprice.json): DIRECTION
      SURVIVES — 0.30 beats 0.45 on net_R in 4/4 independent windows (+0.6/+1.3/
      +0.8/+2.4R) — but MAGNITUDE IS GONE: b65 quoted +10.6R (M5) / +22.1R
      (M15), the honest effect is +0.6..+2.4R per 6000 bars, ~1/15th, so b65's
      win was ~93% the phantom runner b105 deleted. NOT ONE-SIDED (b110's test):
      no-trail beats 0.30 on cached exp_R (0.284 vs 0.278) and on W1 (0.227 vs
      0.211) while 0.80 wins W1's net_R — the exit grid is FLAT in the trail
      dimension, so the trail is NOT a lever and the real cost of leaving b115
      un-restarted is ~1R per 6000 bars, not 20R (this re-prices b115's
      "consequence while un-restarted" note). SECOND GAP FOUND IN THE SAME READ:
      live returns max(risk*mult, $3.00) — an ABSOLUTE floor the lab never
      modelled, so the lab trailed TIGHTER than live on small-risk trades; binds
      on 61.8% of W4's trades (median risk $8.84), 7.3% cached, 0% W2 — a
      regime-dependent parity gap. engines/backtest.py + backtest_real.run_backtest
      now carry trail_floor (DEFAULT 0.0: every pre-b117 number byte-identical,
      pinned by AST) and the ledger scores both grids; with the floor modelled
      the verdict is unchanged (grid stays flat, max spread <0.06R). NO live
      change shipped. 17 tests in tests/test_b117_trail_reprice.py: the boot-tree
      0.45 claim is re-derived from immutable git objects (b116's frame rule —
      this item is argued in the boot-commit frame and says so), the runner
      census is recomputed from the real share function, the floored and
      unfloored W4 grids MUST differ (anti-vacuity: identical numbers would mean
      trail_floor is dead code) while W2's MUST be identical, and the probe is
      pinned read-only. Filed b118 (the lab bar vs live HEAD drift is now a
      decision, not a discovery).
- [ ] b115 OPERATIONS — RESTART THE TWO TRADING DAEMONS ONTO HEAD, GUARDED
      (follow-up to b114, 2026-09-07): the drift is measured, the fix is
      operational. Preconditions, all checkable: (1) `positions_list` from the
      read-only /api/positions is EMPTY (a restart mid-position hands the
      watchdog's job to hermes_runtime's fallback path — survivable, but there
      is no reason to test that on a live ticket), (2) the full suite is green
      on the HEAD being loaded, (3) restart one service at a time
      (`systemctl --user restart hermes-position`, then `hermes-signal`) and
      after each: heartbeat file data/xau_plan/watchdog_heartbeat is fresh
      (<60s), the journal/state files still parse, and
      `python3 scripts/b114_daemon_code_drift.py` reports
      changed_since_boot == [] for that daemon. Cost of NOT doing it: the
      watchdog keeps the pre-b65 0.45R trail and the signal listener keeps
      accepting non-gold instruments the parser now rejects. This run did not
      restart anything (hard rule: autopilot never touches the live trading
      path); the operator/owner decides the window. CONSEQUENCE WHILE IT STAYS
      UN-RESTARTED: the funnel already scored the 0.30R runner trail (b65's
      sweep, +11R M5/+22R M15 over 0.45R in all four independent slices) and
      live has not run it once — so the measured exit improvement is committed
      but INERT, and any "live underperforms the funnel on the runner leg"
      round should check this ledger before blaming the entry filter. Note the
      two implementations are separate: the funnel trails via
      backtest_ohlc(trail_after_partial=...), live via
      trade_management._trail_params — so the drift does NOT corrupt the funnel
      numbers, it only withholds their benefit.
      B117 RE-PRICED THIS NOTE (2026-09-07): the withheld benefit is NOT ~20R.
      b65's +10.6R/+22.1R was measured on the pre-b105 engine whose phantom
      full-size runner let the trail touch every trade; under the corrected
      engine 0.30 beats 0.45 by only +0.6..+2.4R per 6000 bars (net_R, 4/4
      windows) and the whole trail grid is FLAT (no-trail wins cached exp_R).
      So the restart is still correct hygiene — it also loads b74g's instrument
      gate, b109's ladder_fields and b106's computed_rr, which b114 found in the
      same closure — but it must NOT be sold as a ~20R exit improvement, and any
      "live underperforms the funnel on the runner leg" round should read
      data/backtest/b117_trail_reprice.json before blaming anything.
- [ ] b116 MEASUREMENT PROCEDURE — BEFORE QUOTING LIVE BEHAVIOUR, ASK WHICH
      COMMIT THE RUNNING PROCESS BOOTED FROM (reusable procedure from b114,
      2026-09-07): b113 says a census must be taken in the frame the gate runs
      in; b114 is the same disease on the TIME axis. Every audit, backlog note
      and report in this repo reads the working tree and says "live does X" —
      but position_daemon/signal_daemon are long-lived Python processes that
      bound their modules at import, so "live" means "the tree that was HEAD at
      the last restart", and Restart=always only fires after a crash. Measured
      cost: the watchdog booted 17s before the b65 trail fix and 3.5 days of
      position management ran 0.45R while every document quoted 0.30R. RULE:
      before any claim about what production does (and before any decision that
      rests on such a claim — a gate retune, a lane promotion, an "inert
      because it never fires" argument), (1) resolve the boot commit of the
      process that owns the code path (`ps -o lstart` → last commit at or
      before that time), (2) diff the process's transitive import closure
      against HEAD, (3) if anything on the path changed since boot, the claim
      describes the LAB, not the box — say so and either restart (guarded,
      b115) or re-measure in the boot tree. Cheap version:
      `python3 scripts/b114_daemon_code_drift.py` prints both daemons' boot
      commit and drifted closure files in under a second, read-only.
- [x] b112 TRADER CODE REVIEW — THE SIGNAL GATE PENALISES A WARNING FAMILY THAT
      HAS NEVER FIRED AND IGNORES THE TWO THAT HAVE (found by b106, 2026-09-06;
      spared-direction pin: tests/test_b106_parser_decision_contract.py::
      TestB106WarningCoverage::test_b112_*). DECIDED 2026-09-06 by the measured
      round the item itself demanded — NO PENALTY, no gate change, and b106's
      premise turns out to be a MEASUREMENT-FRAME ARTIFACT. scripts/
      b112_warning_frame_probe.py re-parsed all 29 journal signals in BOTH
      frames through the real parser + real gate (ledger
      data/backtest/b112_warning_frame.json): the LIVE frame (current_price>0,
      what the listener always passes when the market is open) sees
      symbol_defaulted_xauusd 15/29, no_symbol_found 0, sl_* 0 — while b106's
      OFFLINE census (parse_signal(raw) with no price) saw defaulted 4 and
      no_symbol_found 11, because the parser's `_gold_abbrev` branch only
      fires when a price is passed. And every offline no_symbol_found row has
      symbol=="" → is_valid False → the listener `continue`s BEFORE
      evaluate_signal: that family NEVER reaches the gate in any frame, so
      penalising it taxes an unreachable population. The defaulted family —
      the only one that does reach it (52% of gate-reachable) — fails the
      penalty on BOTH sides: COST = every scheme (−0.5, −1.0, Check-1-half)
      flips exactly 1/29 signals (idx 0, score 6.0→5.5), and the two signals
      that actually executed in production (idx 4, 9) don't flip because under
      the CURRENT parser they don't clear the gate even un-penalised (4:
      direction_conflict, 9: poor_rr_0.5 after b74's ladder fix — the journal
      rows are stale artefacts of an older parser); BENEFIT = the defaulted
      legs look worse in the 1358-leg channel replay (0.105R vs 0.125R, WR
      53.6% vs 70.7%, scripts/b112_defaulted_performance.py + ledger
      data/backtest/b112_defaulted_performance.json) but the split is
      CHANNEL-CONFOUNDED: 664 of 707 filled defaulted legs are radin-main,
      which contributes only 3 named-gold legs; within the channels carrying
      both populations goldfree's defaulted side is n=6 (noise) and olivex's
      is n=0 filled — no usable control anywhere. The warning encodes the
      channel's POSTING STYLE (does it type "XAUUSD"?), not trade quality.
      Check 8 stays sl_-scoped (dead-but-correct: it fires on impossible SL
      geometry, which the parser also flags with −0.1 confidence). 9 tests in
      tests/test_b112_warning_penalty_measured.py pin the frame artifact, the
      1/29 flip count, the confound floors (each floor FIRES if the sample
      grows enough to make the decision possible again), and the no-change
      shipped state; b106's spared-direction pin is untouched. 10 tests here
      (the b113 frame rule carries its own named pin,
      test_b113_a_frame_census_must_record_both_frames_side_by_side, per the
      b102 discipline that a filed item needs a name-carrier — b102's
      tripwire caught the first draft and was right).
- [x] b111 TRADER CODE REVIEW — THE TWO LIVE LADDER PRODUCERS DISAGREE ON GRADE
      DONE 2026-09-07 (shipped via STEP-0 harvest of the previous run's
      uncommitted work, verified this run: 1132 green, live cycle rc=0, plus an
      INDEPENDENT re-check of the inertness premise over 1592 real plan
      snapshots — 68 aligned+trend>=3.0, 0 with a non-continuation regime, so
      the watchdog's looser A was unreachable in the data as well as in the
      producer sweep): the three lookalike grade rules are now ONE definition
      (engines.plan.setup_grade), the watchdog's pre-b45 inline copy is gone,
      and b109's "aligning would change the live breakeven lock" premise is
      measured FALSE (scripts/b111_blast_radius_probe.py, ledger
      data/backtest/b111_blast_radius.json, 8+ tests in
      tests/test_b111_grade_rule_aligned.py). Original note follows.
      (found by b109, 2026-09-06; spared-direction pin:
      tests/test_b109_share_fn_contract.py::TestB109ProducerParity::
      test_b111_*). position_daemon.build_trade inlines a PRE-b45 grade rule:
      an A needs only aligned+trend>=3.0 (NO regime clause) and 'mixed'
      alignment reaches B, while hermes_runtime._infer_setup_grade /
      auto_executor require regime in {breakout,pullback}_continuation for an A
      and send 'mixed' to C (b45, 2026-08-31, justified by two mixed/range
      sells that netted -56.7$). In production the watchdog is alive whenever a
      position exists, so the ladder decision that ACTUALLY runs is the
      watchdog's looser rule. Measured over 1540 plan_history files
      (scripts/b109_probe_lane_reachability.py): the two rules agree on the
      strong-runner lane (0 disagreements — the collapse makes it grade-A-only
      on both sides) but differ on the WEAK-lane share (runtime 86.9% vs
      watchdog 68.1% of plans), and the weak/balanced split feeds
      _breakeven_stop: grade>=2 + momentum>=0.65 locks +0.15R instead of plain
      BE. So the watchdog locks profit on plans the canonical rule calls C.
      DECISION NEEDED (b89 class, human gate): align the watchdog onto
      _infer_setup_grade (tightening — but it changes live exit behaviour, so
      it needs its own measured round), or document the divergence as intended.
      b109 deliberately did NOT align it. Before deciding, re-run the probe:
      the runner-lane agreement is pinned at 0 disagreements (
      test_b111_the_two_rules_agree_on_the_runner_lane_and_differ_on_weak) and
      the weak-lane drift is pinned as a 5%-40% band (measured 293/1558 =
      18.8%), so either rule changing shape fires instead of rotting.
- [x] b109 TRADER CODE REVIEW — THE BACKTEST'S "LIVE" LADDER IS A CONSTANT:
      SHIPPED 2026-09-06: strategy_signal now emits the live ladder fields
      through ONE shared derivation (engines.trade_management.ladder_fields,
      called by hermes_runtime.cycle + position_daemon.build_trade + the
      backtest), engines/backtest.py carries them into the trade dict, and the
      re-measurement (scripts/b109_ladder_parity_rescore.py, ledger
      data/backtest/b109_ladder_parity_rescore.json) says the A-grade runner
      leg is WORTH NOTHING: d_exp_R -0.015 cached / +0.003 W1 / +0.021 W2 /
      -0.004 W3 / -0.001 W4 — MIXED SIGN, max |delta| 0.021R, maxDD_R
      unchanged on all five legs, so by b110's neutrality rule the
      b80/b81/b108 numbers and the ~0.20-0.23R merit bar STAND. Two structural
      findings came out of the read-through: (a) the four-way AND in
      _partial_close_fraction COLLAPSES to `setup_grade == 'A'` (both producers
      derive all four inputs from alignment+trend_strength and hardcode
      rr_remaining=2.0 — verified over every distinct (alignment,trend,regime)
      in 1540 real plans, scripts/b109_probe_lane_reachability.py), so b55's
      "a thesis the parity backtest cannot model" was one threshold, and the
      `rr_remaining<=1.2` weak clause has been dead since it was written; (b)
      the two live producers do NOT share a grade rule — filed as b111.
      b108's contract tests were EDITED to certify the fix from both
      directions (fields arrive / ladder discriminates / lab arms keep their
      shape), not deleted. 14 tests in tests/test_b109_share_fn_contract.py,
      1105 green, live cycle OK. Original note follows.
      engines/backtest.py's trade dict does not satisfy
      trade_management._partial_close_fraction's contract (found by b108,
      2026-09-06, pinned by tests/test_b109_share_fn_contract.py — EDIT those
      tests, do not delete them, when this ships). lab_harness.LADDER passes
      the REAL live function and backtest.py's b55 comment claims it does so
      "so it can read grade AND momentum/rr/structure from it" — it cannot:
      live reads setup_grade/momentum_strength/rr_remaining/structure_state,
      the backtest dict supplies grade/style/entry/sl/tp/... and NONE of the
      four. rr_remaining therefore defaults to 0.0, which trips the
      `rr_remaining <= 1.2` branch unconditionally, so the function returns
      (1.0, 'weak_full_exit_at_tp1') on EVERY call — measured: 935/935 calls
      on the cached funnel, including all 84 A-grade signals. WHY NO NUMBER
      MOVED YET: live's weak AND balanced lanes both return 1.0, and the only
      lane that returns 0.3 (strong-runner: grade A + momentum>=0.8 + rr>=2 +
      healthy) has never fired live (0 occurrences in data/ or logs/, matching
      b55's note), so the constant currently agrees with live by luck, not by
      construction. DO NOT "fix" it by passing the fields through without a
      re-measurement: the A-grade book would start carrying a 0.3 runner leg
      the funnel has never been scored with, invalidating b80/b81/b108. Plan:
      (1) make strategy_signal emit the four live fields from the SAME plan
      quality dict hermes_runtime reads (trend_strength/alignment), so the
      backtest trade dict is built from live semantics, not a lookalike;
      (2) re-run the b108 funnel + lane set and report the A-grade delta;
      (3) only then decide whether the strong-runner lane is worth modelling
      at all — if it has never fired live in 17+ positions, the honest fix may
      be to DELETE the 0.3 branch from live rather than teach the backtest to
      simulate it (a human gate decision, b89 class).
- [x] b108 TRADER RESEARCH — RE-MEASURE THE FUNNEL + b68 MERIT BAR UNDER THE
      b105-CORRECTED ENGINE. b105 found engines/backtest.py double-counted the
      runner leg (full-size runner booked on top of the realized partial) and
      kept a phantom position alive after a share>=1.0 TP1 close (blocking real
      entries). Fixed + pinned by tests/test_b105_partial_parity.py. On the
      cached 3000 M15 funnel the corrected exp_R is 0.285 (was 0.766), net 463
      (was 1266) — the 0.854R merit bar every b68 round compared against was
      inflated by this bug, and because the inflation tracks TP1-hit-rate it
      was NOT neutral across arms. Re-run the funnel baseline AND the b70
      decision-set arms (pdh/nr7/dayext/h4t lanes) on the SAME windows through
      the corrected engine; re-derive the merit bar; re-decide b70. NO live
      change until the honest numbers are in — this is analysis, not wiring.
      DONE 2026-09-06 (scripts/b108_rescore_corrected.py re-runs b81's
      measure_leg/verdict VERBATIM on cached+W1..W4; ledger
      data/backtest/b108_rescore_corrected.json; 22 tests in
      tests/test_b108_rescore_corrected.py): THE FUNNEL IS WORTH LESS THAN HALF
      OF WHAT WE QUOTED — graded exp_R cached 0.796->0.285, W1 0.676->0.202,
      W2 0.662->0.206, W3 0.767->0.227, W4 0.745->0.222 (net_R 2.5-3.2x lower,
      DD WORSE on 4/5 legs, +5..+16 trades from the freed slot); the new merit
      bar is ~0.20-0.23R on independent windows, 0.285 cached. THE CORRECTION
      IS NOT NEUTRAL, CONFIRMED: nr7htf's margin over the funnel shifts +0.045
      to +0.093R on ALL FOUR windows (one-sided = systematic), the pdh family
      shifts are mixed-sign and smaller; lane_h4pdh's W4 flips from a win
      (+0.019R) to a loss (-0.002R) on the correction alone. B70 RE-DECIDED:
      windows_beaten fall 2->1 (gated_pdh_dayext), 3->2 (h4pdh), 2->1
      (runway), 0->0 (nr7htf) — no lane replicates, and nr7htf now LOSES net_R
      on W1/W2 too (b81's trap got worse). Every remaining lane margin is
      <=0.05R. b70's standing answer ("no lane earns a slot") stands on honest
      numbers, and the side-finding b109 (the ladder's live share fn is fed a
      dict that cannot satisfy its contract — constant 1.0) was filed from the
      same read-through.
- [x] b106 TRADER CODE REVIEW — signal_parser.py vs signal_decision.py: the
      parser's fields vs what the decision layer actually consumes; find
      silently-dropped fields (parsed but never used) and used-but-never-set
      ones; reconcile. Backtest any behavior change with run_backtest.
      DONE 2026-09-06: full census of the boundary, both directions, over the
      real code and the 28-signal journal. ONE used-but-never-set key found and
      fixed: signal_decision reads `signal.get("rr_ratio",0) or
      signal.get("computed_rr",0)` but to_dict() folded computed_rr INTO
      rr_ratio and never emitted the key, so the second operand always yielded
      the default 0 — to_dict() now emits it (PROVABLY INERT: rr_ratio is
      `rr_ratio or computed_rr`, so a falsy rr_ratio means a falsy
      computed_rr; pinned by test_b106_the_emitted_key_is_inert so if the fold
      ever changes, the change is loud). THREE further findings, all measured
      not guessed: (a) the decision layer's own inline RR fallback (Check 5's
      second branch, recompute from entry/sl/tp) is DEAD CODE BY CONSTRUCTION —
      reached 0/28 signals, because the parser already owns that rule; it is
      b109's three-lookalikes disease one step earlier in the pipeline, left in
      place and pinned unreachable rather than deleted (a deletion cannot change
      behaviour but the pin is what makes leaving it safe); (b) the gate's
      warning penalty is sl_-only while the two families that actually fire
      (symbol_defaulted_xauusd 4/28, no_symbol_found 11/28, sl_* 0/28) cost
      nothing, and a defaulted symbol still earns Check 1's full +1.0 — that is
      a live-gate TIGHTENING so it is filed as b112 with a spared-direction pin
      (test_b112_*), not taken; (c) five fields are parsed, emitted and read by
      NO downstream module (entries, tp2, tps, ladder_rr, order_type — grep
      over every non-test non-legacy consumer) and are KEPT on purpose because
      b72 wants the ladder_rr evidence to accumulate before the gate is retuned
      and radin_replay feeds the same dict to the same gate; the census is
      pinned so a future round decides with the list in hand. NO BEHAVIOUR
      CHANGE, so no backtest was owed: the item's own rule was "backtest any
      behavior change", and the only shipped change adds a key nobody reads
      yet. THE REUSABLE PART is the generic tripwire
      test_b106_every_key_the_decision_layer_reads_is_emitted_by_the_parser:
      it derives the producer's key set from to_dict()'s own AST and the
      consumer's from signal_decision's source, so ANY future read of a key the
      boundary does not emit fails — verified to bite (removing the new line
      makes it report ['computed_rr']). 8 tests in
      tests/test_b106_parser_decision_contract.py, 1112 green, live cycle OK.
- [x] b107 RESEARCH ROUND — exit-side improvement: funnel edge is the ENTRY
      filter (b68r4 finding); search literature for exit/TP-ladder methods
      (A-trailing variants, time-stops, news-veto) and MEASURE exp_R/DD in
      the lab on cached+fresh sets. Report numbers; wire nothing without the
      b68 merit bar.
      PROGRESS 2026-09-07: the TIME-STOP leg of this mandate is DONE and
      reported — b129 re-priced the whole b57 grid on the corrected live-parity
      engine over cached+W1..W6 and found the live 36h exit INERT (0.000R for
      removing it entirely), tightening one-sidedly worse, and no arm above
      b119's 0.10R ceiling. The A-TRAILING leg was measured by b117 (grid FLAT)
      and the TP-LADDER legs by b119/b121/b123. What remains unmeasured under
      this mandate: the NEWS-VETO leg (engines/legacy_guards.evaluate_news_lock
      — b31 fixed its shape, no round has ever priced whether the veto earns its
      keep on the funnel) and any exit method from the literature not yet in the
      lab. Keep this item open until the news-veto is priced.
      PROGRESS 2026-09-07 (news-veto leg, cheap-version start): the veto's
      BLAST RADIUS is now measured from the git calendar snapshots (union of
      all 27 committed economic_calendar.json versions, Aug23–Sep12): 14
      strict-high USD/XAU events at 6 unique timestamps (08-26 12:30, 08-28
      14:00, 09-01 14:00, 09-04 12:30, 09-10 12:30, 09-11 12:30 UTC) → ±30min
      blackout = ~6h of veto over 21 days (~1.2% of wall time, all inside the
      US session). What BLOCKS finishing the pricing: the stored funnel
      ledgers (ab_aggressive_data, b121/b129/b130 artifacts) keep per-arm
      AGGREGATES only — no per-trade entry timestamps — so the b110 cheap
      version (arithmetic on two existing ledgers) is impossible for a
      TIME-based gate; it needs one fresh run_backtest pair (veto ON/OFF) on
      the b121 windows. Filed as b131 (ledger entry-time stamp + the ON/OFF
      pair producer). No gate was weakened; nothing wired.
      CLOSED 2026-09-07 (b47): the news-veto leg is now PRICED on a real
      archive — b131 built the dial + clock fields, b132 recovered the
      ForexFactory Wayback archive, b133's prefix-query fix made it deep
      (2025-01-19.., all 7 legs covered). ANSWER: at live's ±30min the veto
      is one-sided NEGATIVE on exp_R (mean -0.0094R; the deleted entries were
      winners on 5 of 6 evidence legs) and no width is a lever — it stays
      live insurance (fail-closed on calendar outage), never a merit claim.
      Every leg of b107's mandate (time-stops b129, A-trailing b117,
      TP-ladder b119/b121/b123, news-veto b131-b133) is now measured.
- [x] b131 TRADER RESEARCH (from b107 news-veto leg, 2026-09-07) — PRICE THE
      NEWS-VETO ON THE FUNNEL: run_backtest has no time-of-day veto parameter
      and the stored ledgers carry NO per-trade entry timestamps, so a
      time-based gate cannot be priced by ledger arithmetic (b110 cheap
      version fails for TIME gates — reusable lesson: an aggregate-only ledger
      can only re-price LEVEL-based arms). Procedure: (1) add an additive
      `news_veto_windows` parameter to engines/backtest_real.run_backtest
      (default None = byte-identical, same discipline as b130's
      time_stop_hours), (2) stamp each trade's entry bar time into the ledger
      so future time-gate questions become arithmetic, (3) run the ON/OFF pair
      on the b121 fresh windows (W1..W6) using the veto calendar already
      measured in b107's progress note (6 unique high-impact USD timestamps,
      ±30min), (4) price by NEUTRALITY per b110 (delta exp_R vs delta net_R
      vs delta maxDD_R per window, one-sided test across >=3 windows) and
      report; wire nothing without the b68 merit bar.
      DONE 2026-09-07 (b131 run): FINDING — the live ±30min news veto is
      INERT on the funnel: the only historical calendar that exists (git
      union of committed economic_calendar.json = Aug23..Sep12 2026, 6 unique
      high-impact timestamps) intersects exactly 2 of 1243 funnel entries
      (both in `cached`), Δexp_R = -0.026R there and 0.000 on all six W-legs;
      no arm clears b119's 0.10R ceiling even at a synthetic ±24h NFP-cadence
      veto (max 0.026R, mean +0.009R). The veto costs nothing measurable and
      buys nothing measurable on this data — it stays as live insurance
      (fail-closed on calendar outage), nothing re-tuned. Steps 1+2 shipped:
      engines/backtest.py gained the additive `news_veto_windows` dial
      (applied after signal_fn, mirroring auto_executor Check 7's order) and
      trade_log now carries entry_time/exit_time per trade; producer
      scripts/b131_news_veto_pricing.py (veto windows probed through the REAL
      evaluate_macro_filter = parity by construction; OFF arm byte-identical
      to b129 incumbent on all 7 legs); tests/test_b131_news_veto_dial.py
      pins empty-dial no-op, exact-entry removal, Check-7 order, clock
      fields. CAVEAT (b131's own step-3 premise was wrong): the b107 note's
      6 timestamps do NOT intersect W1..W6 at all — pricing the veto on the
      fresh windows needs a real historical event archive (FF yearly feeds
      404; TradingView API 403), so the W-leg numbers are coverage-zero,
      not evidence of no-effect there. Filed b132 for the archive problem.
- [x] b132 TRADER RESEARCH PREREQ — GET A REAL HISTORICAL EVENT CALENDAR
      ARCHIVE (from b131, 2026-09-07): b131 proved the veto question CANNOT
      be answered on W1..W6 with the data on this box — the git-union
      calendar covers only Aug23..Sep12 2026, so six of seven legs have
      coverage-zero and "inert" is a data artifact there, not a finding.
      Probed and dead: nfs.faireconomy.media yearly feeds (404 for 2024/25/26
      and week variants), TradingView calendar API (403), finnhub (needs key).
      Procedure: (a) find a reachable free historical-events source (candidates
      to test: investing.com calendar export via browser tool, myfxbook,
      forexfactory's weekly JSONs captured week-by-week going forward, or
      akshare/pandas_datareader-style packages if installable offline),
      (b) store it as data/calendar/events_archive_<range>.json in the SAME
      event shape economic_calendar.py already parses, (c) re-run
      scripts/b131_news_veto_pricing.py with the archive swapped into
      git_union_calendar() — the dial, the parity probe, and the neutrality
      grid are all already built, so this is a data task, not a code task.
      REUSABLE LESSON (b131): before designing a time-gate study, intersect
      the gate's DATA window with the measurement windows FIRST (one-line
      timestamp overlap check); b131's own step-3 premise failed that check
      and the study had to report coverage-zero legs instead of deltas.
      DONE 2026-09-07 (b132 run): THE SOURCE WAS THE WAYBACK MACHINE — the
      Internet Archive crawled nfs.faireconomy.media/ff_calendar_thisweek.json
      DAILY (95 snapshots, 2026-05-03..2026-09-12, CDX API + `id_` raw mode);
      scripts/b132_event_archive_fetch.py dedupes them into
      data/calendar/events_archive_ff_wayback_20260503_20260912.json
      (1941 events, 81 high USD/XAU, live's exact event schema).
      scripts/b132_news_veto_real_calendar.py re-priced the veto on it:
      FINDING — at live's ±30min the veto deletes entries whose OWN R was
      positive (cached +2.8R/4 entries, W1 +0.5R/3) and cached exp_R FALLS
      -0.053 (b131's git-union answer was -0.026 — the real calendar moved
      it 2x); no arm is a lever: ±720/±1440min clear b119's 0.10R exp_R
      ceiling ONLY by subtraction (net_R negative on covered legs, maxDD
      worse) — lever_test() flags inflation_by_subtraction and is_lever=False
      everywhere. W2..W6 stay coverage-zero (archive starts 2026-05-03,
      before that FF's feed wasn't crawled here) — veto stays live insurance
      (fail-closed), no wiring change. tests/test_b132_real_event_archive.py
      (10 tests) + registered in b127 CHECKS (check_b132_derived_blocks).
- [x] b133 TRADER RESEARCH — REGISTER b131'S LEDGER IN b127 CHECKS + EXTEND
      THE EVENT ARCHIVE BACKWARDS (from b132, 2026-09-07): (a) b131 shipped
      data/backtest/b131_news_veto_pricing.json WITHOUT a check in
      scripts/b127_producer_reproduction.py CHECKS — b128's ship-time rule
      violated; add check_b131_derived_blocks (its producers: windows(),
      veto_census, deltas, neutrality, verdict — read the script for exact
      names). (b) The Wayback CDX for ff_calendar_thisweek.json only reaches
      2026-05-03; probe ff_calendar_prevweek.json / nextweek variants and
      per-week URLs for older crawls to push the archive back over W2..W6
      spans, then re-run b132's pricing (covered-leg vote is n=2 today,
      below b129's one_sided_strict floor of max(3, half) — more legs is the
      ONLY way the veto question gets a strict answer).
      REUSABLE LESSON (b132): an ENTRY-REMOVING arm (veto/filter/gate) must
      NEVER be judged on exp_R alone — deleting trades inflates exp_R by
      subtraction; require net_R and maxDD to agree before calling it a lever
      (b132's lever_test is the template).
      DONE 2026-09-07 (b133 harvest, committed 05a61f9 by b47): (a)
      check_b131_derived_blocks registered in CHECKS (22/22 reproductions
      exact). (b) THE ARCHIVE WAS NEVER THIN — THE CDX QUERY WAS: exact-url
      lookups are blind to every `?version=<hash>` capture; the PREFIX query
      reaches 2025-01-19 (145 days, 5043 events, 303 high USD/XAU), ALL SEVEN
      legs now covered and the covered-leg vote went n=2 -> n=7. THE VETO
      QUESTION NOW HAS A STRICT ANSWER: at live's ±30min the delta is
      one-sided NEGATIVE (mean -0.0094R, 4 legs vs 1), the vetoed entries were
      winners on 5 of 6 evidence legs (W2 covered but vetoed ZERO entries —
      coverage is not evidence), and no arm is a lever; ±120min is negative on
      7/7 net_R. Veto stays live insurance; nothing wired. Also fixed the
      BROKEN-HEAD cause: engines/backtest.py cited
      test_b131_news_veto_pricing (the file shipped as _dial) — b104 phantom.
- [ ] b110 RESEARCH PROCEDURE — PRICE AN ENGINE FIX BY ITS NEUTRALITY, NOT JUST
      ITS LEVEL (reusable procedure from b108, 2026-09-06): when a backtest
      engine defect is fixed, re-running the baseline is only half the job.
      b105's runner double-count moved the funnel's exp_R by -0.45..-0.54R on
      every leg — a reader could conclude "the bar moved, the rankings stand".
      b108's per-arm test (lane-relative shift = d_lane_exp_R - d_funnel_exp_R
      on the SAME bars, per independent window) showed the shift is NOT
      uniform: lane_nr7htf's margin moved +0.045..+0.093R on ALL FOUR windows
      (one-sided = systematic, its TP1-hit profile differs from the funnel's)
      and one lane's per-window verdict flipped sign. RULE: after any engine
      fix, (1) re-measure BOTH sides of every stored comparison on identical
      bars, (2) compute the per-arm relative shift per window, (3) treat a
      one-sided shift across >=3 independent windows as proof the old
      arm-vs-arm rankings were contaminated, and (4) pin the flip cells by
      name so the pre-fix verdict cannot be re-quoted. Cheap version: the
      shift is arithmetic on two ledgers of the same measurement — no new
      runs needed once both exist.
- [ ] b113 MEASUREMENT PROCEDURE — A CENSUS THAT FEEDS A GATE DECISION MUST BE
      TAKEN IN THE FRAME THE GATE RUNS IN (reusable procedure from b112,
      2026-09-06): b112 was filed from an offline re-parse of the live signal
      journal (parse_signal(raw_text) with no price) and its premise — "the
      no_symbol_found family fires 11/28 and costs nothing" — turned out to be
      an artifact of that frame: the live listener always passes
      current_price>0, which switches the parser's `_gold_abbrev` branch, so
      the live frame sees 0 no_symbol_found; and the offline ones never reach
      the gate anyway (symbol=="" → is_valid False → dropped upstream).
      RULE: before any number measured offline is used to argue for or
      against a live-gate change, (1) state which production call-site the
      measurement emulates and what arguments that site actually passes,
      (2) re-measure through the same entry point with those arguments
      reconstructed (b112 used radin_replay.price_at on bridge M5 candles —
      the same price/band the listener would have seen), and (3) check
      reachability: does the measured population survive every upstream
      filter before the gate, or does it die at is_valid /
      names_other_instrument / the freshness gate? A warning/field census
      over an unreachable population is decoration. Cheap version: the
      frame diff is one extra parse per journal row.
- [x] b68 STRATEGY LAB CONTINUOUS LOOP (user standing order 2026-09-03: "keep searching strategies/analysis methods, pick the best, test, bring into the real structure"). Each run: (a) pick ONE new candidate method not yet in data/backtest/b62_strategy_lab.json (sources: quant literature, ICT/SMC concepts not yet measured, session/volatility patterns; web search is low-signal — prefer implementing from the concept definition), (b) implement it as a standalone signal_fn in scripts/b62_strategy_lab.py style (indexed() adapter, ATR-based geometry, grade B), (c) run through engines.backtest.backtest_ohlc on the CACHED dataset (data/backtest/ab_aggressive_data.json, 3000 M15 bars) with spread 0.20 AND with the live b60 ladder (partial_share_fn=_partial_close_fraction, tp1_position=0.50, trail_after_partial=0.5), (d) append the row to data/backtest/b62_strategy_lab.json, (e) MERIT BAR: only propose wiring into the live funnel if exp_R beats the current funnel's 0.854R/trade (b61 best arm) on BOTH the cached set and one fresh fetch; otherwise record the rejection in ## Findings with numbers. NEVER weaken existing gates to make a new arm look better; the funnel stays the exit manager. Baseline table so far (exp_R, cached M15): funnel b60 0.854 | asia_break 0.18 | ema_pullback 0.114 | bb_bounce 0.035 | donchian -0.013 | sweep_rev -0.004 | fvg_retest -0.020 | ny_orb -0.098 | rsi_rev -0.226 | vwap_fade 0.380 (ladder; fresh-set 0.436 vs funnel 0.576 — REJECTED 2026-09-03, see Findings). SMC/RTM round (b63/b63b, 2026-09-03): turtle_soup 0.508 cached / 0.469 fresh, eqh_sweep 0.085 / 0.638, ote 0.62 / 0.299, breaker 0.008 / 0.113, ob_first_retest 0.978 (n=3) / 0.483 (n=6), sweep_choch_ob 1.702 (n=2) / 1.066 (n=4) — none beat the funnel on BOTH sets with a usable n; funnel stays. Momentum round (b68r2, 2026-09-03): atr_expand_all 0.362 / fresh 0.443, atr_expand_lny 0.344 / 0.432 — REJECTED, loses on both sets (see Findings). HTF-trend+pullback round (b68r3, 2026-09-03): htf_pull_50... [truncated]
      (progress 2026-09-03, rounds 1+2 done: vwap_fade and atr_expand tested+rejected
      (Findings). Round 4 (b68e, PDH/PDL breakout) done this run: REJECTED as a
      replacement (loses cached 0.627 vs 0.854) but the FIRST arm to beat the funnel on
      fresh data (0.640 vs 0.576) and the additive-lane probe says it ADDS total R —
      escalated into new todo b70 (capacity analysis), nothing wired live.
      METHOD
      RULE learned: the 0.854 bar is CACHED-set specific — on fresh 6000 bars the funnel
      itself scores 0.576, so every future confirm MUST re-measure the funnel on the SAME
      fresh data and require the arm to beat BOTH numbers. PATTERN so far: the b60 ladder
      drags mean-reversion/momentum arms from negative-plain to positive-ladder but never
      into contention (0.34-0.44 fresh band); the funnel's edge is its ENTRY FILTER, not
      the exit. Round 3 (b68r3, HTF trend + discount/premium pullback — the funnel's OWN
      entry class, standalone) also REJECTED: 0.317/0.346 fresh vs funnel 0.577 — even a
      correct-class entry idea measured standalone does not approach the funnel, because
      the funnel stacks MANY context conditions (regime+SMC merge+range-kill+grade+blueprint
      geometry) where the lab arm has one. Remaining unmeasured candidates: overnight-gap
      fade (MEASURED 2026-09-03: only 26 daily gaps in 3000 M15 bars, 6 of them weekend —
      n too thin to ever clear the bar on this dataset, skip), range-compression breakout
      at session open (after b69 heals the dead compression arm), killzone-session open
      drift (MEASURED 2026-09-03: first-hour direction predicts the next 5h at t=0.65-0.67
      for London/NY opens — noise, not an edge; the 16:00-broker hour shows t=2.03 but that
      is one hour out of 24, a multiple-comparisons artifact). Round 4 (b68r4, PREVIOUS
      TRADING DAY high/low close-confirmed breakout) is the FIRST arm to beat the funnel on
      fresh data (0.640 vs 0.576, n=108) but loses cached (0.627 vs 0.854) -> REJECTED as a
      replacement; the additive-lane probe says it is COMPLEMENTARY -> new todo b70.
      Round 5 (b68r5, NR7 compression breakout) MEASURED 2026-09-03: nr7_break_c 0.584
      cached / 0.460 fresh, nr7_break_w10 0.598 / 0.517 vs funnel 0.854 / 0.586 —
      REJECTED as replacement (loses BOTH sets), but its additive lane is the strongest
      probe yet (fresh lane exp_R 0.620 > funnel 0.586, tot_R +64%) -> data appended to
      b70's queue, nothing wired. See Findings for the full numbers + the b69 range probe.
      Round 6 (b68r6, TRADING-DAY EXTENSION continuation — the path-shape family the
      b68g probe picked on the strongest raw drift this loop has ever measured, t=7.4)
      is REJECTED on every axis: cached 0.327/0.361 vs 0.854, fresh 0.312/0.345 vs
      0.585, and its additive lane is NEGATIVE (0.410 vs 0.585 — the weakest lane of
      three, because the arm fires 2.5x more often than the funnel and squats in the
      single slot). METHOD RULE from it: raw drift != tradeable edge (overlapping
      samples inflate t; only de-overlapped trade-level R is honest). See Findings.
      Remaining unmeasured families: none of the classic ones left (mean-rev, momentum,
      trend+pullback, level breakout, compression breakout, SMC/RTM, day path-shape,
      gap, session drift — all screened and rejected). Next rounds should either (a)
      test a COMBINATION the funnel does not already use (e.g. two of the rejected
      families gated on each other), or (b) stop and let b70's capacity question decide.
      Round 7 (b68r7, 2026-09-04 — option (a), FIRST round measured entirely on the
      b71 harness): NR7 squeeze breakout GATED on trading-day-extension agreement
      (pure intersection, nr7 geometry unchanged, dayext as direction oracle only).
      REJECTED as replacement: cached ladder_ts 0.622 (n=68) vs funnel 0.854; fresh
      0.587 (n=135) vs funnel 0.590 on the SAME bars. The gate DOES lift its own
      control (nr7_w10: 0.598->0.622 cached, 0.519->0.587 fresh) — the combination
      direction is real but sub-funnel. ADDITIVE LANE (funnel-first, combo on free
      bars, fresh): n 350 vs 322, tot_R 202.6 vs 189.8 (+6.8%) but exp_R 0.579 <
      0.590 and dd_R -6.9 worse than -5.0 — the gated nr7 does NOT earn a slot;
      feeds b70 as a NEGATIVE lane candidate. See Findings.
      Round 8 (b68i, 2026-09-04 — second combination, round-4 x round-5 per the
      b72 playbook): PDH/PDL close-confirmed breakout GATED on the resolved
      direction of the most recent NR7 squeeze (pdh geometry unchanged, squeeze
      as direction oracle only). REJECTED as replacement: cached ladder 0.406
      (n=21) vs control pdh_w10 0.627 — the gate LOWERS its own control (the
      round-7 gate lifted it), and fresh 0.603 (n=40) vs funnel 0.590 is a
      nominal pass on a noise-sized sample while cached fails 2.1x. Lane
      (funnel-first, gated pdh on free bars, fresh): exp_R 0.580 < 0.590,
      tot_R 189.0 vs 189.8 — the extra trades add nothing. Stretch probe
      explains it: gated entries are MORE stretched from the broken level
      (mean 0.667 vs 0.558 ATR) — a squeeze-then-breakout has already given
      the follow-through away by the time PDH breaks. See Findings.
      Round 9 (b68j, 2026-09-04 — THIRD combination, the b73-recommended
      path-on-path pairing: pdh geometry gated on day-extension commitment,
      the pairing type whose gate LIFTED its control in round 7): the FIRST
      arm in the loop's history to PASS the merit bar on per-trade R on BOTH
      sets — cached ladder_ts 0.924 (n=23) vs funnel 0.854, fresh 0.891
      (n=39) vs funnel 0.590 on the SAME bars (e25 variant: 1.105/0.947 at
      n=19/33). Selection proven real by a COMPLEMENT arm (what the gate
      drops): 0.398 cached / 0.467 fresh — below the 0.627/0.609 control, so
      the gate removes the WORST pdh trades, not a lucky subset. Stretch
      probe (b73): gated 0.564 vs control 0.558 ATR — the lift is
      INFORMATIONAL, not geometric (round 8's failure mode absent).
      ADDITIVE LANE on the same fresh bars is the FIRST lane to beat the
      funnel on ALL THREE axes: exp_R 0.634 > 0.590, tot_R 212.4 > 190.6,
      dd -4.1 BETTER than -5.0, n 335 > 323. NOT wired (hard rule): n is
      4-12% of the funnel's and it is ONE fresh set — promotion requires the
      b74 replication (cached + >=2 more independent fresh windows, live
      gate stack, kill-switch streaks) which folds into b70. See Findings.
      Round 10 (b68r10, 2026-09-04 — the REVERSED pairing of round 9: dayext
      geometry gated on a same-day PD-break oracle, b71 harness + b72/b73
      playbook): REJECTED as replacement — cached ladder_ts 0.369 (n=222) vs
      funnel 0.854, fresh 0.371 (n=461) vs funnel 0.590 on the SAME bars. The
      gate LIFTS its control on both sets (0.327->0.369, 0.316->0.371) and the
      opposite-path cut (day extended one way, last PD break the other) is the
      WORST variant on both sets (0.151/0.108) — selection is real in BOTH
      directions of this pairing, so the dayext<->PD-level agreement signal is
      a genuine property, not a subset fluke. But the lane is NEGATIVE (exp_R
      0.471 < 0.590, dd -12.6 vs -5.0) and the stretch probe explains why:
      agree entries sit ~4 ATR from the broken level (the extension trigger
      prints HOURS after the break — a chase tax), vs round 9's 0.56 ATR where
      the geometry IS the fresh break. METHOD RULE (new todo b75): in a
      combination, the GEOMETRY supplier should be the FRESHER event of the
      pair; gating a lagging confirmation on its own leading signal buys a
      lift in R but pays it in stretch. Nothing wired. See Findings.
      Round 11 (b68l, 2026-09-04 — METHODOLOGY round, harvested from the
      previous run's uncommitted work + pinned with 19 tests this run):
      the last-6000 "fresh" set used by rounds 1-10 CONTAINS ALL 3000
      cached bars (measured overlap = 3000/3000) — the merit bar was never
      out-of-sample. Re-measured the whole b70 decision set on two windows
      that exclude the cached regime (W1 2026-04-14→07-15, W2 2026-01-12→
      04-14, zero overlap with cached and each other, b71 harness, funnel
      re-measured on the SAME bars: 0.524/0.521 — the 0.854 cached bar is
      confirmed regime-inflated). RESULT: round 9's champion FAILS
      replication (0.928 W1 vs 0.447 W2) and its gate's selection FLIPS
      SIGN between windows (complement 0.415→0.743 vs agree 0.928→0.447)
      — the dayext gate is a regime interaction, not a property; nr7 loses
      both windows (0.437/0.390). The UNGATED pdh control (round 4) is the
      ONLY arm beating the funnel on both independent windows (0.612/0.623,
      n=95/100) — first replicated out-of-regime arm in the loop's history;
      its gated lane replicates only a MARGINAL positive (< +0.05R).
      Nothing wired; b70/b74 notes updated. See Findings.
      Round 12 (b68m, 2026-09-04 — shipped via STEP-0 harvest: the previous run
      wrote the whole round and died before committing, b46 shape; verified +
      pinned this run by 24 tests in tests/test_b68m_htf_pdh_lab.py): PDH
      geometry x HIGHER-TIMEFRAME TREND-STATE oracle (EMA50 level+slope on
      H1/H4, only FULLY CLOSED HTF bars read — stricter than the funnel's own
      convention). FIRST arm in loop history to satisfy ALL THREE replication
      conditions on the b68l windows: pdh_h4t_agree beats the funnel on BOTH
      independent windows (0.657 W1 / 0.927 W2 vs 0.524/0.521), beats its own
      ungated control on both (0.612/0.623), and keeps agree>cut ordering on
      both (cut 0.451/0.631) — the exact check round 9's dayext gate failed.
      H1's gate is ~90% vacuous (measured + recorded so nobody quotes it as a
      filter); H4's is 0.54-0.61 with a real disagree cut; agree-subset state
      age median >=9 H4 bars proves a slow STATE, not an event in disguise
      (b75 rule-6 probe); stretch delta gated-vs-control <= +0.04 ATR — the
      lift is informational, round 10's chase tax absent. HONEST DISCLOSURE:
      on the IN-SAMPLE cached leg the selection ordering FLIPS (disagree 1.237
      n=11 > agree 0.641) — per b76 the cached regime is exactly what cannot
      be trusted, and the flip is pinned by a test so it can't be quietly
      dropped. Lane replicates only a MARGINAL positive (0.534/0.535 vs
      0.524/0.521, < +0.05R — same shape as round 11's lane). NOT wired:
      n=55/63 and TWO windows; promotion requires b74's >=3-window
      replication + live gate stack + kill-switch streak math. See Findings.
      Round 13 (b68n, 2026-09-04 — SHIPPED VIA STEP-0 HARVEST: the previous run
      wrote the whole round — W3 window builder + b68n lab + 17 tests + ledger —
      and died before committing, b46 shape 5th occurrence; verified this run):
      W3 (2025-10-08→2026-01-12, 6000 bars, zero overlap asserted) spends b74's
      THIRD DRAW on the round-12 champion and, for the first time, gates the
      FUNNEL's own entries on the H4-trend state. RESULT 1: pdh_h4t_agree FAILS
      W3 (0.505 vs funnel 0.528 on the same bars) — the round-12 champion is
      2-of-3 windows, NOT promoted; its control pdh_w10 collapses harder
      (0.370), so the gate still lifts pdh on W3 but not above the funnel.
      RESULT 2: funnel_h4t_agree is the FIRST arm to beat the funnel on ALL
      THREE independent windows (0.617/0.553/0.536 vs 0.524/0.521/0.528,
      n=203/228/209) — but the margins SHRINK (0.093→0.032→0.008) and the
      selection ordering FLIPS on W3 (cut 0.553 > agree 0.536, the exact check
      that killed round 9's champion), so it is a candidate for the b74
      protocol, not a winner; wiring a new filter into the live funnel is a
      human decision regardless. RESULT 3: the h4pdh lane loses W3
      (0.515 vs 0.528) — lane evidence now 2-of-3. Nothing wired. See Findings.
      Round 14 (b68n4, 2026-09-04 — b74's FOURTH DRAW, scripts/
      b68n4_fourth_draw.py + W4 slice in b68l_windows.py + 19 tests): W4
      (2025-07-09→2025-10-08, zero overlap asserted) settles the round-13
      candidate. funnel_h4t_agree DIES: 0.517 (n=267) vs funnel 0.532
      (n=340) on the SAME bars. The margin series read CHRONOLOGICALLY
      (W4 oldest → W1 newest) is -0.015/+0.008/+0.032/+0.093 — MONOTONIC
      in recency: the H4-state gate's edge is a property of the RECENT
      regime, not of gold M15 (the loop's cleanest decay curve, and the
      b74 protocol's decay-pricing question answered NO). The round-12
      champion pdh_h4t_agree beats W4 (0.597 vs 0.532, n=82) but failed
      W3 — 3-of-4, still not replication; the lane beats W4 (0.546) after
      losing W3 — also 3-of-4. FOUR independent windows now put the
      funnel at 0.524/0.521/0.528/0.532 (stable ~0.52-0.53) and NO lab
      arm has ever cleared all of them. After 14 rounds the screening
      question is answered: the live funnel's entry filter remains the
      best measured thing; future rounds must justify themselves against
      b77's decay rule before burning a draw. Nothing wired. See Findings.
      Round 15 (b68o, 2026-09-05 — the one LEVEL family never measured:
      previous-TRADING-WEEK high/low close-confirmed breakout, round 4's
      geometry one timeframe up, justified under round 14's novelty rule):
      REJECTED under b74's all-windows rule. pwh_break_w10 prints the best
      cached number since round 9 (1.262, n=18) but the funnel on the SAME
      cached bars is 0.558, and on the four independent windows it wins only
      2-of-4 (W2 0.618 / W3 0.601 beat; W1 0.344 / W4 0.514 lose vs
      0.524/0.532); t50 wins 3-of-4 but loses W1 badly (0.307). b77
      pre-flight MIXED on both arms — no monotone ramp, no stable edge.
      Regime fingerprint: the arm's direction mix FLIPS by window (cached
      24/24 BUY, W1 39/52 SELL). Nothing wired. See Findings.
      Round 16 (b68p, 2026-09-05 — weekly level as ORACLE not geometry:
      pdh_break_w10 gated on >=1.0*ATR RUNWAY to the previous trading
      week's extreme in trade direction; first round run under b78's mix
      disclosure from the start): REJECTED 2-of-4 windows (W1 0.831 / W2
      0.729 beat funnel 0.524/0.521; W3 -0.085 / W4 0.424 lose 0.528/0.532)
      and the gate's SELECTION ORDERING FLIPS — runway>no_runway holds on
      exactly ONE of four windows (the round-9 killer check, now pinned by
      a test); the DROPPED set out-earns the kept set on W2/W3/W4. Stretch
      clean (informational, no chase tax); b77 MIXED; lane 2-of-4 marginal
      (<+0.05R) — feeds b70, nothing earned a slot. b78 itself IMPLEMENTED
      this round (mix ships per arm per leg in the confirm ledger + the
      registry rows + 3 pinning tests) and marked done. See Findings.
      Round 17 (b68q, 2026-09-05 — the last unmeasured pairing of the
      loop's two strongest survivors: nr7 compression breakout (round 5,
      best additive lane) x the H4 trend-state oracle (round 12, the only
      gate that lifted its control on both independent windows); nr7
      geometry UNCHANGED, oracle verbatim from b68m, pure intersection):
      REJECTED 1-of-4 windows (only W4 0.586 beats funnel 0.532; W1 0.437
      / W2 0.469 / W3 0.471 lose 0.524/0.521/0.528; cached 0.679
      informational). The gate's SELECTION ORDERING is the loop's most
      consistent — agree > disagree on ALL FOUR independent windows, the
      check that killed rounds 9/13/16 — yet the LIFT does not replicate
      (W1 tie, W3 LOWER; b77 MIXED): the H4 state genuinely ranks nr7
      trades, ranking just isn't worth 0.05R here. Frequency is the lane
      killer: n~290-306/window (~90% of the funnel's) → lane 2-of-4,
      every margin <+0.05R. b78 mix: agree arm one-sided in 3 of 5 legs —
      the gate IS a direction filter. Stretch flat (<=0.02 ATR). Nothing
      wired. See Findings.
      Round 18 (b68r, 2026-09-05 — the ladder ITSELF as the object, no new
      arm: the funnel's A/B/C grade populations measured as three books on
      the corrected b80 bar, cached+W1..W4, live ladder+time exit): the live
      min_grade=B gate is CONFIRMED on selection (B>C on exp_R 4-of-4
      windows AND all 8 window x side cells — the cliff is at B) but the
      ungated book earns MORE total net_R on all four windows (+29..+57R;
      the dropped C-book's marginal trade is +0.21..+0.37R, positive but
      below the kept bar, and its DD is worse everywhere) — both prices now
      on record, gate unchanged. A>B replicates only 3-of-4 (W4 -0.166R) and
      the side-split proves the flip is a DIRECTION cell (A-SELL W4 0.085),
      not a rung property; tightening B->A gives up -261.7R — NOT proposed.
      13 tests pin reproduction vs b80 + both verdicts. See Findings.
      Round 19 (b86, 2026-09-05 — b84's named next filter, measured as books
      rather than a new arm: the range-kill confidence gate, regime==range &
      bias!=neutral & smc_conf < 0.35 -> neutral, live literal in
      hermes_runtime.build_live_plan, backtest twin strategy_signal
      (range_kill_conf=...)). RESULT 1: the gate is a NO-OP at the live
      threshold — 0 signals killed on 5-of-5 legs, dropped book empty
      everywhere, and the trade book is BYTE-IDENTICAL across the whole
      threshold ladder 0.0 never-kill .. 0.99 always-kill (cached 0.796/99,
      W1 0.676/174, W2 0.662/165, W3 0.767/190, W4 0.745/166 at every t).
      RESULT 2 (the real finding): at full power it removes 462-988 signals
      per leg (49-57% of the raw population) and EVERY killable signal is
      C-grade — the population MIN_SETUP_GRADE='B' already rejects — so its
      live-gated book is 0 trades on all five legs; it only trades when the
      grade gate is removed (117-274 trades, exp_R 0.341-0.452). The rule is
      FULLY SHADOWED by the grade gate: it can never be the reason a live
      trade is skipped. RESULT 3: it is directionally RIGHT — the shadowed
      book earns below the funnel on every leg (cached included), so the
      intent is sound, the placement is redundant. RESULT 4 (b84 contrast):
      min_rr had a reachable cliff (learning steps +0.25); this knob has NO
      adaptive path at all — 0.35 is a literal, learning.py cannot touch it,
      so the no-op is permanent until a human edits. Nothing wired, nothing
      removed (hard rule: never weaken a gate — deleting a redundant gate is
      a human decision, and it is the only thing this round could propose).
      INTEGRITY: gate_conf_0.35 reproduces b80's gradeB_rr15 exactly on all
      5 legs (b83), and the live population is a subset of the never-kill
      population on every leg. 15 tests. See Findings.
       Round 20 (b88, 2026-09-05 — b87's named next gate: DEFCON, the ONLY live
       gate whose input is the book's own past trades, so this round audited the
       INPUT before pricing the rule). FINDING 1 (real defect, FIXED in
       engines/risk.compute_performance_state): the new-day branch returned a
       state dict WITHOUT `recent_closed`, so the first evaluation cycle of every
       UTC day handed DEFCON an empty window at loss_streak=0/daily_pnl=0.0 ->
       GREEN BY CONSTRUCTION, whatever yesterday did. Measured blast radius: 122
       of 259 first-entry-of-day cycles (cached+W1..W4) sat at an invented level —
       107 should have been YELLOW, 15 RED. Fix carries the window through the
       rollover; it is STRICTLY tightening (daily_pnl is 0.0 on that cycle so RED
       cannot fire, YELLOW only halves risk), and loss_streak stays reset on
       purpose because it also feeds check_kill_switch. FINDING 2 (measured, NOT
       changed — a human decision): the docstring says "last 10 closed trades",
       the code takes the last 10 DEALS from a feed that includes opening deals,
       so the window holds ~5 exits and RED's `total>=5` sits exactly on that
       halving; the corrected window would move W1 from GREEN 90/YELLOW 72 to
       GREEN 11/YELLOW 148 — a global tightening, so it is a PROPOSAL (new todo
       b89), not a side effect. FINDING 3 (the b87 template applied honestly):
       DEFCON BINDS (6-12 RED, 40-80 YELLOW per leg of 99-190 trades) and is NOT
       redundant — 44 of 45 RED entries sit below CONSECUTIVE_LOSSES_LIMIT=4
       where the kill switch is silent — but it does not EARN its cost as a
       filter: the dropped book earns 0.51-1.23R vs the kept book's 0.66-0.76R on
       4 of 5 legs. Kept anyway (hard rule: never weaken a gate; a trip wire that
       costs foregone R buys tail protection, not mean R). FINDING 4: no adaptive
       path touches it (learning.py's changes dict never carries a DEFCON key).
       METHOD BUG caught in this round's own replay: folding trades in ENTRY
       order handed DEFCON a future loss (lookahead in the feedback loop); the
       replay now folds in EXIT order against a chronological deal feed, per b77.
       INTEGRITY: defcon_off reproduces b80's gradeB_rr15 exactly on all 5 legs
       (b83), and the ledger stamps the sha256 of engines/risk.py it was built
       against so a stale ledger cannot pass as current. 22 tests in
       tests/test_b88_defcon_books.py; full numbers in
       data/backtest/b88_defcon_books.json + logs/b88_run_chrono.log.
- [x] b89 DEFCON WINDOW: DEALS vs TRADES — HUMAN DECISION (found by b88,
       2026-09-05, NOT applied by autopilot). engines/risk.compute_performance_state
       documents `recent_closed` as "last 10 closed trades" but slices the last 10
       DEALS from a feed that also contains opening deals (entry==0), so DEFCON's
       window holds ~5 closed trades and RED's `total>=5` trigger sits exactly on
       that halving. b88 measured the corrected (closing-deals-only) window: the
       level mix moves from GREEN 90/YELLOW 72/RED 12 to GREEN 11/YELLOW 148/RED 15
       on W1 — a GLOBAL TIGHTENING of the only feedback-loop gate, which is a gate
       change and therefore out of autopilot scope (hard rule). Decide one: (a) fix
       the slice to match the docstring and re-price the funnel under it, or (b) fix
       the docstring to match the code and record that RED is reachable only because
       of the deal-level slice. Either way add a test pinning the window's exit count
       so the two cannot drift again.
       DONE 2026-09-05 (option (b) shipped by the 21:13 run, left unmarked —
       b46 shape; verified this run: ledger reproduces byte-identical, both
       code shas match, 15 tests green): DEFCON's window is 10 DEALS = 5 exits
       in an alternating book; RED needs EVERY exit an SL; dilution is
       one-directional (deal slice is HARDER than the docstring's trade slice,
       never looser), so option (a) stays a human decision.
- [x] b93 MEASURE THE MEDIUM BEFORE THE GATE (reusable procedure from b92,
      2026-09-06): b84's book template (kept vs dropped population on
      cached+W1..W4) silently assumes the dataset can REPRESENT the gate's
      population. It cannot for any CLOCK-domain gate: the backtest fetch is
      weekday-only (0 Sunday bars in all 5 legs, b92), so post-open cooldown,
      restart cooldown and market-hours all read "0 kills" for a reason that
      says nothing about the gate. RULE: before running a bind test, print the
      medium's coverage of the gate's population (bars per weekday, per hour,
      per regime) and if it is zero, switch domains — analytic reach (share of
      trading time), the LIVE record (plan_history cycle stamps for restart
      arms; execution_log/plan_history for market-hours blocks), and the
      shadow probe (evaluate the OTHER time gates at the exact minutes this
      one protects). Never report a clock-domain "0 kills" as b86's no-op.
      FIRST APPLICATION (cheap, mostly pre-computed by b92): market-hours —
      the last item in b84's queue. Its population is Sat/Sun/Fri-after-22
      bars: zero in every dataset, so the book verdict is pre-decided; the
      honest rows are (a) the live record — how many master cycles ran while
      market_hours blocked (plan_history created_at weekday/hour histogram),
      (b) the shadow row — cooldown's window is a strict SUBSET of
      market_hours' OPEN period (b92 probed it: market_hours allows Sun
      23:00-23:14), so the two time gates are DISJOINT, neither shadows the
      other, and together they tile the calendar, and (c) reachability —
      is_market_open's boundaries are literals, learning cannot move them.
      Ship as scripts/b93_market_hours_gate.py reusing b92's domain skeleton.
      DONE 2026-09-06: THE MEDIUM IS FRAME-SHIFTED, NOT EMPTY — dataset bar
      stamps are broker SERVER time (~UTC+3, offset from broker_clock.json),
      proven by the daily-halt hour (00 naive / 21 true) and the weekly gap
      (Mon 01 naive / Sun 22 true); b92's "0 Sunday bars" was a frame artifact,
      the Sunday bars exist (48-111 per leg). market_hours live fire-rate
      282/771 distinct cycles (Fri/Sat/Sun only); shadow grid DISJOINT from
      cooldown; ESCALATED (b89 class, NOT applied): gate literals Sun 23:00/
      Fri 22:00 UTC vs broker real Sun 22:00/Fri 21:00 — Friday side is ~1h
      PERMISSIVE into the 10018 window. scripts/b93_market_hours_gate.py +
      data/backtest/b93_market_hours_gate.json + 16 tests.
- [ ] b104 [META] SEMANTIC AUDITS NEED A REALITY-BINDING END-TO-END CHECK, NOT JUST
      FIXTURES (reusable procedure from b103, 2026-09-06): a tripwire whose
      predicate reads MEANING (prose, naming, intent) cannot be validated by
      fixtures alone — a fixture only proves the predicate fires on the shapes
      its author imagined, and every one of b103's rules 4/5/6 was a shape the
      author had NOT imagined, each found only when the predicate was pointed
      at the repo's REAL prose and REAL git history. RULE: pair every such
      audit with a check that the FINDINGS RESOLVE TO REAL ENTITIES — b103's
      version asserts that every item number the prose scan binds must exist as
      a backlog item, so a phantom claim (a number nobody ever filed) fails
      even though the predicate itself never crashed; the same shape works for
      any semantic scan (a flagged file must exist, a named test must be
      collectable, a cited config key must appear in .env.example). SECOND
      HALF OF THE RULE, and the part that made it bite: assert the scan is NOT
      VACUOUS on the same real data (found set must be non-empty) — a reality
      check that reads zero findings passes on a dead predicate. THIRD: when a
      shared helper layer DOCUMENTS N rules, pin one test class per rule and
      cross-check the count (b103 shipped with rule 5 documented and unowned;
      the docstring's own rule table is the checklist).
- [x] b103 PROSE-AUDIT HYGIENE: MERGE WRAPPED COMMENT LINES, LET NEGATION
      WIN, SCAN COMMIT MESSAGES TOO (reusable procedure from b102,
      2026-09-06): any future tripwire that reads ENGLISH PROSE for a policy
      claim (not code structure) inherits three bugs b102 hit while measuring
      its own predicate, each pinned by a test in
      tests/test_b102_nonwidening_pins.py. (1) MERGE BEFORE SENTENCING — a
      claim wrapped across two '#' lines strands the item number in one half
      and the verb in the other and the claim VANISHES (b102's first version
      missed one of its four live claims this way); consecutive comment lines
      must join into one block before splitting on sentence ends. (2) A
      'HISTORY/SHIPPED' SPARE MUST NOT BE A BARE SUBSTRING — 'deliberately
      not widened in this commit' CONTAINS 'widened in', so the naive
      shipped-check made the audit blind to the exact shape it was written to
      catch; require the shipping evidence to NAME the item ('widened in
      b100') and let a negated widening verb always win. (3) THE MEDIA UNDER
      AUDIT MUST INCLUDE GIT HISTORY — b99 parked b100 in its COMMIT MESSAGE
      only, so a code-prose-only scan reports a clean repo while the rule is
      being violated; replay `git log --format=%H%x01%B` over a bounded window
      and check each claim against the CURRENT test-method names. General
      lesson for every prose audit: before trusting a green result, ask which
      media it reads and whether a wrapped or negated phrasing can hide the
      claim.
      DONE 2026-09-06 (SHIPPED VIA STEP-0 HARVEST — the previous run wrote the
      whole layer + its test file + the b102 refactor and died before
      committing, b46 shape; and its own HEAD 50cf480 was stamped BROKEN by
      verify_head, so the harvest is also the push-gate heal). The three rules
      above plus THREE MORE the layer found while being built now live in
      tests/prose_audit.py (shared, non-test_ so discovery skips it), with
      b102 refactored into its first consumer (predicates re-exported, not
      copied — the tests still bind the REAL ones): (4) A QUOTED PHRASE IS A
      MENTION, not a decision, and the item binds NEAREST the verb — this is
      the bug that made HEAD 50cf480 BROKEN (b102's commit-message replay
      flagged b102's OWN message, which quotes the vocabulary, and bound it to
      an incidental 'b94'); (5) EXTRACT PROSE FROM THE TOKENIZER/AST, not from
      'any line containing a hash', or a tripwire's own fixtures — which must
      quote the vocabulary to pin it — read as policy prose; (6) A QUOTE IS ONE
      SENTENCE — found BY THIS RUN's new reality-binding test: the splitter cut
      on '. ' INSIDE quoted examples (rule-4 examples carry ellipses), so the
      tail half had no opening quote, the mention spare died on the very
      sentences documenting it, and a phantom claim bound to 'b94' escaped every
      fixture test and was caught only repo-wide. 26 tests
      (tests/test_b103_prose_audit.py, one class per rule incl. the 8 this run
      added for rules 5 and 6), 1052 green, live cycle OK.
- [x] b102 DELIBERATE NON-WIDENINGS MUST BE PINNED AS TESTS, NOT COMMIT
      MESSAGES (reusable procedure from b100, 2026-09-06): when a widening
      is measured free but deliberately NOT shipped (scope discipline —
      one widening per commit), the decision lives nowhere unless a test
      pins the spared shape with the future item's number in its name
      (b100's test_plain_assert_identity_stays_spared_pending_b101). RULE:
      every "we chose NOT to widen here" gets (a) a spared-direction test
      named after the parked item, and (b) a line in that item saying the
      pin must be EDITED, not deleted, when it ships — so the flip is
      deliberate and dated, and the boundary cannot rot into an accident
      in either direction. Cheap audit next tripwire round: grep the
      b94-file docstrings for 'filed as bNN' / 'deliberately NOT' and
      check each one has a matching named test.
      DONE 2026-09-06: shipped as tests/test_b102_nonwidening_pins.py — an
      AST+prose audit over tests/, scripts/, engines/ and root (257 files,
      self-excluded like b94 excludes itself, floor test proves the scan
      scans) that binds every live non-widening claim to a test method whose
      NAME carries the item, plus the backlog-side check that each parked
      widening todo says "edited, not deleted". MEASURED AUDIT RESULT: 4 live
      code-prose claims (all b94's b101 sentences) + 2 commit-message claims
      (b100's b101 note, b99's b100 note) — ALL already pinned, so the rule
      ships green on day one and the audit is a tripwire, not a queue of
      victims (b98's shape). Two scope decisions recorded by measurement:
      'deliberately NOT edited' (b89's engines/risk.py note) is a file-scope
      statement already pinned by b88's byte-identity test, NOT a parked
      widening — dropped from the verb list after it fired on correct prose;
      and the history-spare must name the item, because 'not widened in this
      commit' contains 'widened in' (a real false-negative caught by replaying
      b99's actual commit message — pinned by
      test_negated_widening_is_a_claim_even_when_it_reads_like_history). The
      commit-message replay (last 100 messages vs CURRENT test names) is the
      piece that makes the rule enforce the "not commit messages" half.
      Hygiene lessons filed as new todo b103. 16 new tests, 1026 green, live
      cycle OK.
- [ ] b101 [META] PLAIN-ASSERT IDENTITY SIBLING (from b100, 2026-09-06): b100
      widened the self.assert* identity family (assertIs/assertIsNot/
      assertIsNone/assertIsNotNone) but deliberately did NOT flip the
      plain-assert `is` form — `assert main['detached'] is False` /
      `assert _checkout_is_detached() is True` — because b99 had parked
      exactly that shape in its SPARED pin list on purpose, and flipping
      the previous commit's pin inside a new widening is the
      multi-widening-in-one-commit shape this repo's audit history warns
      about. Measured 2026-09-06 (AST replay of the b101 predicate —
      Compare with Is/IsNot, either operand a probe/state-key and the
      other a _hardcoded_answer — over all 73 test files): ZERO offenders,
      so it is a free widening, same shape as b99/b100. Ship as its own
      item: add the Is/IsNot elif branch to scan()'s plain-assert pass
      reusing _state_subscript/_direct_probe/_hardcoded_answer, and MOVE
      the three shapes now pinned spared by
      TestIdentityAsserts.test_plain_assert_identity_stays_spared_pending_b101
      into the caught list (that test is the boundary pin — it must be
      edited, not deleted, so the flip is deliberate and dated). Decide
      the reversed direction (`assert None is probe()`) at the same time:
      b100's self.assert* branch covers both operand orders, the plain
      path's Eq branch does too, so symmetry says yes.
- [x] b100 IDENTITY-ASSERT SIBLING OF THE b94 DISEASE (from b99, 2026-09-06):
      the scan flags `assertEqual(probe(), X)` and bare `assert probe()`, but
      NOT `assertIs(probe(), False)` / `assertIsNone(list_worktrees(REPO))` —
      hardcoding the answer through the identity family is the same disease
      as ==-with-a-literal. Measured 2026-09-06 (AST replay over all 73 test
      files): ZERO offenders for assertIs/assertIsNot (probe or state-key vs
      a Constant) and for assertIsNone/assertIsNotNone (probe or state-key) —
      a free widening, same shape as b99's. Deliberately NOT shipped inside
      b99: b99's scope was the empty-container item + the plain-assert
      asymmetry, and a third silent widening in one commit is exactly what
      this repo's audit history warns about. Ship as its own item: extend
      scan() pass 2 with an IDENTITY_ASSERTS set ({assertIs, assertIsNot,
      assertIsNone, assertIsNotNone}), reuse _hardcoded_answer/
      _state_subscript/_direct_probe, pin both directions synthetically
      (identity caught, `assertIsNone(obj.attr)` spared) + the
      repo-wide-clean pin.
      DONE 2026-09-06: re-measured first (kernel replay of the widened
      predicate over all 73 files: 0 offenders — free confirmed). Shipped
      IDENTITY_ASSERTS on scan() pass 2 exactly as specified: the unary
      implicit-None branch (assertIsNone/assertIsNotNone on a probe or
      state-key) and the pair branch (assertIs/assertIsNot, BOTH operand
      orders, mirroring assertEqual). Scope decision recorded in the file:
      the negative forms stay IN because PAIR_ASSERTS has always contained
      assertNotEqual — dropping them would leave the tripwire blind to
      `assertIsNotNone(probe())` while it still catches its `!= None`
      twin. The plain-assert `is` sibling was NOT flipped (b99 parked it
      as a spared pin; one widening per commit) — measured free, filed as
      b101, and pinned in place by
      test_plain_assert_identity_stays_spared_pending_b101 so the boundary
      cannot be forgotten in either direction. 5 new tests
      (TestIdentityAsserts: pair caught both orders, implicit-None caught,
      foreign-object identity spared, b101 boundary pinned, in-memory
      repo-wide anti-vacuity + repo-wide-clean pin); 1010 green, live
      cycle OK.
- [x] b99 PROBE-RESULT COMPARED TO AN EMPTY CONTAINER LITERAL (from b97,
      2026-09-06): the b94 scan's _scalar() accepts None/bool/int/float/str/
      bytes, so `assertEqual(list_worktrees(REPO), [])` (or == (), == {}) —
      hardcoding "no worktrees"/"no output" as the answer a live probe exists
      to discover — is NOT flagged, while `assertFalse(probe())` is. The
      shape exists in the wild (b96's OLD leak test asserted a COUNT of the
      shared listing; the empty-container sibling is the same disease).
      Measured 2026-09-06: extending _scalar to EMPTY container constants
      flags ZERO offenders in the current 73-file suite, so it is a free
      widening — ship it with 2-3 synthetic pins (empty list/tuple/dict
      caught, non-empty list spared) plus the repo-wide-clean pin.
      DONE 2026-09-06: re-measured first (kernel AST replay of the widened
      predicate over all 73 files: 0 offenders — free confirmed). Shipped
      _empty_container()/_hardcoded_answer() ([] () {} set() frozenset();
      set()/frozenset() are CALLS in the AST, not Constants) on the
      self.assert* pair path, AND the measured-free sibling the item did not
      name: the PLAIN-assert COMPARISON (`assert probe() == []`,
      `assert main['detached'] == False`) was caught on the self.assert*
      path but not the bare-assert path — an asymmetry, not a policy; now
      flagged with the same predicate (Eq/NotEq only). Non-empty containers
      stay spared (structural/derived claim, b96 fixture-comparison shape);
      len()/sorted() wrappers stay spared (derived size claim). 6 new tests
      (TestEmptyContainerAndPlainAssert) pin both directions + an in-memory
      repo-wide anti-vacuity for the b99 shape itself; identity family
      (assertIs/None on a probe) measured 0 offenders too but deliberately
      NOT widened silently — filed as todo b100. 1005 green, live cycle OK
      (reassess, no_trade).
- [x] b97 B95 RESIDUAL BLIND SPOT: PROBES IN NON-TEST HELPER MODULES
      (from b95, 2026-09-06): the sibling resolution (seed 2) only walks
      modules named test_* living in tests/. A checkout-state probe with a
      NON-vocabulary name (e.g. `def _shape()` wrapping symbolic-ref) that
      lives in a shared helper (tests/hermetic.py, a future
      tests/_gitutil.py, or a scripts/ module) and is imported into a test
      slips past BOTH seeds — the name misses PROBE_NAME_WORDS and the
      module misses the test_* filter. Fix: widen the loader to resolve ANY
      ImportFrom module reachable from tests/ on sys.path (hermetic.py
      first), and reuse sibling_probes() there; keep the vocabulary seed as
      the unresolvable-source fallback. Small, tests-only.
      DONE 2026-09-06: resolve_src() walks tests/, repo root, and scripts/
      (the roots the suite sys.path-inserts) for ANY dotted module; seed (2)
      now imports only names the module EXPOSES at top level
      (exported_probes) — without that filter the widening would seed a
      consumer with head_verify's LOCALS ('r','add','rm' trace as state
      calls inside its functions) and light up unrelated tests. The
      per-loader memo made the sweep 61s -> 3.8s (27748 -> 78 loader calls).
      6 new tests (TestNonTestHelperModules) + repo-wide-clean pin; widened
      scan flags ZERO existing offenders. New todo b99 (empty-container
      literal sibling of the same disease).
- [ ] b98 [META] SHARED-STATE COUNT CLAIMS MUST BE OWNER-ATTRIBUTED (reusable
      procedure from b96, 2026-09-06): a test that asserts a COUNT of
      shared, mutable state (`len(git worktree list) == 1`, `len(listdir
      of a lock/tmp dir) == N`) is a flake whenever the repo supports a
      concurrent actor — b94's tripwire deliberately SPARED the derived
      `len(...)==1` shape as location-independent, and it was still wrong:
      location-independence fixes WHERE the suite runs, not WHO ELSE is
      running. RULE: before asserting a count of shared state, ask "can a
      supported concurrent process legitimately change this number?" If
      yes: (1) attribute the claim — count only entries the test's own
      process tree can prove it left behind (b96: owner.pid +
      head_verify.owner_state, the same tool the sweep uses, so test and
      sweeper agree on what "orphan" means); (2) derive every exclusion
      from git's/OS's own answer (b94 rule — --git-common-dir for the main
      worktree, never the author's cwd); (3) close the OPPOSITE race (an
      entry appearing mid-check) by re-confirming after a short beat
      before going RED — a real leak is permanent, a concurrent one is
      transient; (4) pin BOTH directions with the fixture builders the
      production-side sweeper already uses (alive owner spared AND the old
      assertion provably fails on the same state; dead owner still
      counts) so the fix cannot silently become `assert [] == []`. Cheap
      audit next run: grep tests/ for assertEqual(len(...)) over anything
      not built by the test itself (repo listings, /tmp, process tables)
      — b96's sweep found this file is the only remaining instance today,
      so this is a tripwire-candidate rule, not a queue of victims.
- [ ] b87 [META] GATE-SHADOWING TEST: MEASURE A FILTER AGAINST THE OTHER FILTERS,
      NOT JUST AGAINST NOTHING (reusable procedure from b86, 2026-09-05):
      b84's template (kept book vs dropped book vs the counterfactual knob
      position) proves whether a gate BINDS. It cannot prove whether a gate
      MATTERS: a gate can fire constantly on a population that a DIFFERENT
      live gate already rejects, and read as an active risk control while
      never once being the reason a trade was skipped. b86 caught exactly
      that on range-kill: 49-57% of raw signals are killable at the ceiling,
      100% of them C-grade, live-gated book 0 trades on 5-of-5 legs. RULE:
      for every filter, add the REDUNDANCY row — take the population the
      gate can kill at full power, classify it by the OTHER live gates' own
      verdicts (grade, rr, DEFCON, cooldown, market hours), and run it as a
      book twice: once under the live gate stack (what the executor would
      actually trade) and once with only THIS gate removed. If the live-stack
      book is empty on every leg while the single-removal book trades, the
      gate is shadowed and its protection is being provided by something
      else; say so in the ledger and never propose deleting it on that basis
      (a shadow is also a backstop if the shadowing gate ever moves). Also
      record REACHABILITY next to it — whether any adaptive path (learning.py)
      can move the knob at all — because a no-op that can never be tightened
      is dead code with a risk vocabulary, and a no-op that CAN be tightened
      is the b84 cliff hazard. Cheap: one extra book pair per filter on the
      existing legs. Remaining queue in b84's order: DEFCON, cooldown,
      market-hours (each gets the bind test if unmeasured, then this one).
      PROGRESS 2026-09-06: DEFCON done (b88). COOLDOWN done (b92,
      scripts/b92_cooldown_gate.py + data/backtest/b92_cooldown_gate.json +
      11 tests) — and it produced a NEW verdict class: the gate lives in the
      CLOCK domain, not the book domain. All 5 legs have ZERO Sunday bars
      (datasets are weekday-only), so the post-open window contains 0 funnel
      signals and the b84 book template CANNOT price this gate — "0 kills"
      here is a measurement-medium artifact, not b86's no-op. Measured in the
      domains that can see it instead: live master-cycle log (1 restart arm in
      1542 cycles / 8 days — the b30 fix holds), analytic reach (0.21% of
      trading time), shadow row (market_hours ALLOWS Sun 23:00-23:14 →
      cooldown is the ONLY gate on its window, the opposite of range-kill),
      reachability (learning cannot move either knob). Remaining: market-hours.
- [x] b71 LAB HARNESS: every arm must be re-measured under the LIVE time_exit
      (reusable procedure from b68 round 6). The round-6 level-anchored arm printed
      exp_R +1.096 — the best number any lab arm has ever produced — and it was an
      artefact: mean stop 5.66 ATR from entry (max 11.2) and mean hold 87 M15 bars
      (max 520 = 5+ days), i.e. a swing position scored on an intraday board. Under
      the live 36h time_exit (backtest_ohlc time_stop_bars=144) it collapsed to
      +0.787R on n=41. The lab harness (scripts/b68*_lab.py + the confirm scripts)
      never passes time_stop_bars, so ANY arm whose natural hold exceeds 36h is
      measured under exit rules live will never give it. Fix: add a
      `time_stop_bars=144` pass to the standard arm grid (or, cheaper and equally
      honest: report mean/max hold in bars alongside exp_R and FAIL the round's own
      summary if mean_hold > 144 without a time-stopped re-measurement), and pin it
      with a test that the shipped JSON carries the hold column. Small, lab-only,
      read-only. Also worth pinning in the same pass: the fade/level-stop geometry
      trap (risk <= 0 silently drops every signal -> trades:0 read as "no edge";
      b69 class, caught in round 6's own control arm) — a one-line assertion in the
      lab runner that any arm reporting trades:0 must name which clause never fired.
      (done 2026-09-04: engines/lab_harness.py is the ONE measurement harness —
      run_arm() scores every arm THREE ways (plain / ladder / ladder_ts = live b60
      ladder + live time exit), the time exit is DERIVED from
      legacy_guards.MAX_POSITION_AGE_HOURS and the dataset's own bar spacing (M15→144,
      M5→432, never hardcoded), every row carries mean/p95/max hold + holds_over_time_exit,
      and a trades:0 row must carry a zero_reason from diagnose() (never_fired /
      invalid_geometry / min_rr / grade / slot_occupied / raised). check_honesty()
      flags the w10 shape; scripts/b71_recheck_round6.py re-measured ALL round-6 arms
      and shipped data/backtest/b71_harness_recheck.json — it REPRODUCES the artefact
      exactly (ladder 1.096 → ladder_ts 0.787, n 30→41) and the honesty summary names
      BOTH level-anchored arms (w10 AND w10_e25) via a p95-hold clause added during
      this run: w10's MEAN hold (87.5) is under the 144 limit, only its TAIL (p95 248,
      max 520) is swing-shaped — mean-hold-only checking would have missed the real
      artefact. 12 tests in tests/test_b71_lab_harness.py pin the shipped JSON columns,
      the artefact numbers, the derivation, the three diagnose verdicts, honesty
      both-directions, and that no live-path module imports the harness. NOTE: the
      harness module itself was left UNCOMMITTED by the previous run (b46 shape) —
      shipped via this run's harvest commit.)
- [ ] b70 [META] ADDITIVE-LANE CAPACITY ANALYSIS (follow-up to b68 round 4, 2026-09-03): the
      pdh_break_w10 arm (scripts/b68e_pdh_lab.py, 1.0*ATR stop beyond the previous
      TRADING day's extreme, close-confirmed) is the first lab arm that beats the live
      funnel on fresh data (exp_R 0.640 vs 0.576, n=108) and the funnel's own merit bar
      rejects it as a REPLACEMENT (cached 0.627 vs 0.854). But the additive-lane probe —
      funnel first, arm only on bars the funnel leaves empty, one position at a time —
      measured n 354 vs 319, tot_R 197.9 vs 183.6 (+7.8%), exp_R 0.559 vs 0.576
      (-0.017R), dd_R 7.0 vs 5.0 on the SAME fresh 6000 M15 bars
      (data/backtest/b68e_pdh_confirm.json). That is a CAPACITY question (does an extra
      ~35 trades/6000 bars at slightly worse per-trade quality and worse DD earn its
      slot?), NOT an expectancy question, and it must be settled before anything touches
      the live structure. Decide with: (1) the same lane replay on the CACHED set and on
      at least two independent fresh fetches (the single fresh set is one sample — the
      arm's fresh win may be luck; b68 round-1 METHOD RULE applies to lanes too),
      (2) the live gate stack the lane would have to pass anyway (MAX_OPEN_POSITIONS=1
      means the lane trades only when the funnel's slot is FREE — measure how often that
      is actually true in live, from plan_history/execution_log, not from the backtest),
      (3) DD and losing-streak impact on the DEFCON/kill-switch inputs, and (4) the
      grade-gate precedent: a C-grade arm that occupies the single slot was rejected in
      the 2026-08-30 audit for blocking later B setups — the same blocking argument
      applies to a lane entry that is still open when a funnel A setup appears. Do NOT
      wire anything live on the strength of one fresh set. Read-only analysis.
      (progress 2026-09-03, round 5: a SECOND lane candidate now has lane data —
      nr7_break_w10 (scripts/b68f_nr7_lab.py). Its fresh lane (data/backtest/
      b68f_nr7_confirm.json) is the strongest probe yet: n 499 vs funnel 323,
      tot_R 309.5 vs 189.2 (+120R incremental — ~8x what pdh's lane added),
      lane exp_R 0.620 ABOVE the funnel's 0.586 — which also proves the lane
      is NOT funnel-trades + free extras: the arm's open positions BLOCK some
      funnel entries (one-position model), changing the mix. b70 must now
      compare BOTH lanes (pdh vs nr7 vs funnel+pdh+nr7 stacked), measure the
      blocking cost explicitly, and replay on cached + >=2 fresh fetches
      before any capacity decision.)
      (progress 2026-09-03, round 6: a THIRD lane candidate has data and it is
      NEGATIVE — dayext_cont_a10 (scripts/b68g_dayext_lab.py) lane exp_R 0.410
      vs funnel 0.585, dd_R 17.6 vs 5.0 (data/backtest/b68g_dayext_confirm.json).
      Ranking so far: nr7 0.620 > pdh 0.559 > funnel 0.585 > dayext 0.410, so
      b70 can DROP dayext from the lane comparison and decide between nr7 and
      pdh (note nr7 is the only lane above the funnel's own per-trade R). New
      capacity sub-question the dayext lane exposed: lane quality is
      anti-correlated with how OFTEN the arm fires (dayext fires on 800 bars =
      2.5x the funnel's 323 and crowds the single slot; nr7 455, pdh 108) —
      b70 should measure slot-contention directly, not just tot_R.)
      (progress 2026-09-04, round 7: a FOURTH lane has data and it tests the
      contention question DIRECTLY — the GATED nr7 (nr7 x dayext agree,
      data/backtest/b68h_combo_confirm.json) fires 3x less than raw nr7 (135
      vs 453 fresh trades) and its lane is NEGATIVE: exp_R 0.579 < funnel
      0.590, dd_R -6.9 vs -5.0, despite the arm's own exp_R being the best
      non-funnel number measured (0.587). So round 6's anti-correlation rule
      holds in reverse: cutting frequency raised per-trade R but the lane's
      MARGINAL trades still sit below the funnel average. b70's decision set
      is unchanged (nr7 vs pdh vs stacked) — the gated variant is dropped
      like dayext. Read-only.)
      (progress 2026-09-04, round 8: a FIFTH lane — the GATED pdh (pdh x NR7
      squeeze agree, data/backtest/b68i_squeeze_pdh_confirm.json) — repeats
      the round-7 shape on the other ingredient: fresh lane exp_R 0.580 <
      funnel 0.590 (dd -4.1 vs -5.0, tot_R 189.0 vs 189.8 — the +4 extra
      trades add NOTHING, while the ungated pdh lane on the same bars carried
      tot_R 206.1). Unlike round 7 the gate does not even lift its own
      control (cached 0.627 -> 0.406). Two gated combinations now measured,
      both lane-negative: gating a lane arm to raise its standalone R is NOT
      the lever — b70 should decide on the UNGATED nr7/pdh lanes only.)
      (progress 2026-09-04, round 9: a SIXTH lane — the dayext-GATED pdh
      (pdh x day-extension agree, data/backtest/b68j_dayext_pdh_confirm.json)
      — is the FIRST lane to beat the funnel on ALL THREE axes on its fresh
      set: exp_R 0.634 > 0.590, tot_R 212.4 > 190.6, dd -4.1 BETTER than
      -5.0 (n 335 vs 323). Rounds 7/8 said gating is not the lever; round 9
      refines that: gating on a PATH oracle that fires only ~37% of pdh
      signals (the committed-day subset) is the one gate that improved every
      axis, while gating on compression (round 8) or on the nr7 geometry
      (round 7) did not. b70's decision set must now be re-ordered:
      gated-pdh(dayext) > nr7 0.620 > funnel 0.590 > pdh 0.576 > gated-pdh
      (squeeze) 0.580-flat > dayext 0.410 — but this is ONE fresh set on a
      39-trade arm; b74 (replication) gates any promotion. Read-only.)
      (progress 2026-09-04, round 10: a SEVENTH lane — the REVERSED pairing
      (dayext geometry gated on same-day PD-break agree, data/backtest/
      b68k_pdh_dayext_confirm.json) — is NEGATIVE: lane exp_R 0.471 < funnel
      0.590, dd_R -12.6 vs -5.0 despite +208 extra trades. The gate lifted
      its own control on both sets (0.327->0.369 cached, 0.316->0.371 fresh)
      yet the lane still dilutes — the arm fires on 461 gated signals (1.4x
      the funnel's 323), so slot crowding (round 6's rule) dominates the
      quality lift. Decision set unchanged: gated-pdh(dayext) and raw nr7
      remain the only positive lanes; dayext-based lanes stay dropped whether
      gated or not. Read-only.)
      (progress 2026-09-04, round 11 — THE DATA MOVED UNDER THIS ITEM: the
      b68l re-measure on truly independent windows (see Findings) shows the
      contaminated "fresh" set inflated most lane evidence. On W1/W2 the
      gated-pdh(dayext) lane replicates only a MARGINAL positive (< +0.05R
      vs funnel on both windows, DD no better on W2), nr7's arm loses both
      windows standalone, and the UNGATED pdh_w10 is the only arm beating
      the funnel on both windows. b70's decision set must be RE-SCORED on
      W1/W2 lanes (cached + W1 + W2, not cached + one contaminated fresh)
      before any capacity conclusion; the round 5-10 lane numbers quoted
      above are contaminated-fresh artefacts and must not be reused.)
      (progress 2026-09-04, round 12 harvest: the H4-gated pdh lane
      (data/backtest/b68m_htf_pdh_confirm.json) is the second
      replicated-positive lane on clean windows — exp_R 0.534/0.535 vs
      funnel 0.524/0.521 on W1/W2, margin < +0.05R on both, dd mixed (worse
      W1, better W2). Same MARGINAL shape as round 11's lane, so two
      independent gated lanes now agree the lane delta is small; the
      interesting result is the ARM's standalone replication (0.657/0.927),
      which belongs to b74, not to a lane slot. b70's decision set on clean
      windows: ungated pdh_w10 (0.612/0.623) and pdh_h4t_agree (0.657/0.927)
      as REPLACEMENT candidates vs the funnel's 0.524/0.521, lanes marginal.
      Read-only.)
      (progress 2026-09-04, round 13 harvest: W3 KEEPS LANE EVIDENCE WEAK —
      the h4pdh lane (funnel-first + gated pdh on free bars) LOSES W3
      (0.515 vs funnel 0.528 on the same bars, data/backtest/
      b68n_funnel_gate_w3.json) after marginal positives on W1/W2: lane
      evidence is now 2-of-3 windows and below b74's replication bar. The
      round's only three-window positive is funnel_h4t_agree — a REPLACEMENT
      FILTER question (cut the funnel's disagreeing entries), not a lane, and
      its W3 margin is +0.008R with the selection ordering flipped. b70's
      clean-window decision set shrinks to: pdh_w10 (0.612/0.623/0.370 —
      FAILS W3) and pdh_h4t_agree (0.657/0.927/0.505 — FAILS W3) as
      replacement candidates, both now 2-of-3; no lane clears three windows.
      Read-only.)
      (progress 2026-09-04, round 14: W4 CLOSES THE BOOK on the current
      decision set — funnel_h4t_agree dies on the fourth draw (0.517 vs
      funnel 0.532), the h4pdh lane beats W4 (0.546) but is 3-of-4 after
      losing W3, and pdh_w10 loses W4 (0.480, 2-of-4). No arm or lane
      clears ALL FOUR independent windows, so b70's capacity question has
      nothing left to weigh: the answer on clean windows is "no lane earns
      a slot". The four-window funnel baseline (0.524/0.521/0.528/0.532)
      is the bar any future lane must clear on EVERY window. Read-only.)
- [x] b78 DIRECTION-MIX DISCLOSURE FOR LEVEL-BREAKOUT ARMS (reusable procedure
      from b68 round 15, 2026-09-05): the weekly-breakout arm's BUY/SELL split
      FLIPS between windows (cached 24/24 BUY, W1 13 BUY/39 SELL) — so a
      single-window exp_R for any level-breakout arm is really "the number for
      whichever way that regime broke", and two windows with the same exp_R but
      opposite mixes are NOT the same measurement. RULE: every future round's
      ledger must carry the probe's buy/sell split per leg (level_probe already
      ships it — just don't drop it from the confirm JSON), and the verdict
      text must quote the mix whenever a window's number is used as evidence;
      an arm whose sign of edge flips with the direction mix is regime-gifted
      even when b77's margin series says MIXED. Cheap: docs/procedure + one
      assertion in the next round's test that every shipped leg carries
      buy+sell>0 facts. Read-only, lab-only.
      (done 2026-09-05 via b68 round 16: implemented as a STRUCTURE, not a
      convention — scripts/b68p_confirm_runway.py side_mix() re-runs each arm
      through the b71 exit grid and records the BUY/SELL split of the TRADES
      it actually takes (slot occupancy can change the mix, so raw-signal
      counts would lie) into every arm row of every leg; the verdict block
      carries buy/sell per arm per window; the registry rows carry the mix per
      leg; and tests/test_b68p_runway_lab.py pins it three ways —
      buy+sell==trades and >0 for every arm×leg in the shipped ledger, the
      mix present in the verdict cells, and the mix present in the registry
      windows. The round also PROVED the disclosure earns its keep: the
      no_runway complement is one-sided per regime (W3 32B/2S, W4 62B/12S)
      while the gated arm is two-sided everywhere — invisible without the mix,
      and it is exactly why the gate's flip reads as regime-gifted.)
- [x] b85 AUTOPILOT REPORT: ATTRIBUTE COMMITS BY TIME, NOT BY AUTHOR
      (2026-09-05, from the user's 'این خطا مال چیه' on the 13:00 report):
      that report was false in three of its lines. A run hit the 55-minute
      ceiling (rc=124) having committed NOTHING; the report diffed
      prev_head..HEAD, found one commit — a MANUAL fix made at 11:53, between
      two runs — and printed '⏱️ ... اما کارش کامیت شده بود', '🛠 تغییرات این
      اجرا' and '📌 1 تغییر کد کامیت ... ثبت شد'. The operator was told a lost
      step was safe when the step had never existed. Fix: pure helpers in
      engines/autopilot_report_lib.py (run_start_from_log reads the LAST UTC
      'run start' marker from logs/autopilot.log; classify_commits splits
      %ct\x1f%s lines into this-run vs other by commit time, falling back to
      the old behaviour when no marker exists); scripts/autopilot_report.py
      now keys the ⏱️ 'work was committed' claim, the 🛠 block and the 📌 count
      off THIS RUN's commits only, and lists the rest under '🧹 ثبت‌شده بیرون
      از این اجرا'. Also: the 📋 backlog tick is counted from the working tree,
      so when nothing was committed it now says '(هنوز ثبت نشده — دور بعد)'
      instead of implying it is banked. Pinned by
      tests/test_b85_report_attribution.py (14 tests: marker parsing, boundary,
      mixed window, unparsable time, plus two end-to-end renders on a
      throwaway repo with controlled GIT_AUTHOR_DATE — the exact 13:00 shape
      must NOT claim committed work, and a real in-run commit still must).
      Lesson for any future report generator: a diff range is not an
      attribution; state WHO/WHEN did the work or say nothing.
- [x] b81 RE-SCORE THE b70 LANE DECISION SET AGAINST THE CORRECTED (b80) BAR
      (follow-up to b80, 2026-09-05): b81's OWN premise was wrong and that is
      the finding: the note said the lane arms are "unaffected by the fix",
      but every shipped lane row is `funnel(row) or arm(row)` — the lane's
      PRIMARY signal source is the funnel's own A/B/C-graded signals, so the
      lanes carried the same C-grade trades the live executor rejects.
      Re-reading the ledgers against b80's gradeB column would have corrected
      one side of the comparison and left the other broken, so b81 RE-MEASURED
      all four lanes under the live gate on cached+W1..W4
      (scripts/b81_lane_rescore.py -> data/backtest/b81_lane_rescore.json,
      both conventions per leg; the ungraded re-measure reproduces all 16
      shipped ledger rows EXACTLY, which is the integrity proof). Result: the
      gate lifts each pdh-family lane by +0.13..+0.26R, the same order as the
      funnel's own lift, so the corrected verdict is 2-of-4
      (gated_pdh_dayext), 3-of-4 (h4pdh), 2-of-4 (runway), 0-of-4 (nr7htf) —
      NO lane clears b74's all-windows rule, and the best margin anywhere is
      +0.061R. b70's standing answer ("no lane earns a slot") is now settled
      on the corrected bar, and nr7htf is the clean illustration of the trap:
      it adds +46..+67 net_R on all four windows with a positive marginal
      trade, yet loses exp_R everywhere — volume is not quality. 17 tests in
      tests/test_b81_lane_rescore.py pin the reproduction, the corrected
      verdict, the premise-falsifying lift, and the net_R trap. Nothing wired.
      See Findings.
      [original note, superseded above:] b70's lane numbers were all produced by
      `run_arm()` WITHOUT the live grade gate, so every lane-vs-funnel
      comparison in that item compared a GRADED lane against an UNGRADED
      funnel. The lane arms (pdh/nr7 variants, all grade "B") are unaffected
      by the fix, but the funnel they are measured against moves from
      0.521-0.532 to 0.662-0.767 on W1-W4 — so the two lanes b70 still calls
      positive (gated-pdh(dayext) and raw nr7) are almost certainly negative
      on clean windows, and b70's standing answer ("no lane earns a slot")
      becomes firmer, not weaker. Do this WITHOUT new compute: the lane rows
      are already shipped in data/backtest/b68{l,m,n,n4,p,q}_*.json — read
      them, compare against data/backtest/b80_gate_parity.json's gradeB
      column, and rewrite b70's decision set. Read-only, lab-only.
- [ ] b82 [META] PARITY TRIPWIRE: THE LAB HARNESS MUST NOT BE ALLOWED TO DRIFT FROM
      run_backtest AGAIN (reusable procedure from b80, 2026-09-05): b80 was
      the second measurement-parity bug in this lab (b71 was the first — the
      missing time exit). Both were silent because the harness re-declared its
      own gate constants instead of deriving them from the canonical runner.
      Fix as structure: add a test that asserts engines/lab_harness.py's
      measurement defaults (SPREAD, MIN_RR policy, LIVE_MIN_RR, LIVE_MIN_GRADE,
      LADDER keys, derived time exit) are EXACTLY the defaults of
      engines.backtest_real.run_backtest's signature — inspect.signature on
      both, compare parameter by parameter, and FAIL with a named diff if any
      default diverges. That turns the whole class of bug into a red test the
      next time someone adds a gate to live and forgets the lab. Small,
      tests-only.
- [ ] b83 [META] COMPOSITE-SIGNAL PARITY RULE: A FIX TO A COMPONENT MUST RE-PRICE ANY
      MEASUREMENT THAT EMBEDS IT (reusable procedure from b81, 2026-09-05):
      when a measurement bug is found in a component (b80: the funnel baseline
      lacked the live grade gate), the follow-up work must NOT assume that
      other rows built from that component are unaffected. Any composite
      signal — `funnel(row) or arm(row)`, a lane, a blended score, an
      ensemble — INHERITS the component's bug in proportion to how often that
      component supplies the trade. b81's own founding note made exactly this
      mistake ("the lane arms are all grade B, so they are unaffected") and
      the shipped lane rows turned out to be inflated by +0.13..+0.26R, the
      same order as the funnel's own lift, because a lane is funnel-FIRST.
      PROCEDURE: (1) grep the ledgers/scripts for every consumer of the buggy
      component, not just the ones that call it directly — look for the
      composition operator, not the name; (2) for each consumer, ask what
      fraction of its trades the component supplies (a lane at ~90% funnel
      share is the funnel with a sticker); (3) re-MEASURE under the fix rather
      than re-READING the old rows against the new bar — a one-sided
      correction produces a confident wrong verdict; (4) prove the re-measure
      is honest by reproducing the OLD row exactly with the OLD convention
      (b81 does this for 16/16 legs and pins it in a test), so a changed
      verdict can only come from the fix, never from drift; (5) state the
      corrected verdict under the SAME replication rule as the components
      (b74's all-windows rule applies to lanes too). Cheap here (~4 min for
      5 legs x 5 rows); the wrong alternative was a published wrong answer.
- [x] b84 MEASURE THE GATE, NOT JUST THE ARM (reusable procedure from b68
      round 18, 2026-09-05): every live FILTER (grade gate, min_rr, DEFCON,
      cooldown) must eventually be measured as BOOKS — run the funnel's own
      kept population and dropped population each as a standalone book
      through the live-parity harness on cached+W1..W4 — and reported on
      BOTH R axes (exp_R per trade AND total net_R + DD), because round 18
      proved one filter can win 4-of-4 on selection while losing 4-of-4 on
      volume (+29..+57R given up by min_grade=B; marginal trade
      +0.21..+0.37R). A filter whose dropped book's marginal trade is
      NEGATIVE everywhere is a true cliff (B/C: 8-of-8 window x side cells);
      one whose flip is confined to a single grade x side cell is a
      DIRECTION artifact, not a rung property (A/B on W4 sell) — never
      tighten a gate off a cached-leg or single-cell number. Reuse
      scripts/b68r_grade_ladder_lab.py's book_fn/side_mix/_side_split
      structure; pin reproduction against the shipped parity ledger
      (b80_gate_parity.json) as the round's first test. Small, lab-only,
      read-only. Next filter due: min_rr=1.5 (b80 measured rr 1.549-1.552
      at the funnel's own entries — the gate is nearly never-binding there,
      so the book measurement may be cheap and could retire a dead knob).
      DONE 2026-09-05 (shipped in 5679746, tick harvested by the 12:35 run —
      b84_rr_gate_books.py + 12 tests + ledger): min_rr=1.5 is a NO-OP on
      the funnel's own book (0 dropped trades on all 5 legs) because
      _reanchor_blueprint manufactures every rr at floor+0.05 (spike
      1.547-1.554, share>=0.997 inside the band on all windows) — the gate
      checks its own builder's output, a tautology not a filter; the real
      risk is the CLIFF: learning.py's first +0.25 step (1.75) kills
      98.9-100% of entries on all 4 windows (-257.3R given up, 3 trades
      left, pays 2-of-4 only) — knob stays (never weaken), but any future
      adaptive-floor proposal must clear this ledger first.
- [ ] b85d [META] FIXTURE-COMPLETENESS RULE FOR SUBPROCESS TESTS (reusable procedure
      from the 12:35 run, 2026-09-05): a test that runs a repo script in a
      THROWAWAY fixture dir (copy of the script + symlinked engines) inherits
      the script's whole import surface — including fallback imports like
      `from env_loader import load_dotenv` that only fire on hosts WITHOUT
      python-dotenv. b85's fixture copied the script but not env_loader.py,
      so the child died at import (rc=1) whenever the suite ran under a
      python WITHOUT dotenv (system python3): 2 tests red in the working
      tree, while the same suite under the Hermes venv (has dotenv) is
      green — a HOST-DEPENDENT test, invisible to whoever runs it from the
      venv. RULE: when a test shells out to a repo script, copy (or
      symlink) EVERY module the script's import fallbacks can reach — the
      fixture must be complete for the WORST host, not the author's; and
      when a failure appears in one runner and not another, diff the
      interpreters (venv vs system) before suspecting the code. Fixed by
      shipping env_loader.py into the fixture (tests/test_b85_report_
      attribution.py). Small, tests-only.
- [ ] b79 [META] GATE FIRE-RATE STABILITY PRE-FLIGHT (reusable procedure promised
      by b68 round 16's Findings, 2026-09-05; first metric measured in round
      17): before spending four b74 draws on a gated arm, measure the
      oracle's PASS RATE per window (gate_share in the probe block) and the
      median threshold-crossing age of the kept subset. An oracle whose
      pass-rate swings by regime (round 16's weekly-runway: 36%-68%) cannot
      produce a regime-independent selection — close the round on the probe
      alone. ROUND 17 CALIBRATION: the H4 gate's pass rate is the loop's
      most stable (0.433/0.451/0.461/0.462) and its selection ordering is
      the loop's cleanest (4-of-4 agree>cut) — and the arm STILL failed the
      merit bar 1-of-4 (lift over control replicated only 2-of-4). So b79
      is a NECESSARY-not-sufficient screen: a stable fire rate rules out
      regime-gifted selection, it does not promise a replicating LIFT; the
      lift-vs-control test (already in every confirm ledger) stays the
      binding check. Implement as structure: add a pass-rate-swing column
      (max-min gate_share across legs) to the verdict block in
      scripts/b68*_confirm_*.py and a pre-flight FAIL line in the round
      summary when swing > 20 points. Small, lab-only, read-only.
- [ ] b72 [META] COMBINATION-ROUND PLAYBOOK (reusable procedure from b68 round 7, for
      every future b68 round that gates one family on another): (1) build the
      combo as a PURE INTERSECTION — one arm supplies the geometry unchanged,
      the other is a direction/timing oracle only, so no new stop geometry can
      reintroduce the b69/round-6 traps; (2) ship an ANTI-VACUITY probe with
      the ledger (fire counts of each ingredient + agree/disagree split of the
      gated subset) — a combination whose gate fires on ~100% or whose
      agree/disagree split is ~0/100 is the same arm twice, not a combo;
      (3) always re-measure the UNGATED ingredient as a control arm in the
      same run so the gate's delta is same-dataset same-harness; (4) pin the
      CONFIRM ledger's verdict numbers (funnel vs arm vs lane) with a test,
      not just the cached lab — round 7's cached 0.622 would have looked like
      a lane promotion until the fresh 0.587-vs-0.590 lane said no; (5) quote
      lane exp_R AND dd_R together — round 7 proved a lane can add tot_R
      (+6.8%) while being negative on both per-trade R and DD. Small, docs/
      procedure only unless a round needs it.
- [ ] b73 [META] COMBINATION-ROUND SEQUENCING RULE (reusable procedure from b68 rounds
      7+8, 2026-09-04): the two measured combination rounds split cleanly by
      WHICH ingredient acts as the gate — a DAY-PATH gate (dayext) LIFTED its
      control (nr7 0.598->0.622 cached), a COMPRESSION gate (NR7 squeeze
      resolution) LOWERED its (pdh 0.627->0.406) because the squeeze's
      information is already spent by the time a level break confirms (stretch
      probe: gated entries 0.667 vs 0.558 ATR from the broken level). Future
      combination rounds should therefore (a) prefer gating a LEVEL/PATH
      ingredient on another PATH ingredient, not on a compression state, and
      (b) run the stretch probe (entry distance from the trigger level) as a
      STANDARD part of every combination confirm — it explained round 8's
      failure before the R numbers did and costs one loop. Cheap to apply:
      stretch_probe() already exists in scripts/b68i_confirm_squeeze_pdh.py;
      fold it into the b72 playbook checklist on the next combination round.
      Read-only, docs/procedure only.
      (update 2026-09-04, round 10: the rule REFINED by the reversed pairing.
      Round 9 confirmed (a): path-gated level geometry lifted hard (0.627 ->
      0.924) with clean stretch (0.564 vs 0.558 ATR). Round 10 ran the mirror
      — level-gated PATH geometry — and the gate lifted its control on BOTH
      sets (0.327->0.369, 0.316->0.371, disagree arm worst on both) yet the
      arm stayed 2.3x below the funnel and its lane negative. The stretch
      probe says why the lift is small: agree entries sat 4.0 ATR from the
      broken level (the extension trigger prints HOURS after the break) vs
      round 9's 0.56 ATR. So (a) is necessary but not sufficient — the
      pairing must also pick the RIGHT member as geometry supplier: the
      FRESHER event of the pair (the one whose signal bar IS the trigger)
      should carry the stop, and the background state should be the oracle.
      Splitting {level, path} by freshness, not just type -> new todo b75.)
- [ ] b75 [META] GEOMETRY-FRESHNESS RULE FOR COMBINATION ROUNDS (reusable procedure
      from b68 round 10, 2026-09-04): both directions of the dayext<->PD-level
      pairing now have data. Forward (round 9: level geometry, path oracle):
      lift +0.30R, stretch 0.56 ATR, merit bar PASSED. Reversed (round 10:
      path geometry, level oracle): lift +0.04R, stretch 4.0 ATR, rejected.
      Same two ingredients, same pure-intersection discipline — the ONLY
      difference is which event carries the stop. RULE: in a combination arm,
      the geometry supplier must be the FRESHER event (the one whose signal
      bar is the trigger itself); gating a lagging confirmation on its own
      leading signal buys a real but small R lift and pays for it in stretch
      (chase tax) and slot crowding.
      (CAVEAT 2026-09-04, round 11: the dayext<->PD-level "genuine property"
      premise behind this rule is DOWNGRADED — on truly independent windows
      the gate's agree-vs-complement ordering FLIPS SIGN between regimes
      (0.928>0.415 on W1, 0.447<0.743 on W2). The freshness/stretch mechanics
      still measure real chase costs, but the dayext gate must not be
      trusted as a stable direction oracle in future rounds.)
      CHECK before writing a round: measure
      the oracle's typical LAG from the geometry's trigger bar (count of bars
      between the oracle event and the geometry signal bar); if the median
      lag > ~8 bars (2h on M15) the pairing is probably reversed and should
      be flipped. Cheap to apply: the lag counter is a 5-line loop over the
      same scan gate_probe() already does; fold it into the b72 checklist as
      rule (6) on the next combination round. Read-only, docs/procedure only.
- [ ] b76 [META] CONFIRM SETS MUST PROVE INDEPENDENCE (reusable procedure from b68
      round 11, 2026-09-04 — the loop's biggest methodology finding: rounds
      1-10's "fresh" confirm set was the last 6000 M15 bars, which contains
      100% of the 3000 cached bars, so the merit bar's "beat the funnel on
      BOTH sets" was a set vs its own superset for ten rounds and produced
      at least one false champion). RULE: any confirm/backtest script that
      fetches "the last N bars" must (a) compute the overlap with every
      in-sample set it is compared against, (b) record the number in the
      shipped ledger, and (c) either assert it is ZERO or label the set
      in-sample in the ledger so no reader can quote it as out-of-sample.
      The reusable builder is scripts/b68l_windows.py (deep fetch ->
      strictly-before slicing -> H1/H4 context padding -> overlap facts
      recorded); the reusable verdict rule is
      b68l_confirm_independent.verdict() (PASS = beats the funnel's
      ladder_ts on the SAME bars in >=N-1 of N windows; None/tie never
      beats). Cheapest real fix: a shared helper engines/lab_windows.py
      exposing independent_window(cached_path, n, before_ts) +
      overlap_with(rows, span) that every future confirm calls instead of
      hand-fetching, plus a tripwire test that no scripts/b*_*_confirm*.py
      fetches last-N bars without recording an overlap fact. Read-only,
      lab-only.
- [ ] b77 [META] CHRONOLOGICAL-DECAY TEST BEFORE SPENDING A DRAW (reusable procedure
      from b68 round 14, 2026-09-04 — the todo round 14's Findings promised but
      never wrote; added by the round-14 harvest run). The fourth draw killed
      funnel_h4t_agree, and the SHAPE of the kill is the lesson: margins
      quoted window-by-window (+0.093/+0.032/+0.008/−0.015) look like a
      candidate slowly decaying toward the bar, but read in CHRONOLOGICAL order
      (W4 oldest → W1 newest) they are MONOTONIC INCREASING — the edge grows
      with recency, which means it is a property of the recent regime, not of
      the market. A candidate like that cannot be expected to survive forward
      out of the regime that feeds it, and no further draw can rescue it.
      RULE: before spending a new window draw on a candidate, assemble every
      already-measured window for that arm, sort by TIME (not by window label),
      and fit/inspect the margin series: if the margins are monotone in
      recency (all same-sign slope, |slope| >= 0.02R per window-step) the
      candidate is regime-gifted — STOP, do not burn the draw, record the
      decay curve as the verdict. The check is 5 lines over the ledger rows
      the round already ships (see b68n4_fourth_draw.verdict()'s margin_series
      + the chronological-monotonicity test in tests/test_b68n4_fourth_draw.py
      for the exact shape); fold it into b74's protocol as step (0) — a
      pre-flight, cheaper than the draw itself. Also pin: window labels are
      NEWEST-FIRST (W1 newest), so any code that reads a "decay W1→W4" series
      is reading time BACKWARDS — the round-14 near-miss was exactly this
      misread. Read-only, docs/procedure + a small helper only.
- [ ] b74 [META] CANDIDATE PROMOTION PROTOCOL (reusable procedure from b68 round 9,
      the FIRST arm ever to pass the merit bar — the loop has never needed
      this before): a lab arm that beats the funnel on both sets is a
      CANDIDATE, not a winner. Before any wiring proposal, it must survive:
      (1) REPLICATION on >=2 more independent fresh windows (non-overlapping
      with each other and with the cached set) — a single fresh set is one
      draw of the same regime that produced the cached number; (2) the FULL
      LIVE GATE STACK (DEFCON, session filter, cooldown, news blackout)
      applied on top — the lab measures the funnel+arm in isolation, the
      live system filters both, and a lane that only fires in already-blocked
      hours is worth zero; (3) KILL-SWITCH STREAK MATH: the lane's trades
      feed CONSECUTIVE_LOSSES_LIMIT=4 and the daily-loss gate, so compute
      the joint streak behaviour of funnel+lane, not the lane alone; (4) the
      b70 slot/capacity model — a lane that cannot get a slot when it fires
      adds tot_R on paper only. Pin the protocol as a test the way b71
      pinned the harness: scripts/b74_replicate_candidate.py taking an arm
      name + N windows, emitting a replication table, PASS only if exp_R
      beats the funnel on the SAME bars in >=N-1 of N windows AND the pooled
      n clears 100. Cheap: the machinery (indexed/backtest_ohlc/lane_sim/
      stretch_probe) already exists in b68j/b68i/b70. Read-only; wiring
      stays a human decision per the b68 merit bar.
      (progress 2026-09-04, round 11: HALF OF THIS PROTOCOL IS NOW BUILT AND
      IT ALREADY KILLED THE ONLY CANDIDATE. scripts/b68l_windows.py is the
      reusable independent-window builder (W1/W2, zero overlap asserted +
      recorded, H1/H4 context padded) and b68l_confirm_independent.verdict()
      is the replication rule (PASS = beats the funnel's ladder_ts on the
      SAME bars in BOTH windows; None exp_R and ties never beat — pinned on
      synthetic ledgers by tests/test_b68l_independent.py). Running it on
      round 9's champion: FAILS (0.928 W1 / 0.447 W2). What is still missing
      for b74 proper: (a) a CLI taking arm name + N windows instead of the
      hardcoded round-11 arm list, (b) the live-gate-stack filter (DEFCON/
      session/cooldown/news) applied on top of the lab signal, (c) the
      kill-switch streak math on funnel+lane jointly, (d) >=3 windows so
      N-1-of-N has teeth. The next candidate that passes the merit bar gets
      run through this, not through a contaminated last-6000 fetch.)
      (progress 2026-09-04, round 12 harvest: THERE IS NOW A CANDIDATE WORTH
      RUNNING — pdh_h4t_agree is the first arm to clear steps (1)-lite: two
      independent windows, beats the funnel on both (0.657/0.927 vs
      0.524/0.521), beats its control on both, selection ordering stable out-
      of-regime (round 9's killer check passed). Still missing before any
      wiring proposal: a THIRD window (W3 = 6000 bars before W2 — the broker
      history reaches 2024-02, so it exists), the pooled-n >=100 check
      (55+63=118 already clears it), the live-gate-stack filter, and the
      kill-switch streak math. b74 proper is now the highest-value lab item
      in the queue.)
      (progress 2026-09-04, round 13 harvest: THE THIRD DRAW RAN AND KILLED
      THE CHAMPION — pdh_h4t_agree fails W3 (0.505 vs funnel 0.528, n=74):
      2-of-3 windows is NOT replication, b74's >=3-window rule just earned
      its keep a second time (it also killed round 9's champion). The new
      candidate from this round is funnel_h4t_agree — the funnel's own
      signals gated on the H4 state — the FIRST arm to beat the funnel on
      all three windows (0.617/0.553/0.536 vs 0.524/0.521/0.528, pooled
      n=540), but with shrinking margins (+0.093→+0.032→+0.008) and the
      agree-vs-cut ordering FLIPPED on W3 (the round-9 killer check). It
      enters b74's protocol as the top candidate: a 4th window if the broker
      history gives one, the live-gate-stack filter, kill-switch streak math,
      and the pooled-margin trend (a gate whose edge decays to +0.008R may
      be real-but-worthless — the protocol should price the DECAY, not just
      the mean). Read-only.)
      (progress 2026-09-04, round 14: THE DECAY QUESTION IS ANSWERED — the
      fourth draw (W4) ran and funnel_h4t_agree DIES (0.517 vs funnel 0.532
      on the same bars). The four margins in CHRONOLOGICAL order are
      -0.015/+0.008/+0.032/+0.093 — a monotone ramp in RECENCY, so the
      gate's edge is a recent-regime property, not a stable one; the
      candidate is closed, no further protocol steps owed. pdh_h4t_agree
      and the h4pdh lane are both 3-of-4 windows — also closed under an
      all-windows rule. b74's remaining protocol pieces (live-gate-stack
      filter, kill-switch streak math) have NO surviving candidate to run
      on: every arm the loop ever produced is now screened out on >=3
      independent windows. The protocol machinery stays for the next
      candidate; the decay-pricing lesson is promoted to todo b77.)
- [x] b69 DEAD LAB ARM: b63's `compression` arm fired 0 trades on both cached 3000
      M15 and the b63b fresh set (data/backtest/b63_smc_rtm_lab.json shows
      trades:0 for plain AND ladder) — its "(hi-lo) > 0.9*ATR(50)" tightness gate
      plus the contracting-halves condition never co-occur on gold M15. Either
      loosen the definition to something that actually fires (measure the range
      distribution first) or remove it from the lab registry so future rounds do
      not read "compression tested" as "compression measured". Small, lab-only.
      (done 2026-09-03 via b68 round 5: range_probe in scripts/b68f_nr7_lab.py MEASURED
      the distribution — 12-bar range/ATR(50) ratio min 0.671, p05 1.83, median 3.35;
      the 0.9*ATR tightness clause fires 1/2940 bars, the full b63 combo 0/2940 — so the
      gate was mathematically unreachable on gold M15, not "tested and flat". The arm is
      annotated DEAD at its definition site (b63_smc_rtm_lab.py) with the numbers, the
      loosened definition that actually fires (NR7 squeeze, 506 occurrences) was
      implemented and MEASURED this round (rejected as replacement, positive lane), and
      tests/test_b68f_nr7_lab.py pins combo_count<=2 + nr7_count>100 from the shipped
      JSON so the premise can't rot silently.)
- [x] b66 Absolute REPO-PATH literals — the b64 bug class one level down (reusable procedure from b64/b65): the b64 scan pins hardcoded HOST literals, but the same "works on this box, silently wrong anywhere else" shape sits in hardcoded filesystem paths: scripts/probe_gates.py and scripts/measure_neutral.py do `sys.path.insert(0, '/home/ai/hermes-trading')` + `load_dotenv('/home/ai/hermes-trading/.env')`, scripts/gen_backtest_report.py opens `/home/ai/hermes-trading/reports/...` and `.../data/backtest/sweep_results_v2.json` as literals, scripts/offsite_backup.py BASE, scripts/autopilot_digest.py ROOT, notifier/dashboards.py ROOT (b39-justified: read-only by design), engines/paths.py PRODUCTION_ROOT (the ONE canonical default — allowlist material), scripts/autopilot.sh's cd + inline python paths. Move the repo or run under another user and each of these either breaks LOUDLY (good) or reads/writes the WRONG tree while reporting success (the b46/b48 disease from the filesystem side — e.g. a digest pointed at an old checkout summarizes stale state). Fix: extend the b64 analyzer with a path-literal rule — any production .py/.sh containing the literal '/home/ai/hermes-trading' (or any absolute path under a home dir that engines/paths.PRODUCTION_ROOT also resolves to) outside the allowlist fails and names the file; heal consumers to Path(__file__)-derived roots or engines.paths accessors (b39 pattern), allowlist the canonical default with a written reason + liveness check (b40 rule), and pin the two-language scope + anti-vacuity floors the b64 file already documents. Small, read-only.
- [x] b65 Bridge consumers must bootstrap their OWN env (found by the b64 audit, healed same run): b64 scans literals; b52-b63 scan env READS — a file that resolves the bridge through bridge_client and never loads .env is invisible to ALL of them, and that is exactly what the audit turned up twice in production files. (1) cli.py imported bridge_client with NO load_dotenv: every `cli.py status` call went out tokenless → 'Bridge: OK' next to 'Account: HTTP_401', and the positions line skipped the ok-check, so a 401 printed 'Open Positions: 0' — an auth failure rendered as an empty account (verified live: 401s + balance-less output before the fix, $4982.77 after). (2) cli.py `run` had `os.environ['HERMES_DRY_RUN'] = str(args.live).lower()` on a store_true flag — INVERTED: bare `cli.py run` wrote 'false' (= LIVE, real orders on this box's .env) and `--live` wrote 'true' (= dry-run). (3) hermes_runtime.main() read no env and called cycle() with its default dry_run=False — a bare `python3 hermes_runtime.py` was a live-order-by-accident path (saved only by the 401s from the same missing bootstrap). All three healed: shared try-dotenv-except-env_loader pattern (b30/env_loader rule), dry-run default matching hermes_master's parse, positions ok-check; hermes_master (production entry, always passed dry_run=DRY_RUN) untouched. Tripwire: tests/test_b65_env_bootstrap.py — AST scan: every production file that CONSTRUCTS BridgeClient must CALL load_dotenv (43 consumer files, all clean after the heal), scope floor ≥40 ctor sites, pre-b65 replay, and BEHAVIOURAL subprocess tests: cli import restores the token, `cli.py run` → DRY=true / `--live` → DRY=false through the real argparse with hermes_master stubbed, cmd_status with a fake 401 bridge must print ❌ never '0', runtime main() knob wiring + safe-default source pin. PROVEN to bite: HEAD cli.py restored → 4 RED; HEAD hermes_runtime.py → 2 RED; restored. 471 green, live cycle rc=0 (monitor, no_trade).
      (done 2026-09-03: see b65 entry above — implemented, tested, and shipped inside the b64 run as the live-finding follow-up, same convention as b63's bridge_health_monitor heal.)
      (done 2026-09-03, shipped via STEP-0 harvest + this run's follow-up: the previous run wrote the whole heal (20 scripts/*.py + notifier/dashboards.py + engines/paths repo_root()/repo_file() + the four cron-critical .sh deriving REPO_ROOT from BASH_SOURCE, with the two quoted python heredocs reached through exported seams HERMES_AUTOPILOT_REPO_ROOT/HERMES_VERIFY_REPO_ROOT) and died before committing; tests/test_b66_repo_path_literals.py (15 tests) verified green after one fix — repo_path_hits_py must SORT by line (ast.walk is BFS, so an f-string constant is yielded after later top-level statements; the replay assertion saw [1,3,2]). THE HARVEST'S OWN verify_head RUN THEN FOUND A REAL PRODUCTION BUG (b66-follow-up, same run): with the install literal gone, the clean worktree genuinely has no .env → no bridge token → bridge_client._get() returns {ok:false, error:'HTTP_401', data:{raw:...}} with data a DICT, and dashboards.trade_home() iterated it, hit the string KEYS and died (AttributeError 'str' has no 'get') → the operator's home panel renders an error card on any auth blip, and on the SIGNAL path the same shape degraded open_positions to 0 (already_in_position gate blind — the b65 auth-as-empty-account class in a new hat). The bug was always there; the ROOT literal HID it by loading the PRODUCTION .env inside an isolated worktree, so verification always saw a list. Fix: engines/bridge_payload.positions_list/position_count is the ONE shape-safe reader (daemon's no-ok leniency preserved — reading that shape empty would falsely report tracked tickets CLOSED, the duplicate-open hazard), 4 consumers migrated, hermes_runtime._positions_list delegates. 15 tests in tests/test_b66b_positions_shape.py incl. the exact 401 payload replayed through the real panels + an AST ban on hand-rolled .get('data') iteration in the four consumers + anti-vacuity proving the OLD comprehension raises. 501 green, live cycle rc=0 (monitor, wait_for_pullback). SIDE FINDING → b67 (same unsafe read for the deals/rates/account envelopes).)
- [x] b64 Literal host/URL scan for production code (reusable procedure from b63): the b63 audit found scripts/bridge_health_monitor.py — the watchdog that pages ops every 5 min when the bridge dies — with the bridge URL hardcoded as TWO module-level literals and NO env read at all (fixed this run), and the same shape still sits in the one-off probe/deploy scripts (_check_bridge.py, _deploy_bridge.py, _probe_win.py, _check_bridge_patch.py, _patch_bridge_position_id.py: hardcoded 192.168.10.51 in winrm.Session/URL strings). The b52/b62/b63 scans only see env READS — a file that never reads env is invisible to all of them. Fix: extend the tripwire family with a literal scan — any production .py (root/scripts/engines/notifier) containing a hardcoded IPv4 literal or an http(s)://host URL string outside an allowlist of justified last-resort defaults (bridge_client's WIN_IP default, offsite_backup's chain default, the new bridge_urls()/weekly_report derivations — each with a written reason + liveness check, b40 rule) fails and names the file; decide per probe script: heal to env resolution or move to legacy_removed/ (probes are dead one-offs — healing them is optional, hiding them from the scan is not). Small, read-only.
      (done 2026-09-03, shipped via STEP-0 harvest — the previous run wrote the whole item but died before committing (b46 machinery working as designed): tests/test_b64_literal_hosts.py (12 tests) + the two heals + three retirements verified, completed, and proven this run. Sensitive-host set is DERIVED from .env.example (RFC1918 by rule + documented hosts by contract — a future named host is covered automatically), loopback/bind-all exempt by rule not allowlist, docstrings/shell-comments exempt (prose ≠ resolution), both languages scanned (b44 lesson), 6-entry allowlist each with a written reason + DEAD-EXEMPTION liveness check. Decisions: _check_bridge.py healed onto bridge_client (DEPLOY.md step 5 smoke test — must follow the documented host; also deleted a second copy of the precedence logic), _deploy_bridge.py healed with the b62 chain + WIN_USER, the three dead surgery probes retired to legacy_removed/scripts_old/ (two of them MUTATE the Windows box — retirement is a safety gain). Anti-vacuity: scan must find ≥5 files incl. bridge_client/offsite_backup/health_monitor/autopilot.sh and ≥90 .py + ≥4 .sh scope. PROVEN to bite: HEAD _check_bridge.py restored → 2 RED naming the file+line; a fresh synthetic probe with the literal → instant violation (the allowlist is keyed per-file — a new file inherits nothing). Healed probe verified LIVE read-only (health OK, balance 4982.77). SIDE FINDINGS → b65 (done: env-bootstrap class, invisible to every scan) + b66 (todo: absolute repo-path literals, the same class one level down). 471 green, live cycle rc=0 (monitor, no_trade).)
- [x] b63 Two DOCUMENTED keys encode one fact and can DRIFT (found by the b62 audit): .env and .env.example both set HERMES_WIN_IP=192.168.10.51 AND HERMES_BRIDGE_URL=http://192.168.10.51:5050 — the same host written twice. bridge_client's precedence: BRIDGE_URL wins when set, so an operator who moves the bridge and updates only HERMES_WIN_IP keeps trading against the OLD host — the b62 silent-stale shape, one level up (documented↔documented, so the b62 knob-shadow scan deliberately cannot flag it: two documented keys MAY share a value, e.g. TELEGRAM_CHAT_ID/AUTOPILOT_REPORT_CHAT_ID both point at the ops chat). Fix: a targeted drift check — parse the host out of HERMES_BRIDGE_URL's VALUE and assert it equals HERMES_WIN_IP in .env.example (and in the real .env when present, skip in clean worktrees); on mismatch fail naming the precedence. Alternative: drop HERMES_BRIDGE_URL from .env.example and let bridge_client derive it from HERMES_WIN_IP (it already does when unset) — but that changes the deploy contract, so prefer the check. Small, read-only.
      (done 2026-09-02: took the CHECK (not the contract change). parse_host_drift() compares the host embedded in HERMES_BRIDGE_URL's value against HERMES_WIN_IP in .env.example (always) and the real .env (skip in clean worktrees), failing with the precedence that makes it silent; plus scan_literal_bridge_url_defaults() — a production HERMES_BRIDGE_URL read may carry NO inline literal default (the fallback must DERIVE from HERMES_WIN_IP, bridge_client parity, or be absent). THE AUDIT FOUND A LIVE CONSUMER WORSE THAN THE DOCUMENTED DRIFT: scripts/bridge_health_monitor.py (cron */5, the watchdog that pages ops when the bridge dies) had the URL hardcoded in TWO module-level literals and read NO env at all — move the bridge and ops gets 'bridge down' every 5 min forever while the REAL bridge failing goes unseen; now bridge_urls() resolves at CALL time (b39 lesson: main() loads .env after import) with bridge_client precedence. weekly_report's literal default healed the same way (b52 fixed its NAME, b63 removes its duplicated VALUE). 7 new tests: two main tripwires (example + real .env), consumer literal scan, drift replay (fires on disagree, clean on match/missing-key/unparseable), literal-default replay (pre-b63 shape fires, derived fallback + bare read clean), anti-vacuity floors (host parser + both keys present AND agreeing), behavioural precedence replay of BOTH healed consumers in fresh subprocesses. PROVEN to bite: restored weekly_report literal + half-migrated .env.example (IP→10.0.0.77, URL left behind) → 6 tests RED naming both files, restored. 451 green, live cycle rc=0 (monitor, no_trade); health monitor ran a real tick OK. SIDE FINDING → new todo b64 (hardcoded IPs in probe scripts — invisible to every env-read scan).)
- [x] b62 WIN_HOST vs HERMES_WIN_IP: two names, one fact (found by the b61 audit). .env.example documents HERMES_WIN_IP (read ONLY by bridge_client.py), while scripts/offsite_backup.py reads WIN_HOST — a DOCUMENTED_KNOBS exemption whose inline default is the hardcoded 192.168.10.51. The b52 reverse scan cannot see this: WIN_HOST is not in .env.example so it is outside the dead-key check, and the knob's liveness test only asks "does anyone read it" (yes — its own default). Consequence: a bridge host change moves HERMES_WIN_IP and the trading path follows, but the daily off-box backup silently keeps pushing to the OLD IP (default wins, no error) — the exact "wrong name + inline default = SILENT" shape b52 documented for BRIDGE_URL. Fix: make offsite_backup resolve WIN_HOST = os.getenv('WIN_HOST') or os.getenv('HERMES_WIN_IP', '192.168.10.51') (explicit override still possible), and add a b52-side check that no DOCUMENTED_KNOBS default duplicates the VALUE of a .env.example key (grep literal IPs/URLs in knob readers) — or simply drop WIN_HOST from the knobs and document it. Small, read-only.
      (done 2026-09-02: chained WIN_HOST = getenv('WIN_HOST') or getenv('HERMES_WIN_IP', default) in offsite_backup (explicit override kept) and added scan_knob_default_shadows() to test_b52: a DOCUMENTED_KNOBS read whose LITERAL inline default equals the .env.example VALUE of a DIFFERENT documented key is a shadow (knob-scope only — documented↔documented value sharing can be legitimate, see new todo b63; empty defaults never fire). env_reads refactored onto a shared walker that keeps the literal default VALUE, not just its presence. 5 new tests: main tripwire, source-shape pin (chain present, standalone default banned), a REAL-subprocess precedence replay (override > documented > last-known default — env_loader never overrides existing env, so injected values win over .env), behavioural replay of the exact pre-b62 shape through the real analyzer + healed/innocent controls, anti-vacuity floor on the doc-value parser. PROVEN to bite: reverting the offsite_backup chain → 3 tests RED (shadow scan names WIN_HOST→HERMES_WIN_IP), restored. 444 green, live cycle rc=0 (monitor, no_trade). SIDE FINDING → new todo b63.)
- [x] b61 Reverse-direction env liveness: documented keys with NO reader (found by the b52 audit). b52 pins every READ name exists in the universe; nobody pins the inverse — a key in .env.example that production never reads is a stale deploy contract (a fresh server gets a documented knob that does nothing). Measured 2026-09-02: GIT_TOKEN_FILE is in .env.example but read by NOTHING — git_sync.sh hardcodes `cat .git_token`. Fix: extend tests/test_b52_env_names.py with a documented-but-unread check (allowlist for genuinely external keys, e.g. ones consumed by shell/systemd rather than Python), and either wire GIT_TOKEN_FILE into git_sync.sh or drop it from .env.example. Small, read-only.
      (done 2026-09-02: chose WIRE over DROP — .env already carries GIT_TOKEN_FILE and .env is off-limits, so dropping from .env.example would flip the .env↔example drift test RED. git_sync.sh now sources .env (same set -a pattern as hermes_cron.sh, verified safe on this box's values incl. WIN_PASS specials) and reads "${GIT_TOKEN_FILE:-.git_token}" — behaviour byte-identical when the key is unset, which is exactly what the b45 end-to-end throwaway-repo tests run. The reverse scan (documented_key_readers/scan_dead_documented_keys) counts readers in BOTH languages: Python via env_reads, shell via $KEY/${KEY:-…} expansion — a Python-only scan was the blind spot that let the hardcode hide; EXTERNAL_READERS allowlist exists but is deliberately EMPTY (every documented key now has a real reader) with a liveness test so a dead exemption can't linger. 5 tests in TestB52EnvNames: main tripwire, GIT_TOKEN_FILE wired+pinned to the SHELL half specifically, anti-vacuity floors, and a behavioural replay (inject a fake key → flagged; heal it with a fake .sh reader → clean). PROVEN to bite: reverting the git_sync wiring → 3 tests RED incl. the dead-key scan naming GIT_TOKEN_FILE, restored. 439 green, live cycle rc=0 (monitor, no_trade). SIDE FINDING → new todo b62.)
- [x] b34 Runtime FALLBACK management path CRASHED on real bridge data (done 2026-08-30, found while verifying b32): hermes_runtime._pos_obj did int(p['type']) but bridge v2 /api/positions sends the STRING 'BUY'/'SELL' → ValueError propagates through cycle() and hermes_master (neither has a guard) → EVERY 15-min tick DIES while a position is open and the watchdog is dead — exactly the double-failure the fallback exists to cover (no plan, no monitor, no entries, no alerts). position_daemon._pos_obj already handled both shapes; the two consumers disagreed on the wire format. No test caught it because every MockBridge returns positions=[]. Fix: _pos_type() normalizer (string→0/1, unknown→SELL never silent BUY) + 6 tests in tests/test_runtime_fallback_management.py replaying a production-shaped open SELL through the REAL cycle() against a fake bridge (crash tests RED against old code; also pins the heartbeat handoff — fresh heartbeat ⇒ runtime must NOT manage — and b7b commit-on-acceptance on the fallback path). 153 green, live cycle rc=0.
- [x] b32 news_lock is ALIVE but only on the fallback path (found by b31): position management in production runs in position_daemon.py (watchdog heartbeat <60s → hermes_runtime's management block skips), and the daemon calls evaluate_trade_management directly — it never imports or evaluates legacy_guards, so the now-fixed news_lock still cannot protect a live position. Wire evaluate_news_lock (+ time_exit) into the daemon's 5s loop the same way hermes_runtime merges them (priority 1/2 ahead of the legacy chain), reusing the same runtime_state['management'] commit-on-broker-acceptance discipline from b7b/b10b. CAUTION: this changes live EXIT behaviour on a real demo account — do it behind a test that replays a blackout window against a fake bridge, and keep the tighten-only guard (already proven by test_never_loosens_stop).
      (done 2026-08-30 in f6f84c6; VERIFIED this run: manage_position() runs the full priority chain with once-per-fingerprint guard memory + commit-on-broker-acceptance, 20 tests in tests/test_daemon_guards.py replay blackout/stale-position against FakeBridge, the watchdog process (PID 61892) was restarted 13:21 UTC — after the commit — so the live loop IS the new code. The checkbox was simply never flipped. b34 above was found in the same audit.)
- [x] b37 The fallback path's guard merge is still `except Exception: pass` (found by b35) — DONE 2026-08-30, and the hole was live-reachable, not theoretical: the lookup `plan.get('context',{}).get('macro',{}).get('calendar')` raised AttributeError on the shape the MONITOR PATH ITSELF writes (`plan['context']['macro'] = macro_snap`, macro_snap=None after a failed analyze_macro — production current_plan.json right now has context.macro absent entirely), the bare pass ate it, and BOTH guards (36h time_exit + pre-news SL tighten) vanished silently for that position, every cycle, forever. Fix: named `hermes_runtime.evaluate_legacy_guards()` returning (management, status) — shape-safe `_plan_calendar`, position_daemon-parity `_guard_calendar` (plan → live fetch, so news_lock finally gets a calendar on the plan/reassess path that never writes one), a real logger (`_runtime_log`, the runtime had NONE), status in the manage payload + the Telegram brief, and `hermes_master.alert_degraded_guards()` → send_ops. Deliberate decision on the open question: a guard-eval error does NOT block new entries (entry has its own b30 fail-closed blackout gate, and MAX_OPEN_POSITIONS=1 means a cycle that just failed to manage cannot open a second trade) but IS loud. Added: dedupe (same state+detail pages once per 6h, log line every cycle — a 15-min master on a calendar outage would otherwise page 4x/hour until ignored), call-time `_log_file()/_report_file()` (LOG_FILE was bound at import → any test importing hermes_master wrote production logs/master.log; verified byte-identical after the suite). 33 tests in tests/test_b37_guard_visibility.py — 24 of them RED against the old code (verified by stashing the two source files), incl. an AST tripwire that fails if the merge is ever re-wrapped in a bare pass. 209 green, live cycle rc=0 (reassess, 0 open positions).
- [x] b38 Verify b35 calibration handoff LIVE after market open (done 2026-08-31 00:45 UTC — VERIFIED END-TO-END, both halves): the file appeared at 00:32:18 UTC, ~90min after the 23:00 reopen, not ~15s — and that gap is CORRECT behaviour, not a bug: the daemon needs two consecutive live ticks (BROKER_OFFSET_MAX_GAP_SEC=60) to prove the stream, and the first post-weekend polls carried a stale weekend stamp, so samples were rejected until the feed went truly live (bridge_health.log shows OK from 00:30). Content: offset_sec 10798.6 ≈ 10800 (CapitalXtend UTC+3) ✅, source position_daemon ✅, rewritten every ≤5min (00:32→00:37→…) ✅. Reader half: live `load_offset()` returned 10798.383, and `hermes_runtime._fallback_opened_at()` on the REAL current tick resolved to 00:45:39 UTC calibrated vs 03:45:38 raw — the exact 3h de-rotation b35 exists for, so a fallback time_exit now measures age correctly. No code change needed; the 24h reader TTL + freshness re-verification is the standing guard (a calibration older than 24h reads as None → detection-time fallback).
- [x] b39 Import-time path binding (done 2026-08-31 — the class b37 surfaced, closed repo-wide): hermes_master LOG_FILE/REPORT_FILE (b37) + notifier/telegram LOG_DIR + position_daemon dead LOG_FILE + signal_daemon/signal_monitor LOG_FILE + cli.py PLAN/RUNTIME/REPORT + engines/backtest_real RESULTS_DIR (which also mkdir'd production data/ at IMPORT time) + hermes_runtime BASE_DIR/DATA_DIR/PLAN_DIR aliases + notifier/dashboards PAUSE_FLAG/AUDIT_LOG — all converted to call-time accessors through engines.paths. The dashboards pair was the dangerous one: PAUSE_FLAG is WRITTEN by the operator 'auto:pause' button and AUDIT_LOG by _audit(), so a test or staging run exercising a control action would have toggled the REAL autopilot pause and polluted the REAL audit trail. Tripwire: tests/test_b39_import_time_paths.py imports EVERY production module in a FRESH SUBPROCESS under a temp HERMES_DATA_ROOT (in-process is unsound — discovery pre-imports the tree) and fails on any module-level Path still resolving under production, with a justified ALLOWED list (dashboards ROOT/DATA stay: read-only by design) and test_allowed_entries_are_still_real so a dead exemption can't linger as a silent hole. 219 green, live cycle rc=0.
      SIDE FINDING (same run, pre-existing failure at HEAD, not caused by b39): tests/test_safety_gates.py::test_market_closed_blocks_signal_order patched `market_hours.is_market_open`, but the gate calls auto_executor's OWN from-import binding — so the fake never reached it, the real clock said "open", the order went out, and the test had been VACUOUS since the day it was written (it only surfaced because the market flipped state). Fixed by patching the binding the caller actually uses + asserting error=='market_closed'. Same bug class as b34's wire-shape disagreement: two modules, one fact, no test touching the real seam.
- [x] b41 Monkeypatch-the-wrong-binding audit (done 2026-08-31): audited EVERY patch site in tests/ (assignment, setattr, patch.object — 30 sites, AST-scanned not eyeballed) against production module-level `from X import f` bindings. The repo was already clean (b39's fix held; every remaining source-module patch targets a LAZY importer), but the audit found 2 live LEAK hazards of the shape test_audit_fixes documents: test_b37 patched notifier.telegram.send_ops and test_failclosed_news_spread patched engines.storage.load_current_plan/append_execution_log WITHOUT pre-importing the module-level shadowing consumers (hermes_master / hermes_runtime) — if discovery order ever made that consumer's first import land inside the patch window, its real binding is permanently poisoned. Fixed with up-front imports in both files. Tripwire: tests/test_b41_patch_bindings.py parses prod + tests, flags any source-module patch whose consumer (a) isn't pre-imported in the test file (leak) or (b) calls the name by bare module-level copy (vacuous) unless an ALLOWED entry carries a written reason (5 justified exemptions, incl. b37's lazy send_ops), with test_allowed_entries_are_still_real + a minimum-findings count so a dead exemption or a silently-unparsed test file can't bypass it. PROVEN to bite: replays the ACTUAL pre-b39 test_safety_gates.py from git history through analyze() and asserts it is flagged. 226 green, live cycle rc=0 (reassess, execute=False), logs/master.log byte-identical across the suite.
- [x] b40 b37 alert-state observability follow-up: `data/ops/guard_alert_state.json` is written by hermes_master but read by nothing — scripts/autopilot_digest.py and scripts/dashboard_bot.py should surface "guards degraded since <at>" so a degraded management path is visible on the dashboards, not only in the ops chat. Small, read-only.
      (done 2026-08-31: engines/guard_status.py is the ONE canonical reader (path + cooldown constant shared with the writer, staleness = cooldown+4 cycles → "last observed" hedge, unknown states still surface, corrupt file → no line never a crash); wired into ops verdict, ops_auto, trade_home, trade_risk, master report, and the daily digest; dashboard_bot gets it via ops_render. 17 tests in tests/test_b40_guard_observability.py incl. writer→reader contract and a single-seam tripwire. VERIFIED THIS RUN: 243 green, live cycle rc=0. NOTE: the previous run implemented this but committed hermes_master.py with `git commit -am`, which silently skipped the NEW untracked guard_status.py → HEAD was BROKEN on a clean checkout (ModuleNotFoundError) until this commit; that bug class is now b42.)
- [x] b35 Runtime fallback time_exit uses the BROKER epoch as if it were UTC (done 2026-08-30): new engines/broker_clock.py — the watchdog publishes its b32 calibration (only when ≥1 tick sample was ACCEPTED; 0.0=unmeasured is never written as a measurement) with a 5-min rewrite throttle + ±14h sanity bound + 24h reader TTL; hermes_runtime's fallback now resolves opened_at by priority: calibrated broker epoch → watchdog detection time (watchdog_state.json) → raw epoch (old behaviour, last resort only). Every degradation errs EARLY, never late. 17 tests in tests/test_broker_clock.py (3 of the 4 real-cycle tests verified RED against old code: a 37h-old position was left unmanaged past the 36h limit; now closes). 170 green, live cycle rc=0, daemon restarted onto the new code.
- [x] b42 Clean-checkout import integrity (done 2026-08-31 — and the item itself proved the bug class a SECOND time: the previous run WROTE tests/test_b42_tracked_imports.py but committed with `git commit -am` again, so the tripwire that exists to catch untracked files was itself left untracked; found while picking this item). Finished properly this run: analyzer now scans BOTH the working tree AND the HEAD tree (the 88cac1e shape is invisible from a dirty disk — the missing file sits there locally the whole time; only a HEAD-tree scan catches a commit that is already broken), plus test_no_untracked_production_python fails on ANY untracked .py in the repo (git add -A made loud). Found and fixed a real hole in the ref-scan path on first use: `from bridge_client import BridgeClient` crashed analyze_ref('HEAD') — plain module, get_src('__init__.py') raised RuntimeError from git show, only OSError/KeyError were caught; broadened + pinned by test_plain_module_attribute_import_survives_a_ref_scan. PROVEN to bite: injected a tracked-file-imports-disk-only-module scenario → both HEAD-scan and untracked-file checks went RED, restored clean. Commit-discipline rule (never `git commit -am`, always `git add -A`) written into this file's header. 252 green, live cycle rc=0.)
- [x] b44 Post-commit HEAD verification (done 2026-08-31 — and it caught TWO live bugs in its own machinery before the suite even ran): (1) scripts/verify_head.sh — written by the previous run but left UNTRACKED (the b42 bug class, third occurrence, this time on a .sh file which the untracked-scan could not see because it only matched .py) → the stray-file scan now covers .py AND .sh, pinned by test_stray_filter_catches_shell_not_just_python; (2) the script logged 'VERDICT=BROKEN rc=0' on the real 43c5f52 run — bash `if cmd; then…fi` followed by `RC=$?` captures the IF-compound status (always 0), never the condition's, so the recorded exit code was a lie → rewritten run-then-capture, pinned by test_verify_head_script_captures_real_rc (asserts the bash semantics AND that no `RC=$?` ever sits directly after an `fi` in the script). Wired as step 4b of the autopilot procedure (backlog header + scripts/autopilot.sh prompt): after every commit, `bash scripts/verify_head.sh` re-checks the FRESH HEAD via git archive (no .env/untracked/pycache — exactly what cron sees) with test_b42_tracked_imports + test_b44_clean_checkout, appends the verdict to logs/verify_head.log, pages ops via Telegram on BROKEN, never blocks. The old BROKEN verdict in the log was TRUE (test_b44_clean_checkout.py was untracked at 43c5f52) — the alert fired ([TELEGRAM] 200) and the next commit healed it: the mechanism works end-to-end. 277 green, live cycle rc=0.)
- [x] b36 Shared production-shaped bridge fixtures (reusable procedure from b34): every MockBridge in tests/ hand-rolls payloads, and none of them ever returned a position — that's why the int('SELL') crash survived to production. Add tests/fixtures_bridge.py with pos_raw()/tick/account builders that MIRROR scripts/mt5_http_server_v2.py field-for-field (type as 'BUY'/'SELL' strings, price_open, broker epoch time), have test_integration, test_daemon_guards and test_runtime_fallback_management import them, and add a drift test that greps the server source for the response keys and fails if the fixture shape no longer matches the producer.
      (done 2026-08-31 — found FULLY IMPLEMENTED but UNCOMMITTED in the working tree from an interrupted previous run (the b36 files were staged 'A' with unstaged edits, 403 lines that git_sync could never push); this run verified and shipped it. tests/fixtures_bridge.py = the single production-shaped payload source (pos_raw/tick/account/deal/rate builders mirroring mt5_http_server_v2.py, string BUY/SELL type, broker-clock epochs, legacy-int shape reproducible); test_b36_bridge_fixtures.py AST-parses the server and pins positions/tick/account/deals/OHLC key sets + envelopes + the b34 string-type ternary, and trips on consumer files re-hand-rolling position dicts; test_integration, test_daemon_guards, test_runtime_fallback_management and test_broker_clock now build payloads ONLY through the fixtures. PROVEN to bite: injected a bogus field into POSITION_FIELDS → 2 drift tests RED, restored. 296 green, live cycle rc=0 (monitor, wait_for_pullback).)
- [x] b46 Detect ABANDONED UNCOMMITTED work (reusable procedure from b36): b36 was found fully implemented (403 lines: fixtures + drift test + 4 consumer migrations) but left staged/uncommitted in the working tree by an interrupted run — invisible to cron, GitHub, and verify_head (all see only HEAD), and the backlog still said todo. Add a read-only check to scripts/autopilot_digest.py (and the ops panel): `git status --porcelain` filtered to *.py/*.sh under tests/, engines/, scripts/, *.py at root — if any dirty/untracked file is older than ~60 min (file mtime), surface "UNCOMMITTED CODE for Xh: <files>" as a warning line. Code sitting dirty in the tree is work that can silently vanish (checkout/reset/crash) and that no push protects. Never auto-commits, never touches trading paths.
      (done 2026-08-31: engines/dirty_work.py is the ONE canonical git-status reader (b40 pattern) — porcelain -z parse with the R/C two-field shape consumed so a rename source can't leak as a bogus entry, *.py/*.sh scope (b44 lesson: .sh matters), deleted tracked code has no mtime → always counts, non-repo/failed git → None never a raise (hermetic temp roots self-disable), 60-min mtime threshold so an agent mid-edit never pages. Wired into ops home verdict + ops:auto panel (lazy import, b41-safe) and the daily digest via a NEW HERMES_REPO_ROOT seam so the digest test asserts against a throwaway repo, never the live tree's dirtiness. PROVEN to bite: replays the exact b36 shape (staged 'A' + unstaged edits, 3h-old mtime) through a real git repo → flagged with the right age; fresh 5-min edit → silent; dirty data/*.json (production churns them every 15 min) → invisible. Tripwire: no production module may hand-parse git status again. 316 green, live cycle rc=0.)
- [x] b47 Autopilot run must HARVEST abandoned work before picking a new item (follow-up to b46): scripts/autopilot.sh should run engines.dirty_work.scan() before building the PROMPT and, if it fires, prepend an instruction: "UNCOMMITTED CODE detected from a previous run: <files> — verify it (run the suite), commit it as its own commit FIRST, then pick the top todo." That turns the b36 recovery from luck-of-the-audit into procedure. Small, prompt-only, never touches trading paths.
      (done 2026-08-31: scripts/autopilot_harvest.py is a print-only STEP 0 block generator over dirty_work.scan (names every file + git status + age, demands suite-green → own `harvest:` commit → verify_head.sh → only then the top todo); autopilot.sh captures it before launching the agent and prepends to PROMPT, fail-safe `|| true` so a broken check never kills a run. 9 tests in tests/test_b47_harvest.py: end-to-end subprocess replays the exact b36 shape (staged AM, 3h old) → STEP 0 printed, clean repo / fresh edit / non-repo → silent; the bash prepend semantics are replayed for real; an ordering tripwire asserts the harvest runs BEFORE the agent launches. LESSON pinned in-file: a subprocess script with a HERMES_REPO_ROOT seam must separate CODE_ROOT (sys.path for imports) from SCAN_ROOT (the repo being scanned) — the first draft inserted the throwaway repo into sys.path, `from engines import dirty_work` died, the fail-safe swallowed it, and the b36 test went silently RED-empty; the digest avoids this by inserting only the real code root. The b42 untracked tripwire also fired live during this run (new files flagged mid-suite) — working exactly as designed. 325 green, live cycle rc=0.)
- [x] b48 Test-seam env vars must redirect STATE, never CODE (done 2026-08-31): AST tripwire tests/test_b48_env_seam_code_vs_state.py — for every production script (scripts/*.py + root *.py) that reads a HERMES_*_ROOT env var (os.getenv/environ.get/environ[]/setdefault, incl. HERMES_DATA_ROOT), no variable transitively holding that value (direct read, alias chain, Path(env)/f-string/BinOp wrappers, `from sys import path` shape) may appear in a sys.path.insert/append argument. Audit result: the repo is CLEAN — autopilot_digest.py inserts only its file-derived ROOT and consumes the env var as scan data; autopilot_harvest.py has the correct CODE_ROOT (hardcoded real repo) / SCAN_ROOT (env) split. Pinned beyond the static rule: minimum-findings count (≥2 seam readers, so a dead parse can't pass by finding nothing), CODE_ROOT-is-hardcoded-and-env-free assertion on the harvester, and a BEHAVIOURAL replay of the exact silent-death mode — the real harvester subprocess run against a throwaway repo containing a shadowing engines/ package that RAISES on import: STEP 0 still prints (proving code resolves from the fixed root); with the b47 first-draft shape injected (sys.path.insert(0, SCAN_ROOT)) 3 tests go RED, incl. the behavioural one failing on an EMPTY string — the very signature of a fail-safe swallowing a broken import. Restored clean. 335 green, live cycle rc=0.
- [x] b49 Fail-safe scripts must not be indistinguishable from no-op scripts (done 2026-08-31): engines/selfcheck.py is the two-function seam — `fail(section, exc)` inside a swallow block is a NO-OP in normal mode (behaviour byte-identical to `pass`) and re-raises RuntimeError naming the section under `--self-check`/HERMES_SELFCHECK=1; self-check mode also suppresses outbound side effects (digest never sends Telegram, report never writes its STATE — a probe must not consume a pending report). Wired into autopilot_harvest (all 1 swallows), autopilot_digest (all 6 guard blocks), autopilot_report (git helper/state/narrative + rc-arg flag-safe), engines.dirty_work (git call). autopilot.sh now runs the harvester WITH --self-check and captures HARVEST_RC=$? immediately (b44 lesson), logging 'SELFCHECK FAILED' loudly while still never blocking the run — the blind `|| true` that made BROKEN==CLEAN is gone. Three states now have three signatures: rc≠0 = broken, rc=0+text = alive-and-firing, rc=0+empty = genuinely clean. 17 tests in tests/test_b49_selfcheck.py: the ambiguity DEMONSTRATED (harvester with PATH stripped: normal = rc0+empty exactly like clean; self-check = rc≠0 naming 'harvest scan'), b36-shaped throwaway repo under self-check prints STEP 0 rc0, AST tripwire (no unseamed swallow may return in the wired files, min-findings count, print/log bodies exempt as already-loud) PROVEN to bite on synthetic source. LESSON pinned in-file: ast.walk returns a GENERATOR — iterating it twice makes the second check silently vacuous (the tripwire passed a print-swallowing block until materialized). 357 green, live cycle rc=0.
- [x] b50 verify_head.sh must run the FULL suite on the clean checkout, not just the 2 import tests
      (done 2026-08-31, shipped via STEP-0 harvest commit c607fec — the previous run wrote it but died before committing; verified this run: 369 green, and verify_head.sh now runs the WHOLE suite inside a clean DETACHED WORKTREE of HEAD (git archive is unusable — no .git dir, so b42/b44/b46 git checks certify the wrong tree), minimal env + HERMES_DATA_ROOT inside the throwaway tree, HERMES_B50_NESTED recursion guard, stamps data/ops/head_verified.json; VERDICT=OK rc=0 tests=369 logged for c607fec. Prerequisite: tests/ made location-independent (root from __file__), pinned by test_b50_suite_is_location_independent.py incl. the real-history replay proving 920ed0d verifies BROKEN.)
- [x] b45 git_sync pushes UNVERIFIED HEAD (found while wiring b44): scripts/git_sync.sh runs on cron every 15 min and pushes whatever HEAD is — including a HEAD that verify_head.sh would call BROKEN (the 43c5f52 shape: new module/test left untracked). The ops chat then gets a Telegram alert saying HEAD may die while GitHub already has the broken commit, and any future re-clone/restore-from-remote inherits it. Fix is small and read-only: have verify_head.sh stamp the verified sha into data/ops/head_verified.json ({sha, verdict, at}); git_sync.sh skips the push (logs it) when HEAD != last VERIFIED-OK sha AND the stamp is younger than ~1h (age guard so a dead verifier can never freeze pushes forever — fail-open on staleness, loud in the log). Never touches trading paths. NOTE: do b50 first — a push gate keyed to a verifier that only checks imports would certify 920ed0d-shaped HEADs as good.
      (done 2026-08-31 on top of b50's stamp: engines/head_verify.py gained decide_push (pure rule: fresh OK-for-this-sha pushes; BROKEN/TIMEOUT blocks; sha-mismatch blocks "not yet verified"; missing/stale/unparseable FAILS OPEN with the reason always logged — three outcomes, three log signatures) + push_decision glue + a `push-gate` CLI (stdout is contract JSON — paths.read_json_safe's WARN line had to be routed to stderr or it poisoned the parse; exit 0=push/1=block). git_sync.sh: idle ticks (ahead=0) exit before the gate; blocked branch logs PUSH BLOCKED and exits WITHOUT pushing (no Telegram re-page — verify_head.sh is the one voice, b40); gate crash/timeout = fail-open logged. LESSON pinned by the end-to-end replay: the gate must resolve HEAD from the CALLER's cwd (git_sync cd's into the repo it pushes), not the code's own repo — the first draft certified the wrong tree, the exact b46/b48 disease from the git side. 23 tests in tests/test_b45_push_gate.py incl. a REAL throwaway repo + local bare origin: BROKEN stamp → commit stays unpushed, OK stamp → pushed, stale BROKEN → fail-open pushed. 392 green, live cycle rc=0.)
- [x] b51 A crashed run leaves HEAD unverified and the gate fail-opens after 1h (follow-up to b45): the autopilot procedure runs verify_head.sh as step 4b AFTER the commit — if the run dies between step 4 and 4b (or an operator commits by hand), the fresh HEAD carries no stamp, and git_sync's deliberate fail-open pushes it unverified once the old stamp ages out. Fix: scripts/autopilot.sh should run verify_head.sh at the START of every run (before the harvest block) when `git rev-list origin/master..HEAD` is non-empty or the stamp sha != HEAD — a crashed run then heals its own verification on the next tick, and the push gate closes again. Read-only, never blocks the run, log+alert only.
      (done 2026-09-02: engines/head_verify.py gained unpushed_count (None when origin is unresolvable — 'unknown' never reads as 'pushed') + decide_start_verify (pure rule: ahead>0 OR stamp-sha≠HEAD → heal; ONE deliberate exclusion — a non-OK verdict already naming HEAD does NOT re-verify, else ops would be paged every hour for the same known-broken commit, b37 alert-hygiene lesson; the fix for BROKEN is a new commit, which flips the sha clause and re-arms) + start_verify_decision glue + a `start-verify` CLI (stdout contract JSON, exit 0=verify/1=skip). autopilot.sh asks it at run start, BEFORE the harvest block, captures SV_RC immediately (b44), runs verify_head.sh on rc=0, logs loudly on a broken gate, never exits. 21 tests in tests/test_b51_start_verify.py incl. the b45 caller-cwd lesson replayed (throwaway repo HEAD ≠ code repo HEAD → decision answers about the CALLER's tree) and a full crashed-run end-to-end: no stamp + unpushed → heal requested, push-gate blocks meanwhile, after the heal stamp the gate allows, after the push the run goes quiet. STEP-0 HARVEST FIRED FOR REAL this run (b47 machinery working): two probe scripts left uncommitted by an interrupted run (scripts/_check_live.py, _today_pnl.py) — both read os.getenv('BRIDGE_TOKEN'), a name that exists NOWHERE (.env has HERMES_BRIDGE_TOKEN) and never loaded .env → tokenless 401 probes; fixed to the shared env_loader pattern, verified live (account 4982.77, 0 open, today +11.70$/10 trades), shipped as its own harvest commit 9ca6632 + verify_head OK. 428 green, live cycle rc=0 (monitor, wait_for_pullback).)
- [x] b52 Dead-env-var-name tripwire (found by the b51 harvest): the two harvested probe scripts read os.getenv('BRIDGE_TOKEN') — a name that exists in NO .env, no systemd unit, no crontab — so the failure mode is a confusing tokenless 401, not a loud KeyError. test_env_loader.py pins dotenv USERS without a fallback, but nobody pins that every env var a production script READS actually exists somewhere (HERMES_BRIDGE_TOKEN, HERMES_WIN_IP, HERMES_DATA_ROOT, …). Add an AST scan: collect os.getenv/environ[...] names in scripts/*.py + root *.py, resolve the known universe (.env keys + documented defaults + test seams), fail on any name outside it with no inline default. Small, read-only.
      (done 2026-09-02: tests/test_b52_env_names.py — universe = .env.example keys (tracked contract; .env is gitignored and ABSENT in the b50 worktree so it can never be the source of truth) + OS-standard names + DOCUMENTED_KNOBS each with a written reason and a liveness test (b40 lesson: dead exemption = silent hole). Scan covers root/scripts/engines/notifier (wider than the item asked), getenv/environ.get/environ[] reads only (writes excluded — head_verify sets HERMES_SELFCHECK for children), dynamic keys skipped. THE SHARPER FINDING: the audit turned up TWO more dead names the b51 harvest never saw — ab_b55_meta.py still had BRIDGE_TOKEN, and weekly_report.py (Friday cron, LIVE) read BRIDGE_URL with a hardcoded default: the wrong name + inline default = the default silently wins even though HERMES_BRIDGE_URL is configured, so a bridge host change would leave the report pointing at the old IP with NO error anywhere. That's why the rule flags unknown names default or not — an inline default doesn't make a dead name safe, it makes it SILENT. Both fixed to the real keys; .env↔.env.example drift check added (currently identical). PROVEN to bite: re-injected the old BRIDGE_URL shape → 2 tests RED, restored. 434 green, live cycle rc=0 (monitor, no_trade).)
- [x] b31 Staleness audit of every gate input (done 2026-08-30 — the three named inputs measured HEALTHY, but the probe found a DEAD safety guard instead, now fixed): (a) plan.context.macro.calendar age at plan-creation: median 0 min, max 9 min over 70 archived plans — fresh, no budget needed; (b) runtime_state['management'] per-ticket flags: 0 entries live, and tickets are broker-unique, so the reuse hazard is theoretical — no leak observed; (c) performance_state.day: compute_performance_state rebases correctly on rollover (verified: stale day 2020-01-01 → daily_pnl 0/trades 0 on read). THE REAL FINDING: evaluate_news_lock — the guard that tightens SL 30min before high-impact news — was mathematically DEAD: get_upcoming_events() writes {'high_impact':[...]}, the guard only read 'events', fell through to the dict, failed isinstance(list) and returned None for EVERY production input (reproduced: FOMC 10min away in production shape → None; raw shape → correct lock). Fix: read 'high_impact' first; 9 regression tests in tests/test_news_lock.py (the production-shape test goes RED against the old code; tighten-only + never-loosens-stop pinned). 126 green, live cycle OK. Probes: scripts/probe_news_lock.py, scripts/probe_b31_staleness.py.
- [x] b30 Signal path: fail-OPEN news/spread gates (done 2026-08-30 — audit found the reality was WORSE than the todo assumed, 4 distinct holes, all fixed + 14 tests in tests/test_failclosed_news_spread.py, 7 of which go RED against the old code):
      (1) `fetch_economic_calendar()` NEVER raised — both sources failing returned
      `{'source':'unavailable','events':[]}`, which `evaluate_macro_filter` scored
      allowed=True, AND cached that empty payload as 'no news' for 6h. Measured on
      this box: ForexFactory failed 2 of 4 direct fetches (tradingview fallback: 4/4
      dead), so this was live-reachable, not theoretical. Now: fresh cache → refetch →
      stale cache within HARD_STALE_HOURS=24 (flagged stale/degraded) → explicit
      `unavailable`, and `_save_cache` refuses to overwrite a good cache with events=[].
      (2) `evaluate_macro_filter` maps unavailable → allowed=False ('calendar_unavailable'):
      no news visibility is no longer the same fact as no news.
      (3) The signal path's news gate was a -2.0 SCORE PENALTY, not a block: a
      high-confidence aligned signal scored 7.5 and executed straight through FOMC
      (verified: 8.0-capable signals stayed above the 6.0 threshold even penalised).
      Now a hard skip, matching apply_macro_guard on the plan path.
      (4) run_signal_check's staleness+spread block ended in `except Exception: pass`,
      so a failed tick read skipped BOTH guards and the order went out unchecked; a
      tick with ask but no bid also computed spread as 0.00 (passed any gate). Now
      no-tick / incomplete-tick / gate-error all skip with *_fail_closed reasons.
      Also fail-closed the plan path's own `except Exception: pass` around the macro
      guard. Net: gates can now only block on error, never green-light on error.
      117 tests green, live cycle OK (reassess, execute=False), real calendar verified
      fresh (forexfactory, 110 events, 4 USD high-impact, allowed=True).
- [x] b29 Safety gates FAIL CLOSED (done 2026-08-30: evaluate_proposal's learned-grade/DEFCON/cooldown gates did `except Exception: pass` = a corrupted state file silently BYPASSED the gate and let the trade through; signal_listener's account-policy/kill-switch block fell back to trade_allowed=True on error. All four now return execute=False with *_gate_error; tests/test_failclosed_gates.py locks it — verified the 3 new tests go RED against the old code. 103 green, live cycle OK)
- [x] Management-path broker rejection is SILENT + corrupts state (CLOSED 2026-08-30: b7b fixed executed-flag; b10b-era daemon retries rejected moves every 5s and only commits state on broker acceptance; b17 adds instant Telegram alert on rejected breakeven/trail — trade on original stop is no longer silent):
      `evaluate_management_action` hardcodes `executed=True` on every bridge call — the exact
      b7 bug class, but on the exit side. `/api/modify` returns HTTP 400 + `ok:false` on
      retcode != DONE (invalid stops / trade disabled / off quotes), so a FAILED breakeven or
      trail move reports success: watchdog sets `breakeven_active`, runtime persists
      `filled_tp_levels`, and the operator is told the stop moved when it did not. Consequence
      is worse than a bad report — a winning position keeps its ORIGINAL stop out in the field
      with the system believing it is protected. Compounding this, `filter_management_by_insights`
      (DEFCON runner-disable) is documented as "wired in trade_management" but is called by
      NOBODY — YELLOW/RED never stops a trail. Fix: mirror broker acceptance, roll back
      optimistic state on rejection, wire the dead DEFCON filter into the single choke point.
- [x] Spread gate for live entries (done 2026-08-30: MAX_ENTRY_SPREAD=0.60 in hermes_runtime, env HERMES_MAX_SPREAD, entry-path only): the parity funnel never looks at real-time
      spread (cost is linear in trades, verified 2026-08-30), so news/rollover
      spikes (XAUUSD can blow past 2.0) are unguarded in live. Evaluate a
      max-spread pre-entry gate in hermes_runtime (read-only tick check, e.g.
      skip if ask-bid > 0.60) — propose threshold from tick history, do NOT
      weaken existing gates.
- [x] Zone-width sanity (done 2026-08-30: A/B 8/12/20 bars on 13 M5 windows — 8: 12/13 prof +970/225t, 12: 13/13 +949/206t, 20: 13/13 +788/179t → keep 12, best balance): long/short entry zones are 0.5 ATR wide from a 12-bar window —
      test 8/12/20-bar lookbacks in the parity funnel, pick best by PnL+trades.
- [x] Alert hygiene (done 2026-08-30: audit of 4 execute=True events — 2 real fills DID alert, 2 broker rejections were SILENT; b10 now sets skip_reason=broker_rejected so master brief + Telegram surface every rejection)
      within 60s of every live execution (check report path in hermes_master.py).
- [x] Reusable A/B template (done 2026-08-30: scripts/ab.py — cached M5 dataset + run_backtest(data=) + const-patch or kwarg specs, restores state after; first use: BE-at-R curve 0.4→848/0.5→949/0.6→990/0.7→1030/0.9→966/noBE→966 → peak at 0.7R but KEEP live 0.5R: later BE = looser protection, +6$/wk not worth tail risk, tighten-only rule)
      dataset + run_backtest(data=...) + exclude_styles prefixes in backtest_ohlc)
      — reuse for future branch A/Bs: SMC range-kill rule on/off, macro blackout
      on/off, BE-at-R 0.4 vs 0.5.
- [x] Ticket→plan linkage (done 2026-08-30: ticket column in execution_log + exact join in learning.analyze, proximity kept as fallback): execution_log.csv has no ticket column and orders carry no
      Hermes comment, so journal trades can only be attributed to plans by time
      proximity (48h lookback in learning.analyze). Add 'ticket' to the
      append_execution_log rows in hermes_runtime.py + signal_listener.py (result
      already contains it) so future regime joins are exact, not heuristic.

## Findings
- 2026-09-07 b117 — THE TRAIL IS NOT A LEVER: b65'S EXIT EVIDENCE WAS ~93% THE
  b105 PHANTOM RUNNER (scripts/b117_trail_reprice.py +
  data/backtest/b117_trail_reprice.json + 17 tests). Re-pricing b65's
  0.45->0.30 trail decision under the corrected engine, arms differing ONLY in
  trail_after_partial on identical bars: the DIRECTION holds (0.30 > 0.45 on
  net_R in 4/4 independent windows) but the MAGNITUDE collapses from b65's
  +10.6R (M5) / +22.1R (M15) to +0.6..+2.4R per 6000 bars — because pre-b105 the
  ladder was a constant 1.0 and a phantom full-size runner survived every TP1, so
  the trail touched every trade; post-b105 only the A-grade runner lane (~20-27%
  of gate-passed signals) can be trailed at all. The grid is FLAT, not one-sided
  (b110's test): no-trail wins cached exp_R (0.284 vs 0.278) and W1 (0.227 vs
  0.211), 0.80 wins W1's net_R — so no trail retune earns a live change, and
  b115's restart is worth ~1R/6000 bars on the exit axis, not ~20R. SECOND GAP
  from the same read-through: live _trail_params floors the distance at $3.00
  absolute (max(risk*mult, 3.0)) and the lab never modelled it, so the lab
  trailed TIGHTER than live wherever risk < $10 — 61.8% of W4's trades, 7.3%
  cached, 0% W2 (a regime-dependent parity gap, invisible on the legs that were
  quoted most). engines/backtest.py/backtest_real.run_backtest gained
  trail_floor (default 0.0 — every stored number byte-identical, AST-pinned);
  with the floor modelled the verdict is unchanged. Filed b118: the lab bar
  (0.50) still differs from live HEAD (0.30) — now a decision, not a discovery.
- 2026-09-06 b108 — THE FUNNEL BASELINE AND THE b70 LANE SET, RE-MEASURED UNDER
  THE b105-CORRECTED ENGINE (scripts/b108_rescore_corrected.py +
  data/backtest/b108_rescore_corrected.json + 22 tests in
  tests/test_b108_rescore_corrected.py). b108 re-runs b81's measurement
  VERBATIM — b81.measure_leg/verdict/lane closures IMPORTED, not restated — on
  the same bars, same harness, same ladder, same live grade gate; only the
  engine changed (runner leg scaled by 1-partial_taken; share>=1.0 closes at
  TP1 and frees the slot). FINDING 1 — THE BAR HALVED AND MORE: graded funnel
  exp_R cached 0.796->0.285, W1 0.676->0.202, W2 0.662->0.206, W3 0.767->0.227,
  W4 0.745->0.222; net_R collapses 2.5-3.2x; DD gets WORSE on 4 of 5 legs (W3
  -5.1 -> -7.6) because the phantom runner used to paper over drawdowns; the
  freed slot admits +5..+16 real entries per leg. The honest merit bar is
  ~0.20-0.23R on independent windows (0.285 cached), not 0.854R and not
  0.52-0.53R. FINDING 2 — THE INFLATION WAS NOT NEUTRAL, as b105 predicted:
  lane-relative margin shift (d_lane_exp_R minus d_funnel_exp_R) is POSITIVE on
  all four windows for lane_nr7htf (W1 +0.071 / W2 +0.045 / W3 +0.093 /
  W4 +0.052 — its arm hits TP1 less often than the funnel, so the funnel lost
  more), while the pdh
  family's shifts are mixed-sign and smaller (|max| 0.032). A neutral bug
  cannot produce a one-sided shift, so every arm-vs-arm margin printed before
  b105 is contaminated by the arms' differing TP1-hit profiles. FINDING 3 —
  ONE DECISION-RELEVANT FLIP: lane_h4pdh's W4 comparison moves from a win
  (+0.019R) to a loss (-0.002R) purely because of the correction. FINDING 4 —
  B70 RE-DECIDED, ANSWER UNCHANGED BUT FIRMER: windows_beaten on exp_R fall
  2->1 (gated_pdh_dayext), 3->2 (h4pdh), 2->1 (runway), 0->0 (nr7htf); no lane
  replicates on all four windows under either engine, every surviving margin is
  <=0.05R, and nr7htf's net_R trap got worse — it now SUBTRACTS net_R on W1
  (-9.7R) and W2 (-4.9R) where b81 had it adding on all four. FINDING 5 (side
  finding, filed as b109): reading the ladder call path exposed that
  lab_harness feeds the REAL _partial_close_fraction a dict that cannot satisfy
  its contract (live reads setup_grade/momentum_strength/rr_remaining/
  structure_state; the backtest dict supplies none of them), so rr_remaining
  defaults 0.0 and the function returns (1.0, weak_full_exit_at_tp1) on 935/935
  calls — the "live-parity ladder" is a constant that agrees with live only
  because the strong-runner lane has never fired. INTEGRITY: this ledger's
  old_* columns equal the shipped b81 ledger cell-for-cell (pinned), and the
  cached funnel cell equals b105's own independently-measured 0.285/110.
  Nothing wired, nothing weakened; the numbers only got more honest.
- 2026-09-06 b103 — SHARED PROSE-AUDIT LAYER (tests/prose_audit.py +
  tests/test_b103_prose_audit.py; b102 refactored into its first consumer).
  SHIPPED VIA STEP-0 HARVEST (b46 shape): the previous run wrote the layer, its
  test file and the b102 re-export refactor and died ~5 minutes before this run
  started, leaving them UNCOMMITTED — and its own HEAD 50cf480 was stamped
  VERDICT=BROKEN by verify_head.sh (push gate closed, ops paged). The harvest
  was therefore also the heal: the stranded work is exactly what makes HEAD
  green again, which is the designed loop (b47/b51) working, not an accident.
  WHAT THE LAYER IS: b102 shipped the first tripwire that reads ENGLISH PROSE
  for a policy claim instead of code structure, and hit bugs a structural scan
  never has. Its fixes lived inside its own file, so the next prose audit would
  re-discover them; prose_audit.py is the reusable form and b102 now imports
  (not copies) every predicate.
  THE SIX RULES, each pinned by a test class: (1) merge consecutive '#' lines
  before splitting into sentences, or a wrapped claim vanishes; (2) a negated
  widening verb always beats the history-spare, and shipping evidence must NAME
  the item — 'not widened in this commit' contains 'widened in'; (3) git log is
  a medium under audit, a decision recorded only in a commit message leaves the
  tree looking clean; (4) a phrase inside quotes is a MENTION, not a decision,
  and the b-number binds NEAREST the verb — this is the bug that broke HEAD
  50cf480: b102's replay flagged b102's own message for quoting its vocabulary
  and bound it to an incidental 'b94' three clauses away; (5) extract prose from
  the TOKENIZER and the AST, never from 'any line with a hash' — a tripwire's
  fixtures must quote the vocabulary to pin it, and a line scan sentences those
  strings as policy prose; (6) A QUOTE IS ONE SENTENCE — found by THIS run.
  NEW FINDING (rule 6, the reason to keep going after a harvest): the stranded
  layer documented five rules but owned four test classes, so the first thing
  this run did — pin rule 5 — immediately caught a sixth bug the previous run
  never saw. prose_audit's own nearest_item docstring quotes an example
  containing an ellipsis; the naive splitter cut INSIDE the quote, the tail half
  had no opening quote, quoted_spans() found nothing, the mention spare died on
  the exact sentence written to demonstrate it, and a phantom claim bound to
  'b94' — an item that exists nowhere as a parked widening. Every fixture test
  passed on it; only the repo-wide reality-binding check (every bound item must
  exist in the backlog) caught it. Fix: split_sentences() skips boundaries
  inside quoted spans, and BOTH prose paths (code and commit messages) go
  through it, so the spare can no longer be split away from a claim.
  METHOD RULE -> new todo b104: a semantic/meaning-reading audit cannot be
  validated by fixtures alone (a fixture only proves the predicate fires on the
  shapes its author imagined — rules 4, 5 and 6 were each a shape its author had
  NOT imagined). Pair it with a check that the FINDINGS RESOLVE TO REAL
  ENTITIES, and assert the scan is non-vacuous on the same real data, or the
  reality check passes on a dead predicate.
  Nothing wired into the trading path: no gate, no exit, no order call touched.
  26 tests in tests/test_b103_prose_audit.py (8 added by this run for rules 5
  and 6, incl. the anti-vacuity pair proving the same words UNQUOTED are still
  claims), 1052 green, live cycle OK.


- 2026-09-06 b92 (b87 queue item 3) — THE COOLDOWN GATE CANNOT BE MEASURED AS
  A BOOK: IT LIVES IN THE CLOCK DOMAIN (scripts/b92_cooldown_gate.py +
  data/backtest/b92_cooldown_gate.json + 11 tests). b84's template (kept vs
  dropped book on cached+W1..W4) assumes the gate's population exists inside
  the dataset. For cooldown it does not: every leg is weekday-only (0 Sunday
  bars in 21k bars total), so the post-open window (Sun 23:00->23:15 UTC)
  holds ZERO funnel signals on 5-of-5 legs. Reading that as "no-op" — b86's
  verdict for range-kill — would be a measurement-medium artifact: the harness
  is blind, the gate is not. The honest rows are in the other three domains:
  BIND-in-clock (analytic reach: 15 min/week = 0.21% of the 117 h session),
  LIVE RECORD (plan_history created_at: 1542 cycles over 8 days, exactly ONE
  gap >= 30 min -> the restart guard armed once — the b30 fix holds in the
  field, vs 100% arming before it), SHADOW (b87's question, answered by
  probing market_hours at Sun 23:00-23:14: it ALLOWS every minute of the
  window, so cooldown is the ONLY gate on its window — the exact opposite of
  range-kill's full shadowing by MIN_SETUP_GRADE), REACHABILITY (learning.py
  moves min_rr/min_grade/risk_mult only; both cooldown constants are literals,
  operator-only like b86's knob). Verdict: gate stays, untouched (hard rule);
  what changed is the METHOD — a gate's bind test must first check that the
  measurement medium can represent the gate's population at all.
- 2026-09-05 b86 (b68 round 19) — THE RANGE-KILL GATE IS A NO-OP AT LIVE AND
  FULLY SHADOWED BY THE GRADE GATE AT FULL POWER
  (scripts/b86_range_kill_books.py + data/backtest/b86_range_kill_books.json +
  15 tests in tests/test_b86_range_kill_books.py). b84's template applied to
  the filter it named next: `regime==range and bias!=neutral and smc_conf <
  0.35 -> bias=neutral` (hermes_runtime.build_live_plan literal; backtest twin
  strategy_signal(range_kill_conf=...), the only funnel parameter ever made
  A/B-able — scripts/ab_range_kill.py, 2026-08 — and never measured in R).
  BIND TEST: 0 signals killed at 0.35 on 5-of-5 legs; the trade book is
  byte-identical across the whole ladder 0.0/0.35/0.5/0.7/0.99 (cached
  0.796/99, W1 0.676/174, W2 0.662/165, W3 0.767/190, W4 0.745/166 — kill_share
  0.0 at every t on every leg). SHADOW TEST (b86's own question, new todo
  b87): at the practical ceiling 0.99 the rule removes 462/739/837/858/988
  signals (49-57% of the raw population) and the killed grade mix is
  {'C': 100%} on EVERY leg — the population MIN_SETUP_GRADE='B' already
  rejects — so the killed book run under the live gates is 0 trades on all
  five legs, while the same book UNGATED trades 117-274 times at exp_R
  0.341-0.452, below the funnel's own 0.524-0.796 on the same bars everywhere.
  The gate aims at the worst book in the system and never gets to shoot: the
  protection operators attribute to range-kill is actually provided by the
  grade gate. REACHABILITY (b84 contrast): min_rr's cliff was reachable by
  learning.py's +0.25 steps; this knob has NO adaptive path — learning
  adjusts min_rr/min_grade/risk_mult only — so the no-op is permanent until a
  human edits the literal. Nothing wired, nothing removed: deleting a shadow
  is a human decision (and a shadow is a backstop if the grade gate ever
  moves). INTEGRITY (b83): gate_conf_0.35 reproduces b80's gradeB_rr15
  exactly on all 5 legs; live population ⊆ never-kill population on every
  leg; time exit derived (144 M15 bars), not hardcoded.

- 2026-09-05 b81 — THE LANES WERE INFLATED BY THE SAME BUG AS THE FUNNEL, AND
  THE CORRECTED BAR SETTLES b70 AGAINST EVERY LANE
  (scripts/b81_lane_rescore.py + data/backtest/b81_lane_rescore.json + 17 tests
  in tests/test_b81_lane_rescore.py). b81's founding note said the lane arms
  were "unaffected" by b80 because lab arms all declare grade "B". WRONG, and
  the reason is structural: a lane is `funnel(row) or arm(row)`, so the
  funnel's own A/B/C-graded signals are the lane's PRIMARY source — the lane
  inherited the C-grade trades the live executor rejects. Re-reading the
  shipped ledgers against b80's gradeB column (the item's own instruction)
  would have corrected one side of the comparison and left the other broken, so
  this item RE-MEASURED instead: all four lanes, both conventions
  (min_grade=None / min_grade=live), on cached+W1..W4, same bars/harness/
  ladder. INTEGRITY: the ungraded re-measure reproduces all 16 shipped ledger
  rows exactly, and the ungraded funnel reproduces b80's nogates column on
  every leg — the lane closures are verbatim, nothing was retuned.
  NUMBERS: the gate lifts a pdh-family lane by +0.13..+0.26R exp_R — the same
  order as the funnel's own lift (within 0.10R of it on every window), which is
  what "the lane IS mostly the funnel" looks like measured. Corrected verdict
  under b74's all-windows rule: gated_pdh_dayext 2-of-4, h4pdh 3-of-4 (loses
  W3 by -0.05R), runway 2-of-4, nr7htf 0-of-4. NO lane replicates; the largest
  margin anywhere is +0.061R (runway/W1). b70's standing answer — no lane earns
  the slot — is now settled on a clean bar rather than merely un-beaten.
  THE TRAP nr7htf exposes: it adds +46..+67 net_R on ALL FOUR windows and its
  marginal trade is positive everywhere (+0.13..+0.20R), yet it loses exp_R on
  all four. A capacity question asked on tot_R alone votes YES on a lane the
  per-trade question rejects; quote exp_R and net_R together, never one.
  Also cleaned: a detached worktree leaked in /tmp by a killed verify_head run
  (b50's cleanup test was red repo-wide because of it) — `git worktree remove
  --force` + `prune`. Nothing wired; no gate touched.

- 2026-09-05 b80 — THE LAB'S FUNNEL BASELINE WAS MEASURED WITHOUT A LIVE GATE:
  THE MERIT BAR WAS TOO SOFT, AND THE FUNNEL IS BETTER THAN 17 ROUNDS BELIEVED
  (engines/lab_harness.py + scripts/b80_gate_parity.py +
  data/backtest/b80_gate_parity.json + 6 tests in tests/test_b80_gate_parity.py).
  Root cause: `run_arm()` passed only `min_rr` to `backtest_ohlc` and never
  `min_grade`, while the canonical live-parity runner
  `engines.backtest_real.run_backtest` defaults to `min_grade="B", min_rr=1.5`.
  The funnel emits 58-67% C-grade signals per window (cached 542/848, W1
  893/1429, W2 1021/1544, W3 1030/1767, W4 1167/1745) that the LIVE executor
  rejects at auto_executor Check 6 — so every round's CURRENT_FUNNEL baseline
  was a funnel-minus-one-gate, measured ~0.15-0.24R too LOW. Lab arms all
  self-declare grade "B", which is why the gap was invisible: the gate is a
  no-op for an arm and a majority filter for the funnel.
  CORRECTED BAR (b60 ladder + live time exit, exp_R): cached 0.558→0.796,
  W1 0.524→0.676, W2 0.521→0.662, W3 0.528→0.767, W4 0.532→0.745. Trade
  counts roughly halve (W1 316→174, W2 315→165, W3 332→190, W4 340→166) and
  maxDD improves on every window (W3 -9.6→-5.1, W2 -8.0→-5.1).
  SECOND FINDING — the RR gate is REDUNDANT for the funnel: 0 signals below
  MIN_RISK_REWARD=1.5 on all five legs (the blueprint floors RR at 1.55), so
  gradeB and gradeB_rr15 are identical everywhere. Pinned by a test so a
  future funnel change that breaks the redundancy is noticed.
  CONSEQUENCE FOR THE LOOP — re-scored every arm in every shipped confirm
  ledger against the corrected bar (arms are unaffected by the fix, only the
  bar moved): NO arm beats it on ANY of the four independent windows at the
  ≥0.05R level with usable n. The best per window are pdh_runway W1 0.831
  (+0.155, n=59) and W2 0.729 (+0.067), pdh_no_runway W2 0.968 / W3 0.812 —
  all the same arms that failed replication on the OTHER windows, so no
  promotion is implied; but the round-14 conclusion "no lab arm has ever
  cleared all four windows" is now much stronger, and the funnel's own
  four-window stability is 0.662-0.796, not 0.521-0.532. The loop's standing
  verdict — the live entry filter is the best measured thing — was understated.
  Nothing wired; no gate weakened (the fix only ADDS a live gate to a
  measurement). Any historical round whose arm beat the funnel by <0.25R must
  be re-read against the corrected bar before its numbers are reused.

- 2026-09-05 b68 round 17 — SELECTION WITHOUT A REPLICATING LIFT IS NOT AN
  EDGE: THE H4 GATE RANKS NR7 TRADES PERFECTLY AND STILL LOSES (scripts/
  b68q_nr7htf_lab.py + scripts/b68q_confirm_nr7htf.py; 22 tests in
  tests/test_b68q_nr7htf_lab.py). Candidate: the last unmeasured pairing of
  the loop's two strongest survivors — round 5's nr7 compression-breakout
  geometry (the best additive lane ever measured) x round 12's H4 trend-state
  oracle (the only gate that lifted its control on BOTH independent windows),
  pure intersection, geometry unchanged, oracle verbatim from b68m. RESULT:
  REJECTED 1-of-4 windows (W4 0.586 beats funnel 0.532; W1 0.437 / W2 0.469 /
  W3 0.471 lose 0.524/0.521/0.528; cached 0.679 informational). The round's
  real output is the DISSOCIATION between ordering and lift: the gate's
  agree>disagree selection ordering holds on ALL FOUR independent windows —
  the single most consistent selection in 17 rounds, the exact check that
  killed rounds 9/13/16 — and the complement is uniformly bad (0.367/0.323/
  0.430/0.293, below funnel everywhere). Yet the arm still fails the merit
  bar, because the LIFT over the ungated control replicates only 2-of-4 (W1
  tie 0.437->0.437, W3 LOWER 0.533->0.471; b77 MIXED). A gate can rank a
  population correctly and still add nothing: nr7's own spread between its
  best and worst subsets is ~0.1R, while the funnel-vs-nr7 gap is ~0.1R the
  OTHER way — perfect sorting of a population that starts 0.05-0.1R behind
  ends 0.05-0.1R behind. Frequency is the second killer: the H4 gate on nr7
  keeps ~45% of signals (n~290-306/window, ~90% of the funnel's own), so the
  lane dilutes to 2-of-4 with every margin <+0.05R. b78 mix disclosure: the
  agree arm is one-sided in 3 of 5 legs (cached 87B/14S, W1 63B/226S, W4
  228B/59S) — an H4-trend gate IS a direction filter, so its exp_R is the
  number for whichever way the regime ran; the two-sided legs (W2 163B/125S)
  are exactly the windows where the gate's lift was real. Stretch flat
  (<=0.02 ATR every window — pure intersection by construction, b75-clean).
  Gate pass-rate probe (b79's metric, measured here for the first time):
  0.433/0.451/0.461/0.462 across W1-W4 — the most STABLE fire rate of any
  oracle in the loop (weekly-runway swung 36-68%), which is consistent with
  round 12's finding that the H4 state is the cleanest oracle — and it shows
  b79 is a NECESSARY-not-sufficient screen: a stable pass rate cannot
  guarantee a replicating lift. After 17 rounds: no lab arm has cleared all
  four windows; the funnel's 0.52-0.53 band stands; the two-survivor
  combination space is now exhausted (pdh x dayext r9, pdh x squeeze r8,
  pdh x h4t r12, funnel x h4t r13/14, pdh x runway r16, nr7 x h4t r17).

- 2026-09-05 b68 round 18 — THE GRADE LADDER MEASURED AS BOOKS: THE LIVE B
  GATE IS CONFIRMED ON SELECTION AND CONTRADICTED ON VOLUME, IN THE SAME
  LEDGER (scripts/b68r_grade_ladder_lab.py; 13 tests in
  tests/test_b68r_grade_ladder.py; ledger data/backtest/b68r_grade_ladder.json).
  No new arm and no new gate this round — the OBJECT was the funnel's own
  grade ladder (A/B/C), which 18 rounds of comparisons quote but nobody had
  ever measured as three books on the corrected (b80) bar. Each grade
  population was run through the live-parity harness (b80's funnel_signals
  reused verbatim per b83, ladder + live time exit, cached+W1..W4, one slot
  per book). REPRODUCTION first: the B book equals b80's shipped gradeB
  funnel column to 3 decimals on all 5 legs (99/174/165/190/166 trades,
  0.796/0.676/0.662/0.767/0.745 exp_R) — the capture is the same machine.
  FINDING 1 (the gate stands): B > C on exp_R on ALL FOUR independent
  windows (+0.272/+0.321/+0.275/+0.175 chronological W4->W1) and on ALL
  EIGHT window x side cells — min_grade=B stays, the cliff is at B.
  FINDING 2 (the honest counterweight, b81's both-axes rule): the UNGATED
  book earns MORE total net_R on all four windows (+57.4/+29.5/+54.9/+48.0)
  because the dropped C trades are not garbage — their marginal trade is
  +0.33/+0.21/+0.37/+0.34R, positive everywhere but below the kept book's
  bar, and the ungated DD is WORSE on every window (-6.8..-10.2 vs
  -2.0..-4.9). The gate buys quality-per-trade and DD with volume; that is
  a policy choice the live config already made, now with both prices on
  record. FINDING 3 (b78's mix question answered): A > B replicates only
  3-of-4 (W4 -0.166R), and the side-split shows the flip is a DIRECTION
  cell, not a rung property — A-SELL on W4 is the weak book (0.085 vs
  A-BUY 0.745 there), while A beats B on both sides of the newest window.
  Tightening the live gate B->A would give up -261.7R of net across the
  four windows (3-of-4 windows pay, the oldest draw doesn't): NOT proposed,
  and pinned as not-universal so a future run cannot re-propose it from the
  cached leg alone. Regime note: the legs span a 4x ATR swing (W4 mean TR
  4.3 -> W2 16.3), so "rung X always ranks" was never going to survive;
  only the B/C cliff did. Nothing wired, no gate weakened, no live module
  touches the lab (pinned).

- 2026-09-05 b68 round 16 — THE WEEKLY-RUNWAY GATE IS THE LOOP'S CLEANEST
  SELECTION FLIP: THE ORACLE'S FIRE RATE IS ITSELF REGIME-GIFTED (scripts/
  b68p_runway_lab.py + scripts/b68p_confirm_runway.py; 20 tests in
  tests/test_b68p_runway_lab.py). Candidate: round 4's pdh_break_w10 (the
  only arm ever replicated 2-of-2 on clean windows) gated on a NEW oracle
  type — the previous trading week's extreme as BACKGROUND STATE (does the
  entry have >=1.0*ATR room to the weekly high/low in trade direction?),
  pure intersection, geometry unchanged, zero-lag by construction (b73/
  b75-clean: stretch delta <= +0.11 ATR on every window). RESULT: 2-of-4
  windows (W1 0.831 / W2 0.729 beat funnel 0.524/0.521; W3 -0.085 / W4
  0.424 lose 0.528/0.532) — b74 all-windows rule FAILS. But the round's
  real output is the SHAPE of the failure: the gate's SELECTION ORDERING
  (agree > complement, the check that killed round 9's champion) holds on
  exactly ONE of four windows. On W2/W3/W4 the DROPPED set out-earns the
  kept set — W3 keeps 48 trades at -0.085R while cutting 34 trades worth
  +0.812R. WHY: the room distribution is a regime proxy, not a stable
  property — median room-to-weekly-extreme is +6.46 ATR on W1 (young week,
  trend just starting) and -0.79 ATR on W4 (the week had already run), and
  the gate's pass-rate swings 36%-68% across windows (W4 50/138, W2 57/116,
  W1 75/111); in a regime where
  every day-break is late-in-the-week, "no runway" selects the STRONGEST
  continuation trades (the week is being extended BY those breaks). b78
  (implemented as a structure this round — side_mix() ships the BUY/SELL
  mix of actual trades for every arm on every leg) makes the mechanism
  visible: the complement arm is one-sided per regime (W3 32B/2S, W4
  62B/12S, cached 19B/0S) — the no-runway trades are the late chase of an
  already-extended week, and whether chasing an extension pays depends on
  which way that week broke. Lane funnel+runway: 2-of-4 (0.546/0.543 beat,
  0.485/0.519 lose), margin <+0.05R — b70's answer unchanged. b77
  pre-flight MIXED on agree and complement alike. After 16 rounds: no lab
  arm has cleared all four windows; the funnel's 0.52-0.53 band stands;
  the level-as-oracle family is now screened too. METHOD RULE -> new todo
  b79 (gate fire-rate stability pre-flight: measure the oracle's PASS RATE
  per window BEFORE its R — an oracle whose pass-rate or threshold-crossing
  median swings by regime cannot produce a regime-independent selection,
  and this round could have been closed on that 5-line probe alone).
  Nothing wired (hard rule). Registry rows pdh_runway + pdh_no_runway carry
  the five-leg numbers + the mix. Ledger: data/backtest/
  b68p_runway_confirm.json.

- 2026-09-05 b68 round 15 — THE WEEK-LEVEL BREAKOUT IS ALSO SCREENED OUT, AND
  THE DIRECTION MIX IS A NEW REGIME FINGERPRINT (scripts/b68o_weekly_lab.py +
  scripts/b68o_confirm_weekly.py; 24 tests in tests/test_b68o_weekly_lab.py).
  Round 14 said future rounds must justify themselves; this one did on
  novelty — the previous TRADING WEEK's high/low is the level every ICT desk
  draws next to PDH/PDL and the only level family never measured. Geometry is
  round 4's close-confirmed break lifted verbatim one timeframe up (b75: the
  level break IS the trigger, so the geometry supplier is the fresh member).
  RESULT: pwh_break_w10 prints cached ladder_ts 1.262 (n=18) — the best
  cached number since round 9 — but the funnel on the SAME cached bars is
  0.558, and the b74 all-windows rule kills it: 2-of-4 independent windows
  (W2 0.618 / W3 0.601 beat 0.521/0.528; W1 0.344 / W4 0.514 lose
  0.524/0.532). t50 wins 3-of-4 but loses W1 at 0.307. b77 pre-flight MIXED
  on both arms (no monotone recency ramp, no stable edge). NEW DISCLOSURE
  SHAPE: the arm's BUY/SELL mix flips by window — cached 24/24 BUY, W1 13
  BUY/39 SELL — so any single-window number for a level-breakout arm is
  really "the number for whichever way that regime broke", and the future
  rounds should quote the mix alongside exp_R (level_probe already ships it).
  After 15 rounds: no lab arm has ever cleared all four windows; the funnel's
  0.52-0.53 band stands. HARVEST NOTE: this is the 6th b46-shape occurrence —
  the previous run wrote the whole round (2 scripts + 24 tests + both ledgers)
  and died before committing; this run verified it, fixed 2 real defects the
  uncommitted tests exposed (harness column names dd_R/over_time_stop vs the
  real maxDD_R/holds_over_time_exit, and verdict() reading row['dd_R'] which
  nulled every dd in the shipped ledger), appended the two registry rows, and
  shipped it. Nothing wired.

- 2026-09-04 b68 round 14 — THE FOURTH DRAW KILLS THE CANDIDATE, AND THE
  KILL SHAPE IS THE FINDING (scripts/b68n4_fourth_draw.py + W4 slice in
  scripts/b68l_windows.py; 19 tests in tests/test_b68n4_fourth_draw.py).
  Round 13's funnel_h4t_agree — the first arm ever to beat the live
  funnel on all three independent windows — faces b74's fourth draw: W4
  (2025-07-09→2025-10-08, 6000 M15 bars, zero overlap with cached/W1/W2/
  W3 measured + asserted). RESULT: DIES — ladder_ts 0.517 (n=267) vs the
  funnel's 0.532 (n=340) on the SAME bars. But the round's real output is
  the SHAPE of the four margins. Quoted window-by-window they looked like
  a decay W1→W4 (+0.093/+0.032/+0.008/−0.015); read in CHRONOLOGICAL
  order (W4 oldest → W1 newest) they are MONOTONIC INCREASING: −0.015/
  +0.008/+0.032/+0.093. The gate's edge grows with recency — it is a
  property of the RECENT H4 regime (the loop's own cached 0.854 lesson
  again, now at arm level), not of gold M15. That monotone curve is the
  cleanest regime-dependence measurement the loop has ever produced and
  it answers b74's round-13 "price the DECAY" question with a flat NO:
  a candidate whose edge is a linear ramp in recency cannot be expected
  to survive forward out of the regime that feeds it. SECONDARY ROWS:
  pdh_h4t_agree (round-12 champion) BEATS W4 (0.597 vs 0.532, n=82) but
  failed W3 — 3-of-4, not replication; its ungated control pdh_w10 loses
  W4 (0.480) — 2-of-4; the h4pdh lane beats W4 (0.546) after losing W3 —
  3-of-4. FOUR independent windows now bracket the funnel at 0.524/
  0.521/0.528/0.532 — the live funnel's out-of-regime expectancy is
  STABLE ~0.52-0.53R, and after 14 rounds NO lab arm has cleared all
  four windows. The screening question the standing loop was created to
  answer is now ANSWERED: the funnel's entry filter is the best measured
  thing on this market; further single-arm rounds have low prior.
  Nothing wired (hard rule); registry row funnel_h4t_agree carries all
  four windows + the NOT-wired verdict. METHOD RULE → new todo b77
  (chronological-decay test before any draw is spent).

- 2026-09-04 b68 round 13 — W3 THIRD DRAW + THE H4-STATE GATE APPLIED TO
  THE FUNNEL ITSELF (scripts/b68l_windows.py W3 slice + scripts/
  b68n_funnel_gate_w3.py; 17 tests in tests/test_b68n_funnel_gate_w3.py).
  SHIPPED VIA STEP-0 HARVEST: the previous run wrote the whole round and died
  before committing (b46 shape, 5th occurrence); this run verified the ledger
  against the scripts' claims (W3 meta zero-overlap asserted; cross-round
  continuity: round 13's W1/W2 funnel + pdh rows reproduce round 12's shipped
  numbers exactly — pinned by a test), added the round-13 backlog note, the
  b70/b74 progress notes and this entry. FINDING 1 — the round-12 champion
  FAILS its third draw: pdh_h4t_agree ladder_ts 0.505 (n=74) vs funnel 0.528
  on the SAME W3 bars (2025-10-08→2026-01-12), after 0.657/0.927 on W1/W2.
  Two windows was b74's floor, not its finish line; the arm is 2-of-3 and
  stays a lab row. Its ungated control collapses harder (0.370), so the H4
  gate still LIFTS pdh on W3 (+0.135R) — the gate is not fake, the funnel
  bar is what it cannot clear. FINDING 2 — the round's real candidate:
  gating the FUNNEL's own signals on the H4-trend state (funnel_h4t_agree,
  never measured before — round 12 only ever gated pdh) is the FIRST arm in
  loop history to beat the funnel on ALL THREE independent windows: 0.617 vs
  0.524 (W1), 0.553 vs 0.521 (W2), 0.536 vs 0.528 (W3), n=203/228/209 — a
  real subset (gate_share 0.68-0.77, cut_share 0.13-0.21, state-age median
  11-17 H4 bars: a slow STATE, b75 rule 6). BUT the margins SHRINK window by
  window (+0.093 → +0.032 → +0.008) and the SELECTION ORDERING FLIPS on W3
  (disagree cut 0.553 > agree 0.536) — the exact regime-flip signature that
  killed round 9's champion on b68l. On cached (in-sample) the flip is also
  there (cut 0.687 > agree 0.57). So the honest read: the agree subset is
  >= the funnel on every window, but the gate's DISAGREE-CUTS-losers story
  only holds out-of-regime on W1/W2, not W3. NOT wired (hard rule): a
  funnel-entry filter change is a live-gate-stack decision, needs the full
  b74 protocol (live gates, kill-switch streak math, a 4th window if the
  broker history can give one) and stays a human decision. FINDING 3 — the
  h4pdh additive lane loses W3 too (0.515 vs 0.528, 2-of-3): b70's clean-
  window lane evidence weakens further; the only lane-shaped positive left
  across all three windows is the funnel-gate itself (which is a REPLACEMENT
  filter question, not a lane). METHOD NOTE: three independent windows now
  agree the funnel scores ~0.52-0.53 ladder_ts out-of-regime (0.524/0.521/
  0.528) — the cached 0.854/0.558 bar is confirmed regime-inflated for the
  third time. See b70/b74 progress notes.

- 2026-09-04 b68 round 12 — COMBINATION: PDH breakout x HTF-trend STATE
  oracle (scripts/b68m_htf_pdh_lab.py + b68m_htf_pdh_confirm.py; 24 tests in
  tests/test_b68m_htf_pdh_lab.py). SHIPPED VIA STEP-0 HARVEST: the previous
  run wrote the whole round (2 scripts + test + 2 ledgers + registry rows) and
  died before committing — the b46 shape for the fourth time; this run
  verified the ledgers against the scripts' own claims, added the backlog
  round-12 note + this Findings entry, and shipped it as its own harvest
  commit. THE FIRST ARM TO PASS FULL REPLICATION: pdh_h4t_agree (round-4's
  replicated pdh_w10 geometry, unchanged, gated on the H4 EMA50 trend STATE —
  only FULLY CLOSED H4 bars read, no lookahead) beats the funnel's ladder_ts
  on BOTH truly independent windows (0.657 W1 n=55 / 0.927 W2 n=63 vs funnel
  0.524/0.521 on the SAME bars), beats its own ungated control on both
  (0.612/0.623 — the gate adds, it is not "pdh again"), and keeps
  agree > disagree ordering on BOTH windows (cut 0.451 n=31 / 0.631 n=23) —
  the exact test round 9's dayext champion failed when its selection flipped
  sign between regimes. b72/b73/b75 probes all clean: H4 gate_share 0.54-0.61
  (a real filter; H1's 0.88-0.91 is nearly vacuous and is RECORDED so nobody
  quotes H1 as a filter), agree-subset state-age median 9-18 H4 bars (a slow
  STATE, not an event in disguise — b75 rule-6), stretch delta gated−control
  ≤ +0.04 ATR (informational lift, round 10's 4-ATR chase tax absent).
  HONEST FLIP DISCLOSED: on the IN-SAMPLE cached leg the ordering inverts
  (disagree 1.237 n=11 > agree 0.641) — b76 says the cached regime is exactly
  what cannot be trusted; the flip is pinned by a test so the write-up can
  never quietly drop the row. LANE (funnel-first, H4-gated pdh on free bars)
  replicates only a MARGINAL positive: 0.534/0.535 vs 0.524/0.521 (< +0.05R,
  dd worse on W1 −6.9 vs −6.1, better on W2 −5.7 vs −8.0) — b70 weighs it as
  marginal, like round 11's lane, NOT as a headline. NOT WIRED (hard rule):
  n=55/63 is 17-20% of the funnel's sample and two windows is b74's floor,
  not its >=3-window + live-gate-stack + kill-switch-streak protocol. METHOD
  NOTE: the round's own cached-leg funnel row (0.558 via the b71 harness on
  the same 3000 bars) vs the 0.854 quoted in the b68 header since round 1 —
  the 0.854 came from the b61 arm grid, not the harness; another reason the
  cached bar is informational only. See b70/b74 progress notes.

- 2026-09-04 b68 round 11 — METHODOLOGY: THE MERIT BAR WAS NEVER
  OUT-OF-SAMPLE (scripts/b68l_windows.py + b68l_confirm_independent.py;
  harvested from the previous run's uncommitted work per b47, pinned this
  run by 19 tests in tests/test_b68l_independent.py). Rounds 1-10 fetched
  "the last 6000 M15 bars" as the FRESH confirm set. Measured: the cached
  3000-bar set (2026-07-15→08-28) sits at the END of the broker's M15
  history, so the last 6000 bars contain ALL 3000 cached bars — overlap
  3000/3000. Every "beat the funnel on BOTH sets" verdict for ten rounds
  compared a set against its own superset; the "fresh" number was the same
  July-August regime plus 3000 extra bars. This round fixes the
  MEASUREMENT, not the strategy: W1 = 6000 bars 2026-04-14→07-15 (ends
  where cached begins), W2 = 6000 bars 2026-01-12→04-14, both asserted
  zero-overlap with cached and each other (facts recorded in the JSON,
  pinned by tests), H1/H4 context padded 200h so the funnel never starves.
  The whole b70 decision set re-run through the b71 harness with the funnel
  measured on the SAME bars per window (round-4 rule). FINDING 0 — the
  baseline itself: the funnel scores 0.524 (W1) / 0.521 (W2) vs its cached
  0.854; the 0.854 bar was regime-inflated, and the two independent windows
  agree with each other closely. FINDING 1 — round 9's champion (pdh x
  dayext, the ONLY arm ever to pass the merit bar) FAILS replication:
  ladder_ts 0.928 on W1 (n=38) but 0.447 on W2 (n=38) vs funnel 0.521 —
  it beats the funnel in exactly one of two out-of-regime windows, i.e.
  the cached+contaminated-fresh pass was regime luck. b74's replication
  requirement just earned its keep. FINDING 2 — the gate's SELECTION FLIPS
  SIGN between regimes: agree > complement on W1 (0.928 vs 0.415) but
  agree < complement on W2 (0.447 vs 0.743, n=60/63 — real samples both
  sides). Round 9's complement probe "proved selection is real"; out-of-
  regime it proves the opposite. The dayext<->PD-level agreement is a
  REGIME INTERACTION, not a property of gold M15 — rounds 9+10's
  "selection is symmetric" conclusion is downgraded. FINDING 3 — the
  UNGATED pdh control (round 4's pdh_w10) is the ONLY arm that beats the
  funnel on BOTH independent windows (0.612 vs 0.524, 0.623 vs 0.521,
  n=95/100): the loop's first genuinely replicated arm, and the gate that
  "lifted" it in round 9 actually made it regime-fragile. FINDING 4 —
  nr7 loses both windows standalone (0.437/0.390, n≈480): its round-5
  "strongest lane" status was also contamination. The gated lane
  (funnel-first + gated pdh on free bars) replicates only a MARGINAL
  positive (0.559/0.534 vs 0.524/0.521, < +0.05R/trade, DD no better on
  W2) — b70 must weigh it as marginal, not as round 9's headline. METHOD
  RULE (new todo b76): every confirm script that fetches "the last N bars"
  must assert its overlap with the cached set is ZERO (or record the
  measured overlap in the ledger and name the set as in-sample); the
  b68l_windows builder is the reusable pattern. Nothing wired live; the
  funnel stays. 19 tests pin window integrity (incl. the 3000/3000
  contamination fact), the harness contract on both windows, all four
  verdicts with sample sizes, and verdict()'s replication rule on synthetic
  ledgers (None exp_R never beats, tie never beats).

- 2026-09-04 b68 round 10 — COMBINATION (REVERSED pairing): day-extension
  continuation geometry x same-day PD-break direction oracle
  (scripts/b68k_pdh_dayext_lab.py + b68k_confirm_pdh_dayext.py; b72 playbook,
  4th pairing; the mirror of round 9 — same two ingredients, roles flipped:
  dayext_cont_a10 supplies the geometry unchanged, the last close-confirmed
  break of the previous day's extreme WITHIN today is the oracle). REJECTED
  as replacement: cached ladder_ts 0.369 (n=222) vs funnel 0.854, fresh 0.371
  (n=461) vs funnel 0.590 on the SAME bars. But the round produces three real
  findings. (1) SELECTION IS SYMMETRIC: the gate lifts its control in BOTH
  directions of the pairing (round 9: 0.627->0.924; round 10: 0.327->0.369
  cached, 0.316->0.371 fresh) and in both directions the cut it drops is the
  WORST arm (round 9 complement 0.398/0.467; round 10 disagree 0.151/0.108 —
  a day that extended one way while the last level break went the other is
  the weakest continuation in the family). Dayext<->PD-level agreement is a
  genuine property of gold M15, not a subset fluke of one pairing. (2) THE
  LIFT DEPENDS ON WHICH MEMBER CARRIES THE STOP: forward pairing lifted
  +0.30R, reversed +0.04R — the stretch probe measures the cost: reversed
  agree entries sit 4.01 ATR from the broken level (median 2.92; the
  extension trigger prints HOURS after the break, so the entry chases),
  forward entries sat 0.56 ATR (the break IS the trigger). -> new todo b75
  (geometry-freshness rule). (3) LANE #7 NEGATIVE: funnel-first + gated
  dayext on free bars, fresh: n 531 vs 323, tot_R 250.2 vs 190.6 (+31%) but
  exp_R 0.471 < 0.590 and dd_R -12.6 vs -5.0 — a quality lift that survives
  gating cannot beat slot crowding when the arm still fires 1.4x the funnel's
  frequency (round 6's rule holds for gated variants too). b70 decision set
  unchanged: gated-pdh(dayext) and raw nr7 remain the only positive lanes.
  Nothing wired live. 19 tests (tests/test_b68k_pdh_dayext_lab.py) pin the
  pure-intersection contract, the EXACT-PARTITION property of the three cuts
  (agree XOR disagree XOR notyet over the dayext set — new probe shape this
  round), the no-lookahead oracle with its broken-level carriage, the
  round-6 control reproduction (0.327 n=407), both-sets selection ordering,
  and the shipped fresh verdicts (merit bar fails both sets; lane negative
  on R and DD; stretch > 2 ATR chase tax). 603 green.

- 2026-09-04 b68 round 9 — COMBINATION: PDH breakout x day-extension agreement
  (scripts/b68j_dayext_pdh_lab.py + b68j_confirm_dayext_pdh.py; b72 playbook,
  3rd pairing; b73's recommended type — a LEVEL ingredient gated on a PATH
  ingredient, the pairing whose gate LIFTED its control in round 7). THE
  FIRST ARM IN THE LOOP'S HISTORY TO PASS THE MERIT BAR: cached ladder_ts
  0.924R n=23 vs funnel 0.854, fresh 0.891R n=39 vs funnel 0.590 measured on
  the SAME fresh bars (e25 variant 1.105/0.947 at n=19/33; the 1.5-ATR arm
  is the honest one — e25 is the same arm tuned on the probe). The gate
  fires on ~37% of pdh signals (23/62 cached, 39/106 fresh) — a real subset,
  not a rounding error. SELECTION PROVEN REAL by a new probe, the COMPLEMENT
  arm (what the gate DROPS): 0.398 cached / 0.467 fresh — below the
  0.627/0.609 control, so the gate removes the WORST pdh trades; a lucky
  subset would have left the complement at-or-above control. STRETCH PROBE
  (b73): gated entries 0.564 ATR from the broken level vs control 0.558 —
  the lift is INFORMATIONAL, not geometric; round 8's failure mode absent.
  ADDITIVE LANE on the same fresh bars: FIRST lane to beat the funnel on ALL
  THREE axes — exp_R 0.634 > 0.590, tot_R 212.4 > 190.6, dd -4.1 BETTER than
  -5.0, n 335 > 323 (funnel-first priority; the lane's 12 combo trades carry
  the delta). WHY it works where rounds 7/8 failed: day-extension is a
  same-day PATH oracle (the day has already committed >=1.5 ATR in the
  breakout direction) — it confirms the level break is a continuation of
  committed flow, not a first-push exhaustion; NR7-squeeze (round 8) is a
  PAST-compression state whose information is spent by breakout time. NOT
  WIRED (hard rule + merit bar wording): n=39 is 12% of the funnel's fresh
  sample and it is ONE fresh set; promotion requires b74 replication
  (>=2 more independent windows, live gate stack, kill-switch streak math,
  b70 slot model) before any proposal, and the decision stays human. Feeds
  b70 as lane #6 (now the top of the decision set). 21 tests
  (tests/test_b68j_dayext_pdh_lab.py), 584 green.

- 2026-09-04 b68 round 7 — COMBINATION: NR7 squeeze x day-extension agreement
  (scripts/b68h_combo_lab.py + b68h_confirm_combo.py, FIRST round measured
  end-to-end on the b71 harness — plain/ladder/ladder_ts + hold columns on
  every row, zero honesty complaints on both sets). The round-6 note asked for
  option (a): two rejected families gated on each other. The combo is a PURE
  INTERSECTION — nr7_break wide supplies the geometry unchanged, dayext
  continuation (>=1.5 ATR from the trading-day open after 13:00 UTC) is used
  ONLY as a direction oracle, so no new stop geometry can sneak in. The gate
  is real, not vacuous: of 560 nr7 signals the dayext gate fires on 34-40%,
  and agree/disagree split ~50/50 (109 vs 113 at ext=1.5) — the two arms are
  genuinely independent conditions. RESULT: the gate LIFTS its own control on
  both sets — cached ladder_ts 0.598 -> 0.622 (n 218 -> 68), fresh 0.519 ->
  0.587 (n 453 -> 135) — the combination direction is REAL. But it still loses
  the merit bar on both sides: cached 0.622 vs funnel 0.854, fresh 0.587 vs
  funnel 0.590 on the SAME 6000 bars. ADDITIVE LANE (funnel-first, combo on
  free bars, fresh): n 350 vs 322, tot_R 202.6 vs 189.8 (+6.8%) but exp_R
  0.579 < 0.590 and dd_R -6.9 vs -5.0 — unlike raw nr7 (the strongest lane,
  0.620 fresh) the GATED variant does NOT earn a slot: cutting frequency 3x
  bought +0.068R per trade but the lane's marginal trades still sit below the
  funnel's average, and DD got worse. FINDING FOR b70: lane quality tracks
  how much marginal volume the arm brings, not its standalone exp_R — the
  gated arm is the cleanest counter-example yet. Nothing wired live.
  tests/test_b68h_combo_lab.py (11 tests) pins the pure-intersection contract,
  the anti-vacuity probe, the round-5 control reproduction, the rebind of all
  three module datasets, and the shipped fresh-set verdict numbers.

- 2026-09-04 b68 round 8 — COMBINATION: PDH breakout x NR7 squeeze direction
  (scripts/b68i_squeeze_pdh_lab.py + b68i_confirm_squeeze_pdh.py, second round
  on the b71 harness + b72 playbook). The other pairing the round-7 note
  implied: round 4's ingredient (pdh_break_w10, the lane reference) gated on
  round 5's ingredient (NR7 squeeze, used ONLY as a direction oracle — the
  most recent NR7 bar within 6/8 bars, resolved = a later close beyond its
  range; pdh geometry unchanged). Gate is non-degenerate on both sets (cached:
  74 pdh signals, gate resolves 54%, agree/disagree 25/15; fresh: 151 signals,
  55%, 45/38). RESULT: the gate LOWERS its own control — cached ladder 0.627
  -> 0.406 (n 54 -> 21), the opposite of round 7 where the dayext gate lifted
  nr7 (0.598 -> 0.622). Fresh ladder_ts 0.603 (n=40) nominally beats funnel
  0.590 but n=40 is noise and the cached bar fails 2.1x -> dead as a
  replacement on both sets. ADDITIVE LANE (funnel-first, gated pdh on free
  bars, fresh): n 326 vs 322, tot_R 189.0 vs 189.8, exp_R 0.580 < 0.590 —
  gating cut pdh's fresh frequency 110 -> 40 yet the lane still adds nothing,
  and it is WORSE than the ungated pdh lane on the same bars (0.576 with
  tot_R 206.1 — more volume, more total R). WHY: the confirm's stretch probe
  shows gated entries sit FURTHER from the broken level (mean 0.667 vs 0.558
  ATR at entry): a squeeze that already resolved upward pushes price past PDH
  late and stretched, so the entry pays for the confirmation twice — the
  classic breakout-chase tax. FINDING (new todo b73): the two combination
  rounds split cleanly by WHICH ingredient gates — a day-path gate lifted its
  control, a compression gate lowered it; the compression family's information
  is already spent by the time a level break confirms. Nothing wired live.
  tests/test_b68i_squeeze_pdh_lab.py (17 tests) pins the pure-intersection
  contract, the oracle's no-lookahead window (synthetic squeeze resolution),
  anti-vacuity on both shipped probes, the round-4 control reproduction, the
  rebind+LEVELS rebuild across all four module datasets, and the shipped
  fresh-set verdict numbers (gate lowers control; lane adds nothing).

- 2026-09-03 b68 round 6 — TRADING-DAY EXTENSION continuation
  (scripts/b68g_probe.py screen + b68g_dayext_lab.py + b68g_confirm_dayext.py,
  live-parity funnel, 0.20$ spread, b60 ladder). New family: PATH SHAPE of the
  trading day (how far price has moved from the day's open), not a level and
  not an indicator. The probe screened 10 conditions by raw ATR-normalised
  forward drift and the result was one-sided: |close - day_open| >= 2.5 ATR
  after 13:00 UTC CONTINUES (+0.400 ATR at 8 bars t=4.9, +0.945 ATR at 24 bars
  t=7.4, n=918) while fading it LOSES — the strongest raw drift the loop has
  ever measured. THE FINDING IS THAT THE DRIFT DID NOT CONVERT: cached 3000
  M15 ladder dayext_cont_a10 +0.327R (n=407), _e25 +0.361R (n=328) vs funnel
  +0.854R; fresh 6000 M15 +0.312R (n=800) / +0.345R (n=672) vs funnel +0.585R
  on the SAME bars -> REJECTED as replacement (loses both sets, by 2x). The
  ADDITIVE-LANE probe is NEGATIVE too — lane n 747, exp_R 0.410 vs funnel
  0.585, dd_R 17.6 vs 5.0: the arm fires on 800 bars (2.5x the funnel's 323),
  so a funnel-first lane lets it squat in the single slot through real funnel
  setups and the mix degrades. It is the WEAKEST of the three lanes measured
  (pdh 0.559, nr7 0.620, dayext 0.410) despite the strongest raw drift.
  METHOD RULE (reusable, added as todo b71): a high raw-drift t-stat is NOT
  evidence of tradeable edge — P3/P4's samples overlap (2310 and 918 of 2940
  bars, most of them consecutive), so serial correlation inflates t; only the
  de-overlapped trade-level R (one position at a time) is honest, and here it
  says the drift is eaten by the stop. CONTROL arm: fading the extension
  (dayext_fade_a10) scored -0.136R plain / +0.150R ladder (n=321) — mean
  reversion on the day-shape family is dead on gold M15, matching vwap/bb/rsi.
  GEOMETRY TRAP caught in this round's own control (b69 class): a fade arm
  with a LEVEL-anchored stop puts the stop on the wrong side of the entry
  (risk <= 0) and silently drops every signal -> trades:0 that reads as "no
  edge" when nothing was measured; pinned by
  tests/test_b68g_dayext_lab.py::TestDeadArmTrap. SECOND geometry trap: the
  level-anchored CONTINUATION arm (dayext_cont_w10, stop at day_open +/- 1 ATR)
  printed +1.096R — its mean stop is 5.66 ATR from entry (max 11.2) and its
  mean hold is 87 bars (max 520), i.e. it is a swing position, not an intraday
  trade, and its R is not comparable to the funnel's ~1 ATR risk. Under the
  LIVE 36h time_exit (time_stop_bars=144) it collapses to +0.787R (n=41,
  net_R 32.9 -> 32.3, dd -1.0 -> -3.0). RULE: any lab arm whose mean hold
  exceeds the live time-exit must be re-measured with time_stop_bars=144
  before its exp_R is quoted. Nothing wired live.

- 2026-09-03 b68 round 5 — NR7 volatility-compression breakout
  (scripts/b68f_nr7_lab.py + b68f_confirm_nr7.py, live-parity funnel, 0.20$
  spread, b60 ladder): the compression->expansion family, finally MEASURED —
  b63's compression arm was mathematically dead (b69, done this run: the
  12-bar range/ATR(50) ratio on gold M15 has MIN 0.671 and p05 1.83, so the
  "<=0.9*ATR" gate fired 1/2940 bars and the full combo 0/2940). The healed
  definition is Carter's NR7 (narrowest plain range of the last 7 bars, 506
  occurrences on cached): enter next-bar open on a CLOSE-CONFIRMED break of
  the squeeze range within 6 bars. Cached 3000 M15 ladder: nr7_break_c
  +0.584R (n=326), nr7_break_w10 +0.598R (n=218) vs funnel +0.854R — the
  best cached numbers of any standalone arm since the loop began. Fresh
  6000 M15: +0.460R (n=708) / +0.517R (n=455) vs funnel +0.586R (n=323) on
  the SAME bars -> REJECTED as replacement (loses both sets, per the merit
  bar). But the ADDITIVE-LANE probe (funnel-first, arm on free bars, one
  position at a time) is the strongest yet: lane n 499, tot_R 309.5 vs
  funnel 189.2 (+64% total R), lane exp_R 0.620 vs funnel 0.586 — the FIRST
  lane whose per-trade expectancy is ABOVE the funnel's (pdh's lane diluted
  -0.017R; nr7's lane ADDS +0.034R while adding 176 more trades), dd 6.3
  vs 5.0. Two independent positive lanes (pdh, nr7) now queue at b70; the
  capacity analysis must compare both plus a stacked lane on >=2 fresh
  fetches. Nothing wired live.
  PATTERN UPDATE: nr7_break_c's fresh n=708 (2.2x the funnel) with exp_R
  still 0.46 says the squeeze-break signal is COMMON and mildly positive on
  its own, and nr7_break_w10 is the second arm (after pdh_break_w10) whose
  cached-to-fresh move beats the funnel's own decay (0.598->0.517, -14%,
  vs the funnel's 0.854->0.586, -31%) — consistent with the funnel's cached
  0.854 bar being partly dataset drift rather than pure edge. CAUTION for
  b70: in the lane model an open arm position BLOCKS any funnel signal that
  arrives mid-trade (the engine is one-position-at-a-time), so lane exp_R
  0.620 is not automatically "the funnel's trades + free extra R" — the
  blocking cost is exactly what b70's gate analysis must measure.
- b66/b66b EXIT-GRID ROUND 2 (2026-09-03, REJECTED-NO-CHANGE, incumbent kept):
  2D grid TP1-step x partial-share on the winning trail=.30. TP1: .60 wins M5
  (+2.1R) but .45 wins M15 (+7.0R) — contradictory, incumbent .50 sits between
  and loses <3% on either; not worth the churn. SHARE: b66 had a bug (flat
  share ignored because grade-fn overrides it) — b66b tested it correctly:
  live grade-based share 184.3R M5 / 211.5R M15 vs flat 30/50/70% all far
  worse (91-168R). Grade-weighted partial sizing CONFIRMED as real edge.
  Exit geometry now declared locally optimal; next lever = fresh live sample.

- b65/b65b/b65c EXIT-GEOMETRY SWEEP (2026-09-03, INTEGRATED): swept 12 exit
  arms on the live funnel, same entries. TP-shape arms (no-partial, TP1=0.75,
  earlier BE, time-stop) all lost on total R. ONE arm won in every
  independent slice: runner trail 0.45R -> 0.30R. Evidence: M5 6000 bars
  +189.1 vs +178.5R total; M15 6000 bars +209.4 vs +187.3R; M5 older half
  +97.0 vs +93.8; M5 recent half +91.0 vs +84.1. Integrated in
  engines/trade_management.py _trail_params balanced_trail 0.45->0.30
  (strong-runner 0.6 lane untouched, never fired live). 507 tests green,
  position watchdog restarted. TP1=0.75 had the best mean/trade (+0.70R)
  but harvested FEWER total R (fewer trades) — rejected on dollar-weight.
- 2026-09-03 b68 round 4 — PREVIOUS-TRADING-DAY high/low close-confirmed breakout
  (scripts/b68e_pdh_lab.py + b68e_confirm_pdh.py, live-parity funnel, 0.20$ spread,
  b60 ladder): the FIRST arm in the loop that beats the funnel on fresh data, and it
  still fails the merit bar. Candidate picked by a raw-drift probe on the cached set:
  of 141 touches of the prior day's extreme, a bar that CLOSES BACK INSIDE (a sweep)
  drifts only +0.38 ATR against the break (t=0.8, noise), while a bar that CLOSES
  THROUGH it drifts +1.00 ATR WITH the break over 24 bars (n=72, t=+2.1) — the
  strongest raw predictive split this loop has produced, and the reason the arm
  requires close confirmation instead of a wick. Trading-day boundary is 01:00-23:45
  UTC (the data's own daily break; grouping by broker CALENDAR date splices two
  sessions and invents a level no desk would draw). Cached 3000 M15 ladder:
  pdh_break_t50 +0.493R (n=67), pdh_break_w10 +0.627R (n=54) vs funnel +0.854R.
  Fresh 6000 M15: t50 +0.484R (n=136) vs funnel +0.576R, but **w10 +0.640R (n=108)
  vs funnel +0.576R on the SAME bars** — the arm wins fresh and loses cached, so per
  the both-sets rule it is REJECTED as a funnel REPLACEMENT. Stop width is the whole
  story: 0.5 ATR (textbook tight) gets wicked out (plain 0.193R), 1.0 ATR survives
  the ladder (0.627/0.640) — the same "the ladder rescues, the entry doesn't" pattern
  in reverse: here the ladder rescues a WIDE stop, not an arm.
  ADDITIVE-LANE PROBE (new this round, not a merit-bar test): funnel-first, arm only
  on bars the funnel leaves empty → n 354 (vs 319), tot_R 197.9 (vs 183.6, +7.8%),
  exp_R 0.559 (vs 0.576, -0.017R dilution), dd_R 7.0 (vs 5.0). Under the real
  one-position-at-a-time model the arm is COMPLEMENTARY, not a replacement: it adds
  ~35 trades and ~14R per 6000 bars at a small per-trade dilution and a worse DD.
  That is a CAPACITY decision, not an expectancy one, and it needs its own gate
  analysis before anything touches live → new todo b70.
- 2026-09-03 b68 round 3 — HTF trend + pullback-depth entry (scripts/b68_htf_lab.py
  + b68d_confirm_htf.py, live-parity funnel, 0.20$ spread, b60 ladder): the first arm
  from the funnel's OWN entry class — H1 swing-pivot trend (HH leg up / LL leg down,
  pivots confirmed k=2, only bars CLOSED before the signal — no lookahead), enter next
  M15 open in trend direction only after price retraced into discount (close below
  50% or 61.8% of the last H1 impulse leg) on a bullish rejection bar (mirror for
  premium/SELL), SL 0.25 ATR beyond the leg extreme, TP 2R. Cached 3000 M15 ladder:
  htf_pull_50 +0.271R (n=74), htf_pull_618 +0.194R (n=68) vs funnel +0.854R. Fresh
  6000 M15: +0.317R (n=142) / +0.346R (n=135) vs funnel +0.577R (n=319) on the SAME
  data, and DD is 2x worse (10.7R vs 5.0R). REJECTED — loses on both sets. The deeper
  61.8% filter does NOT beat the shallow 50% filter (opposite of the ICT textbook
  claim on this data: more filtering just thins to the same weak expectancy).
  STRONGEST evidence yet for the loop's core pattern: a single correct-class entry
  condition (HTF trend + discount) is nowhere near the funnel, whose edge is the
  STACK of context conditions (regime, SMC merge, range-kill, grade, blueprint
  geometry) — standalone arms land in the 0.27-0.44 fresh band regardless of family
  (mean-reversion, momentum, now trend-pullback). The funnel stays.
- 2026-09-03 b68 round 2 — ATR-expansion continuation (scripts/b68_expand_lab.py
  + b68c_confirm_expand.py, live-parity funnel, 0.20$ spread, b60 ladder): enter
  next-bar open in the direction of a FRESH expansion bar (TR > 1.8 x ATR14, close
  in the extreme quarter of its range, prior bar not itself an expansion), SL 0.25
  ATR beyond the signal bar, TP 2R. Cached 3000 M15: all-sessions plain -0.191R
  (n=61), ladder +0.362R (n=104); London/NY-only ladder +0.344R (n=69). Fresh 6000
  M15: all +0.443R (n=202), L/NY +0.432R (n=134) vs funnel +0.577R (n=319) on the
  SAME data. REJECTED — loses on both sets and both session filters; the session
  restriction cuts DD (9.5R→6.1R) but not enough. Pattern confirmed a 2nd time:
  the ladder turns a losing momentum arm positive (payoff 1.9) yet never nears the
  funnel — entry filtering, not exit geometry, is where the funnel's edge lives.
- 2026-09-03 b68 round 1 — session-anchored VWAP band fade (scripts/b68_vwap_lab.py
  + b68b_confirm_vwap.py, live-parity funnel, 0.20$ spread, b60 ladder): fade a
  2-sd stretch off the UTC-day-anchored VWAP on a rejection bar. Cached 3000 M15:
  plain -0.259R (n=86), ladder +0.380R (n=118). Fresh 6000 M15: +0.436R (n=223)
  vs funnel +0.576R on the SAME data (and vs the 0.854 backlog bar). REJECTED —
  loses on both sets; the ladder rescues mean-reversion arms into positive but not
  into contention. Also healed: HEAD 587b181 shipped b63b_confirm_top_smc.py
  WITHOUT load_dotenv (b65 tripwire RED on a clean checkout) — fixed same commit.
- 2026-08-30 neutral_bias gate audit (scripts/measure_neutral_forgone.py, 5883
  replay bars): the 3163 neutral bars look like +8183$ forgone (60.3% WR), but
  the NON-neutral baseline is +3.47$/bar at 59.3% WR — the raw number is
  dataset drift, not edge. Neutral bars are 0.49$/bar WORSE than bars the
  system trades. Gate is earning its keep; unchanged. (1326 of the neutrals
  are forced by range-kill.)
- 2026-08-30 b15 verified LIVE: 08:00 cron tick stamped _last_master_run but
  did NOT re-arm cooldown (until stayed 07:50). First time in this system's
  life that a new entry is not auto-killed at tick start.
- 2026-08-30 grade-gate efficacy audit (scripts/measure_grade_edge.py, 348 trades
  across 13 M5 windows, min_grade=None so C setups traded too): grade DOES rank
  quality — A 55.2% WR/$3.54 avg, B 52.9%/$4.33, C 45.9%/$1.32. C is still net
  +239$ but earns 1/3 of B per trade AND occupies the single position slot,
  blocking later B setups. MIN_SETUP_GRADE=B stays. (answers 'funnel too tight':
  this gate earns its keep; the loose ones were the parity bugs, already fixed)

- 2026-09-03 b62 strategy lab (scripts/b62_strategy_lab.py, 8 classic intraday
  methods x 3000 cached M15 bars, live engine, 0.20$ spread): the user's standing
  demand was "find the best strategies, test them, put them in the structure".
  Tested: asia range breakout, NY ORB, EMA20/50 pullback, RSI(14) reversion,
  Bollinger bounce, Donchian-20 breakout, liquidity-sweep reversal, FVG retest.
  BEST classic arm = asia_break +0.18R/trade (n=13, too thin to trust);
  everything else is at or below zero. The CURRENT funnel (b61 best arm) is
  +0.854R/trade n=172 — 4.7x the best classic. Adding the ladder exit to the
  classic arms did not rescue them (same numbers; exit geometry is not the
  bottleneck, entry quality is). DECISION: none of the classic methods earns a
  place in the live structure; the funnel stays. Loop continues via todo b68.

- 2026-08-30 ICT concepts edge audit (scripts/measure_ict_edge.py, 1274 real M5
  samples, forward 1h move vs baseline): NONE of the 8 unused concepts has a
  usable directional edge (all |t| below 2.3). silver_bullet window shows a
  NEGATIVE -0.41 ATR drift (|t|=2.2, n=166 — thin, not actionable alone).
  DECISION: keep them report-only; do NOT wire into the funnel. Found and
  fixed a dead detector on the way: compute_session_liquidity swept_high/low
  were mathematically always False (range included its own sweepers) — fixed
  plus 2 regression tests (76 green).

## Done
- [x] 2026-09-08 b136 TRADER CODE REVIEW — ACCOUNT-HEALTH POLICY WAS EMITTING A
      REGIME THE SIZING PATH IGNORED (fresh review round; top todos were [META]
      or human-gated): engines/risk.assess_account_policy can emit four regimes
      with a risk_multiplier, but the live entry path never reads that field —
      sizing gates off the literal sets STOP/TIGHT_REGIMES in auto_executor
      alone, and "recovery" (drawdown >= 2.5%) was in NEITHER: at the deepest
      account stress the bot sized entries at FULL 2% risk, LARGER than
      "defensive" (0.5x). Fix = add "recovery" to TIGHT_REGIMES (strict
      tightening, matches the policy's own 0.5 multiplier; normal path
      bit-identical). Proof: scripts/b136_regime_wiring_census.py walks the real
      202-cycle deal history (regimes fired: normal 170, defensive 32 — recovery
      never yet fired, so this was a loaded gun, not an active loss) and
      DISCOVERS the emittable set from the policy function, then runs the real
      evaluate_proposal per regime; verdict flipped
      UNWIRED_REGIME_PRESENT:recovery -> ALL_EMITTABLE_REGIMES_WIRED. 6 new
      tests (tests/test_b136_regime_wiring.py) pin wiring+ordering, red on the
      old code (3 failures), green after. Filed b137 (the reusable wiring-census
      procedure).
- [x] 2026-09-06 b105 TRADER CODE REVIEW — trade_management.py vs LIVE JOURNAL:
      ladder branches walked against the journal + watchdog log; FOUND A CORE
      BACKTEST PARITY DEFECT — engines/backtest.py booked the post-TP1 runner at
      FULL size on top of the realized partial, and a share>=1.0 TP1 close (the
      live balanced/weak lane) left a phantom runner that also blocked real
      entries. Fixed (runner scaled by 1-share; share>=1.0 closes at TP1, frees
      slot); funnel exp_R on cached M15 0.766 -> 0.285 (live journal realizes
      0.10R — corrected engine is much closer); 9 new tests, 1069 green, live
      cycle OK. Consequence filed as b108 (re-measure merit bar + b70 set).
- [x] 2026-09-06 b96 B50 LEAK TEST MADE CONCURRENCY-SAFE (owner-attributed
      count): tests/test_b50_suite_is_location_independent.py's
      test_worktree_is_cleaned_up_after_verification asserted
      `len(git worktree list) == 1` — a claim about SHARED repo state that
      any legitimate concurrent verifier invalidates (b91's contract KEEPS a
      live-owner worktree; the 2026-09-06 b94 run went RED on a healthy repo
      when a background suite overlapped a verify_head.sh). New shape:
      _unowned_leftovers() lists worktrees through head_verify's own parser
      and spares (a) this checkout, (b) the MAIN worktree derived from git's
      own `rev-parse --git-common-dir` answer — never from the author's cwd,
      because inside a nested verification REPO is not the main tree (b94
      rule), and (c) any prefixed leftover whose owner.pid is ALIVE
      (owner_state, the exact tool b91 built for the sweep). Dead/unknown
      owners still count, so the b91 incident shape stays detected; the test
      re-confirms after 2s before going RED, closing the opposite race (a
      verifier registering mid-check). 4 new tests (LeakTestIsConcurrencySafe)
      pin BOTH directions with b91's real-worktree fixture builders — alive
      owner spared while the OLD assertion provably fails on the same state
      (anti-vacuity assert inside the test), dead owner counted, unknown
      owner counted, main tree never a leftover — 993 green, live cycle OK
      (no_trade). Reusable rule filed as todo b98.
- [x] 2026-09-06 b95 CROSS-MODULE PROBE RESOLUTION IN THE b94 TRIPWIRE:
      scan() now seeds the probes set from imports — (1) any imported name
      matching the probe-shape vocabulary (detach/bare/gitdir/commondir/
      worktree/checkout; ALL-CAPS constants spared), (2) names resolved
      against the SIBLING test module's own traced set through an injectable
      loader (recursive, cycle-guarded), covering plain, `as`-aliased, and
      star imports, plus `import test_X as m; m.probe()` via the sibling's
      traced names. The repo-wide sweep was refactored to a shared
      sweep_offenders(files) over in-memory (name, src) pairs — b95's
      anti-vacuity probe injects the synthetic offender as a PAIR instead of
      writing a temp file into tests/, removing a race with concurrent suite
      runs (the b96 flake class, avoided pre-emptively). 10 new tests
      (catch: imported/aliased/star/module-object/probe-shaped-without-source;
      spare: MockBridge-style legit imports, ALL-CAPS constants; cycle
      termination; real b91 sibling resolves _checkout_is_detached; end-to-end
      sweep catches the offender shape) — 989 green, live cycle OK (no_trade).
- [x] 2026-09-06 b94 LOCATION-DEPENDENT TEST TRIPWIRE: tests/test_b94_
      location_dependent_tripwire.py — an AST scan (not grep: the b91 shape
      hides inside `main = next(w for w in wts ...)` dataflow that grep
      cannot bind) over every tests/*.py that fails any assertion comparing
      a git-CHECKOUT-STATE value (detached/bare/gitdir/commondir keys of a
      parsed worktree listing, or the direct result of a subprocess probe
      asking git symbolic-ref/--git-dir/worktree) to a hardcoded literal or
      bare truthiness — including plain `assert x['detached']`. Probe names
      are traced through assignments and helper-function bodies, so
      `assertFalse(_checkout_is_detached())` is caught as hardcoding the
      answer the probe exists to discover. Derived claims are deliberately
      SPARED (len(listing)==1 in b50's leak test, state-key vs live-probe
      equality = the FIXED shape). Audit result: b50 and b91 are clean
      today (pinned by name so a refactor back into the shape fails loudly),
      and the whole 71-file suite has ZERO other offenders — the b91b fix
      was the last instance. Scan pinned against REAL history: 937e82f's
      copy of the b91 test must produce the exact `assertFalse(main[
      'detached'])` hit (b41 discipline; worktrees share the object store
      so `git show` reads identically from any checkout shape). 6 tests,
      979 green, live cycle OK (no_trade).
- [x] 2026-08-30 Spread/slippage sensitivity: edge is cost-INSENSITIVE — spread is a
      linear per-trade tax (entry/exit geometry unchanged), measured on the 13 cached
      robustness windows via run_backtest(spread_override=...): gross 0.00 → +1112.95,
      0.20 (live) → +1065.64, 0.35 → +1030.19, 0.50 → +994.70; identical 196 trades,
      63.2% WR, 12/13 profitable windows at EVERY level; break-even spread ≈ 2.86
      (16x the 0.18 live demo tick spread). Live assumption (0.20) is conservative.
      Tool: scripts/spread_sensitivity.py; results data/backtest/spread_sensitivity_results.json.
      Also removed dead _exit_price() in engines/backtest.py and locked the symmetric
      one-spread cost model with test_spread_symmetric_buy_and_sell. 73 tests green, live cycle OK.
- [x] 2026-08-30 env_loader fallback everywhere: 5 scripts (_check_bridge,
      autopilot_digest, backtest_sweep, ab_aggressive_entry, verify_chain) imported
      dotenv bare → crashed on this box (python-dotenv absent); backtest_robustness
      hand-parsed only HERMES_BRIDGE_TOKEN. ALL now use the shared
      try-dotenv-except-env_loader pattern. Sweep also caught 2 LIVE DAEMONS
      (position_daemon.py, signal_daemon.py) hand-parsing .env with a weaker parser
      (no quote stripping → quoted tokens passed to bridge verbatim); switched too.
      Locked in by tests/test_env_loader.py::test_every_dotenv_user_has_fallback —
      repo-wide scan that fails if any non-test .py touches .env without the
      fallback. 72 tests green, live cycle OK (reassess, execute=False).
- [x] 2026-08-30 Backtest robustness: parity funnel on 13 NON-OVERLAPPING 500-bar
      windows (separate weeks, May 21→Aug 28, broker history allowed, one cached
      dataset; H1/H4 context time-padded before each window). Variance: PnL mean
      +132.66 sd 118.83 (min −57.84 / max +434.81), WR mean 50.6% sd 12.7
      (26.9→79.2), trades ~26/week sd 3. 12/13 weeks profitable, +1724.61 total
      over 341 trades — edge is broad, not a few lucky weeks; one bad week
      (late May) ≈ 0.5R of a normal week. Tools: scripts/backtest_robustness.py
      (resumable, window-by-window state files), results in
      data/backtest/robustness_results.json. 71 tests green, live cycle OK.
- [x] 2026-08-30 CRITICAL FIX found by the run gate: python-dotenv missing on this
      box → hermes_master's `except ImportError: load_dotenv = lambda: None`
      silently skipped .env → no bridge token → 401 → 'insufficient_market_data'
      on EVERY direct cycle (pre-existing since at least 08-28; one prior
      autopilot even mislabeled it 'weekend, expected'). Cron masked it by
      exporting .env in the wrapper. Fix: engines/env_loader.py fallback
      (dotenv-compatible: no-override, quotes, comments) wired into the 4 core
      entrypoints + tests/test_env_loader.py; gate now passes.
- [x] 2026-08-30 Journal by session+regime: analyze() now emits by_session and
      by_session_regime (asia/london/newyork × trend/range/unknown); session bounds
      parity-tested against hermes_runtime._detect_session; regime joined via
      time-proximity to execution_log (dry-run/failed excluded, 48h lookback) →
      plan_history quality.regime. Finding: all 5 journaled trades pre-date any
      logged successful execution → regime='unknown' (honest, not guessed); exact
      join impossible until execution_log gains a ticket column → new todo added.
      64 tests green, live cycle OK.
- [x] 2026-08-30 A/B aggressive premium/discount entries (parity funnel, 3000 M15 bars
      ~31 days, spread 0.20, one cached dataset for all runs): KEEP — they ADD ~80% of PnL.
      Baseline (live) 156 trades / 57.0% WR / +807.76; PD-aggressive disabled 60 / 56.7% /
      +161.22; all aggressive disabled 40 / 65.0% / +123.24. Per-style: aggressive_premium
      n=81 +448.49, aggressive_discount n=56 +319.56, aggressive_value n=6 +22.80,
      pullback n=13 +16.91. Geometry sane (max win 68.3 / max loss −36.5). Decision:
      live behaviour unchanged. Tools added: exclude_styles prefix filter + style tag in
      backtest_ohlc/run_backtest (53 tests green), scripts/ab_aggressive_entry.py,
      results in data/backtest/ab_aggressive_results.json.
- [x] 2026-08-29 Analysis-chain audit round 2 (context.py math, macro chain, plan funnel):
      ATR→true-range; bias threshold volatility-relative; trend_strength ATR-normalized
      (was saturating every gate: grade always A, vol always high, momentum always 1.0);
      FF calendar currency field fixed (was empty → filter passed everything);
      macro_filter date-key fixed + wired into BOTH entry paths (plan + signal) —
      news blackout was dead in production; removed 7 dead functions;
      backtest now runs the EXACT live funnel (parity by construction, no hand-copied
      gates) → 26 trades / 61% WR / +92.39 USD on 7.4 days of real M15 data. 52 tests green.
