#!/usr/bin/env python3
"""Data Migration: JSON → SQLite Database.

Migrates existing JSON/CSV data to the new centralized database.

Usage:
    python3 scripts/migrate_to_database.py [--dry-run] [--verify]
"""

import sys
import json
import csv
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, List, Any

# Add project root
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from database import Database


class DataMigrator:
    """Migrate data from JSON/CSV to Database."""
    
    def __init__(self, data_dir: Path, db: Database, dry_run: bool = False):
        self.data_dir = data_dir
        self.db = db
        self.dry_run = dry_run
        self.stats = {
            'plans': 0,
            'trades': 0,
            'signals': 0,
            'journal': 0,
            'errors': []
        }
    
    def migrate_all(self):
        """Run all migrations."""
        print("=" * 60)
        print("📦 Hermes Trading - Data Migration")
        print("=" * 60)
        print(f"Source: {self.data_dir}")
        print(f"Target: {self.db.db_path}")
        print(f"Mode: {'DRY RUN' if self.dry_run else 'LIVE'}")
        print()
        
        # Run migrations
        self.migrate_plans()
        self.migrate_trades()
        self.migrate_signals()
        self.migrate_journal()
        
        # Report
        self.print_summary()
    
    def migrate_plans(self):
        """Migrate trading plans from JSON."""
        print("📋 Migrating Plans...")
        
        plan_file = self.data_dir / 'xau_plan' / 'current_plan.json'
        if not plan_file.exists():
            print("  ⚠️  No plans found")
            return
        
        try:
            with plan_file.open() as f:
                plan = json.load(f)
            
            if not self.dry_run:
                # Convert to database format
                db_plan = {
                    'plan_id': plan.get('plan_id', f"plan-{int(datetime.now().timestamp())}"),
                    'symbol': plan.get('symbol', 'XAUUSD'),
                    'timeframe': plan.get('timeframe', 'M5'),
                    'bias': plan.get('bias', 'neutral'),
                    'session': plan.get('session'),
                    'value_low': plan.get('zones', {}).get('value', {}).get('low'),
                    'value_high': plan.get('zones', {}).get('value', {}).get('high'),
                    'long_entry_low': plan.get('zones', {}).get('long_entry', {}).get('low'),
                    'long_entry_high': plan.get('zones', {}).get('long_entry', {}).get('high'),
                    'short_entry_low': plan.get('zones', {}).get('short_entry', {}).get('low'),
                    'short_entry_high': plan.get('zones', {}).get('short_entry', {}).get('high'),
                    'atr': plan.get('atr'),
                    'grade': plan.get('quality', {}).get('grade'),
                    'setup_score': plan.get('quality', {}).get('setup_score'),
                    'created_at': self._parse_timestamp(plan.get('created_at')),
                    'expires_at': self._parse_timestamp(plan.get('expires_at')),
                    'status': 'active' if plan.get('next_reassessment') else 'expired',
                    'analysis': plan.get('context', {})
                }
                
                self.db.save_plan(db_plan)
            
            self.stats['plans'] += 1
            print(f"  ✅ Migrated plan: {plan.get('plan_id', 'unknown')}")
        
        except Exception as e:
            self.stats['errors'].append(f"Plans: {e}")
            print(f"  ❌ Error: {e}")
    
    def migrate_trades(self):
        """Migrate trade history from MT5 deals."""
        print("\n📈 Migrating Trades...")
        
        # Legacy: trades were in execution_log.csv
        exec_log = self.data_dir / 'xau_plan' / 'execution_log.csv'
        if not exec_log.exists():
            print("  ⚠️  No trade log found")
            return
        
        try:
            with exec_log.open(newline='', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                trades = list(reader)
            
            # Filter: only real trades (have ticket)
            real_trades = [t for t in trades if t.get('ticket') and t.get('ticket').strip()]
            
            if not self.dry_run:
                for trade in real_trades:
                    try:
                        # Parse and validate
                        ticket = int(trade['ticket'])
                        entry = float(trade.get('entry', 0))
                        
                        if ticket <= 0 or entry <= 0:
                            continue  # Skip invalid
                        
                        db_trade = {
                            'ticket': ticket,
                            'position_id': None,
                            'symbol': 'XAUUSD',
                            'side': trade.get('side', 'buy').lower(),
                            'volume': float(trade.get('lot', 0.01)),
                            'entry_price': entry,
                            'stop_loss': float(trade.get('sl')) if trade.get('sl') and trade.get('sl').strip() else None,
                            'take_profit': float(trade.get('tp')) if trade.get('tp') and trade.get('tp').strip() else None,
                            'source': 'plan',
                            'source_ref': trade.get('plan_id'),
                            'entry_time': self._parse_timestamp(trade.get('at')),
                            'status': 'closed',
                            'comment': trade.get('source', '')
                        }
                        
                        self.db.save_trade(db_trade)
                        self.stats['trades'] += 1
                    
                    except Exception as e:
                        self.stats['errors'].append(f"Trade {trade.get('ticket')}: {e}")
            else:
                self.stats['trades'] = len(real_trades)
            
            print(f"  ✅ Migrated {len(real_trades)}/{len(trades)} trades (skipped {len(trades)-len(real_trades)} dry-run)")
        
        except Exception as e:
            self.stats['errors'].append(f"Trades: {e}")
            print(f"  ❌ Error: {e}")
    
    def migrate_signals(self):
        """Migrate signals from JSON."""
        print("\n📡 Migrating Signals...")
        
        signals_dir = self.data_dir / 'signals'
        if not signals_dir.exists():
            print("  ⚠️  No signals directory found")
            return
        
        signal_files = list(signals_dir.glob('*.json'))
        
        if not signal_files:
            print("  ⚠️  No signals found")
            return
        
        try:
            for signal_file in signal_files:
                with signal_file.open() as f:
                    signal = json.load(f)
                
                if not self.dry_run:
                    db_signal = {
                        'signal_id': signal.get('id', signal_file.stem),
                        'symbol': signal.get('symbol', 'XAUUSD'),
                        'direction': signal.get('direction', 'buy'),
                        'entry_price': float(signal.get('entry', 0)),
                        'stop_loss': float(signal.get('sl', 0)),
                        'take_profit': float(signal.get('tp', 0)),
                        'source': signal.get('source', 'telegram'),
                        'source_id': signal.get('message_id'),
                        'raw_message': signal.get('text', ''),
                        'confidence_score': signal.get('score', 0.5),
                        'quality': signal.get('quality', 'acceptable'),
                        'status': signal.get('status', 'pending'),
                        'received_at': self._parse_timestamp(signal.get('received_at'))
                    }
                    
                    self.db.save_signal(db_signal)
                
                self.stats['signals'] += 1
            
            print(f"  ✅ Migrated {len(signal_files)} signals")
        
        except Exception as e:
            self.stats['errors'].append(f"Signals: {e}")
            print(f"  ❌ Error: {e}")
    
    def migrate_journal(self):
        """Migrate trade journal from CSV."""
        print("\n📓 Migrating Journal...")
        
        journal_file = self.data_dir / 'xau_plan' / 'trade_journal.csv'
        if not journal_file.exists():
            print("  ⚠️  No journal found")
            return
        
        try:
            with journal_file.open(newline='', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                entries = list(reader)
            
            if not self.dry_run:
                for entry in entries:
                    try:
                        # Journal entries reference trades
                        ticket = int(entry.get('ticket', 0))
                        
                        # Insert journal entry
                        self.db.execute(
                            """INSERT INTO trade_journal (
                                ticket, setup_grade, setup_style, session,
                                net_pnl, exit_type, close_time, notes
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                            (
                                ticket,
                                entry.get('grade'),
                                entry.get('style'),
                                entry.get('session'),
                                float(entry.get('profit', 0)) if entry.get('profit') else None,
                                entry.get('exit_type'),
                                self._parse_timestamp(entry.get('close_time')),
                                entry.get('comment')
                            )
                        )
                        
                        self.stats['journal'] += 1
                    
                    except Exception as e:
                        self.stats['errors'].append(f"Journal entry {entry.get('ticket')}: {e}")
            else:
                self.stats['journal'] = len(entries)
            
            print(f"  ✅ Migrated {len(entries)} journal entries")
        
        except Exception as e:
            self.stats['errors'].append(f"Journal: {e}")
            print(f"  ❌ Error: {e}")
    
    def _parse_timestamp(self, value: Any) -> int:
        """Parse timestamp from various formats."""
        if not value:
            return int(datetime.now(timezone.utc).timestamp())
        
        if isinstance(value, (int, float)):
            return int(value)
        
        if isinstance(value, str):
            try:
                dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
                return int(dt.timestamp())
            except:
                return int(datetime.now(timezone.utc).timestamp())
        
        return int(datetime.now(timezone.utc).timestamp())
    
    def print_summary(self):
        """Print migration summary."""
        print("\n" + "=" * 60)
        print("📊 Migration Summary")
        print("=" * 60)
        print(f"Plans:    {self.stats['plans']}")
        print(f"Trades:   {self.stats['trades']}")
        print(f"Signals:  {self.stats['signals']}")
        print(f"Journal:  {self.stats['journal']}")
        print(f"Errors:   {len(self.stats['errors'])}")
        
        if self.stats['errors']:
            print("\n⚠️  Errors:")
            for error in self.stats['errors'][:10]:  # Show first 10
                print(f"  • {error}")
            if len(self.stats['errors']) > 10:
                print(f"  ... and {len(self.stats['errors']) - 10} more")
        
        print("\n" + ("✅ Migration completed!" if not self.dry_run else "ℹ️  Dry run completed"))
        print("=" * 60)


def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(description='Migrate data to database')
    parser.add_argument('--dry-run', action='store_true', help='Simulate without writing')
    parser.add_argument('--data-dir', type=str, default='data', help='Data directory')
    args = parser.parse_args()
    
    # Setup
    data_dir = PROJECT_ROOT / args.data_dir
    db = Database()
    
    # Migrate
    migrator = DataMigrator(data_dir, db, dry_run=args.dry_run)
    migrator.migrate_all()


if __name__ == '__main__':
    main()
