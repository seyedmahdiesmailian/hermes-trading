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
- [ ] b68 STRATEGY LAB CONTINUOUS LOOP (user standing order 2026-09-03: "keep searching strategies/analysis methods, pick the best, test, bring into the real structure"). Each run: (a) pick ONE new candidate method not yet in data/backtest/b62_strategy_lab.json (sources: quant literature, ICT/SMC concepts not yet measured, session/volatility patterns; web search is low-signal — prefer implementing from the concept definition), (b) implement it as a standalone signal_fn in scripts/b62_strategy_lab.py style (indexed() adapter, ATR-based geometry, grade B), (c) run through engines.backtest.backtest_ohlc on the CACHED dataset (data/backtest/ab_aggressive_data.json, 3000 M15 bars) with spread 0.20 AND with the live b60 ladder (partial_share_fn=_partial_close_fraction, tp1_position=0.50, trail_after_partial=0.5), (d) append the row to data/backtest/b62_strategy_lab.json, (e) MERIT BAR: only propose wiring into the live funnel if exp_R beats the current funnel's 0.854R/trade (b61 best arm) on BOTH the cached set and one fresh fetch; otherwise record the rejection in ## Findings with numbers. NEVER weaken existing gates to make a new arm look better; the funnel stays the exit manager. Baseline table so far (exp_R, cached M15): funnel b60 0.854 | asia_break 0.18 | ema_pullback 0.114 | bb_bounce 0.035 | donchian -0.013 | sweep_rev -0.004 | fvg_retest -0.020 | ny_orb -0.098 | rsi_rev -0.226 | vwap_fade 0.380 (ladder; fresh-set 0.436 vs funnel 0.576 — REJECTED 2026-09-03, see Findings). SMC/RTM round (b63/b63b, 2026-09-03): turtle_soup 0.508 cached / 0.469 fresh, eqh_sweep 0.085 / 0.638, ote 0.62 / 0.299, breaker 0.008 / 0.113, ob_first_retest 0.978 (n=3) / 0.483 (n=6), sweep_choch_ob 1.702 (n=2) / 1.066 (n=4) — none beat the funnel on BOTH sets with a usable n; funnel stays. Momentum round (b68r2, 2026-09-03): atr_expand_all 0.362 / fresh 0.443, atr_expand_lny 0.344 / 0.432 — REJECTED, loses on both sets (see Findings). HTF-trend+pullback round (b68r3, 2026-09-03): htf_pull_50 0.271 / fresh 0.317, htf_pull_618 0.194 / fresh 0.346 — REJECTED, loses on both sets (see Findings).
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
