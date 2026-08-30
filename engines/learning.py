"""Adaptive learning engine — journal analysis → parameter adjustments.

Phase 6 of the Hermes project: the system must "learn from data and past
performance". This module closes the loop:

1. journal()      — records every executed trade's outcome (from MT5 deal
                    history) into data/xau_plan/trade_journal.csv
2. analyze()      — computes stats per setup-grade / session / side, plus a
                    session × regime breakdown (asia/london/newyork ×
                    trend/range) so risk_mult can become session-aware later
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


def journal(bridge, days: int = 30) -> int:
    """Sync closed MT5 deals into the journal CSV. Returns rows added."""
    existing_keys = {(r.get('ticket'), r.get('close_time')) for r in _load_journal()}
    r = bridge.get_history_deals("XAUUSD", days)
    if not (isinstance(r, dict) and r.get('ok')):
        return 0
    deals = r.get('data', r.get('deals', [])) or []
    # Map order-ticket → entry deal type, so we can record the TRADE side
    # (a BUY position is closed by a SELL deal — the closing deal type is the
    # opposite of the trade direction).
    entry_side_by_order: dict[str, str] = {}
    for d in deals:
        if str(d.get('entry', '1')) in ('0', 'IN'):
            entry_side_by_order[str(d.get('order') or d.get('ticket'))] = \
                'BUY' if str(d.get('type')) in ('0', 'BUY') else 'SELL'
    rows = []
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
        })
    if not rows:
        return 0
    journal_csv = paths.trade_journal()
    new_file = not journal_csv.exists()
    journal_csv.parent.mkdir(parents=True, exist_ok=True)
    with journal_csv.open('a', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        if new_file:
            w.writeheader()
        w.writerows(rows)
    return len(rows)


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

    def stats(sub: list[dict]) -> dict:
        profits = [float(r['profit'] or 0) for r in sub if r.get('profit') not in (None, '')]
        if not profits:
            return {}
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
    if wr < 0.40 and avg < 0:
        if cur_rr < RR_FLOOR_CEILING:
            changes['min_rr'] = _clamp(cur_rr + 0.25, RR_FLOOR_FLOOR, RR_FLOOR_CEILING)
        if cur_grade_idx < GRADES.index(GRADE_CEILING):
            changes['min_grade'] = GRADES[cur_grade_idx + 1]
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
    learning_json.parent.mkdir(parents=True, exist_ok=True)
    learning_json.write_text(json.dumps(cur, indent=1), encoding='utf-8')
    return cur


def run_learning_cycle(bridge) -> dict:
    """One full loop: journal → analyze → adjust → apply. Called by cron/daemons."""
    added = journal(bridge)
    deltas = adjustments()
    state = apply(deltas.get('changes') or {})
    return {'journaled': added, 'proposal': deltas, 'learning_state': state}
