# Modern SMC / ICT Research — XAUUSD Intraday (2025–2026 State of the Art)

**Prepared for:** Hermes automated XAUUSD trading system (MT5 bridge, Linux)
**Date:** 2026-10-06
**Scope:** Methods *beyond* the already-implemented ICT 2021 baseline (OB / FVG / liquidity grab / killzones in `engines/smc.py`).
**Posture:** Skeptical. The brief states that RSI(2) mean-reversion, EMA trend-following, liquidity sweeps, HTF alignment filters and D1 bias filters have already been A/B tested on real data and **all failed**. This document treats that as the prior.

---

## 0. TL;DR — the three sentences that matter

1. **The dominant reason retail SMC "works" in backtests is look-ahead bias in pattern timestamping, not edge.** A working paper that held everything fixed and varied *only* the bar at which an order-block signal is timestamped found the retroactive convention adds a median **+0.98 R per trade and +37.2 percentage points of win rate**; the causal version of the same rule wins 33.7–38.4% at a 2R target against a 33.3% no-edge baseline. [Quark Quantitative Research, Andreev & Howden](https://quarkresearch.cc/papers/paper_lookahead_fake_edge.pdf)
2. **The only mechanism in the entire SMC/ICT stack with genuine, independent, peer-reviewed support is stop-order clustering at round numbers** — and it is not ICT's discovery. [Osler, NY Fed Staff Report 125 (2001)](https://www.newyorkfed.org/research/staff_reports/sr125.html) and [SR 150 (2002)](https://www.newyorkfed.org/research/staff_reports/sr150.html) measured real order data: stop-losses cluster *just past* round numbers while take-profits sit *on* them, and stop-loss cascades measurably amplify price moves.
3. **Everything ICT added on top of that mechanism — FVG entry, displacement confirmation, order-block retest — appears to actively destroy the edge** by adding lag and look-ahead. A mechanical four-stage benchmark found the pure ICT variant (sweep + FVG) returned **−1.00 R at 32.26% win rate**, while the older Wyckoff sweep+volume variant (+20.00 R, 40.0%) and the Al Brooks failed-breakout variant (+21.00 R, 48.89%) were profitable. [The Quant Scientist](https://thequantscientist.com/blog/the-marketing-of-liquidity-sweeps-how-data-science-proves-ict-broke-a-100-year-old-edge)

**Ranked recommendation (full specs in §5):**
| # | Method | Core mechanism | Data needed | Confidence |
|---|--------|----------------|-------------|------------|
| 1 | **Round-Number Liquidity Sweep Reversion** (Osler-anchored Turtle Soup) | Stop-cluster just past big-figure grid line → overshoot → revert | OHLC only (**have it**) | **Medium-High** |
| 2 | **Volume-Confirmed Wyckoff Spring / Upthrust** | Sweep + *volume* confirmation + close-back-inside, no FVG | OHLC + tick_volume (**have it**) | **Medium** |
| 3 | **London Judas-Swing Fade / New York Breakout Continuation** | 47.4% of London sessions sweep *both* OR sides | OHLC + session clock (**have it**) | **Medium** |

All three are the **same underlying mechanism** (failed breakout at a stop cluster) validated from three independent directions: central-bank order-flow data, a mechanical multi-era backtest, and 16 years of gold session statistics. That convergence is the strongest argument in this document.

---

## 1. The finding that should change how you backtest anything

### 1.1 The look-ahead plague in price-structure backtests

**Source:** [Andreev & Howden, "A Look-Ahead Convention in Intraday Price-Structure Backtests", Quark Quantitative Research](https://quarkresearch.cc/papers/paper_lookahead_fake_edge.pdf)

An order block is *defined* as the last opposing candle before a displacement move. Therefore **no candle can be classified as an order block until the displacement has already completed.** Chart annotations drawn after the fact stamp the entry on the order-block candle instead of the displacement bar.

Results, holding instrument, geometry, costs, sizing and exits fixed and varying **only the timestamp bar**:

| Convention | Win rate (2R target) | Mean R net of costs | Day-clustered t |
|---|---|---|---|
| Retroactive (as usually quoted) | **78.4%** | **+1.158** | 108.4 |
| Causal (prefix-replay, honest) | **37.8%** | **+0.021** | 1.87 |

Across 13 cost-tier × bar-interval cells (US equities + 2 crypto pairs, 2016–2022): causal win rates all fall in **33.7%–38.4%**, versus **33.3%** for a 2R target with *no edge at all*. Their verdict: "the manufactured effect is larger than any genuine effect measured elsewhere in the" study.

**Credibility tier: B (unpublished working paper, but the mechanism is mechanically airtight and trivially reproducible).** We do not need to trust their numbers — we can verify it on our own data in an afternoon by re-running any existing SMC signal with a strict prefix replay.

> **Action for Hermes:** every backtest in `engines/backtest.py` must be re-verified with a **prefix-replay harness** — re-derive each signal from truncated bar history only, with no detector-controlled bookkeeping. Any signal whose win rate is materially (>5pp) higher in the current harness than in prefix replay is look-ahead contaminated and cannot be trusted. **This is likely the single highest-leverage thing to do before implementing any new method.** It is plausible that the existing +248 USD / 54% win-rate result is partly manufactured this way; 54% at a 2R target with real spreads is a suspiciously good number given the paper's 33.7–38.4% causal band.

### 1.2 The multi-era mechanical benchmark

**Source:** [The Quant Scientist, "ICT vs. Price Action: Is Liquidity Sweep Trading a Data-Backed Edge?"](https://thequantscientist.com/blog/the-marketing-of-liquidity-sweeps-how-data-science-proves-ict-broke-a-100-year-old-edge) (published June 2026)

They benchmarked the *same* trap phenomenon across its three historical formulations:

| Stage | Model | Trades | Win rate | Net return |
|---|---|---|---|---|
| 1 | Raw breakout trap | 183 | 34.97% | +9.00 R |
| 2 | **Wyckoff (sweep + volume)** | 100 | 40.00% | **+20.00 R** |
| 3 | **Al Brooks F2 (failed breakout + volume)** | 45 | 48.89% | **+21.00 R** |
| 4 | **Pure ICT (sweep + FVG)** | 31 | **32.26%** | **−1.00 R** |

Their diagnosis of why the ICT variant is the only loser:
1. **The Exhaustion Trap** — ICT "displacement" is often a climactic exhaustion move; by the time the FVG forms you are mathematically buying the local top.
2. **The Return-to-FVG Lag** — requiring price to retrace into the FVG introduces structural lag that destroys the momentum edge.

**Credibility tier: C+ (small samples — 31 trades for the ICT variant — single-asset-class blog study, no peer review).** Directionally consistent with §1.1 and independently reaches the same conclusion: **FVG-based entry timing is the problem, not the sweep itself.** The transferable insight is the *direction of the difference*, not the R figures.

---

## 2. The graveyard: widely-touted methods that do NOT work

These should **not** be implemented. Evidence quality varies, but the prior from your own A/B failures aligns with the external record.

| Method | Status | Evidence |
|---|---|---|
| **ICT Silver Bullet** (10:00 NY macro + FVG) | **FAIL** | Independent backtest reports: *"backtested 7 ICT setups for 10 years. Silver Bullet lost 46% of capital"* — [r/InnerCircleTraders](https://www.reddit.com/r/InnerCircleTraders/comments/17d6dkr/ict_silver_bullet/). Vendor pages ([Backtrex](https://backtrex.com/en/blog/ict-silver-bullet-strategy-trading-guide), [FluxCharts](https://www.fluxcharts.com/articles/ict-silver-bullet-strategy-explained-how-to-identify-and-trade-it)) quote win rates with no methodology. Note your repo already has `evaluate_silver_bullet_setup()` in `engines/smc.py` — it is the most likely candidate for the look-ahead audit in §1.1. |
| **ICT "2025 Model"** | **REBRAND, no new edge** | [Atlastep comparison](https://atlastep.com/blog/smc-vs-ict): the 2025 Model is the annual rebrand of the 2024 Model — "time + price + FVG" with OTE 62–79% retracement. Same components you already implement, re-packaged. No independent validation exists. |
| **CISD (Change in State of Delivery)** | **REBRAND** | [ICT Traderr explainer](https://icttraderr.com/change-in-the-state-of-delivery/) describes CISD as "a shift in price delivery, typically after a liquidity grab… often accompanies or leads into an MSS." This is CHoCH/MSS with a new name. No independent validation. |
| **FVG / order-block entry timing** | **FAIL as an entry trigger** | §1.1 (causal win rate ≈ no-edge baseline) and §1.2 (only losing variant in the four-stage benchmark). Retain FVG/OB as *context/targets*, delete as entry triggers. |
| **Opening Range Breakout on gold (naive)** | **FAIL in London, ~coin-flip in NY** | [Open Market Journal](https://openmarketjournal.com/research/gold-opening-range-breakout): 7,948 sessions / 16 years. London ORB: clean break **16.8%**, fakeout 35.3%, **roundtrip "Judas" 47.4%**. NY ORB: clean break 22.7%, whipsaw 22.3%. Taking the first London breakout at face value makes you the liquidity. |
| **HTF alignment / D1 bias filters** | **FAIL (already confirmed in-house)** | Consistent with the Open Market Journal finding that London sweeps are *manipulation* and NY breaks are *distribution* — a single static daily bias cannot separate the two, so it filters out exactly the good trades. |
| **Footprint / CVD / delta / DOM order flow on MT5 CFD feed** | **DATA DOES NOT EXIST** | [MQL5 blog, Erkut](https://www.mql5.com/en/blogs/post/774007): typical MT5 forex/CFD feed is quote-only — "volume" is tick count, not traded size, and there is **no aggressor flag**, so "real footprint data and real CVD simply do not exist. Anything your indicator shows must be estimated from price movement." Same article: **volume profile survives** (tick volume correlates well with real activity), footprint "suffers most." Do not build on delta. |
| **MMXM / Market Maker Models** | **UNTESTABLE as taught** | [Hadal Instruments glossary](https://hadalinstruments.com/glossary/market-maker-model/) is unusually candid: the model is *"Constructed and not measured"*, the admissible-array list *"is an election, and the wider it is, the more likely some array lies near any turn at all, which makes the model easier to see and harder to test"*, and explicitly flags *"Not established: How often a first half and a reversal are followed by the second half."* Useful as a target-projection framework; useless as an entry signal. |

---

## 3. What actually has support

### 3.1 The only peer-reviewed mechanism in the SMC stack: stop-order clustering

**Sources:** Carol Osler, Federal Reserve Bank of New York — [Staff Report 125, "Currency Orders and Exchange-Rate Dynamics" (April 2001)](https://www.newyorkfed.org/research/staff_reports/sr125.html) and [Staff Report 150, "Stop-Loss Orders and Price Cascades in Currency Markets" (July 2002)](https://www.newyorkfed.org/medialibrary/media/research/staff_reports/sr150.pdf).

Measured on a large sample of *real* currency orders:

> "a total of 7.4 percent of all stop-loss buy orders are placed at rates ending between 90 and 99, inclusive; in contrast, almost twice as many stop-loss buy orders, **14.4 percent**, are placed at rates ending between **01 and 10**, inclusive."

And the take-profit asymmetry:

> "9.3 percent of take-profit orders are executed **exactly at 00**, while the corresponding percent for stop-loss orders is only **4.4**."

SR150 further establishes that stop-loss orders **do** contribute to price cascades — this is the first empirical study of price-contingent positive-feedback trading in FX.

**Credibility tier: A (Federal Reserve research, peer-reviewed, real order-level data).** Caveat: measured in FX, not gold, and no peer-reviewed replication in XAUUSD exists that I could find. The mechanism should be *at least* as strong in gold — gold's big-figure levels are far more salient to retail than the fourth decimal of EURUSD — but that is an argument, not a measurement. **This specific claim (round-number clustering in XAUUSD) is unverified and should be measured on our own data before any threshold is fitted to it.** See §7 on the backtest protocol.

**Why this matters more than anything else in this document:** it is a *mechanism*, not a pattern. A mechanism tells you *why* the overshoot-and-revert happens, which tells you which levels to trade, where to place the stop (beyond the cluster, not on it), and why the edge shouldn't simply be arbed away (the orders are resting and price-contingent; they are executed regardless of whether anyone knows the pattern).

### 3.2 Gold session architecture (16 years, 7,948 sessions)

**Source:** [Open Market Journal, "Gold's Opening-Range Breakout: London Is a Trap, New York Isn't"](https://openmarketjournal.com/research/gold-opening-range-breakout)

| London ORB outcome | Count | Share |
|---|---|---|
| Clean success (extends) | 689 | **16.8%** |
| Fakeout (closes back inside) | 1,446 | 35.3% |
| **Roundtrip / "Judas" (both sides break)** | 1,938 | **47.4%** |
| No resolution | 19 | 0.5% |

| New York ORB outcome | Share |
|---|---|
| Clean break | **22.7%** |
| Whipsaw | **22.3%** |

**Credibility tier: B−** ("AI-assisted research and commentary", but 7,948 sessions / 16 years with a stated mechanical rule: *first hourly close beyond the opening range, tracked to session end*, tested separately per session). The London vs New York asymmetry is large (47.4% vs 22.3% whipsaw) and is independently consistent with §3.1 and with ICT's own Judas-swing teaching. Recommend we **re-derive this ourselves** on our MT5 data — it is a two-hour job and the rule is fully specified.

### 3.3 Volume profile on a CFD feed: what is and isn't usable

**Source:** [MQL5 blog, Seckin Erkut, "Volume Profile, Footprint Charts and CVD: Is Your Data Real — or a Proxy?"](https://www.mql5.com/en/blogs/post/774007)

> "Volume profile survives best. Tick volume correlates well with real activity, so the shape of the profile — POC location, value area, high and low volume nodes — is usually similar to the real one. Footprint charts suffer most."

**Credibility tier: B (technically correct on data mechanics; author sells a related indicator, so mild incentive bias).** Confirmed against our own probe: `data/probe_m5_5000.json` carries `tick_volume` per bar, so **POC / VAH / VAL are implementable today with no new data**. Delta/footprint are not.

Vendor claims of a gold Value-Area-Fade edge ([PineScriptForge GC Value Area Fade](https://pinescriptforge.com/gc/value-area-fade/backtest): "684 systematically generated signals over Jan 2023 – Mar 2026") are **not credible** — SEO-generated content with no auditable methodology. Treat VA fade as a *hypothesis to test*, not a validated edge.

### 3.4 VWAP

A vendor press release ([Finexus](https://api.finexus.net/api/news/events/0f81beea-49ed-46b2-a63d-1faf719c938e/html)) claims VWAP cross + 150% of 10-min average volume yields +0.42% mean 1-day return vs 0.07% baseline, Sharpe 1.85 long / 1.73 short, 62%/58% win rates, 3.4h average hold.

**Credibility tier: D (unverifiable vendor content with impossible-looking precision).** Do not rely on the numbers. The *underlying* academic anchor is real — Bessembinder (1995) on VWAP as a mean-reversion anchor for large orders, and Hendershott & Menkveld (2021) on VWAP deviations preceding order-flow imbalance — but those describe **execution cost minimization for large orders**, not a tradeable directional alpha for a small account. **Verdict: deprioritize.** Note also that a naive VWAP fade is one of the strategies already confirmed failed in-house.

---

## 4. Candidate survey

Each entry: what it is → entry trigger → timeframe stack → data requirement → validation status.

### 4.1 ICT Turtle Soup (best-specified ICT entry, and it is Wyckoff in disguise)
**What:** Reversal after price sweeps a *multi-session* high/low then closes back inside. Originates from Linda Bradford Raschke's 1990s "Turtle Soup" breakout-fading strategy (published in *Street Smarts* — a real, printed, pre-internet source). ICT wrapped it in MSS + FVG. [ictkillzone.com guide](https://www.ictkillzone.com/ict-turtle-soup).
**Trigger (as specified by the source):** (1) level held ≥2 prior sessions — PDH/PDL, equal highs/lows, prior-week extreme; (2) wick sweeps the level but **body closes back inside** (a close beyond = breakout, not a turtle soup); (3) sweep must be **against** daily bias (fading manipulation, not distribution); (4) active killzone. Entry: after the close-back-inside, drop to M5 and wait for **MSS + the FVG it leaves**, place a limit at the FVG 50% CE on the 2–5 candle retrace; stop beyond the sweep wick high/low.
**Timeframe stack:** daily for level selection + bias → M15/H1 for the level → M5 for entry.
**Data:** OHLC only. **Have it.**
**Validation:** **B−.** The *pattern* is the Wyckoff spring/upthrust, which was the *second*-best performer in the §1.2 benchmark (+20.00 R, 40.0%). The *FVG entry refinement* is exactly what made the pure ICT variant lose. **Use the 2-bar reversal entry (Raschke's original), not the FVG entry.**

### 4.2 MMXM / Market Maker Model (2025-era ICT flagship)
**What:** A full-campaign schematic — original consolidation → staged move away through smaller consolidations → smart-money reversal at a higher-timeframe array → return leg retracing the same pauses. [LuxAlgo library](https://www.luxalgo.com/library/concept/market-maker-models/), [Hadal glossary](https://hadalinstruments.com/glossary/market-maker-model/).
**Concrete detector params (from [FibAlgo](https://www.tradingview.com/script/AvZeEzkr-FibAlgo-ICT-Market-Maker-Model/), usable as a starting state machine):** accumulation = rolling HH/LL over 20 bars with range ≤ 3.5×ATR; manipulation = sweep ≥ 0.3×ATR beyond the range boundary; expansion = candle with body/range ≥ 0.65 and range ≥ 0.8×ATR closing beyond the opposite boundary; invalidation = 2×ATR break the wrong way; timeout = 3× accumulation period.
**Timeframe stack:** H1–D1 for the campaign, M5–M15 at the turn.
**Data:** OHLC only. **Have it.**
**Validation:** **D as an entry signal** (see §2 — Hadal calls it "constructed, not measured"). **B as a *target-projection* framework** — once you are in a sweep-reversion trade, the interior consolidations on the way in are a principled, pre-committed take-profit ladder. **Recommendation: implement the exit ladder, never the entry.**

### 4.3 RTM "Flag Limits" / volumetric order blocks
**What:** [ataquant.com IDM framework](https://ataquant.com/idm-framework-rtm-flag-limits) — instead of the order block at the *base* of the move, use the exact "swap box" level where price crossed on the BOS leg, i.e. "going to the exact level where price turned around… the exact battlefield where buyers finally overpowered sellers."
**Timeframe stack:** M15/H1 for the BOS leg, M5 for the retest.
**Data:** OHLC + tick_volume.
**Validation:** **D.** Single vendor blog, no backtest, no replication. The *intuition* is defensible (a swap level is where the strongest two-way volume occurred, so it is a natural reaction point) and it is cheap to A/B against the current OB base as an alternative POI. Treat as a **POI-selection tweak, not a method.**

### 4.4 Volume-profile / POI-driven ICT (VAH/VAL fade to POC)
**What:** Auction Market Theory — the 70% value area as fair value, fade VAH/VAL rejections toward the POC.
**Trigger:** ≥2 tests of a VA boundary + rejection candle; entry at the boundary, stop 2 ticks beyond it, target POC / partial at VA midpoint.
**Timeframe stack:** M5 profile, M15 confirmation.
**Data:** OHLC + tick_volume. **Have it** (per §3.3, tick volume supports a *shape* profile).
**Validation:** **D (no auditable source).** Worth one backtest because it is cheap and the data exists; expect a range-day dependency (it only works on balanced days, which means it needs a *volatility-regime filter* to avoid being destroyed in trending sessions).

### 4.5 Wyckoff–SMC hybrid (Spring/Upthrust + phase boosting)
**What:** Wyckoff phase classification (accumulation/markup boosts longs, distribution/markdown boosts shorts) as a confidence multiplier on SMC entries. Implemented in [ChartNagari](https://github.com/Ju571nK/ChartNagari) (open-source ICT/Wyckoff detector, 30+ rules, Go + React — worth reading as a reference implementation).
**Trigger:** sweep of a range boundary + **volume expansion on the sweep bar** + close back inside; bias boosted when inside a Wyckoff accumulation/distribution phase.
**Timeframe stack:** H1/D1 phase, M5–M15 entry.
**Data:** OHLC + tick_volume.
**Validation:** **C+.** The §1.2 benchmark is the closest thing to evidence, and the volume-confirmed sweep (+20.00 R) beat raw breakout (+9.00 R) by more than 2×. Volume confirmation is the active ingredient.

### 4.6 Market structure algorithms (swing/BOS/CHoCH detection)
**What:** Fractal swing detection + BOS/CHoCH labelling. Reference implementations: [MarcosACH/market-structure](https://github.com/MarcosACH/market-structure) (PineScript), [ChartNagari](https://github.com/Ju571nK/ChartNagari), and `engines/smc.py` already has `market_structure_phase()` and `_derive_smc_bias()`.
**Validation:** This is **plumbing, not a strategy.** Nobody has published evidence that CHoCH alone has edge. Its value is in defining the swing points that the *other* methods need.
**Action:** adopt a **single, deterministic, parameter-locked swing detector** across all engines so that every method sees the same structure. Divergent swing definitions between methods are a silent overfitting vector.

---

## 5. Ranked recommendation — top 3 for XAUUSD intraday

All three consume only data we already have (OHLC + tick_volume, confirmed present in `data/probe_*.json` and the MT5 bridge). All three are deliberately **the same trade** (failed breakout at a stop cluster) with different confirmation logic and different session handling — which is why they can be A/B tested against each other cleanly.

---

### 🥇 #1 — Round-Number Liquidity Sweep Reversion (highest confidence)

**Why first:** it is the only candidate whose *mechanism* is documented with real order data by a central bank (§3.1), whose *pattern* is the best-performing variant in the multi-era benchmark (§1.2, Al Brooks F2 at +21.00 R / 48.89%), and whose *session behaviour* is confirmed at scale on gold (§3.2). It does not depend on any ICT concept, so it inherits none of the look-ahead baggage.

**What it is:** Resting stop-loss orders cluster just past round numbers (measured: ~2× density in the 01–10 band vs the 90–99 band), while take-profits sit on the round number itself. Price therefore systematically **overshoots** the level to reach the stop cluster and then **reverts** as the cascade exhausts and the take-profit cluster pulls it back. On XAUUSD the relevant grid is coarser than FX: **$50 and $100 increments**, plus half-figures ($25/$50/$75 within a $100 block) as secondary levels.

**Entry trigger (fully specified):**
1. **Level selection.** Compute the $50 grid relative to the current price regime (e.g. near $4,400: 4,350 / 4,400 / 4,450…). Mark a level **active** only if it has been *tested and respected* ≥2 times in the trailing 5 sessions without a hourly close beyond it. This is the "held 2+ sessions" rule from §4.1 — it is what separates a real stop cluster from an arbitrary grid line.
2. **The sweep.** On H1 or M15, price **wicks beyond** the level by ≤ 0.25 × ATR(14,H1) — deep enough to have reached the cluster, shallow enough to still be a sweep rather than a breakout.
3. **The rejection (the part that makes it causal).** Wait for the bar to **close back inside** — i.e. `close` on the *inner* side of the level. **No FVG, no displacement wait, no retrace requirement.** The close-back-inside *is* the signal; this is Raschke's original 2-bar rule and it is what the §1.2 benchmark found superior to the FVG refinement.
4. **Volume confirmation.** `tick_volume(sweep bar) > 1.3 × median(tick_volume, 20)` — evidence the sweep triggered actual order flow rather than drifting through a dead level.
5. **Enter at the open of the next bar** in the reversal direction. **Stop beyond the sweep wick ± (0.10 × ATR)** — beyond the stop cluster, where the trade is objectively wrong. **Target 1:** the *next* round number toward the interior (where the take-profit cluster sits, per Osler). **Target 2 / runner:** the opposite side of the session range. R:R ≈ 2:1 minimum.

**Timeframe stack:** H1 for level selection + ATR → M15 for the sweep and entry → H1 for target.
**Session filter:** **London and New York only.** Explicitly exclude the Asian session (thin liquidity means sweeps are noise, not order flow).
**Data:** OHLC + tick_volume. **Have it. No new data.**
**Evidence:** Osler NY Fed SR125/SR150 (A) for the mechanism; §1.2 (C+) for close-back-inside > FVG entry; §3.2 (B−) for London-sweep frequency.
**Confidence: Medium-High.** Highest in this document, but "medium-high" not "high" — Osler's data is FX not gold, and no one has published a causal backtest of this exact rule on XAUUSD. **We must generate that evidence ourselves.**

---

### 🥈 #2 — Volume-Confirmed Wyckoff Spring / Upthrust

**What it is:** The classical Wyckoff spring (sell-side) and upthrust (buy-side) — a trap that pierces a range boundary to trigger stops and breakout orders, then reverses. Identical in shape to Turtle Soup but with **volume as the explicit confirmation** and **no ICT entry machinery**. This was the +20.00 R / 40.0% variant in the §1.2 benchmark, and it beat the raw breakout trap (+9.00 R) by more than 2× — that delta is the volume filter.

**Entry trigger:**
1. **Range definition.** A consolidation whose H1 high/low have held for ≥6 H1 bars (≈1 session) with range ≤ 3.0 × ATR(14,H1) — tight enough to be genuine consolidation, not a trend pause. *(Borrowed from the FibAlgo MMXM detector, §4.2, which is the one reusable part of that framework.)*
2. **The spring/upthrust.** Price wicks below the range low (spring) or above the range high (upthrust) by ≤ 0.30 × ATR.
3. **Volume confirmation (the active ingredient).** `tick_volume(sweep bar) > 1.5 × median(tick_volume, 20)` — a *higher* bar than method #1, because here the level is a range edge rather than a round number where clustering is guaranteed.
4. **Close-back-inside** on the sweep bar, same as #1. No FVG, no displacement wait.
5. **M5 structure-shift confirmation (cheap, optional).** Enter on the break of the nearest M5 swing in the reversal direction rather than at the next open. Backtest both; the §1.1 audit applies to the M5 swing too, so only keep it if prefix replay survives.
6. **Stop** beyond the sweep wick ± 0.10 × ATR. **Target:** the *opposite* edge of the consolidation range first, then the next liquidity pool beyond it. R:R ≈ 2:1.

**Timeframe stack:** H1 for the range → M15/M5 for the sweep and entry.
**Session filter:** London + NY. Skip the 5 minutes around tier-1 news (your `engines/economic_calendar.py` already supports this).
**Data:** OHLC + tick_volume. **Have it.**
**Evidence:** §1.2 benchmark (C+ — small sample, but the direction is clear and consistent). Wyckoff and Raschke are pre-internet, printed sources, i.e. not influencer lore.
**Confidence: Medium.** The pattern is real; the specific thresholds (1.5×, 0.30×ATR, 6 bars) are guesses that need fitting on a train set with a strict out-of-sample holdout.

---

### 🥉 #3 — London Judas-Swing Fade / New York Breakout Continuation

**What it is:** A **session-asymmetric** treatment of the same phenomenon, derived directly from gold session statistics rather than from any trading guru. The finding: on gold, the first London opening-range break is a liquidity trap **47.4%** of the time (a "Judas swing" that sweeps both sides before resolving) and a genuine breakout only **16.8%** of the time — while New York is close to a coin flip (22.7% clean vs 22.3% whipsaw). The same pattern therefore demands **opposite** handling in the two sessions.

**Entry trigger — London (fade the first break):**
1. Define the London opening range as the first 60 minutes of the London session (use your existing `active_killzone_session()` clock).
2. Wait for price to break the OR high or low, then **close back inside** the OR on an H1 or M15 close.
3. Enter *against* the broken side (short after a failed break of the OR high). **Stop** 0.15 × ATR beyond the sweep extreme. **Target** the opposite OR edge, then the session liquidity beyond it.
4. **Hard rule:** only the *first* failed break per session is tradable. A second failed break means the session is ranging without conviction — and 47.4% roundtrips already tell you London is not where continuation lives.

**Entry trigger — New York (trade the continuation):**
1. Same OR definition for the New York open.
2. On a break, require **volume** `tick_volume > 1.3 × median(20)` and a close beyond the OR edge.
3. Enter **with** the break. **Stop** at the OR midpoint (if breached, the break failed). **Target** 2× the OR height.

**Timeframe stack:** H1 for the OR definition, M15 for the close-back-inside / break confirmation.
**Session filter:** *is* the strategy. London = reversion, New York = continuation. Never Asian.
**Data:** OHLC + tick_volume + session clock. **Have it all.**
**Evidence:** §3.2 (B−), 7,948 sessions / 16 years, gold-specific. This is the only candidate with a **gold-specific** large-sample measurement behind it.
**Confidence: Medium.** The London/NY asymmetry is large and plausible, but the source is AI-assisted commentary with one-line methodology. **Re-derive it on our own MT5 data first** — the rule is fully specified and it is a couple of hours of work. If our numbers reproduce ≈47% / ≈23%, upgrade this to Medium-High.

---

## 6. Data feasibility matrix

| Data | Source | Have it? | Needed for |
|---|---|---|---|
| OHLC (M5/M15/H1/H4/D1) | MT5 bridge | ✅ `data/probe_*.json` | All three methods |
| `tick_volume` per bar | MT5 bridge | ✅ present in probes | #1, #2, #3 (volume filters) |
| Session clock / killzones | `engines/smc.py` `active_killzone_session()` | ✅ | #3 |
| Economic calendar | `engines/economic_calendar.py` | ✅ | news blackout for #2 |
| Real traded volume | — | ❌ not on CFD feed | Volume profile is *usable* via tick volume; **footprint/CVD/delta are impossible** (§3.3) |
| Aggressor flag / DOM | — | ❌ not on CFD feed | Order-flow methods — **do not build** |
| COT | CFTC | ❌ (weekly, free) | Not useful for intraday |

**No new data integration is required to implement and backtest all three recommendations.**

---

## 7. Backtest protocol — mandatory before trusting any of this

1. **Prefix-replay harness (§1.1).** Re-derive every signal from truncated bar history. No detector may read a bar index it could not have known at signal time. This applies to the *existing* SMC engine too.
2. **Causal timestamping.** Entry timestamp = the bar whose close *caused* the signal, never the pattern's anchor bar. If win rate drops >5pp vs the current harness, the old result was manufactured.
3. **Real costs.** Gold spread (typically 20–40 cents on retail CFD) plus commission, applied per trade. At a 2R target with a 30-cent spread and a $3 ATR stop, costs eat roughly 10% of R per side — enough to turn a marginal strategy negative.
4. **Day-clustered t-statistic**, not per-trade t. The Quark paper's retroactive variant hit t=108.4 precisely because it ignored intra-day clustering; the honest t was 1.87.
5. **Fixed 2R target for comparability**, then optimize exits separately. Mixing entry and exit research makes both uninterpretable.
6. **Train / out-of-sample split**, e.g. fit thresholds on 2022–2024, validate on 2025–2026. Every threshold in §5 is currently a guess.
7. **Regime stratification.** Report edge by volatility tercile (ATR percentile) and by session. Method #3 only works because it *is* a session stratification; #1 and #2 need the same lens.
8. **Placebo test.** Run the same entry rule with randomized direction. The [Validated catalog's Gold Momentum (TSM)](https://validatedstrategies.com/strategy/TSM) entry is instructive — profit factor 2.41, 8/11 gates passed, **and still retired** because the placebo test failed, i.e. the edge was indistinguishable from pure gold beta. Any XAUUSD strategy must beat its own placebo.

---

## 8. Honest summary of confidence

- **The core insight — sweep-and-revert at a level where stops cluster — is the best-supported idea in the retail price-action space**, and it is supported by central-bank order data, not by a course. **Medium-High confidence.**
- **Everything ICT layered on top of it (FVG, OB retest, displacement timing) is likely net-negative.** Two independent studies reach this conclusion. **High confidence in the negative claim.**
- **No method in this document has a published causal backtest on XAUUSD.** The 78%-win-rate figures floating around the SMC space are, per §1.1, an artifact of where the entry arrow is drawn. **Any edge we capture must be generated by our own causal backtest.**
- **Expected realistic outcome:** the causal band for a 2R-target price-structure rule is 34–40% win rate per the look-ahead paper. Combined with a genuine stop-cluster mechanism and tight execution, that is a *workable* edge (≈ +0.1 to +0.3 R per trade) — not the +1.2 R that contaminated backtests report. Set expectations accordingly: this is a strategy that survives on volume and discipline, not on a high win rate.
- **What would change my mind, in order of value:** (1) a reproduced in-house causal backtest showing the existing SMC engine's 54% win rate survives prefix replay — if it does, the current engine is fine and the problem is execution, not edge; (2) reproducing the London 47.4% roundtrip figure on our own data; (3) any peer-reviewed study of round-number clustering in gold specifically.

---

## 9. Sources, with credibility tiers

**Tier A — peer-reviewed / central bank**
1. Osler, C. — [NY Fed Staff Report 125, "Currency Orders and Exchange-Rate Dynamics" (2001)](https://www.newyorkfed.org/research/staff_reports/sr125.html) — stop-loss clustering just past round numbers.
2. Osler, C. — [NY Fed Staff Report 150, "Stop-Loss Orders and Price Cascades in Currency Markets" (2002)](https://www.newyorkfed.org/medialibrary/media/research/staff_reports/sr150.pdf) — stop-loss orders cause price cascades.

**Tier B — sound methodology, not peer-reviewed**
3. Andreev & Howden — [Quark Quantitative Research, "A Look-Ahead Convention in Intraday Price-Structure Backtests"](https://quarkresearch.cc/papers/paper_lookahead_fake_edge.pdf) — the look-ahead audit; the most important read in this list.
4. [Open Market Journal, "Gold's Opening-Range Breakout: London Is a Trap, New York Isn't"](https://openmarketjournal.com/research/gold-opening-range-breakout) — 7,948 gold sessions, 16 years. *AI-assisted; re-derive locally.*
5. [MQL5, Erkut — "Volume Profile, Footprint Charts and CVD: Is Your Data Real — or a Proxy?"](https://www.mql5.com/en/blogs/post/774007) — what tick volume can and cannot support on MT5. *Author sells a related indicator.*
6. [Hadal Instruments — Market Maker Model glossary](https://hadalinstruments.com/glossary/market-maker-model/) — the honest "constructed, not measured" critique of MMXM.

**Tier C — blog / small-sample studies, directionally useful**
7. [The Quant Scientist — "ICT vs. Price Action: Is Liquidity Sweep Trading a Data-Backed Edge?"](https://thequantscientist.com/blog/the-marketing-of-liquidity-sweeps-how-data-science-proves-ict-broke-a-100-year-old-edge) — the four-era benchmark. *n=31 for the ICT variant.*
8. [Nordman Analysis — "What Are Liquidity Sweeps and How to Read Them"](https://nordman-algorithms.com/what-are-liquidity-sweeps) — synthesizes Osler; "nobody hunts your stop… stop orders cluster, and that clustering is measurable." *Vendor.*
9. [ictkillzone.com — ICT Turtle Soup guide](https://www.ictkillzone.com/ict-turtle-soup) — the most precise public spec of the Turtle Soup entry.
10. [Quantified Strategies — "Gold Overnight Trading Strategy"](https://www.quantifiedstrategies.com/gold-overnight-trading-strategy/) — overnight edge in gold, but on GLD (ETF) not spot, and "persistent only during periods." **Not transferable to 24h XAUUSD without re-testing.**

**Tier D — influencer / vendor lore; cited only to document the negative results**
11. [Finexus — "VWAP Breakout With Volume Confirmation"](https://api.finexus.net/api/news/events/0f81beea-49ed-46b2-a63d-1faf719c938e/html) — unverifiable VWAP claims. Tier D.
12. [PineScriptForge — GC Value Area Fade](https://pinescriptforge.com/gc/value-area-fade/backtest) — SEO-generated, no auditable methodology.
13. [r/InnerCircleTraders — Silver Bullet thread](https://www.reddit.com/r/InnerCircleTraders/comments/17d6dkr/ict_silver_bullet/) — *"backtested 7 ICT setups for 10 years. Silver Bullet lost 46% of capital."*
14. [Atlastep — "SMC vs ICT"](https://atlastep.com/blog/smc-vs-ict) — confirms the 2025 Model is an annual rebrand of the 2024 Model.
15. [ICT Traderr — CISD explainer](https://icttraderr.com/change-in-the-state-of-delivery/) — CISD = MSS/CHoCH rebranded.
16. [ataquant.com — IDM / RTM Flag Limits](https://ataquant.com/idm-framework-rtm-flag-limits) — plausible POI tweak, zero validation.

**Reference implementations (code, not claims)**
17. [github.com/Ju571nK/ChartNagari](https://github.com/Ju571nK/ChartNagari) — open-source ICT/Wyckoff detector, 30+ rules, Go + React.
18. [github.com/MB-Ndhlovu/ICT-MT5](https://github.com/MB-Ndhlovu/ICT-MT5) — ICT SMC EA for MT5 targeting XAUUSD (M5), NAS100, US30.
19. [github.com/MarcosACH/market-structure](https://github.com/MarcosACH/market-structure) — PineScript swing/CHoCH detection.
20. [FibAlgo ICT Market Maker Model (TradingView)](https://www.tradingview.com/script/AvZeEzkr-FibAlgo-ICT-Market-Maker-Model/) — concrete MMXM detector parameters (§4.2).
21. [Validated — strategy catalog](https://validatedstrategies.com/catalog) — 4,284 strategies, only 3 "validated"; instructive placebo-test discipline ([example: Gold Momentum TSM retired despite PF 2.41](https://validatedstrategies.com/strategy/TSM)).
