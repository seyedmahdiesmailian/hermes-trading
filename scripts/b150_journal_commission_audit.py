"""b150: is the journal's commission complete?

MT5 can charge commission on the IN deal, the OUT deal, or both. The journal
(engines.learning.journal_from_deals) writes ONE ROW PER CLOSING DEAL by the
b75 decision, so if the broker charges on the IN deal too, the journal silently
drops that half and every net-P&L figure derived from it is optimistic.

This script answers the question from the broker's own deal history, per
position, without touching any production file:

  journal_net  = sum(profit + commission + swap) over journal rows
  broker_net   = sum(profit + commission + swap) over ALL deals of the position

READ-ONLY. Writes nothing.
"""
import collections
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from env_loader import load_dotenv  # noqa: E402
from bridge_client import BridgeClient  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")


def num(x):
    try:
        return float(x or 0)
    except (TypeError, ValueError):
        return 0.0


def main():
    deals = BridgeClient().get_history_deals(symbol="XAUUSD", days=30).get("data") or []
    # entry: 0 = IN (open), 1 = OUT (close), 2 = INOUT (partial)
    by_pos = collections.defaultdict(list)
    for d in deals:
        pid = str(d.get("position_id") or d.get("order") or "")
        if pid:
            by_pos[pid].append(d)

    # how is commission distributed across deal entries?
    dist = collections.Counter()
    for d in deals:
        e = str(d.get("entry"))
        c = num(d.get("commission"))
        if c:
            dist[e] += 1
    print("deals carrying non-zero commission, by entry kind "
          "(0=IN, 1=OUT, 2=INOUT):", dict(dist))

    positions_with_in_comm = sum(
        1 for ds in by_pos.values()
        if any(num(d.get("commission")) for d in ds if str(d.get("entry")) in ("0", "2")))
    positions_with_out_comm = sum(
        1 for ds in by_pos.values()
        if any(num(d.get("commission")) for d in ds if str(d.get("entry")) in ("1", "2")))
    print(f"positions: {len(by_pos)} | carrying IN commission: {positions_with_in_comm} "
          f"| carrying OUT commission: {positions_with_out_comm}")

    rows = list(csv.DictReader(open(ROOT / "data/xau_plan/trade_journal.csv")))
    j_comm = collections.defaultdict(float)
    j_profit = collections.defaultdict(float)
    for r in rows:
        pid = str(r.get("position_id") or r.get("ticket") or "")
        j_comm[pid] += num(r.get("commission"))
        j_profit[pid] += num(r.get("profit"))

    broker_comm = {p: sum(num(d.get("commission")) for d in ds) for p, ds in by_pos.items()}
    overlap = [p for p in broker_comm if p in j_comm]
    missing = [(p, broker_comm[p], j_comm[p]) for p in overlap
               if abs(broker_comm[p] - j_comm[p]) > 0.005]
    print(f"\npositions present in BOTH broker and journal: {len(overlap)}")
    print(f"positions whose commission the journal got WRONG: {len(missing)}")
    print(f"  broker commission total (overlap): {sum(broker_comm[p] for p in overlap):+.2f}")
    print(f"  journal commission total (overlap): {sum(j_comm[p] for p in overlap):+.2f}")
    print(f"  UNDER-COUNT: {sum(j_comm[p] - broker_comm[p] for p in overlap):+.2f}")
    for p, b, j in missing[:8]:
        print(f"    pos {p}: broker {b:+.2f} vs journal {j:+.2f}  (journal misses {b - j:+.2f})")

    tot = sum(num(d.get("profit")) + num(d.get("commission")) + num(d.get("swap"))
              for d in deals)
    print(f"\nBROKER all-in net over {len(by_pos)} positions (30d): {tot:+.2f}")
    print("JOURNAL all-in net (same file the weekly report reads): "
          f"{sum(num(r.get('profit')) + num(r.get('commission')) + num(r.get('swap')) for r in rows):+.2f}")
    json.dump({"commission_by_entry_kind": dict(dist),
               "positions": len(by_pos),
               "broker_net_30d": round(tot, 2)},
              open(ROOT / "data/backtest/b150_journal_commission_audit.json", "w"), indent=1)


if __name__ == "__main__":
    main()
