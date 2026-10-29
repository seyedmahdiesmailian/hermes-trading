#!/usr/bin/env python3
"""adapters/watchdog — نگهبان خودکار متاتریدر ۵ و احیای از راه دور سرور ویندوز (Remote MT5 Watchdog).

وظایف اصلی:
۱. پایش سلامت پل ارتباطی لینوکس به ویندوز (HTTP Bridge)
۲. تشخیص قطعی یا فریز متاتریدر ۵ در ویندوز (Process & Session Check via WinRM)
۳. احیای خودکار و بدون دخالت دست MT5 و Bridge در Session 1
۴. اعتبارسنجی اتصال مجدد و ارسال گزارش به تلگرام
"""
from __future__ import annotations

import json
import logging
import os
import time
import urllib.request
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent


class RemoteMT5Watchdog:
    """نگهبان خودکار متاتریدر ۵ با اتصال دوگانه HTTP و WinRM."""

    def __init__(
        self,
        bridge_url: str = "http://192.168.10.51:5050",
        bridge_token: str = "",
        win_host: str = "192.168.10.51",
        win_user: str = "Administrator",
        win_pass: str = "",
    ):
        self._bridge_url = bridge_url.rstrip("/")
        self._bridge_token = bridge_token
        self._win_host = win_host
        self._win_user = win_user
        self._win_pass = win_pass
        self._last_revival_ts = 0.0
        self._consecutive_failures = 0

    def check_health(self) -> dict:
        """بررسی سریع سلامت اتصال بریج و اکانت بروکر."""
        t0 = time.time()
        try:
            req = urllib.request.Request(f"{self._bridge_url}/api/account")
            if self._bridge_token:
                req.add_header("Authorization", f"Bearer {self._bridge_token}")
            with urllib.request.urlopen(req, timeout=4) as response:
                data = json.loads(response.read().decode("utf-8"))
                latency = round((time.time() - t0) * 1000, 1)
                if data.get("balance") is not None or data.get("ok"):
                    self._consecutive_failures = 0
                    return {
                        "ok": True,
                        "status": "HEALTHY",
                        "latency_ms": latency,
                        "login": data.get("login"),
                        "balance": data.get("balance"),
                    }
                else:
                    return {
                        "ok": False,
                        "status": "TERMINAL_NOT_CONNECTED",
                        "error": data.get("error", "Unknown"),
                    }
        except Exception as e:
            self._consecutive_failures += 1
            return {
                "ok": False,
                "status": "BRIDGE_UNREACHABLE",
                "error": str(e),
                "consecutive_failures": self._consecutive_failures,
            }

    def diagnose_windows(self) -> dict:
        """اتصال از طریق WinRM و استعلام دقیق پروسه‌ها و سشن‌ها."""
        try:
            import winrm

            s = winrm.Session(
                self._win_host,
                auth=(self._win_user, self._win_pass),
                transport="ntlm",
                server_cert_validation="ignore",
                read_timeout_sec=25,
                operation_timeout_sec=15,
            )
            ps_cmd = (
                "Get-Process -Name terminal64, python -ErrorAction SilentlyContinue | "
                "Select-Object Id, ProcessName, SessionId, WorkingSet64 | "
                "ConvertTo-Json -Compress"
            )
            r = s.run_ps(ps_cmd)
            out_str = r.std_out.decode("utf-8", "replace").strip()
            if not out_str:
                return {"ok": True, "processes": [], "terminal_running": False, "python_running": False}

            parsed = json.loads(out_str)
            procs = parsed if isinstance(parsed, list) else [parsed]

            term_procs = [p for p in procs if p.get("ProcessName") == "terminal64"]
            py_procs = [p for p in procs if p.get("ProcessName") == "python"]

            return {
                "ok": True,
                "terminal_running": len(term_procs) > 0,
                "terminal_session": term_procs[0].get("SessionId") if term_procs else None,
                "python_running": len(py_procs) > 0,
                "python_session": py_procs[0].get("SessionId") if py_procs else None,
                "processes": procs,
            }
        except Exception as e:
            return {"ok": False, "error": f"WinRM connection failed: {e}"}

    def revive(self, force: bool = False) -> tuple[bool, str]:
        """احیای خودکار متاتریدر ۵ و بریج در Session 1 ویندوز."""
        now = time.time()
        # گارد ضد طوفان: حداقل ۵ دقیقه فاصله بین تلاش‌های احیا
        if not force and (now - self._last_revival_ts < 300):
            wait_s = int(300 - (now - self._last_revival_ts))
            return False, f"احیا اخیراً انجام شده — لطفاً {wait_s} ثانیه صبر کنید."

        self._last_revival_ts = now
        log.warning("RemoteMT5Watchdog: آغاز عملیات بازیابی و ری‌استارت سرور ویندوز...")

        try:
            import winrm

            s = winrm.Session(
                self._win_host,
                auth=(self._win_user, self._win_pass),
                transport="ntlm",
                server_cert_validation="ignore",
                read_timeout_sec=35,
                operation_timeout_sec=25,
            )

            # ۱. بستن پروسه‌های قفل‌شده
            kill_script = "Stop-Process -Name terminal64, python -Force -ErrorAction SilentlyContinue; 'killed'"
            s.run_ps(kill_script)
            time.sleep(2)

            # ۲. راه‌اندازی مجدد در Session 1 با استفاده از استارت‌آپ ویندوز
            # نکته طلایی: اجرای مستقیم شورت‌کات استارت‌آپ تضمین می‌کند پروسه در سشن ۱ دسکتاپ بالا می‌آید
            start_script = (
                r'Start-Process -FilePath "C:\Users\Administrator\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Startup\Start_Hermes_Bridge.bat"; '
                r'Start-Process -FilePath "C:\Users\Administrator\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Startup\MT5.lnk"; '
                r"'started'"
            )
            r = s.run_ps(start_script)
            log.info("RemoteMT5Watchdog: دستور اجرای مجدد صادر شد: %s", r.std_out.decode("utf-8", "replace").strip())

            # ۳. انتظار برای استارت و لاگین MT5 (حداکثر ۲۰ ثانیه)
            for attempt in range(1, 8):
                time.sleep(3)
                h = self.check_health()
                if h.get("ok"):
                    log.info("RemoteMT5Watchdog: اتصال با موفقیت احیا شد (تلاش %d) — تاخیر: %sms", attempt, h.get("latency_ms"))
                    self._consecutive_failures = 0
                    return True, f"احیا موفق بود (تاخیر {h.get('latency_ms')} ms)"

            return False, "پروسه‌ها اجرا شدند اما پاسخ تایید اتصال پس از ۲۰ ثانیه دریافت نشد."
        except Exception as e:
            log.exception("RemoteMT5Watchdog: عملیات احیا با خطا مواجه شد")
            return False, f"خطای سیستمی در احیا: {e}"


def load_watchdog_from_env() -> RemoteMT5Watchdog:
    """ساخت نمونه آماده نگهبان با مقادیر .env."""
    env_file = ROOT / ".env"
    token = ""
    win_pass = ""
    win_host = "192.168.10.51"
    win_user = "Administrator"
    bridge_url = "http://192.168.10.51:5050"

    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                k = k.strip()
                v = v.strip()
                if k == "HERMES_BRIDGE_TOKEN":
                    token = v
                elif k == "WIN_PASS":
                    win_pass = v
                elif k == "HERMES_WIN_IP":
                    win_host = v
                elif k == "HERMES_WIN_USER":
                    win_user = v
                elif k == "HERMES_BRIDGE_URL":
                    bridge_url = v

    return RemoteMT5Watchdog(
        bridge_url=bridge_url,
        bridge_token=token,
        win_host=win_host,
        win_user=win_user,
        win_pass=win_pass,
    )
