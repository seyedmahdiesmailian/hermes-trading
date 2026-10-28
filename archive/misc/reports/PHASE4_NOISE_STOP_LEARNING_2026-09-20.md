# Phase 4 — noise-stop skip, learning size-only, H1 coil lookback

Date: 2026-09-20. Session branch only. Demo. `master` untouched.

## Self Q&A

Q: After Asia 0.5 and MAX_LOT 0.10, what still kills the book?
A: Joined execution_log ticket = journal position_id. 27 fills. Every
   blueprint after 31 Aug has RR exactly 1.55 (reanchor pad). Stops < $8
   on the 5k book netted **−$327**; the four −100$ disasters were
   5.84–6.54. Winners on those tight stops (+70/+42/+19) do not pay for
   the left tail.

Q: Size the 6$ stop down instead of skipping?
A: Already capped at 0.10 lot. 0.10 × $6 is still a noise scalp. A
   professional does not take a stop inside gold's M5 ATR.

Q: Raise learning min_rr to 1.75 because avg is negative?
A: **Halt, not a filter.** b84 measured 99.7% of the funnel sitting in
   1.55±0.06 because `_reanchor_blueprint` manufactures TP at min_rr+0.05.
   The first +0.25 step drops 98.9–100% of trades. Last round's
   `elif avg < 0: min_rr += 0.25` would silence the live box on the next
   `run_learning_cycle`. Size is the lever that actually shrinks the tail.

Q: Invent a $20 envelope around a $7 H1 coil?
A: No — those levels are not in the market. Widen lookback 24h → 72h
   first (live 2026-09-10 plan had a $3 value zone). Envelope only if
   even 3 days is a coil.

Q: Block fabricated 1.55R scalps entirely?
A: Rejected this round. b84/b161 pinned the manufacturer; ripping it
   out without a new funnel measurement would starve entries before H1
   pullbacks are proven live. Noise skip is the evidence-backed cut.

## Shipped

- `MIN_STOP_DISTANCE=8.0` when `balance >= 1500`. Below that, b196's
  5pt/1%/$799 path still prints 0.01 lot.
- Learning `elif avg < 0:` cuts `risk_mult` only. WR<0.40 arm still
  raises RR+grade (broken-system path; live WR is 65%).
- `compute_htf_structure_zones` widens to 72 H1 bars when 24h range <
  max(2 ATR, $15). `zone_source=h1_swing_wide`.

## Book effect (same 27 joined fills)

Skip stop<$8: avoid −478, give up +152, net **+$326** vs the −$102 book.
Learning will no longer halt the funnel on the next cron. Coil plans get
a real swing instead of a $3 scalp zone.

## Untouched

Bridge/auth, master, cadence, premium full risk, killzone gate, reanchor
BUY/SELL asymmetry, TP1 split, 36h time_exit.
