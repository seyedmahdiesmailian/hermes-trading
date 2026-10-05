"""47 signals scored >=6.0 (the execution threshold) yet still skipped.
The score gate passed, so the skip must come from a vote the scorer does
not control: account_policy.trade_allowed, the macro/news filter, or the
downstream evaluate_proposal gauntlet.

Tally the blocking reason on those 47 to see which one dominates.
"""
import sys, json
sys.path.insert(0, '.'); sys.path.insert(0, 'engines')
from env_loader import load_dotenv
load_dotenv('.env')
from engines import paths
from collections import Counter

recs = paths.read_json_safe(paths.signals_log(), [], label="signals_log") or []
c = Counter()
for r in recs:
    d = r.get("decision") or {}
    if (d.get("score") or 0) >= 6.0 and d.get("verdict") == "skip":
        rs = [str(x) for x in (d.get("reasons") or [])]
        blocker = next((x for x in rs if x.startswith(
            ("already_", "account_locked", "market_", "news_", "halted",
             "positions_unreadable", "poor_"))), "other")
        c[blocker] += 1

print("--- why score>=6 signals were skipped ---")
for k, v in c.most_common():
    print(f"{v:3d}x  {k}")
