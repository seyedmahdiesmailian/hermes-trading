"""Adaptive learning engine — journal analysis → parameter adjustments.

Phase 6 of the Hermes project: the system must "learn from data and past
performance". This module closes the loop:

1. journal()      — records every executed trade's outcome (from MT5 deal
                    history) into data/xau_plan/trade_journal.csv
2. analyze()      — computes stats per setup-grade / session / side
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

BASE_DIR = Path('/home/ai/hermes-trading')
PLAN_DIR = BASE_DIR / 'data' / 'xau_plan'
JOURNAL_CSV = PLAN_DIR / 'trade_journal.csv'
LEARNING_JSON = PLAN_DIR / 'learning_state.json'

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
    if not JOURNAL_CSV.exists():
        return []
    with JOURNAL_CSV.open(newline='', encoding='utf-8') as f:
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
    new_file = not JOURNAL_CSV.exists()
    JOURNAL_CSV.parent.mkdir(parents=True, exist_ok=True)
    with JOURNAL_CSV.open('a', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        if new_file:
            w.writeheader()
        w.writerows(rows)
    return len(rows)


# ── 2. Analysis ───────────────────────────────────────────────────────────

def analyze() -> dict:
    rows = _load_journal()
    out = {'sample': len(rows), 'by_side': {}, 'overall': {}}
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
    if LEARNING_JSON.exists():
        try:
            return json.loads(LEARNING_JSON.read_text(encoding='utf-8'))
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
    PLAN_DIR.mkdir(parents=True, exist_ok=True)
    LEARNING_JSON.write_text(json.dumps(cur, indent=1), encoding='utf-8')
    return cur


def run_learning_cycle(bridge) -> dict:
    """One full loop: journal → analyze → adjust → apply. Called by cron/daemons."""
    added = journal(bridge)
    deltas = adjustments()
    state = apply(deltas.get('changes') or {})
    return {'journaled': added, 'proposal': deltas, 'learning_state': state}
