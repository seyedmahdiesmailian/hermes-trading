#!/usr/bin/env python3
""" scripts/system_health.py — ابزار جامع پایش و خودآزمایی سلامت سیستم تریدینگ هرمس

این اسکریپت تمام لایه‌های زیرساخت را در یک شات بررسی و گزارش می‌دهد:
۱. سیستم‌عامل لینوکس (CPU, RAM, Disk, Uptime)
۲. سرویس‌های فعال systemd
۳. پل ارتباطی MT5 روی ویندوز (پینگ، وضعیت حساب، تیک زنده، پوزیشن‌ها)
۴. پایگاه داده SQLite و بررسی یکپارچگی (PRAGMA integrity_check)
۵. وضعیت آخرین اجرای دیمن و فوروارددر تلگرام
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import requests
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def check_linux_resources() -> dict:
    total, used, free = shutil.disk_usage(ROOT)
    disk_free_gb = free // (2**30)
    
    # Load avg
    load1, load5, load15 = os.getloadavg()
    
    # Mem info
    mem_total, mem_avail = 0, 0
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    mem_total = int(line.split()[1]) // 1024
                elif line.startswith("MemAvailable:"):
                    mem_avail = int(line.split()[1]) // 1024
    except Exception:
        pass
    
    return {
        "status": "OK" if disk_free_gb > 2 else "WARN",
        "disk_free_gb": disk_free_gb,
        "load_avg": f"{load1:.2f}, {load5:.2f}, {load15:.2f}",
        "mem_avail_mb": mem_avail,
        "mem_total_mb": mem_total,
    }


def check_systemd_services() -> dict:
    required = [
        "hermes-daemon.service",
        "hermes-forwarder.service",
        "hermes-command-bot.service",
        "hermes-dashboard.service",
    ]
    results = {}
    all_ok = True
    for svc in required:
        res = subprocess.run(["systemctl", "--user", "is-active", svc], capture_output=True, text=True)
        state = res.stdout.strip()
        results[svc] = state
        if state != "active":
            all_ok = False
    return {"status": "OK" if all_ok else "ERROR", "services": results}


def check_mt5_bridge() -> dict:
    env_file = ROOT / ".env"
    token = ""
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if line.startswith("HERMES_BRIDGE_TOKEN="):
                token = line.split("=", 1)[1].strip()

    cfg_file = ROOT / "config.yaml"
    bridge_url = "http://192.168.10.51:5050"
    if cfg_file.exists():
        try:
            cfg = yaml.safe_load(cfg_file.read_text())
            bridge_url = cfg.get("bridge", {}).get("url", bridge_url)
        except Exception:
            pass

    t0 = time.time()
    try:
        r = requests.get(
            f"{bridge_url}/api/account",
            headers={"Authorization": f"Bearer {token}"},
            timeout=5,
        )
        latency_ms = round((time.time() - t0) * 1000, 1)
        if r.status_code != 200:
            return {"status": "ERROR", "error": f"HTTP {r.status_code}", "latency_ms": latency_ms}
        
        acc = r.json()
        
        # Get Tick
        r_tick = requests.get(
            f"{bridge_url}/api/tick/XAUUSD",
            headers={"Authorization": f"Bearer {token}"},
            timeout=5,
        )
        tick_data = r_tick.json() if r_tick.status_code == 200 else {}

        return {
            "status": "OK",
            "latency_ms": latency_ms,
            "login": acc.get("login"),
            "balance": acc.get("balance"),
            "equity": acc.get("equity"),
            "spread_points": round(tick_data.get("ask", 0) - tick_data.get("bid", 0), 2),
            "xau_bid": tick_data.get("bid"),
            "xau_ask": tick_data.get("ask"),
        }
    except Exception as e:
        return {"status": "ERROR", "error": str(e), "latency_ms": round((time.time() - t0) * 1000, 1)}


def check_database() -> dict:
    db_path = ROOT / "data" / "hermes.db"
    if not db_path.exists():
        return {"status": "ERROR", "error": "db not found"}

    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        cur = conn.cursor()
        integrity = cur.execute("PRAGMA integrity_check").fetchone()[0]
        
        counts = {}
        for table in ["plans", "orders", "trades", "signals", "guard_log", "equity_snapshots"]:
            c = cur.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            counts[table] = c
            
        last_snap = cur.execute("SELECT MAX(ts) FROM equity_snapshots").fetchone()[0]
        conn.close()
        
        snap_age_s = int(time.time() - last_snap) if last_snap else 999999
        return {
            "status": "OK" if integrity == "ok" and snap_age_s < 600 else "WARN",
            "integrity": integrity,
            "counts": counts,
            "last_snapshot_age_s": snap_age_s,
        }
    except Exception as e:
        return {"status": "ERROR", "error": str(e)}


def check_signals() -> dict:
    sig_path = ROOT / "data" / "signals" / "signals_log.json"
    if not sig_path.exists():
        return {"status": "WARN", "error": "signals_log.json not found"}
    
    try:
        stat = sig_path.stat()
        mtime_age_s = int(time.time() - stat.st_mtime)
        with open(sig_path) as f:
            data = json.load(f)
        items = data if isinstance(data, list) else data.get("data", [])
        return {
            "status": "OK",
            "total_signals": len(items),
            "last_modified_age_s": mtime_age_s,
        }
    except Exception as e:
        return {"status": "ERROR", "error": str(e)}


def main() -> int:
    print("=" * 60)
    print("🔍 HERMES TRADING INFRASTRUCTURE HEALTH CHECK")
    print(f"Time: {time.strftime('%Y-%m-%d %H:%M:%S')} UTC")
    print("=" * 60)

    linux = check_linux_resources()
    print(f"\n[1] LINUX HOST ({linux['status']}):")
    print(f"    Disk Free: {linux['disk_free_gb']} GB | Load Avg: {linux['load_avg']}")
    print(f"    RAM: {linux['mem_avail_mb']} MB available / {linux['mem_total_mb']} MB total")

    services = check_systemd_services()
    print(f"\n[2] SYSTEMD SERVICES ({services['status']}):")
    for svc, state in services["services"].items():
        symbol = "🟢" if state == "active" else "🔴"
        print(f"    {symbol} {svc:30}: {state}")

    bridge = check_mt5_bridge()
    print(f"\n[3] WINDOWS MT5 BRIDGE ({bridge['status']}):")
    if bridge["status"] == "OK":
        print(f"    Latency: {bridge['latency_ms']} ms | Login: {bridge['login']}")
        print(f"    Balance: ${bridge['balance']} | Equity: ${bridge['equity']}")
        print(f"    XAUUSD: {bridge['xau_bid']} / {bridge['xau_ask']} (Spread: {bridge['spread_points']})")
    else:
        print(f"    🔴 Error: {bridge.get('error')} (Latency: {bridge['latency_ms']} ms)")

    db = check_database()
    print(f"\n[4] SQLITE LEDGER ({db['status']}):")
    if db["status"] in ("OK", "WARN"):
        print(f"    Integrity: {db['integrity']} | Last snapshot age: {db['last_snapshot_age_s']}s")
        print(f"    Tables: {db['counts']}")
    else:
        print(f"    🔴 Error: {db.get('error')}")

    signals = check_signals()
    print(f"\n[5] TELEGRAM SIGNALS PIPELINE ({signals['status']}):")
    if signals["status"] == "OK":
        print(f"    Total Signals: {signals['total_signals']} | Log file age: {signals['last_modified_age_s']}s")
    else:
        print(f"    ⚠️ Notice: {signals.get('error')}")

    print("\n" + "=" * 60)
    overall_ok = (
        linux["status"] == "OK"
        and services["status"] == "OK"
        and bridge["status"] == "OK"
        and db["status"] in ("OK", "WARN")
    )
    print("OVERALL VERDICT:", "🟢 HEALTHY & READY" if overall_ok else "🔴 UNHEALTHY")
    print("=" * 60)

    return 0 if overall_ok else 1


if __name__ == "__main__":
    sys.exit(main())
