"""Adaptive learning engine — journal analysis → parameter adjustments.

Phase 6 of the Hermes project: the system must "learn from data and past
performance". This module closes the loop:

1. journal()      — records every executed trade's outcome (from MT5 deal
                    history) into data/xau_plan/trade_journal.csv
2. analyze()      — computes stats per setup-grade / session / side, plus a
                    session × regime breakdown (asia/london/newyork ×
                    trend/range). Session size is a STATIC prior on the
                    executor (SESSION_RISK_MULT: asia 0.5) — this module
                    still only tightens the GLOBAL risk_mult.
3. adjustments()  — proposes parameter deltas (risk budget, min grade,
                    RR floor) from the stats, with hard safety clamps
4. apply()        — writes the deltas into data/xau_plan/learning_state.json
                    which evaluate_proposal() consults (adaptive gate)

Rules (safety first):
- Never raises risk above the static cap; learning can only tighten.
- Needs MIN_TRADES_SAMPLE (default 15) before suggesting anything.
- All deltas clamped to small steps (±0.2 grade, ±10% risk, ±0.25 RR).
"""
from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path

from engines import paths  # resolved at CALL time so tests can redirect the tree

# Static ceilings — learning may never exceed these
RISK_PCT_CEILING = 0.02          # same as auto_executor.MAX_RISK_PER_TRADE_PCT
RISK_PCT_FLOOR = 0.005
RR_FLOOR_FLOOR = 1.0
RR_FLOOR_CEILING = 2.5
GRADE_CEILING = "A"              # can't require better than the best grade

MIN_TRADES_SAMPLE = 15

GRADES = ["C", "B", "A"]         # ordered worst → best


# ── 1. Journal ────────────────────────────────────────────────────────────

def _load_journal() -> list[dict]:
    journal_csv = paths.trade_journal()
    if not journal_csv.exists():
        return []
    with journal_csv.open(newline='', encoding='utf-8') as f:
        return list(csv.DictReader(f))


# b152: `entry_commission` is APPENDED LAST, never inserted — the same rule
# b144 proved on the risk ledger: a short row written by a drifted process
# stays readable under a wider header (the extra key lands as None under
# DictReader, which readers treat as 0.0), while a mid-tuple column would
# misalign every field after it. The broker charges commission on the IN deal
# as well as the OUT deal (b150: -6.12$ of -12.24$ over 30d lived only on IN
# deals), and journal() writes ONE ROW PER CLOSING DEAL — so without this
# column every net-P&L consumer (the b151 loop, weekly_report, the b143
# reader) is blind to exactly half the commission cost.
JOURNAL_FIELDS = ['ticket', 'close_time', 'side', 'volume', 'price',
                  'profit', 'comment', 'journaled_at', 'position_id',
                  'commission', 'swap', 'entry_commission']


# Columns that can be backfilled from broker deal history by ticket.
_BACKFILLABLE = ('position_id', 'commission', 'swap')


def _entry_fee_totals(deals: list[dict]) -> dict[str, dict]:
    """position_id -> {'fee': sum of IN-deal commission, 'vol': sum IN volume}.

    The feed carries the opening deals too (entry == 0/IN); their commission
    is what the closing-deal rows used to drop (b150)."""
    out: dict[str, dict] = {}
    for d in deals:
        if str(d.get('entry', '')) not in ('0', 'IN'):
            continue
        pid = str(d.get('position_id') or d.get('order') or '')
        if not pid:
            continue
        g = out.setdefault(pid, {'fee': 0.0, 'vol': 0.0})
        try:
            g['fee'] += float(d.get('commission') or 0)
            g['vol'] += float(d.get('volume') or 0)
        except (TypeError, ValueError):
            pass
    return out


def _entry_fee_share(fees: dict[str, dict], deal: dict) -> str:
    """This closing deal's slice of its position's IN-deal commission.

    Prorated by volume: a position opened once and closed in three parts
    bears its entry fee across the three legs in proportion to closed
    volume, so the shares sum to the broker's exact total (volumes were
    verified to reconcile on all 29 live positions, b152 probe). Returns
    '' when the position or its entry deals cannot be resolved — an honest
    zero at read time, never a guess."""
    pid = str(deal.get('position_id') or deal.get('order') or '')
    g = fees.get(pid)
    if not g or not g['fee'] or not g['vol']:
        return ''
    try:
        v = float(deal.get('volume') or 0)
    except (TypeError, ValueError):
        return ''
    return str(round(g['fee'] * (v / g['vol']), 4))


