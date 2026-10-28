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

What DOES work is the Internet Archive's own crawl of the same feed. Each
snapshot is the FOREXFACTORY feed for the week it was captured in, so the
UNION over daily captures is a real, dated, high-impact-tagged event record —
exactly the shape engines/economic_calendar.py already parses.

b133 CORRECTION — THE CDX QUERY WAS THE BUG, NOT THE ARCHIVE
============================================================
The b132 round queried CDX by EXACT url
(`?url=https://nfs.faireconomy.media/ff_calendar_thisweek.json`) and concluded
"the archive only reaches 2026-05-03". That conclusion was an artefact of the
query. ForexFactory ships the feed with a cache-busting `?version=<hash>`
query string, and every 2021..2025 crawl recorded the ORIGINAL url WITH that
query string, so those captures live under a different urlkey and an exact-URL
CDX lookup cannot see them. Measured 2026-09-07 (same host, same feed):

    exact-URL query   : 98 daily 200s  -> 2022 (3), 2026 (95)      [b132's view]
    prefix+urlkey query: 1087 daily 200s -> 2021 (40), 2022 (400), 2023 (419),
                                              2024 (52), 2025 (76), 2026 (100)

So the archive is not thin, it is DEEP — 2025 alone has 76 captured days,
which covers the W3..W6 legs b132 wrote off as coverage-zero. The query below
is therefore the prefix form with a urlkey filter, and fetches use each
capture's OWN original url (not a reconstructed bare one), because Wayback
keys the payload by the url it actually crawled.

REUSABLE LESSON: a "the data does not exist" finding from an index is only as
good as the key you looked it up by. Before writing off a source, re-query it
by prefix/substring and diff the hit counts; a cache-busting query string is
the single most common way a real record hides from an exact-URL lookup.

WHAT THIS SCRIPT DOES
=====================
1. Query CDX (prefix + urlkey filter) for every 200 snapshot of the feed and
   keep (timestamp, original-url) pairs.
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
# b133: the PREFIX form. An exact-url query sees only the 98 bare-URL captures
# (2022 + 2026) and hides the 989 `?version=<hash>` captures of 2021..2025,
# because Wayback keys them under a different urlkey. See module docstring.
CDX = ("http://web.archive.org/cdx/search/cdx"
       "?url=nfs.faireconomy.media&matchType=prefix"
       "&filter=urlkey:.*ff_calendar_thisweek\\.json.*"
       "&output=json&fl=timestamp,original,statuscode,length"
       "&collapse=timestamp:8")
UA = "Mozilla/5.0 (X11; Linux x86_64) hermes-trading-b132/1.0 (research archive)"

# Snapshots older than this are outside every lab window (the 2022 captures)
# and only add noise; the earliest leg start is 2025-01-06.
MIN_SNAPSHOT = "20250101"


def _get(url: str, timeout: int = 30, attempts: int = 4) -> bytes:
    """GET with backoff. The CDX index intermittently accepts the connection
    and then never answers (measured 2026-09-07: the prefix query succeeded in
    3s on one call and timed out at 30s on the next), so a single-attempt fetch
    turns a live archive into a false 'no snapshots'."""
    import time
    last = None
    for i in range(attempts):
        try:
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
        except Exception as exc:                                # noqa: BLE001
            last = exc
            if i < attempts - 1:
                time.sleep(5 * (i + 1))
    raise last


def snapshot_list() -> list[tuple[str, str]]:
    """Every 200-status daily capture of the feed as (timestamp, original-url),
    oldest first.

    b133: the ORIGINAL url is carried through to the fetch, not rebuilt from
    FEED. The 2021..2025 crawls recorded `...json?version=<hash>` and Wayback
    serves the payload under the url it actually crawled, so a reconstructed
    bare url 404s for exactly the years we are trying to recover.
    """
    rows = json.loads(_get(CDX, timeout=90).decode("utf-8", "replace"))[1:]
    out = {}
    for r in rows:
        if len(r) < 3 or r[2] != "200":
            continue
        ts, orig = r[0], r[1]
        if ts < MIN_SNAPSHOT or not orig.endswith(".json") and ".json?" not in orig:
            continue
        out.setdefault(ts[:8], (ts, orig))      # one capture per day
    return [out[k] for k in sorted(out)]


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


def fetch_one(snap: tuple[str, str]) -> tuple[str, list[dict], str | None]:
    ts, orig = snap
    url = f"http://web.archive.org/web/{ts}id_/{orig}"
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
          only: list[tuple[str, str]] | None = None) -> dict:
    snaps = only if only is not None else snapshot_list()
    if not snaps:
        raise SystemExit("CDX returned no usable snapshots — archive blocked?")
    events: dict[tuple, dict] = {}
    failures: dict[str, str] = {}        # transient — must end up at zero
    unrecoverable: dict[str, str] = {}   # Wayback lists it, payload is gone
    per_week: dict[str, int] = {}

    def consume(ts: str, items: list[dict], err: str | None) -> bool:
        """True when the error is transient (worth a retry pass)."""
        if not err:
            per_week[ts[:8]] = len(items)
            for e in items:
                events[(e["date"], e["currency"], e["title"])] = e
            return False
        if "404" in err:
            unrecoverable[ts] = err      # orphan CDX row: index lies, payload gone
            return False
        failures[ts] = err
        return True

    def pass_over(todo: list[tuple[str, str]], serial: bool) -> list:
        import time
        retry = []
        if serial:                                       # polite serial path
            for snap in todo:
                if consume(*fetch_one(snap)):
                    retry.append(snap)
                time.sleep(0.4)
            return retry
        with ThreadPoolExecutor(max_workers=workers) as ex:
            for ts, items, err in ex.map(fetch_one, todo):
                if consume(ts, items, err):
                    retry.append((ts, next(o for t, o in snaps if t == ts)))
        return retry

    retry = pass_over(snaps, serial=workers <= 1)
    for round_no in range(2):                            # transient-only retries
        if not retry:
            break
        if verbose:
            print(f"retry pass {round_no + 1}: {len(retry)} transient failures")
        import time
        time.sleep(10)
        retry = pass_over(retry, serial=True)

    stamps = sorted(per_week)
    # a ts that failed transiently and then 404'd on the retry pass is
    # unrecoverable, not a gap worth retrying — reconcile so `failures` means
    # exactly "still missing, and the archive should be re-fetched".
    for ts in unrecoverable:
        failures.pop(ts, None)
    ordered = sorted(events.values(), key=lambda e: (str(e["date"]),
                                                     e["currency"], e["title"]))
    dates = [e["date"] for e in ordered if e.get("date")]
    return {"source": "forexfactory_via_internet_archive_cdx",
            "feed": FEED,
            "n_snapshots": len(stamps),
            "n_snapshots_failed": len(failures),
            "failures": failures,
            "n_snapshots_unrecoverable": len(unrecoverable),
            "unrecoverable": unrecoverable,
            "snapshot_first": stamps[0] if stamps else None,
            "snapshot_last": stamps[-1] if stamps else None,
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
    print(f"snapshots: {led['n_snapshots']} (failed {led['n_snapshots_failed']}, "
          f"unrecoverable {led['n_snapshots_unrecoverable']})")
    print(f"events: {led['n_events']}  high USD/XAU: {led['n_high_gold']}")
    print(f"event span: {led['event_first']} .. {led['event_last']}")
    print("saved:", os.path.abspath(p))


if __name__ == "__main__":
    main()
