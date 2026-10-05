"""Signal skip census across ALL records, not just the tail."""
import sys, json
sys.path.insert(0, '.'); sys.path.insert(0, 'engines')
from env_loader import load_dotenv
load_dotenv('.env')
from engines import paths
from collections import Counter

recs = paths.read_json_safe(paths.signals_log(), [], label="signals_log") or []
n = len(recs)
print("total records:", n)

verdicts = Counter()
blocks = Counter()       # the vote that actually flipped to skip
for r in recs:
    d = r.get("decision") or {}
    sig = d.get("signal") or {}
    verdicts[d.get("verdict")] += 1
    if d.get("verdict") == "skip":
        reasons = d.get("reasons") or []
        # the first reason is the score-boosting positive vote; the
        # negative/blocking vote is the one trade_allowed hinges on
        for reason in reasons:
            if reason.startswith(("poor_", "already_", "hermes_neutral",
                                  "no_", "market_", "unverified_", "sl_",
                                  "risk_", "duplicate_", "stale_", "low_")):
                blocks[reason] += 1

print("\n--- verdicts ---")
for k, v in verdicts.most_common():
    print(f"{v:3d}x  {k}")

print("\n--- blocking votes on skips ---")
for k, v in blocks.most_common():
    print(f"{v:3d}x  {k}")

# score distribution on skips
sk = [r.get("decision", {}).get("score") for r in recs
      if (r.get("decision") or {}).get("verdict") == "skip"]
ex = [r.get("decision", {}).get("score") for r in recs
      if (r.get("decision") or {}).get("verdict") == "execute"]
if sk:
    print(f"\nskip scores: min={min(sk)} max={max(sk)} mean={sum(sk)/len(sk):.2f}")
if ex:
    print(f"execute scores: min={min(ex)} max={max(ex)} mean={sum(ex)/len(ex):.2f}")
