# Phase 3 — Asia half-risk + hard lot ceiling

Date: 2026-09-20. Session branch only. Demo account.

## Self Q&A (professional trader, not a gate collector)

Q: The book is 65% WR and still net −$102. Why?
A: Payoff, not hit-rate. avgW $29.7 vs avgL −$62.9. Four tickets
   (−106/−104/−100/−95) dominate the year.

Q: When did those four open?
A: execution_log `at`, not journal close_time (Asia entries that die after
   07:00 UTC look like London if you bucket on close). 5 of 8 fat losses
   (net < −40$) opened 00–07 UTC. 16/29 live fills are Asia.

Q: Skip Asia?
A: No. Sep 3 03:00/04:00 buys were +70/+71. Half size, never a block.

Q: Why not inflate the stop to 8$ for sizing (MIN_STOP_FOR_FULL_RISK)?
A: b196 pins a 5pt stop at 1%/$799 to 0.01 lot. Treating the stop as 8$
   would skip that ticket (fail-open relative to the contract). A lot
   ceiling never widens the broker SL and never skips the small-account
   path.

Q: Why 0.10, not 0.05?
A: 0.10 is still 2% of $5k at a 10$ stop — the live default geometry.
   Anything tighter now risks fewer dollars, never more. 0.05 would
   silently cut London/NY winners that the book still prints.

Q: Half premium? Block SMC dead killzone? Cadence 5 vs 15?
A: Rejected. test_b53 requires premium full risk; 16:00–24:00 “dead”
   includes NY afternoon winners; cadence is a live-scheduler question.

## What shipped

- `SESSION_RISK_MULT["asia"]=0.5` on `evaluate_proposal` (plan.session).
  Missing/unknown session = 1.0 (tests + signal-without-plan stay full).
  London/NY = 1.0.
- `MAX_LOT=0.10` as `volume_max` (was 1.0). Tightening only.
- `risk_stack` now carries `session` + `session_mult`. b139/b196 product
  tests multiply the new leg. Ledger schema unchanged (extras dropped).
- learning.py docstring: session size is a STATIC prior on the executor;
  this module still only tightens the GLOBAL `risk_mult`.

## Expected book effect (same 8 fat tickets, ceteris paribus)

Asia 0.5 × lot cap 0.10 would have cut the 0.15–0.17 disasters to ≤0.10
and the Asia ones further to ~0.05–0.08. The Sep 3 Asia winners shrink
the same way. Net: smaller left tail, smaller right tail, the tail that
was killing the account is the left one.

## Untouched

Bridge/auth, windows_bridge, master, cadence, STYLE_RISK_MULT premium,
killzone gate, TP1 split, b88/b89 JSON.
