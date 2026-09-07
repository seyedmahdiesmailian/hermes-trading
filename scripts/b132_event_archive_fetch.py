#!/usr/bin/env python3
"""b132 — BUILD A REAL HISTORICAL EVENT-CALENDAR ARCHIVE (b131's blocker).

WHY THIS EXISTS
===============
b131 priced the live news veto and had to report COVERAGE-ZERO on six of seven
legs: the only historical calendar on this box was the git union of committed
economic_calendar.json versions (Aug 23..Sep 12 2026), so "the veto is inert"
was a finding about `cached`'s tail and an absence of data everywhere else.
b132's own reusable lesson is the precondition this script satisfies: intersect
the gate's DATA window with the measurement windows BEFORE designing the study.

THE SOURCE (measured, not assumed — b131 probed and killed the obvious ones)
============================================================================
nfs.faireconomy.media/ff_calendar_thisweek.json yearly/weekly variants: 404.
forexfactory.com/calendar (historical week): 403 Cloudflare.
investing.com: 403. myfxbook: 403. TradingEconomics /calendar/csv: login
wall (the CSV link redirects to sso). TradingEconomics API guest account:
410 discontinued. TradingView calendar API: 403 (b131).

What DOES work is the Internet Archive's own crawl of the same feed: the CDX
index for nfs.faireconomy.media/ff_calendar_thisweek.json returns ~98 daily
200-responses spanning 2026-05-04 .. 2026-09-06 (plus three isolated 2022
snapshots, which are outside every lab window and are skipped by range).
Each snapshot is the FOREXFACTORY feed for the week it was captured in, so the
UNION over daily captures is a real, dated, high-impact-tagged event record —
exactly the shape engines/economic_calendar.py already parses.

WHAT THIS SCRIPT DOES
=====================
1. Query CDX for every 200 snapshot of the feed.
2. Fetch each snapshot raw (`id_` suffix = no Wayback re-writing; the payload
   arrives gzip-encoded, which is handled).
3. Normalise every event into the repo's own calendar shape, using the SAME
   field mapping as economic_calendar._fetch_forexfactory (country -> currency,
   impact lower-cased) so the archive is a drop-in for the live predicate.
4. Union-dedupe on (date, currency, title) and write
   data/calendar/events_archive_ff_wayback_<first>_<last>.json.

This is a DATA task: no gate, no engine, no live path is touched. The archive
is consumed by scripts/b132_news_veto_real_calendar.py.
"""
from __future__ import annotations

import datetime as dt
import gzip
import json
import os
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
os.chdir(_ROOT)

FEED = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
CDX = ("http://web.archive.org/cdx/search/cdx?url=" + FEED +
       "&output=json&fl=timestamp,statuscode,length&collapse=timestamp:8")
UA = "Mozilla/5.0 (X11; Linux x86_64) hermes-trading-b132/1.0 (research archive)"

# Snapshots older than this are outside every lab window (the 2022 captures)
# and only add noise; the earliest leg start is 2025-01-06.
MIN_SNAPSHOT = "20250101"


def _get(url: str, timeout: int = 30) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
        enc = (r.headers.get("Content-Encoding") or "").lower()
    if "gzip" in enc or raw[:2] == b"\x1f\x8b":
        try:
            raw = gzip.decompress(raw)
        except OSError:
            pass
    return raw


def snapshot_list() -> list[str]:
    """Every 200-status daily capture timestamp of the feed, oldest first."""
    rows = json.loads(_get(CDX).decode("utf-8", "replace"))[1:]
    return sorted(r[0] for r in rows
                  if len(r) >= 2 and r[1] == "200" and r[0] >= MIN_SNAPSHOT)


