"""Hermes Oversight Layer — reads latest analysis snapshot and formats it for review.

This module is called by a cron job to send the latest SMC analysis to Hermes
for quality review. Hermes can then evaluate the analysis and suggest improvements.
"""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(os.environ.get("HERMES_TRADING_DIR", Path.home() / "AppData" / "Local" / "hermes" / "trading"))
PLAN_DIR = BASE_DIR / "xau_plan"
REVIEW_DIR = PLAN_DIR / "review_snapshots"


def save_review_snapshot(plan: dict, smc_result: dict, merged: dict, now: datetime):
    """Save a detailed analysis snapshot for Hermes review."""
    REVIEW_DIR.mkdir(parents=True, exist_ok=True)

    snapshot = {
        "timestamp": now.isoformat(),
        "plan_id": plan.get("plan_id"),
        "bias": plan.get("bias"),
        "session": plan.get("session"),
        "zones": plan.get("zones"),
        "invalidation": plan.get("invalidation"),
        "quality": plan.get("quality"),
        "smc": {
            "bias": smc_result.get("bias"),
            "bias_confidence": smc_result.get("bias_confidence"),
            "signal": smc_result.get("signal"),
            "confidence": smc_result.get("confidence"),
            "poi": smc_result.get("poi"),
            "poi_grade": smc_result.get("poi_grade"),
            "killzone": smc_result.get("killzone"),
            "killzone_weight": smc_result.get("killzone_weight"),
            "order_blocks": smc_result.get("order_blocks", []),
            "fvg": smc_result.get("fvg", []),
            "liquidity_sweep": smc_result.get("liquidity_sweep"),
            "market_structure": smc_result.get("market_structure"),
            "premium_discount": smc_result.get("premium_discount"),
            "breaker_blocks": smc_result.get("breaker_blocks", []),
            "rejection_blocks": smc_result.get("rejection_blocks", []),
            "ote_zone": smc_result.get("ote_zone"),
            "power_of_three": smc_result.get("power_of_three"),
            "turtle_soup": smc_result.get("turtle_soup"),
            "silver_bullet": smc_result.get("silver_bullet"),
            "session_liquidity": smc_result.get("session_liquidity"),
            "volume_imbalance": smc_result.get("volume_imbalance", []),
        },
        "merged": {
            "bias": merged.get("bias"),
            "confidence": merged.get("confidence"),
            "classic_bias": merged.get("classic_bias"),
            "smc_bias": merged.get("smc_bias"),
            "agreement": merged.get("agreement"),
        },
    }

    # Save as latest + timestamped
    latest_path = REVIEW_DIR / "latest_snapshot.json"
    latest_path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")

    ts = now.strftime("%Y%m%d_%H%M%S")
    ts_path = REVIEW_DIR / f"snapshot_{ts}.json"
    ts_path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")

    # Keep only last 50 snapshots
    snapshots = sorted(REVIEW_DIR.glob("snapshot_*.json"))
    if len(snapshots) > 50:
        for old in snapshots[:-50]:
            old.unlink()

    return snapshot


def load_latest_snapshot() -> dict | None:
    """Load the most recent review snapshot. Returns None if too old (market closed)."""
    latest_path = REVIEW_DIR / "latest_snapshot.json"
    if not latest_path.exists():
        return None
    try:
        data = json.loads(latest_path.read_text(encoding="utf-8"))
        # Check snapshot freshness — if older than 30 minutes, it's from a closed market
        ts = data.get("timestamp", "")
        if ts:
            try:
                snap_dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                age_sec = (datetime.now(timezone.utc) - snap_dt).total_seconds()
                if age_sec > 1800:  # 30 minutes
                    return None  # Stale — market is closed
            except Exception:
                pass
        return data
    except Exception:
        return None


def format_review_report(snapshot: dict) -> str:
    """Format snapshot as a Persian review report for Hermes."""
    if not snapshot:
        return "🔴 بازار بسته — snapshot جدیدی موجود نیست. تمام داده‌ها قدیمی هستند."

    ts = snapshot.get("timestamp", "?")
    plan_id = snapshot.get("plan_id", "?")
    bias = snapshot.get("bias", "?")
    session = snapshot.get("session", "?")
    quality = snapshot.get("quality", {})
    smc = snapshot.get("smc", {})
    merged = snapshot.get("merged", {})

    lines = [
        f"🔍 **گزارش نظارتی Hermes**",
        f"",
        f"⏰ زمان: {ts}",
        f"📋 Plan: {plan_id}",
        f"📊 بایاس نهایی: {bias}",
        f"🌍 سشن: {session}",
        f"",
        f"── تحلیل کلاسیک ──",
        f"  بایاس: {merged.get('classic_bias', '?')}",
        f"  رژیم: {quality.get('regime', '?')}",
        f"  قدرت روند: {quality.get('trend_strength', '?')}",
        f"  تراز تایم‌فریم: {quality.get('alignment', '?')}",
        f"",
        f"── تحلیل SMC ──",
        f"  بایاس: {smc.get('bias', '?')}",
        f"  سیگنال: {smc.get('signal', '?')}",
        f"  confidence: {smc.get('confidence', '?')}",
        f"  POI: {smc.get('poi', '?')} (گرید {smc.get('poi_grade', '?')})",
        f"  Killzone: {smc.get('killzone', '?')} (وزن {smc.get('killzone_weight', '?')})",
        f"  ساختار: {smc.get('market_structure', '?')}",
        f"  P/D: {smc.get('premium_discount', '?')}",
        f"  Liq Sweep: {smc.get('liquidity_sweep', '?')}",
        f"",
        f"── Merge ──",
        f"  توافق: {merged.get('agreement', '?')}",
        f"  confidence نهایی: {merged.get('confidence', '?')}",
        f"",
        f"── نواحی ──",
    ]

    zones = snapshot.get("zones", {})
    if zones:
        lines.append(f"  Value: {zones.get('value_low', '?')} — {zones.get('value_high', '?')}")
        lines.append(f"  Long Entry: {zones.get('long_entry_low', '?')} — {zones.get('long_entry_high', '?')}")
        lines.append(f"  Short Entry: {zones.get('short_entry_low', '?')} — {zones.get('short_entry_high', '?')}")

    lines.append(f"  Invalidation: {snapshot.get('invalidation', '?')}")

    # SMC details
    obs = smc.get("order_blocks", [])
    if obs:
        lines.append(f"")
        lines.append(f"── Order Blocks ({len(obs)}) ──")
        for ob in obs[:3]:
            lines.append(f"  {ob.get('type', '?')} | {ob.get('low', '?')}—{ob.get('high', '?')} | mitigated={ob.get('mitigated', '?')}")

    fvgs = smc.get("fvg", [])
    if fvgs:
        lines.append(f"")
        lines.append(f"── FVGs ({len(fvgs)}) ──")
        for f in fvgs[:3]:
            lines.append(f"  {f.get('type', '?')} | {f.get('bottom', '?')}—{f.get('top', '?')} | filled={f.get('filled', '?')}")

    return "\n".join(lines)


def main():
    """Called by cron to output the latest review snapshot."""
    snapshot = load_latest_snapshot()
    report = format_review_report(snapshot)
    print(report)


if __name__ == "__main__":
    main()