def _migrate_journal(journal_csv, deals_by_ticket: dict,
                     entry_fees: dict[str, dict] | None = None) -> None:
    """Add missing columns to an existing journal without losing rows.

    DictWriter appends by fieldnames, so writing a wider row into a narrower
    legacy header silently misaligns every subsequent column. Rewrite the file
    instead, backfilling position_id/commission/swap from the deal history
    where the ticket still resolves, and entry_commission (b152) from the
    position's IN deals, prorated by volume across its closing legs.
    """
    with journal_csv.open(newline='', encoding='utf-8') as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        d = deals_by_ticket.get(r.get('ticket')) or {}
        for col in _BACKFILLABLE:
            if not (r.get(col) or '').strip():
                r[col] = str(d.get(col, '') or '')
        if entry_fees and not (r.get('entry_commission') or '').strip():
            r['entry_commission'] = _entry_fee_share(entry_fees, {
                'position_id': r.get('position_id') or '',
                'order': '', 'volume': r.get('volume') or 0})
    with journal_csv.open('w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=JOURNAL_FIELDS)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, '') for k in JOURNAL_FIELDS})


def journal(bridge, days: int = 30) -> int:
    """Sync closed MT5 deals into the journal CSV. Returns rows added.

    One row per CLOSING DEAL, which is not the same as one row per trade: a
    position closed in three parts (partial TPs) writes three rows. Consumers
    that report a trade count must group by `position_id` — see
    `position_count()` below. (2026-09-04: this distinction is what made the
    weekly report claim "34 trades" for 23 actual positions.)
    """
    existing_keys = {(r.get('ticket'), r.get('close_time')) for r in _load_journal()}
    r = bridge.get_history_deals("XAUUSD", days)
    if not (isinstance(r, dict) and r.get('ok')):
        return 0
    deals = r.get('data', r.get('deals', [])) or []
    deals_by_ticket = {str(d.get('ticket')): d for d in deals}
    # b152: the broker's IN-deal commission never appears on a closing-deal
    # row, so the journal folds it into `entry_commission` — prorated by
    # volume when one position closes in several legs.
    entry_fees = _entry_fee_totals(deals)
    # Map order-ticket → entry deal type, so we can record the TRADE side
    # (a BUY position is closed by a SELL deal — the closing deal type is the
    # opposite of the trade direction).
    entry_side_by_order: dict[str, str] = {}
    for d in deals:
        if str(d.get('entry', '1')) in ('0', 'IN'):
            entry_side_by_order[str(d.get('order') or d.get('ticket'))] = \
                'BUY' if str(d.get('type')) in ('0', 'BUY') else 'SELL'
    rows = []
    journal_csv = paths.trade_journal()
    for d in deals:
        ticket = str(d.get('ticket') or d.get('order') or '')
        close_time = str(d.get('time_done') or d.get('time') or '')
        # entry deals (DEAL_ENTRY_IN) open positions; we journal closes only
        if int(d.get('entry', 1) if str(d.get('entry', 1)).isdigit() else 1) == 0:
            continue
        if (ticket, close_time) in existing_keys:
            continue
        if not ticket:
            continue
        close_type = 'BUY' if str(d.get('type')) in ('0', 'BUY') else 'SELL'
        order_ref = str(d.get('order') or '')
        trade_side = entry_side_by_order.get(order_ref) or (
            'SELL' if close_type == 'BUY' else 'BUY')  # fallback: invert close
        rows.append({
            'ticket': ticket,
            'close_time': close_time,
            'side': trade_side,
            'volume': d.get('volume', ''),
            'price': d.get('price', ''),
            'profit': d.get('profit', ''),
            'comment': (d.get('comment') or '')[:40],
            'journaled_at': datetime.now(timezone.utc).isoformat(),
            'position_id': str(d.get('position_id') or ''),
            'commission': d.get('commission', ''),
            'swap': d.get('swap', ''),
            'entry_commission': _entry_fee_share(entry_fees, d),
        })
    journal_csv.parent.mkdir(parents=True, exist_ok=True)
    _ensure_journal_schema(journal_csv, deals_by_ticket, entry_fees)
    if not rows:
        return 0
    with journal_csv.open('a', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=JOURNAL_FIELDS)
        if not journal_csv.exists() or journal_csv.stat().st_size == 0:
            w.writeheader()
        w.writerows(rows)
    return len(rows)


def _ensure_journal_schema(journal_csv, deals_by_ticket: dict,
                           entry_fees: dict[str, dict] | None = None) -> None:
    """Migrate a legacy journal file to the current column set, in place.

    Re-runs whenever any backfillable column is missing from the header, so
    adding a field later (e.g. commission) still heals existing files.
    """
    if not journal_csv.exists():
        return
    with journal_csv.open(encoding='utf-8') as f:
        header = f.readline()
    if all(col in header for col in JOURNAL_FIELDS):
        return
    _migrate_journal(journal_csv, deals_by_ticket, entry_fees)


def position_count(rows: list[dict]) -> int:
    """Distinct trades represented by journal rows.

    Journal rows are per closing deal, so a position closed in parts yields
    several rows. Rows with no position_id (legacy, un-backfillable) each count
    as their own position — that is the conservative reading.
    """
    seen = set()
    n = 0
    for r in rows:
        pid = str(r.get('position_id') or '').strip()
        if not pid:
            n += 1
            continue
        if pid not in seen:
            seen.add(pid)
            n += 1
    return n


def group_positions(rows: list[dict]) -> dict[str, dict]:
    """Aggregate journal rows into per-position results.

    Returns {position_id: {profit, volume, close_time, side, legs}}. Positions
    are keyed by position_id; legacy rows without one fall back to their own
    ticket so they stay distinct.
    """
    out: dict[str, dict] = {}
    for r in rows:
        key = str(r.get('position_id') or '').strip() or f"t:{r.get('ticket')}"
        try:
            profit = float(r.get('profit') or 0)
        except (TypeError, ValueError):
            profit = 0.0
        try:
            ct = float(r.get('close_time') or 0)
        except (TypeError, ValueError):
            ct = 0.0
        def _num(col):
            try:
                return float(r.get(col) or 0)
            except (TypeError, ValueError):
                return 0.0

        g = out.setdefault(key, {'profit': 0.0, 'net': 0.0, 'volume': 0.0,
                                 'close_time': 0.0, 'side': r.get('side', ''),
                                 'legs': 0})
        g['profit'] += profit
        # Net = gross P&L + commission + swap + entry_commission (b152: the
        # broker's IN-deal fee, prorated to this leg). Legacy rows may lack
        # these columns until migrated, in which case net == gross.
        g['net'] += (profit + _num('commission') + _num('swap')
                     + _num('entry_commission'))
        try:
            g['volume'] = max(g['volume'], float(r.get('volume') or 0))
        except (TypeError, ValueError):
            pass
        g['close_time'] = max(g['close_time'], ct)
        g['legs'] += 1
    return out


# ── 2. Analysis ───────────────────────────────────────────────────────────

# Session buckets (UTC) — must mirror hermes_runtime._detect_session so journal
# stats match the session that actually produced the plan. Kept as a local copy
# on purpose: learning must stay importable without the runtime/bridge stack.
SESSION_BOUNDS = ((0, 7, 'asia'), (7, 13, 'london'), (13, 24, 'newyork'))
REGIME_BUCKETS = {'breakout_continuation': 'trend',
                  'pullback_continuation': 'trend',
                  'range': 'range'}


def session_of(ts: datetime) -> str:
    """UTC timestamp → 'asia' | 'london' | 'newyork' (hermes_runtime bounds)."""
    for lo, hi, name in SESSION_BOUNDS:
        if lo <= ts.hour < hi:
            return name
    return 'newyork'


def _regime_for_plan(plan_id: str) -> str:
    """Join execution_log.plan_id → plan_history/<ts>_<plan_id>.json.

    BUG FIX 2026-08-30: globbed PLAN_DIR instead of PLAN_DIR/plan_history —
    matched nothing, so EVERY regime bucket was 'unknown' and the whole
    session×regime learning breakdown was dead. Also: one plan_id can be
    archived multiple times (reassess churn) — use the NEWEST archive
    instead of bailing on ambiguity.
    """
    if not plan_id:
        return ''
    matches = sorted((paths.plan_dir() / 'plan_history').glob(f'*_{plan_id}.json'))
    if not matches:
        return ''
    try:
        data = json.loads(matches[-1].read_text(encoding='utf-8'))
    except Exception:
        return ''
    return str((data.get('quality') or {}).get('regime') or '')


def _bucket_for(regime: str) -> str:
    return REGIME_BUCKETS.get(regime, 'other')


def analyze() -> dict:
    rows = _load_journal()
    out = {'sample': len(rows), 'by_side': {}, 'overall': {},
           'by_session': {}, 'by_session_regime': {}}
    if not rows:
        return out

    # b151: stats are per POSITION and on NET P&L, not per closing leg on gross.
    # The journal writes one row per closing deal (b75), so a position taken
    # into several TPs contributes several rows; and `profit` excludes
    # commission/swap. On the leg/gross view the loop read win_rate 0.737 and
    # avg +0.07$ while the same data per-position-net read 0.679 and -0.11$ —
    # i.e. the loop believed a losing system was profitable and its only
    # defensive trigger (`wr < 0.40 and avg < 0`) could not fire.
    # b152: the net formula lives in ONE place — group_positions — which now
    # also folds entry_commission (the broker's IN-deal fee). b151 hand-copied
    # that formula into stats() and b152 would have had to copy the fix twice;
    # a duplicated funnel is how the loop went blind in the first place.
    def stats(sub: list[dict]) -> dict:
        legs = [r for r in sub if r.get('profit') not in (None, '')]
        if not legs:
            return {}
        profits = [g['net'] for g in group_positions(legs).values()]
        wins = sum(1 for p in profits if p > 0)
        return {
            'trades': len(profits),
            'win_rate': round(wins / len(profits), 3),
            'net_pnl': round(sum(profits), 2),
            'avg_pnl': round(sum(profits) / len(profits), 2),
        }

    out['overall'] = stats(rows)
    for side in ('BUY', 'SELL'):
        sub = [r for r in rows if r.get('side') == side]
        s = stats(sub)
        if s:
            out['by_side'][side] = s

    # ── session × regime breakdown ──
    # Trade time = journal close_time (unix seconds or ISO). Regime = the
    # bucketed quality.regime of the plan attributed via EXACT ticket join
    # (execution_log.ticket, since 2026-08-30) with a time-proximity fallback
    # for historical rows: the most recent successful (result_ok, non-dry-run)
    # plan execution at or before its close, within EXEC_JOIN_LOOKBACK_H hours.
    # No match → 'unknown' (bucket is skipped from regime stats, never guessed).
    def _trade_time(row: dict):
        raw = str(row.get('close_time') or '')
        if raw.isdigit():
            return datetime.fromtimestamp(int(raw), tz=timezone.utc)
        try:
            ts = datetime.fromisoformat(raw)
        except ValueError:
            return None
        return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)

    EXEC_JOIN_LOOKBACK_H = 48

    exec_events: list[tuple[datetime, str]] = []   # (at, plan_id)
    exec_by_ticket: dict[str, str] = {}            # ticket → plan_id (exact join)
    exec_log = paths.plan_dir() / 'execution_log.csv'
    try:
        with exec_log.open(newline='', encoding='utf-8') as f:
            for r in csv.DictReader(f):
                if str(r.get('dry_run', '')).strip().lower() == 'true':
                    continue
                if str(r.get('result_ok', '')).strip().lower() != 'true':
                    continue
                plan_id = str(r.get('plan_id') or '').strip()
                if not plan_id or plan_id == 'signal':
                    continue
                _tkt = str(r.get('ticket') or '').strip()
                if _tkt and _tkt not in ('None', ''):
                    exec_by_ticket[_tkt] = plan_id
                try:
                    at = datetime.fromisoformat(str(r.get('at') or ''))
                except ValueError:
                    continue
                if at.tzinfo is None:
                    at = at.replace(tzinfo=timezone.utc)
                exec_events.append((at, plan_id))
    except OSError:
        pass
    exec_events.sort(key=lambda x: x[0])

    def _plan_for_close(close_ts: datetime, ticket: str = '') -> str:
        # Exact linkage first (execution_log.ticket exists since 2026-08-30);
        # fall back to time-proximity for historical rows without a ticket.
        if ticket and ticket in exec_by_ticket:
            return exec_by_ticket[ticket]
        best = ''
        for at, plan_id in exec_events:
            if at > close_ts:
                break
            if (close_ts - at).total_seconds() <= EXEC_JOIN_LOOKBACK_H * 3600:
                best = plan_id
        return best

    by_session: dict[str, list[dict]] = {}
    by_session_regime: dict[str, dict[str, list[dict]]] = {}
    for row in rows:
        ts = _trade_time(row)
        session = session_of(ts) if ts else 'unknown'
        plan_id = _plan_for_close(ts, str(row.get('ticket') or '').strip()) if ts else ''
        regime = _regime_for_plan(plan_id)
        bucket = _bucket_for(regime) if regime else 'unknown'
        by_session.setdefault(session, []).append(row)
        by_session_regime.setdefault(session, {}).setdefault(bucket, []).append(row)

    for session, sub in sorted(by_session.items()):
        s = stats(sub)
        if s:
            out['by_session'][session] = s
    for session, buckets in sorted(by_session_regime.items()):
        out['by_session_regime'][session] = {}
        for bucket, sub in sorted(buckets.items()):
            s = stats(sub)
            if s:
                out['by_session_regime'][session][bucket] = s
    return out


