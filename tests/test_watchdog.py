#!/usr/bin/env python3
"""tests/test_watchdog.py — تست‌های واحد نگهبان خودکار متاتریدر ۵ و سرور ویندوز."""
from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest
from adapters.watchdog import RemoteMT5Watchdog, load_watchdog_from_env


class TestRemoteMT5Watchdog:
    def test_init_and_config(self):
        wd = RemoteMT5Watchdog(
            bridge_url="http://192.168.10.51:5050",
            bridge_token="secret",
            win_host="192.168.10.51",
            win_user="Administrator",
            win_pass="password",
        )
        assert wd._bridge_url == "http://192.168.10.51:5050"
        assert wd._win_user == "Administrator"
        assert wd._consecutive_failures == 0

    def test_storm_guard_throttles_revivals(self):
        wd = RemoteMT5Watchdog()
        wd._last_revival_ts = time.time()  # Revival was just now
        ok, msg = wd.revive(force=False)
        assert ok is False
        assert "صبر کنید" in msg

    @patch("urllib.request.urlopen")
    def test_check_health_success(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = b'{"ok": true, "balance": 5000.0, "login": 10382667}'
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        wd = RemoteMT5Watchdog()
        res = wd.check_health()
        assert res["ok"] is True
        assert res["status"] == "HEALTHY"
        assert res["balance"] == 5000.0

    @patch("urllib.request.urlopen")
    def test_check_health_unreachable(self, mock_urlopen):
        mock_urlopen.side_effect = Exception("Connection refused")

        wd = RemoteMT5Watchdog()
        res = wd.check_health()
        assert res["ok"] is False
        assert res["status"] == "BRIDGE_UNREACHABLE"
        assert wd._consecutive_failures == 1

    def test_load_watchdog_from_env(self):
        wd = load_watchdog_from_env()
        assert wd is not None
        assert wd._win_host == "192.168.10.51"
