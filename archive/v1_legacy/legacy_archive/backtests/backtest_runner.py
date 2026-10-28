#!/usr/bin/env python3
"""Backtest Runner — runs real backtests using Bridge data.

Usage:
    python3 backtest_runner.py                     # default: 500 M15 bars
    python3 backtest_runner.py --count 1000        # more bars
    python3 backtest_runner.py --symbol XAUUSD     # specific symbol
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:
    from env_loader import load_dotenv  # python-dotenv missing → local fallback
load_dotenv(Path(__file__).parent / '.env')

from bridge_client import BridgeClient
from engines.backtest_real import run_backtest, save_backtest_result


def format_report(result: dict) -> str:
    """Format backtest results as human-readable text."""
    if not result.get("ok"):
        return f"Backtest failed: {result.get('error', 'unknown')}"

    trades = result.get("trades", 0)
    wins = result.get("wins", 0)
    losses = result.get("losses", 0)
    net_pnl = result.get("net_pnl", 0)
    win_rate = result.get("win_rate", 0)
    bars = result.get("bars_tested", 0)

    lines = [
        "═══════════════════════════════════════════",
        f"BACKTEST RESULTS | {result.get('symbol', 'XAUUSD')}",
        f"Timeframe: {result.get('timeframe', 'M15')} | Bars: {bars}",
        "═══════════════════════════════════════════",
        f"Total trades: {trades}",
        f"Wins: {wins} | Losses: {losses}",
        f"Win rate: {win_rate:.1%}",
        f"Net P&L: {net_pnl:+.2f} points",
    ]

    # Show trade log summary
    trade_log = result.get("trade_log", [])
    if trade_log:
        lines.append("")
        lines.append("Last 10 trades:")
        for t in trade_log[-10:]:
            pnl = t.get("pnl", 0)
            emoji = "+" if pnl > 0 else ""
            lines.append(
                f"  {t.get('side', '?'):4s} {t.get('entry', 0):.2f} → "
                f"{t.get('exit', 0):.2f} | {emoji}{pnl:.2f} | {t.get('exit_reason', '?')}"
            )

    # Drawdown analysis
    if trade_log:
        equity_curve = 0
        peak = 0
        max_dd = 0
        for t in trade_log:
            equity_curve += t.get("pnl", 0)
            peak = max(peak, equity_curve)
            dd = peak - equity_curve
            max_dd = max(max_dd, dd)
        lines.append(f"\nMax drawdown: {max_dd:.2f} points")
        lines.append(f"Profit factor: {wins/(losses or 1):.2f}")

    lines.append("═══════════════════════════════════════════")
    return "\n".join(lines)


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Hermes Backtest Runner")
    parser.add_argument("--symbol", default="XAUUSD", help="Symbol to backtest")
    parser.add_argument("--count", type=int, default=500, help="Number of bars")
    parser.add_argument("--timeframe", default="M15", help="Timeframe")
    parser.add_argument("--json", action="store_true", help="Output raw JSON")
    args = parser.parse_args()

    bridge = BridgeClient()
    health = bridge.health()
    if not health.get("ok"):
        print(f"Bridge unreachable: {health}")
        sys.exit(1)

    print(f"Running backtest: {args.symbol} {args.timeframe} x{args.count} bars...")
    result = run_backtest(bridge, symbol=args.symbol, timeframe=args.timeframe, count=args.count)

    # Save result
    saved_path = save_backtest_result(result, label=f"{args.symbol}_{args.timeframe}")

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(format_report(result))
        print(f"\nFull results saved to: {saved_path}")


if __name__ == '__main__':
    main()