def normalise(items: list[dict], captured: str) -> list[dict]:
    """FF feed -> the repo's calendar shape.

    Field mapping is COPIED from engines/economic_calendar._fetch_forexfactory
    on purpose (b82's parity rule: the archive must be readable by the same
    predicate live runs, so it must not invent its own schema).
    """
    out = []
    for it in items:
        if not isinstance(it, dict):
            continue
        currency = str(it.get("currency") or it.get("country") or "").upper()
        impact = str(it.get("impact", "")).lower()
        if impact not in {"high", "medium", "low"}:
            impact = "medium"
        title = str(it.get("title", ""))
        date = str(it.get("date", ""))
        if not title or not date:
            continue
        out.append({"title": title, "currency": currency, "impact": impact,
                    "date": date, "time": str(it.get("time", "")),
                    "forecast": str(it.get("forecast", "")),
                    "previous": str(it.get("previous", "")),
                    "captured": captured})
    return out


def fetch_one(ts: str) -> tuple[str, list[dict], str | None]:
    url = f"http://web.archive.org/web/{ts}id_/{FEED}"
    try:
        body = json.loads(_get(url).decode("utf-8", "replace"))
    except Exception as exc:                                # noqa: BLE001
        return ts, [], f"{type(exc).__name__}: {exc}"
    return ts, normalise(body if isinstance(body, list) else [], ts), None


def _glob(path: str = "data/calendar/events_archive_ff_wayback_*.json") -> list[str]:
    import glob
    return sorted(glob.glob(path))


def existing_snapshots() -> set[str]:
    """Snapshot timestamps already captured in any archive on disk (so a retry
    pass fetches only what failed instead of re-crawling 95 weeks)."""
    have: set[str] = set()
    for p in _glob():
        try:
            d = json.load(open(p))
        except Exception:                                     # noqa: BLE001
            continue
        for e in d.get("events", []):
            if e.get("captured"):
                have.add(str(e["captured"]))
        for ts in (d.get("failed_ts") or []):
            have.discard(str(ts))
    return have


def build(workers: int = 5, verbose: bool = True,
          only: list[str] | None = None) -> dict:
    snaps = only if only is not None else snapshot_list()
    if not snaps:
        raise SystemExit("CDX returned no usable snapshots — archive blocked?")
    events: dict[tuple, dict] = {}
    failures: dict[str, str] = {}
    per_week: dict[str, int] = {}
    if workers <= 1:                                          # polite serial path
        import time
        for ts in snaps:
            r = fetch_one(ts)
            if r[2]:
                failures[ts] = r[2]
            else:
                per_week[ts[:8]] = len(r[1])
                for e in r[1]:
                    events[(e["date"], e["currency"], e["title"])] = e
            time.sleep(0.4)
    else:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            for ts, items, err in ex.map(fetch_one, snaps):
                if err:
                    failures[ts] = err
                    continue
                per_week[ts[:8]] = len(items)
                for e in items:
                    events[(e["date"], e["currency"], e["title"])] = e
    ordered = sorted(events.values(), key=lambda e: (str(e["date"]),
                                                     e["currency"], e["title"]))
    dates = [e["date"] for e in ordered if e.get("date")]
    return {"source": "forexfactory_via_internet_archive_cdx",
            "feed": FEED,
            "n_snapshots": len(snaps),
            "n_snapshots_failed": len(failures),
            "failures": failures,
            "snapshot_first": snaps[0], "snapshot_last": snaps[-1],
            "event_first": dates[0] if dates else None,
            "event_last": dates[-1] if dates else None,
            "n_events": len(ordered),
            "n_high_gold": sum(1 for e in ordered
                               if e["impact"] == "high"
                               and e["currency"] in ("USD", "XAU", "GOLD")),
            "events": ordered}


def out_path(led: dict) -> str:
    a = (led["event_first"] or "")[:10].replace("-", "")
    b = (led["event_last"] or "")[:10].replace("-", "")
    return f"data/calendar/events_archive_ff_wayback_{a}_{b}.json"


def main() -> None:
    led = build()
    p = out_path(led)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w") as f:
        json.dump(led, f, indent=1)
    print(f"snapshots: {led['n_snapshots']} (failed {led['n_snapshots_failed']})")
    print(f"events: {led['n_events']}  high USD/XAU: {led['n_high_gold']}")
    print(f"event span: {led['event_first']} .. {led['event_last']}")
    print("saved:", os.path.abspath(p))


if __name__ == "__main__":
    main()
