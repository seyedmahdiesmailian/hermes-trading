"""Why is every forwarded signal skipped? Read the per-signal reasons."""
import sys, json
sys.path.insert(0, '.'); sys.path.insert(0, 'engines')
from env_loader import load_dotenv
load_dotenv('.env')
from engines import paths

recs = paths.read_json_safe(paths.signals_log(), [], label="signals_log") or []
print("total:", len(recs))
# most recent 60
# records are nested: decision.{verdict,reasons,trade_allowed,signal}
recent = recs[-60:]
from collections import Counter
c = Counter()
for r in recent:
    d = r.get("decision") or {}
    sig = d.get("signal") or {}
    c[f"{d.get('verdict')} | {d.get('reasons', ['-'])[0]}"] += 1
print("\n--- last 60 signals ---")
for k, v in c.most_common():
    print(f"{v:3d}x  {k}")

print("\n--- last 3 records (full decision) ---")
for r in recent[-3:]:
    d = r.get("decision") or {}
    sig = d.get("signal") or {}
    print(json.dumps({"verdict": d.get("verdict"),
                      "trade_allowed": d.get("trade_allowed"),
                      "score": d.get("score"), "max": d.get("max_score"),
                      "reasons": d.get("reasons"),
                      "side": sig.get("side"), "entry": sig.get("entry")},
                     ensure_ascii=False, indent=1))
