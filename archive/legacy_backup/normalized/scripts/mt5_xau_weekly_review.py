"""
Weekly Learning Cycle — Sunday evening review of past week's trades.

Input: decision journal entries from the past week
Output: learning report + auto-patch to code parameters

What it does:
  1. Load all journal entries from past 7 days
  2. Analyze win/loss, R-multiple distribution, pattern frequency
  3. Identify top mistakes (missed BE, late exit, bad entry timing)
  4. Generate parameter adjustments (threshold, weight, BE rule tweaks)
  5. Write learning report to trading/xau_journal/learning_WEEK_YYYY-WW.md
  6. Print recommended code patches (Hermes reviews and applies)

Run: Sunday evening (Iran time ~22:00)
"""
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from collections import Counter, defaultdict

JOURNAL_DIR = Path(r"C:\Users\Administrator\AppData\Local\hermes\trading\xau_journal")
SCRIPTS = Path(r"C:\Users\Administrator\AppData\Local\hermes\scripts")
sys.path.insert(0, str(SCRIPTS))


def load_weekly_entries(weeks_back: int = 1) -> list:
    """Load journal entries from past N weeks."""
    if not JOURNAL_DIR.exists():
        return []

    cutoff = datetime.now() - timedelta(weeks=weeks_back)
    entries = []

    for jf in sorted(JOURNAL_DIR.glob("j_*.json")):
        try:
            entry = json.loads(jf.read_text())
            ts = entry.get("timestamp", "")
            dt = datetime.fromisoformat(ts) if ts else None
            if dt and dt >= cutoff:
                entry["_file"] = jf.name
                entries.append(entry)
        except Exception:
            continue

    return sorted(entries, key=lambda e: e.get("timestamp", ""))


def analyze_week(entries: list) -> dict:
    """Analyze weekly journal entries for patterns and lessons."""
    if not entries:
        return {
            "total_decisions": 0,
            "total_trades": 0,
            "summary": "هیچ معامله‌ای این هفته انجام نشد.",
        }

    # Separate decisions from execution records
    decisions = [e for e in entries if e.get("record_type") in ("decision", "hermes_decision")]
    executions = [e for e in entries if e.get("record_type") in ("execution", "trade")]
    trades = [e for e in entries if e.get("record_type") == "trade"]

    # Stats
    total_decisions = len(decisions)
    total_trades = len(trades)

    # Win/Loss from trade records
    wins = []
    losses = []
    r_values = []

    for t in trades:
        pnl = t.get("pnl", t.get("profit", 0))
        risk = t.get("risk_usd", 10.0)
        if risk <= 0:
            risk = 10.0
        r_val = pnl / risk
        r_values.append(r_val)

        if pnl > 0:
            wins.append({"pnl": pnl, "r": r_val, "ticket": t.get("ticket")})
        elif pnl < 0:
            losses.append({"pnl": pnl, "r": r_val, "ticket": t.get("ticket")})

    # Decision patterns
    action_counts = Counter()
    session_counts = Counter()
    bias_used = Counter()
    missed_be = 0
    partial_close_count = 0
    time_exit_count = 0

    for d in decisions:
        action = d.get("decision", d.get("action", "?"))
        action_counts[action] += 1

        snap = d.get("market_snapshot", d.get("snapshot", {}))
        if isinstance(snap, dict):
            session_counts[snap.get("session", "?")] += 1
            bias_used[snap.get("bias", "?")] += 1

        reasoning = d.get("reasoning", d.get("notes", ""))
        if isinstance(reasoning, str):
            if "BE" in reasoning or "breakeven" in reasoning.lower():
                missed_be += 1
            if "partial" in reasoning.lower() or "50%" in reasoning:
                partial_close_count += 1
            if "time" in reasoning.lower() or "exit" in reasoning.lower():
                time_exit_count += 1

    # Win rate
    total_closed = len(wins) + len(losses)
    win_rate = (len(wins) / total_closed * 100) if total_closed > 0 else 0

    # R stats
    avg_r = sum(r_values) / len(r_values) if r_values else 0
    total_r = sum(r_values)
    max_r = max(r_values) if r_values else 0
    min_r = min(r_values) if r_values else 0

    # Identify problems
    problems = []

    if win_rate < 40 and total_closed >= 3:
        problems.append(f"Win rate low ({win_rate:.0f}%) — review entry criteria")
    if avg_r < 0 and total_closed >= 3:
        problems.append(f"Negative avg R ({avg_r:.2f}) — check risk/reward")
    if missed_be > 2:
        problems.append(f"Missed BE {missed_be}x — activate earlier BE rules")
    if max_r > 2.0 and partial_close_count == 0 and total_closed >= 2:
        problems.append("No partial closes despite R>2 — enable partial TP")
    if time_exit_count > total_closed > 0 and time_exit_count / total_closed > 0.5:
        problems.append("Too many time exits — entries too early or holding too long")

    # Suggested parameter adjustments
    params = {}

    if avg_r > 0.5 and len(wins) > len(losses):
        params["be_at_r"] = max(0.3, 0.5 - len(wins) * 0.02)
        params["trail_after_r"] = min(1.5, 1.0 + len(wins) * 0.05)
    elif avg_r < -0.3:
        params["be_at_r"] = min(0.8, 0.5 + abs(avg_r))
        params["trail_after_r"] = min(2.0, 1.0 + abs(avg_r))
        params["partial_at_r"] = max(1.0, 1.5 - abs(avg_r) * 0.5)

    return {
        "total_decisions": total_decisions,
        "total_trades": total_trades,
        "total_closed": total_closed,
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(win_rate, 1),
        "avg_r": round(avg_r, 2),
        "total_r": round(total_r, 2),
        "max_r": round(max_r, 2),
        "min_r": round(min_r, 2),
        "action_distribution": dict(action_counts),
        "session_distribution": dict(session_counts),
        "bias_distribution": dict(bias_used),
        "problems": problems,
        "suggested_params": params,
        "wins_detail": wins,
        "losses_detail": losses,
        "r_values": [round(r, 2) for r in r_values],
        "entries_days": len(entries),
    }


