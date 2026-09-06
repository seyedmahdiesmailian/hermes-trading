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

## Active
- [x] b68 STRATEGY LAB CONTINUOUS LOOP (user standing order 2026-09-03: "keep searching strategies/analysis methods, pick the best, test, bring into the real structure"). Each run: (a) pick ONE new candidate method not yet in data/backtest/b62_strategy_lab.json (sources: quant literature, ICT/SMC concepts not yet measured, session/volatility patterns; web search is low-signal — prefer implementing from the concept definition), (b) implement it as a standalone signal_fn in scripts/b62_strategy_lab.py style (indexed() adapter, ATR-based geometry, grade B), (c) run through engines.backtest.backtest_ohlc on the CACHED dataset (data/backtest/ab_aggressive_data.json, 3000 M15 bars) with spread 0.20 AND with the live b60 ladder (partial_share_fn=_partial_close_fraction, tp1_position=0.50, trail_after_partial=0.5), (d) append the row to data/backtest/b62_strategy_lab.json, (e) MERIT BAR: only propose wiring into the live funnel if exp_R beats the current funnel's 0.854R/trade (b61 best arm) on BOTH the cached set and one fresh fetch; otherwise record the rejection in ## Findings with numbers. NEVER weaken existing gates to make a new arm look better; the funnel stays the exit manager. Baseline table so far (exp_R, cached M15): funnel b60 0.854 | asia_break 0.18 | ema_pullback 0.114 | bb_bounce 0.035 | donchian -0.013 | sweep_rev -0.004 | fvg_retest -0.020 | ny_orb -0.098 | rsi_rev -0.226 | vwap_fade 0.380 (ladder; fresh-set 0.436 vs funnel 0.576 — REJECTED 2026-09-03, see Findings). SMC/RTM round (b63/b63b, 2026-09-03): turtle_soup 0.508 cached / 0.469 fresh, eqh_sweep 0.085 / 0.638, ote 0.62 / 0.299, breaker 0.008 / 0.113, ob_first_retest 0.978 (n=3) / 0.483 (n=6), sweep_choch_ob 1.702 (n=2) / 1.066 (n=4) — none beat the funnel on BOTH sets with a usable n; funnel stays. Momentum round (b68r2, 2026-09-03): atr_expand_all 0.362 / fresh 0.443, atr_expand_lny 0.344 / 0.432 — REJECTED, loses on both sets (see Findings). HTF-trend+pullback round (b68r3, 2026-09-03): htf_pull_50 0.271 / fresh 0.317, htf_pull_618 0.194 / fresh 0.346 — REJECTED, loses on both sets (see Findings).
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
- [ ] b95 B94 SCAN BLIND SPOT: CROSS-MODULE PROBES (from b94, 2026-09-06):
      the tripwire traces probe names WITHIN one module only — a test that
      does `from test_b91_stale_worktree import _checkout_is_detached` and
      then `assertFalse(_checkout_is_detached())` slips past, because the
      imported name is not in the local probes set. Cross-test imports are
      real in this repo (b50 already sys.path-inserts tests/ to import
      hermetic). Fix: seed the probes set with any imported name matching
      the probe-shape vocabulary (or resolve `from tests import ...` names
      against the sibling module's own traced set), pinned by a synthetic
      two-module fixture. Small, tests-only.
- [ ] b87 GATE-SHADOWING TEST: MEASURE A FILTER AGAINST THE OTHER FILTERS,
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
- [ ] b70 ADDITIVE-LANE CAPACITY ANALYSIS (follow-up to b68 round 4, 2026-09-03): the
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
- [ ] b82 PARITY TRIPWIRE: THE LAB HARNESS MUST NOT BE ALLOWED TO DRIFT FROM
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
- [ ] b83 COMPOSITE-SIGNAL PARITY RULE: A FIX TO A COMPONENT MUST RE-PRICE ANY
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
- [ ] b85d FIXTURE-COMPLETENESS RULE FOR SUBPROCESS TESTS (reusable procedure
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
- [ ] b79 GATE FIRE-RATE STABILITY PRE-FLIGHT (reusable procedure promised
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
- [ ] b72 COMBINATION-ROUND PLAYBOOK (reusable procedure from b68 round 7, for
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
- [ ] b73 COMBINATION-ROUND SEQUENCING RULE (reusable procedure from b68 rounds
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
- [ ] b75 GEOMETRY-FRESHNESS RULE FOR COMBINATION ROUNDS (reusable procedure
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
- [ ] b76 CONFIRM SETS MUST PROVE INDEPENDENCE (reusable procedure from b68
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
- [ ] b77 CHRONOLOGICAL-DECAY TEST BEFORE SPENDING A DRAW (reusable procedure
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
- [ ] b74 CANDIDATE PROMOTION PROTOCOL (reusable procedure from b68 round 9,
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
