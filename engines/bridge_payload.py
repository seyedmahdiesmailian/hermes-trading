"""b66-follow-up — ONE shape-safe reader for the bridge /api/positions reply.

Why this module exists (found by the b66 clean-worktree verification, not
invented): every consumer of `get_positions()` reached into the reply by hand
and none of them agreed on the shape.

  * the v2 server (scripts/mt5_http_server_v2.py) sends {ok: true, data:
    [ {ticket, profit, ...}, ... ], count: N} — `data` is a LIST of dicts;
  * bridge_client._get() wraps EVERY non-200 into
    {ok: false, error: 'HTTP_401', data: <parsed body>}, and when the body is
    not JSON it puts {raw: '<text>'} there — so on an auth failure or an MT5
    error page `data` is a DICT;
  * iterating that dict yields its KEYS (strings), and the next
    `p.get('profit')` dies with AttributeError: 'str' object has no
    attribute 'get'.

That is not a hypothetical: `notifier/dashboards.trade_home()` crashed exactly
this way inside the b50 clean-worktree verification (no .env there, so no
bridge token → 401 → dict `data`), and the ops panel swallowed it into
'🔴 پنل does_not_exist خطا داد' — the unknown-panel fallback test only went
RED because it asserts the HOME panel renders. The same hand-rolled read sits
in the SIGNAL PATH's open-position count (engines/signal_listener), where an
exception is caught and degrades to `_open_ct = 0` — i.e. a 401 reads as
"nothing is open" and the already_in_position gate goes blind, the b65
"auth failure rendered as an empty account" shape wearing a different hat.

hermes_runtime already had the right reader (_positions_list) — but it was
private, so nobody else could use it and each consumer re-invented a worse
copy. This is the single canonical version (b40/b46 pattern: one reader, one
voice), and hermes_runtime now delegates to it.

RULE: never iterate `resp['data']` directly. Call positions_list() — it returns
a list of dicts, or an empty list for ANY other shape (missing key, dict,
string, None, non-dict reply, ok explicitly false). An empty list means "no
positions visible", which is what every caller actually wants; a failure is
signalled by the reply's own ok/error fields, never by an exception. The one
deliberate leniency: a reply with NO `ok` key but a real list under `data`
still counts — the position daemon's bridge-failure guard has always accepted
that shape, and reading it as empty would falsely report every tracked ticket
CLOSED (the duplicate-open hazard documented in position_daemon).
"""
from __future__ import annotations


def positions_list(resp) -> list:
    """The open positions in a /api/positions reply, always a list of dicts.

    Empty list on any deviation: ok explicitly false (bridge down / 401 / MT5
    error), `data` not a list (the _get() error envelope puts a DICT there),
    or items that are not dicts (a text body, a list of strings).

    `ok` missing is NOT a failure: the daemon's own bridge-failure guard has
    always treated {data: [...]} without an ok flag as a usable reply, and
    returning [] there would read as "all positions closed" — which is how a
    tracking state gets wrongly reported CLOSED and re-opened as a duplicate.
    """
    if not isinstance(resp, dict) or resp.get('ok') is False:
        return []
    data = resp.get('data')
    if data is None:
        # legacy/alternate key some bridge builds used
        data = resp.get('positions')
    if not isinstance(data, list):
        return []
    return [p for p in data if isinstance(p, dict)]


def position_count(resp) -> int:
    """How many positions the bridge actually shows (never a guess)."""
    return len(positions_list(resp))


def positions_readable(resp) -> bool:
    """True only when the reply is a TRUSTWORTHY view of the open positions.

    positions_list() deliberately answers "[]" for a broken reply, because
    every READER wants "nothing visible". But a WRITER — the entry gate —
    must not treat "I could not see" as "there is nothing there": that is
    the fail-OPEN shape that already cost -56.7$ when account.positions was
    always 0 and MAX_OPEN_POSITIONS never fired (hermes_runtime, b45).

    The distinction, and the reason it needs its own predicate:

        {"ok": False, "error": "HTTP_401"}  -> list [] , readable False
        {"ok": True,  "data": []}           -> list [] , readable True

    Both are empty; only the second one MEANS empty. Callers that are about
    to open risk must gate on this, not on the count alone.

    Lenient in exactly the same one place positions_list is: a reply with no
    `ok` key but a real list under `data`/`positions` is the shape the
    position daemon has always accepted, and calling it unreadable would
    freeze entries on a healthy bridge.
    """
    if not isinstance(resp, dict) or resp.get('ok') is False:
        return False
    data = resp.get('data')
    if data is None:
        data = resp.get('positions')
    return isinstance(data, list)
