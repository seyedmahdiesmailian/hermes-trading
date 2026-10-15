#!/usr/bin/env python3
"""Database verification and health check.

Verifies database integrity and data consistency.

Usage:
    python3 scripts/verify_database.py [--verbose]
"""

import sys
from pathlib import Path
from datetime import datetime, timezone

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from database import get_db


class DatabaseVerifier:
    """Verify database health and data consistency."""
    
    def __init__(self, verbose: bool = False):
        self.db = get_db()
        self.verbose = verbose
        self.errors = []
        self.warnings = []
    
    def verify_all(self):
        """Run all verification checks."""
        print("=" * 60)
        print("🔍 Database Verification")
        print("=" * 60)
        print(f"Database: {self.db.db_path}")
        print()
        
        self.check_schema()
        self.check_data_integrity()
        self.check_referential_integrity()
        self.check_indexes()
        
        self.print_summary()
    
    def check_schema(self):
        """Verify schema exists and is correct."""
        print("📋 Checking Schema...")
        
        expected_tables = [
            'plans', 'trades', 'signals', 'position_state',
            'account_snapshots', 'daily_performance',
            'risk_state', 'safety_events',
            'trade_journal', 'learning_adjustments',
            'config', 'system_state'
        ]
        
        existing_tables = [t['name'] for t in self.db.fetch_all(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )]
        
        for table in expected_tables:
            if table in existing_tables:
                count = self.db.fetch_one(f"SELECT COUNT(*) as cnt FROM {table}")['cnt']
                status = "✅" if count > 0 else "⚠️"
                print(f"  {status} {table:20s} {count:>6} rows")
            else:
                print(f"  ❌ {table:20s} MISSING")
                self.errors.append(f"Table {table} missing")
        
        # Check views
        print("\n📊 Checking Views...")
        expected_views = ['v_active_trades', 'v_recent_performance', 'v_current_plan']
        existing_views = [v['name'] for v in self.db.fetch_all(
            "SELECT name FROM sqlite_master WHERE type='view'"
        )]
        
        for view in expected_views:
            if view in existing_views:
                print(f"  ✅ {view}")
            else:
                print(f"  ❌ {view} MISSING")
                self.warnings.append(f"View {view} missing")
    
    def check_data_integrity(self):
        """Check data consistency and constraints."""
        print("\n🔍 Checking Data Integrity...")
        
        # Check for orphaned trades (no matching plan)
        orphans = self.db.fetch_all(
            """SELECT t.ticket, t.source_ref 
            FROM trades t 
            WHERE t.source = 'plan' 
              AND t.source_ref IS NOT NULL
              AND NOT EXISTS (
                  SELECT 1 FROM plans p WHERE p.plan_id = t.source_ref
              )
            LIMIT 5"""
        )
        
        if orphans:
            print(f"  ⚠️  {len(orphans)} orphaned trades (no matching plan)")
            if self.verbose:
                for orphan in orphans:
                    print(f"      Ticket {orphan['ticket']} -> Plan {orphan['source_ref']}")
            self.warnings.append(f"{len(orphans)} orphaned trades")
        else:
            print("  ✅ No orphaned trades")
        
        # Check for trades without journal entries
        closed_without_journal = self.db.fetch_one(
            """SELECT COUNT(*) as cnt FROM trades t
            WHERE t.status = 'closed'
              AND NOT EXISTS (
                  SELECT 1 FROM trade_journal j WHERE j.ticket = t.ticket
              )"""
        )['cnt']
        
        if closed_without_journal > 0:
            print(f"  ⚠️  {closed_without_journal} closed trades without journal")
            self.warnings.append(f"{closed_without_journal} trades missing journal")
        else:
            print("  ✅ All closed trades have journal entries")
        
        # Check for invalid prices
        invalid_prices = self.db.fetch_all(
            """SELECT ticket, entry_price, stop_loss, take_profit
            FROM trades
            WHERE entry_price <= 0 
               OR (stop_loss IS NOT NULL AND stop_loss <= 0)
               OR (take_profit IS NOT NULL AND take_profit <= 0)
            LIMIT 5"""
        )
        
        if invalid_prices:
            print(f"  ❌ {len(invalid_prices)} trades with invalid prices")
            self.errors.append(f"{len(invalid_prices)} invalid prices")
        else:
            print("  ✅ All prices valid")
    
    def check_referential_integrity(self):
        """Check foreign key relationships."""
        print("\n🔗 Checking Referential Integrity...")
        
        # Check journal -> trades
        orphaned_journal = self.db.fetch_one(
            """SELECT COUNT(*) as cnt FROM trade_journal j
            WHERE NOT EXISTS (
                SELECT 1 FROM trades t WHERE t.ticket = j.ticket
            )"""
        )['cnt']
        
        if orphaned_journal > 0:
            print(f"  ⚠️  {orphaned_journal} journal entries without trade")
            self.warnings.append(f"{orphaned_journal} orphaned journal entries")
        else:
            print("  ✅ All journal entries linked to trades")
    
    def check_indexes(self):
        """Check that indexes exist."""
        print("\n🗂️  Checking Indexes...")
        
        indexes = self.db.fetch_all(
            "SELECT name, tbl_name FROM sqlite_master WHERE type='index'"
        )
        
        print(f"  ✅ {len(indexes)} indexes found")
        
        if self.verbose:
            for idx in indexes:
                print(f"      {idx['name']} on {idx['tbl_name']}")
    
    def print_summary(self):
        """Print verification summary."""
        print("\n" + "=" * 60)
        print("📊 Verification Summary")
        print("=" * 60)
        print(f"Errors:   {len(self.errors)}")
        print(f"Warnings: {len(self.warnings)}")
        
        if self.errors:
            print("\n❌ Errors:")
            for error in self.errors:
                print(f"  • {error}")
        
        if self.warnings:
            print("\n⚠️  Warnings:")
            for warning in self.warnings:
                print(f"  • {warning}")
        
        if not self.errors and not self.warnings:
            print("\n✅ Database is healthy!")
        elif not self.errors:
            print("\n✅ Database is OK (minor warnings)")
        else:
            print("\n❌ Database has issues!")
        
        print("=" * 60)
        
        # Exit code
        return 0 if not self.errors else 1


def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(description='Verify database')
    parser.add_argument('--verbose', '-v', action='store_true', help='Verbose output')
    args = parser.parse_args()
    
    verifier = DatabaseVerifier(verbose=args.verbose)
    exit_code = verifier.verify_all()
    sys.exit(exit_code)


if __name__ == '__main__':
    main()