# ── 3. Adjustments ────────────────────────────────────────────────────────

def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def adjustments() -> dict:
    """Propose parameter deltas from journal stats. Empty dict = keep params."""
    stats = analyze()
    overall = stats.get('overall') or {}
    if overall.get('trades', 0) < MIN_TRADES_SAMPLE:
        return {'reason': f'insufficient_sample_{overall.get("trades", 0)}', 'changes': {}}

    changes: dict[str, float] = {}
    wr = float(overall.get('win_rate', 0) or 0)
    avg = float(overall.get('avg_pnl', 0) or 0)

    cur = load_learning_state()
    cur_rr = float(cur.get('min_rr', 1.5))
    cur_grade_idx = GRADES.index(cur.get('min_grade', 'B'))
    cur_risk = float(cur.get('risk_mult', 1.0))

    # SAFETY RULE: learning can only TIGHTEN. risk_mult may go DOWN when losing
    # but may never be raised here — relaxation is done by the operator, not by
    # a small-sample win streak (legacy bug: it relaxed at WR>=0.55 which let a
    # lucky cluster re-inflate risk right before a losing streak).
    if avg < 0 and wr < 0.40:
        if cur_rr < RR_FLOOR_CEILING:
            changes['min_rr'] = _clamp(cur_rr + 0.25, RR_FLOOR_FLOOR, RR_FLOOR_CEILING)
        if cur_grade_idx < GRADES.index(GRADE_CEILING):
            changes['min_grade'] = GRADES[cur_grade_idx + 1]
        changes['risk_mult'] = _clamp(cur_risk - 0.1, 0.5, 1.0)
    elif avg < 0:
        # Fat left tail with a still-healthy hit-rate (live 65% WR / avg −$3).
        # SIZE only. Raising min_rr here is a kill switch, not a filter:
        # _reanchor_blueprint manufactures every entry at 1.55R (b84: 99.7%
        # of the funnel sits in 1.55±0.06, and the first +0.25 step to 1.75
        # drops 98.9–100% of trades). Grade stays put — same reason as before.
        changes['risk_mult'] = _clamp(cur_risk - 0.1, 0.5, 1.0)
    # NOTE: sell_rr_extra was removed — it was produced here but never consumed
    # by any consumer (dead config).

    return {'sample': overall.get('trades'), 'win_rate': wr, 'changes': changes}