def write_report(analysis: dict) -> Path:
    """Write weekly learning report in Persian."""
    from datetime import datetime as dt
    now = datetime.now()
    week_num = now.isocalendar()[1]

    report_file = JOURNAL_DIR / f"learning_WEEK_{now.strftime('%Y')}-W{week_num:02d}.md"

    lines = [
        f"# گزارش یادگیری هفتگی — هفته {week_num} سال {now.year}",
        f"تاریخ: {now.strftime('%Y-%m-%d')} (یکشنبه)",
        "",
        "---",
        "",
        "## آمار کلی",
        f"- تعداد تصمیم‌گیری: {analysis['total_decisions']}",
        f"- تعداد معاملات: {analysis['total_trades']}",
        f"- معاملات بسته شده: {analysis['total_closed']}",
        f"- برد: {analysis['wins']} | باخت: {analysis['losses']} | Win Rate: **{analysis['win_rate']}%**",
        f"- میانگین R: **{analysis['avg_r']:.2f}** | مجموع R: {analysis['total_r']:.2f}",
        f"- بهترین R: {analysis['max_r']:.2f} | بدترین R: {analysis['min_r']:.2f}",
        "",
        "## توزیع تصمیمات",
    ]

    for action, count in analysis.get("action_distribution", {}).items():
        lines.append(f"- {action}: {count} بار")

    lines.extend([
        "",
        "## توزیع سشن",
    ])
    for session, count in analysis.get("session_distribution", {}).items():
        lines.append(f"- {session}: {count} بار")

    lines.extend([
        "",
        "## توالی R",
        f"R-values: {analysis.get('r_values', [])}",
        "",
        "---",
        "",
        "## مشکلات شناسایی شده",
    ])

    if analysis.get("problems"):
        for p in analysis["problems"]:
            lines.append(f"- ⚠️ {p}")
    else:
        lines.append("- ✅ مشکل خاصی شناسایی نشد.")

    lines.extend([
        "",
        "## تنظیمات پیشنهادی (patch)",
        "```json",
        json.dumps(analysis.get("suggested_params", {}), indent=2),
        "```",
        "",
        "---",
        "",
        "## معاملات برد",
    ])
    for w in analysis.get("wins_detail", [])[:10]:
        lines.append(f"- Ticket {w.get('ticket')}: PnL={w['pnl']:.2f} | R={w['r']:.2f}")

    lines.extend([
        "",
        "## معاملات باخت",
    ])
    for l in analysis.get("losses_detail", [])[:10]:
        lines.append(f"- Ticket {l.get('ticket')}: PnL={l['pnl']:.2f} | R={l['r']:.2f}")

    lines.extend([
        "",
        "---",
        "*گزارش توسط ماژول یادگیری هفتگی Hermes تولید شد.*",
    ])

    report_file.parent.mkdir(parents=True, exist_ok=True)
    report_file.write_text("\n".join(lines), encoding="utf-8")
    return report_file


def run_weekly_review() -> bool:
    """Main entry: load, analyze, write report."""
    print("═══ Weekly Learning Cycle ═══")
    print(f"Now: {datetime.now().strftime('%Y-%m-%d %H:%M')}")

    entries = load_weekly_entries(weeks_back=1)
    print(f"Loaded {len(entries)} journal entries from past 7 days")

    analysis = analyze_week(entries)

    print(f"\n═══ Analysis ═══")
    print(f"Decisions: {analysis['total_decisions']} | Trades: {analysis['total_trades']} | Closed: {analysis['total_closed']}")
    print(f"Win Rate: {analysis['win_rate']}% | Avg R: {analysis['avg_r']:.2f} | Total R: {analysis['total_r']:.2f}")
    print(f"R sequence: {analysis.get('r_values', [])}")

    if analysis.get("problems"):
        print(f"\n⚠️ Problems:")
        for p in analysis["problems"]:
            print(f"  - {p}")
    else:
        print("\n✅ No major problems detected")

    if analysis.get("suggested_params"):
        print(f"\n🔧 Suggested parameter adjustments:")
        for k, v in analysis["suggested_params"].items():
            print(f"  {k} = {v}")

    report_path = write_report(analysis)
    print(f"\n✅ Report written: {report_path}")

    return True


if __name__ == "__main__":
    success = run_weekly_review()
    sys.exit(0 if success else 1)
