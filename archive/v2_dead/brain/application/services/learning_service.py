"""Learning service - adaptive parameter adjustments.

Manages journal, computes trade statistics, and proposes
parameter adjustments based on performance.
"""
from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from brain.domain.entities.learning import (
    SetupGrade,
    TradingSession,
    RegimeBucket,
    JournalEntry,
    PositionSummary,
    TradeStatistics,
    AnalysisResult,
    LearningAdjustments,
    LearningState,
)


class LearningService:
    """Adaptive learning and parameter adjustment service."""
    
    # Constants from legacy
    MIN_TRADES_SAMPLE = 15
    GRADES = ['C', 'B', 'A']
    GRADE_CEILING = 'A'
    RR_FLOOR_FLOOR = 1.5
    RR_FLOOR_CEILING = 2.5
    
    # Session bounds (UTC hours)
    SESSION_BOUNDS = [
        (0, 7, TradingSession.ASIA),
        (7, 13, TradingSession.LONDON),
        (13, 24, TradingSession.NEWYORK),
    ]
    
    # Regime bucket mapping
    REGIME_BUCKETS = {
        'breakout_continuation': RegimeBucket.TREND,
        'pullback_continuation': RegimeBucket.TREND,
        'range': RegimeBucket.RANGE,
    }
    
    def __init__(self, db=None):
        """Initialize with optional database."""
        self.db = db
    
    # ── 1. Position Aggregation ──────────────────────────────────────────
    
    @staticmethod
    def group_positions(rows: list[dict]) -> dict[str, PositionSummary]:
        """Aggregate journal rows into per-position results.
        
        A position may be closed in multiple legs (partial TPs).
        Each leg is one journal row. This aggregates them.
        """
        positions: dict[str, dict] = {}
        
        for row in rows:
            # Key by position_id, fallback to ticket for legacy rows
            pid = str(row.get('position_id') or '').strip()
            key = pid if pid else f"t:{row.get('ticket')}"
            
            def _float(field: str) -> float:
                try:
                    return float(row.get(field) or 0)
                except (TypeError, ValueError):
                    return 0.0
            
            # Aggregate
            if key not in positions:
                positions[key] = {
                    'position_id': key,
                    'side': row.get('side', ''),
                    'profit': 0.0,
                    'net': 0.0,
                    'volume': 0.0,
                    'close_time': 0.0,
                    'legs': 0,
                }
            
            pos = positions[key]
            pos['profit'] += _float('profit')
            pos['net'] += (
                _float('profit') +
                _float('commission') +
                _float('swap') +
                _float('entry_commission')
            )
            pos['volume'] = max(pos['volume'], _float('volume'))
            pos['close_time'] = max(pos['close_time'], _float('close_time'))
            pos['legs'] += 1
        
        # Convert to domain entities
        return {
            key: PositionSummary(
                position_id=data['position_id'],
                side=data['side'],
                volume=data['volume'],
                profit=data['profit'],
                net_pnl=data['net'],
                close_time=data['close_time'],
                legs=data['legs'],
            )
            for key, data in positions.items()
        }
    
    # ── 2. Statistics Computation ────────────────────────────────────────
    
    @staticmethod
    def compute_statistics(rows: list[dict]) -> Optional[TradeStatistics]:
        """Compute trade statistics from journal rows.
        
        Stats are per POSITION (not per leg) and on NET P&L.
        """
        # Filter valid rows
        valid = [r for r in rows if r.get('profit') not in (None, '')]
        if not valid:
            return None
        
        # Group by position
        positions = LearningService.group_positions(valid)
        if not positions:
            return None
        
        # Extract net P&Ls
        pnls = [pos.net_pnl for pos in positions.values()]
        wins = sum(1 for pnl in pnls if pnl > 0)
        
        return TradeStatistics(
            trades=len(pnls),
            win_rate=round(wins / len(pnls), 3),
            net_pnl=round(sum(pnls), 2),
            avg_pnl=round(sum(pnls) / len(pnls), 2),
        )
    
    # ── 3. Session Detection ─────────────────────────────────────────────
    
    @classmethod
    def detect_session(cls, ts: datetime) -> TradingSession:
        """Detect trading session from UTC timestamp."""
        for lo, hi, session in cls.SESSION_BOUNDS:
            if lo <= ts.hour < hi:
                return session
        return TradingSession.NEWYORK
    
    @staticmethod
    def parse_trade_time(row: dict) -> Optional[datetime]:
        """Extract close time from journal row."""
        raw = str(row.get('close_time') or '')
        
        # Unix timestamp
        if raw.isdigit():
            try:
                return datetime.fromtimestamp(int(raw), tz=timezone.utc)
            except (ValueError, OSError):
                return None
        
        # ISO format
        try:
            ts = datetime.fromisoformat(raw)
            return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    
    # ── 4. Regime Detection ──────────────────────────────────────────────
    
    @classmethod
    def bucket_regime(cls, regime: str) -> RegimeBucket:
        """Map plan regime to bucket."""
        return cls.REGIME_BUCKETS.get(
            regime,
            RegimeBucket.OTHER if regime else RegimeBucket.UNKNOWN
        )
    
    @staticmethod
    def find_regime_for_plan(plan_id: str, plan_dir: Path) -> str:
        """Lookup regime from archived plan."""
        if not plan_id:
            return ''
        
        history_dir = plan_dir / 'plan_history'
        if not history_dir.exists():
            return ''
        
        # Find all archives of this plan (may be multiple)
        matches = sorted(history_dir.glob(f'*_{plan_id}.json'))
        if not matches:
            return ''
        
        # Use newest archive
        try:
            data = json.loads(matches[-1].read_text(encoding='utf-8'))
            return str((data.get('quality') or {}).get('regime') or '')
        except Exception:
            return ''
    
    # ── 5. Analysis ──────────────────────────────────────────────────────
    
    def analyze(
        self,
        rows: list[dict],
        exec_log_path: Optional[Path] = None,
        plan_dir: Optional[Path] = None,
    ) -> AnalysisResult:
        """Compute complete trade statistics breakdown.
        
        Args:
            rows: Journal rows (from CSV or database)
            exec_log_path: Path to execution_log.csv
            plan_dir: Path to plans directory
        
        Returns:
            AnalysisResult with overall, by_side, by_session, by_session_regime
        """
        if not rows:
            return AnalysisResult(
                sample_size=0,
                overall=TradeStatistics(0, 0.0, 0.0, 0.0),
                by_side={},
                by_session={},
                by_session_regime={},
            )
        
        # Overall stats
        overall = self.compute_statistics(rows) or TradeStatistics(0, 0.0, 0.0, 0.0)
        
        # By side
        by_side = {}
        for side in ['BUY', 'SELL']:
            side_rows = [r for r in rows if r.get('side') == side]
            stats = self.compute_statistics(side_rows)
            if stats:
                by_side[side] = stats
        
        # By session and session×regime
        by_session = {}
        by_session_regime = {}
        
        if exec_log_path and plan_dir:
            # Load execution log for regime attribution
            exec_by_ticket, exec_events = self._load_execution_log(exec_log_path)
            
            # Group rows
            session_buckets: dict[str, list[dict]] = {}
            regime_buckets: dict[str, dict[str, list[dict]]] = {}
            
            for row in rows:
                ts = self.parse_trade_time(row)
                if not ts:
                    continue
                
                session = self.detect_session(ts)
                session_key = session.value
                
                # Find plan and regime
                ticket = str(row.get('ticket') or '').strip()
                plan_id = self._find_plan_for_close(
                    ts, ticket, exec_by_ticket, exec_events
                )
                regime = self.find_regime_for_plan(plan_id, plan_dir)
                bucket = self.bucket_regime(regime)
                bucket_key = bucket.value
                
                # Accumulate
                session_buckets.setdefault(session_key, []).append(row)
                regime_buckets.setdefault(session_key, {}).setdefault(
                    bucket_key, []
                ).append(row)
            
            # Compute session stats
            for session_key, session_rows in session_buckets.items():
                stats = self.compute_statistics(session_rows)
                if stats:
                    by_session[session_key] = stats
            
            # Compute session×regime stats
            for session_key, buckets in regime_buckets.items():
                by_session_regime[session_key] = {}
                for bucket_key, bucket_rows in buckets.items():
                    stats = self.compute_statistics(bucket_rows)
                    if stats:
                        by_session_regime[session_key][bucket_key] = stats
        
        return AnalysisResult(
            sample_size=len(rows),
            overall=overall,
            by_side=by_side,
            by_session=by_session,
            by_session_regime=by_session_regime,
        )
    
    def _load_execution_log(
        self, exec_log_path: Path
    ) -> tuple[dict[str, str], list[tuple[datetime, str]]]:
        """Load execution log for regime attribution.
        
        Returns:
            (ticket→plan_id dict, sorted (timestamp, plan_id) events)
        """
        exec_by_ticket: dict[str, str] = {}
        exec_events: list[tuple[datetime, str]] = []
        
        if not exec_log_path.exists():
            return exec_by_ticket, exec_events
        
        try:
            with exec_log_path.open(newline='', encoding='utf-8') as f:
                for row in csv.DictReader(f):
                    # Skip dry_run and failed
                    if str(row.get('dry_run', '')).strip().lower() == 'true':
                        continue
                    if str(row.get('result_ok', '')).strip().lower() != 'true':
                        continue
                    
                    plan_id = str(row.get('plan_id') or '').strip()
                    if not plan_id or plan_id == 'signal':
                        continue
                    
                    # Exact ticket join (since 2026-08-30)
                    ticket = str(row.get('ticket') or '').strip()
                    if ticket and ticket not in ('None', ''):
                        exec_by_ticket[ticket] = plan_id
                    
                    # Time-based events
                    try:
                        at = datetime.fromisoformat(str(row.get('at') or ''))
                        if at.tzinfo is None:
                            at = at.replace(tzinfo=timezone.utc)
                        exec_events.append((at, plan_id))
                    except ValueError:
                        continue
        except OSError:
            pass
        
        exec_events.sort(key=lambda x: x[0])
        return exec_by_ticket, exec_events
    
    @staticmethod
    def _find_plan_for_close(
        close_ts: datetime,
        ticket: str,
        exec_by_ticket: dict[str, str],
        exec_events: list[tuple[datetime, str]],
        lookback_hours: int = 48,
    ) -> str:
        """Find plan_id for a closed trade.
        
        Exact ticket join first, time-proximity fallback.
        """
        # Exact join
        if ticket and ticket in exec_by_ticket:
            return exec_by_ticket[ticket]
        
        # Time-proximity (within lookback window)
        best = ''
        for at, plan_id in exec_events:
            if at > close_ts:
                break
            if (close_ts - at).total_seconds() <= lookback_hours * 3600:
                best = plan_id
        
        return best
    
    # ── 6. Adjustments ───────────────────────────────────────────────────
    
    def propose_adjustments(
        self,
        stats: TradeStatistics,
        current_state: LearningState,
    ) -> LearningAdjustments:
        """Propose parameter adjustments based on performance.
        
        SAFETY RULE: learning can only TIGHTEN.
        Risk multiplier may go DOWN but never UP.
        """
        # Insufficient sample
        if stats.trades < self.MIN_TRADES_SAMPLE:
            return LearningAdjustments(
                risk_multiplier=None,
                min_grade=None,
                min_rr=None,
                reason=f'insufficient_sample_{stats.trades}',
            )
        
        wr = stats.win_rate
        avg = stats.avg_pnl
        
        risk_mult = None
        min_grade = None
        min_rr = None
        
        # Current values
        cur_rr = current_state.min_rr
        cur_grade = current_state.min_grade
        cur_risk = current_state.risk_mult
        
        # Grade index
        try:
            cur_grade_idx = self.GRADES.index(cur_grade.value)
        except (ValueError, AttributeError):
            cur_grade_idx = 1  # Default to 'B'
        
        # Rule 1: Severe underperformance (WR < 40% AND losing)
        if avg < 0 and wr < 0.40:
            # Tighten RR
            if cur_rr < self.RR_FLOOR_CEILING:
                min_rr = self._clamp(
                    cur_rr + 0.25,
                    self.RR_FLOOR_FLOOR,
                    self.RR_FLOOR_CEILING,
                )
            
            # Tighten grade
            if cur_grade_idx < self.GRADES.index(self.GRADE_CEILING):
                min_grade = SetupGrade(self.GRADES[cur_grade_idx + 1])
            
            # Reduce risk
            risk_mult = self._clamp(cur_risk - 0.1, 0.5, 1.0)
            reason = 'severe_underperformance'
        
        # Rule 2: Mild underperformance (losing but WR >= 40%)
        elif avg < 0:
            # Only reduce SIZE, don't touch RR/grade
            proposed = self._clamp(cur_risk - 0.1, 0.5, 1.0)
            if proposed < cur_risk:  # Only if not already at floor
                risk_mult = proposed
            reason = 'mild_underperformance'
        
        else:
            reason = 'no_change'
        
        return LearningAdjustments(
            risk_multiplier=risk_mult,
            min_grade=min_grade,
            min_rr=min_rr,
            reason=reason,
        )
    
    @staticmethod
    def _clamp(value: float, lo: float, hi: float) -> float:
        """Clamp value to range."""
        return max(lo, min(hi, value))
    
    # ── 7. State Management ──────────────────────────────────────────────
    
    def apply_adjustments(
        self,
        current: LearningState,
        adjustments: LearningAdjustments,
    ) -> LearningState:
        """Apply adjustments to current state (with safety clamps).
        
        Only tightening is allowed - relaxation is manual.
        """
        if not adjustments.has_changes:
            return current
        
        # Start with current
        risk_mult = current.risk_mult
        min_grade = current.min_grade
        min_rr = current.min_rr
        
        # Apply risk multiplier (can only decrease)
        if adjustments.risk_multiplier is not None:
            proposed_risk = adjustments.risk_multiplier
            risk_mult = self._clamp(
                min(proposed_risk, risk_mult),
                0.5, 1.0
            )
        
        # Apply grade (can only tighten)
        if adjustments.min_grade is not None:
            if adjustments.min_grade >= min_grade:
                min_grade = adjustments.min_grade
        
        # Apply RR (clamped)
        if adjustments.min_rr is not None:
            min_rr = self._clamp(
                adjustments.min_rr,
                self.RR_FLOOR_FLOOR,
                self.RR_FLOOR_CEILING,
            )
        
        return LearningState(
            risk_mult=risk_mult,
            min_grade=min_grade,
            min_rr=min_rr,
            last_updated=datetime.now(timezone.utc).isoformat(),
        )