# ── 4. State + apply ─────────────────────────────────────────────────────

def load_learning_state() -> dict:
    """Effective adaptive parameters (defaults = current static config)."""
    learning_json = paths.learning_state()
    if learning_json.exists():
        try:
            return json.loads(learning_json.read_text(encoding='utf-8'))
        except Exception:
            pass
    return {'min_rr': 1.5, 'min_grade': 'B', 'risk_mult': 1.0,
            'updated_at': None}


def apply(deltas: dict) -> dict:
    """Merge proposed changes into learning_state.json (with clamps)."""
    if not deltas:
        return load_learning_state()
    cur = load_learning_state()
    if 'min_rr' in deltas:
        cur['min_rr'] = _clamp(float(deltas['min_rr']), RR_FLOOR_FLOOR, RR_FLOOR_CEILING)
    if 'min_grade' in deltas and deltas['min_grade'] in GRADES:
        if GRADES.index(deltas['min_grade']) >= GRADES.index(cur.get('min_grade', 'B')):
            cur['min_grade'] = deltas['min_grade']      # only tighten or keep
    if 'risk_mult' in deltas:
        # tighten-only: apply() can only lower risk_mult, never raise it
        proposed = float(deltas['risk_mult'])
        cur['risk_mult'] = _clamp(min(proposed, cur.get('risk_mult', 1.0)), 0.5, 1.0)
    cur['updated_at'] = datetime.now(timezone.utc).isoformat()
    learning_json = paths.learning_state()
    paths.write_json_atomic(learning_json, cur, indent=1)
    return cur


def run_learning_cycle(bridge) -> dict:
    """One full loop: journal → analyze → adjust → apply. Called by cron/daemons."""
    added = journal(bridge)
    deltas = adjustments()
    state = apply(deltas.get('changes') or {})
    return {'journaled': added, 'proposal': deltas, 'learning_state': state}
