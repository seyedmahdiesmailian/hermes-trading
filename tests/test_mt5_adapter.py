""" tests/test_mt5_adapter — تست‌های واحد برای آداپتور MetaTrader 5

تست عملکرد کلاینت MT5، استراتژی شبیه‌سازی، Partial Close، و مدیریت خطاها.
"""
from __future__ import annotations

import json
from pathlib import Path
import pytest

from adapters.mt5 import Mt5Adapter, BridgeError, RETCODE_DESCRIPTIONS
from core.entities import Side, OrderStatus


class TestMt5AdapterDryRun:
    @pytest.fixture
    def adapter(self, tmp_path):
        sim_path = tmp_path / "sim_book.json"
        return Mt5Adapter(
            url="http://127.0.0.1:5050",
            token="dummy_token",
            timeout_s=5,
            dry_run=True,
            sim_state_path=str(sim_path),
        )

    def test_adapter_init_and_sim_load_empty(self, adapter):
        assert adapter._dry_run is True
        assert len(adapter._sim_book) == 0

    def test_dry_run_order_lifecycle(self, adapter, monkeypatch):
        # Mock get_tick so dry_run can get mid price without network
        from core.entities import Tick
        monkeypatch.setattr(adapter, "get_tick", lambda sym: Tick(symbol=sym, bid=2000.0, ask=2001.0, time=1700000000))

        order = adapter.place_order(
            order_id="hms-test-1",
            symbol="XAUUSD",
            side=Side.BUY,
            volume=0.2,
            sl=1990.0,
            tp=2020.0,
        )
        assert order.status == OrderStatus.FILLED
        assert order.ticket > 0
        assert order.volume == 0.2

        # Check in open positions
        positions = adapter.get_open_positions("XAUUSD")
        assert len(positions) == 1
        pos = positions[0]
        assert pos.ticket == order.ticket
        assert pos.volume == 0.2

        # Modify position
        ok_mod = adapter.modify_position(order.ticket, sl=1995.0, tp=2025.0)
        assert ok_mod is True
        assert adapter._sim_book[order.ticket].sl == 1995.0

        # Partial close 50%
        ok_part = adapter.partial_close(order.ticket, percent=50.0)
        assert ok_part is True
        assert adapter._sim_book[order.ticket].volume == 0.10

        # Full close
        ok_close = adapter.close_position(order.ticket)
        assert ok_close is True
        assert len(adapter.get_open_positions("XAUUSD")) == 0

    def test_retcode_descriptions_exist(self):
        assert 10018 in RETCODE_DESCRIPTIONS
        assert "MARKET_CLOSED" in RETCODE_DESCRIPTIONS[10018]
        assert 10027 in RETCODE_DESCRIPTIONS
        assert "AUTOTRADING" in RETCODE_DESCRIPTIONS[10027]
