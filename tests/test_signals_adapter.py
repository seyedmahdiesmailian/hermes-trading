""" tests/test_signals_adapter — تست‌های واحد پایپ‌لاین اعتبارسنجی سیگنال‌های تلگرام

تست پارس سیگنال، حذف تکراری‌ها (Deduplication)، فیلتر سیگنال‌های تاریخ‌گذشته (Stale Signals)،
و اعتبارسنجی هندسه قیمت طلا.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

from adapters.signals import SignalsAdapter
from core.entities import Side


class TestSignalsAdapter:
    @pytest.fixture
    def setup_paths(self, tmp_path):
        log_file = tmp_path / "signals_log.json"
        state_file = tmp_path / "listener_state.json"
        return log_file, state_file

    def test_parse_valid_signal(self, setup_paths):
        log_file, state_file = setup_paths
        now_iso = datetime.now(timezone.utc).isoformat()
        sample = [{
            "id": "sig-001",
            "timestamp": now_iso,
            "raw_text": "BUY XAUUSD 2050 SL 2040 TP 2070",
            "parsed": {
                "symbol": "XAUUSD",
                "side": "BUY",
                "entry": 2050.0,
                "sl": 2040.0,
                "tp": 2070.0,
                "rr_ratio": 2.0,
                "confidence": 0.85
            }
        }]
        log_file.write_text(json.dumps(sample), encoding="utf-8")

        adapter = SignalsAdapter(log_file, state_file)
        signals = adapter.read_new()
        assert len(signals) == 1
        sig = signals[0]
        assert sig.symbol == "XAUUSD"
        assert sig.side == Side.BUY
        assert sig.entry == 2050.0
        assert sig.sl == 2040.0
        assert sig.tp == 2070.0
        assert sig.rr == 2.0

    def test_deduplicate_identical_signals(self, setup_paths):
        log_file, state_file = setup_paths
        now_iso = datetime.now(timezone.utc).isoformat()
        # Same signal appearing twice
        sample = [
            {
                "id": "sig-dup-1",
                "timestamp": now_iso,
                "parsed": {"symbol": "XAUUSD", "side": "SELL", "entry": 2050.0, "sl": 2060.0, "tp": 2030.0}
            },
            {
                "id": "sig-dup-2",
                "timestamp": now_iso,
                "parsed": {"symbol": "XAUUSD", "side": "SELL", "entry": 2050.0, "sl": 2060.0, "tp": 2030.0}
            }
        ]
        log_file.write_text(json.dumps(sample), encoding="utf-8")

        adapter = SignalsAdapter(log_file, state_file)
        signals = adapter.read_new()
        # Only the first one should pass, second is a duplicate!
        assert len(signals) == 1
        assert signals[0].signal_id == "sig-dup-1"

    def test_reject_stale_signal(self, setup_paths):
        log_file, state_file = setup_paths
        # Signal timestamp is 30 minutes ago (stale > 15m)
        old_time = (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat()
        sample = [{
            "id": "sig-old",
            "timestamp": old_time,
            "parsed": {"symbol": "XAUUSD", "side": "BUY", "entry": 2050.0, "sl": 2040.0, "tp": 2070.0}
        }]
        log_file.write_text(json.dumps(sample), encoding="utf-8")

        adapter = SignalsAdapter(log_file, state_file, max_age_s=900)
        signals = adapter.read_new()
        assert len(signals) == 0

    def test_reject_invalid_geometry(self, setup_paths):
        log_file, state_file = setup_paths
        now_iso = datetime.now(timezone.utc).isoformat()
        # BUY with SL higher than Entry
        bad_sample = [{
            "id": "sig-bad-geo",
            "timestamp": now_iso,
            "parsed": {"symbol": "XAUUSD", "side": "BUY", "entry": 2050.0, "sl": 2060.0, "tp": 2070.0}
        }]
        log_file.write_text(json.dumps(bad_sample), encoding="utf-8")

        adapter = SignalsAdapter(log_file, state_file)
        signals = adapter.read_new()
        assert len(signals) == 0

    def test_reject_non_gold_symbols(self, setup_paths):
        log_file, state_file = setup_paths
        now_iso = datetime.now(timezone.utc).isoformat()
        sample = [{
            "id": "sig-eurusd",
            "timestamp": now_iso,
            "parsed": {"symbol": "EURUSD", "side": "BUY", "entry": 1.0850, "sl": 1.0800, "tp": 1.0950}
        }]
        log_file.write_text(json.dumps(sample), encoding="utf-8")

        adapter = SignalsAdapter(log_file, state_file)
        signals = adapter.read_new()
        assert len(signals) == 0

    def test_parse_raw_text_signal(self, setup_paths):
        log_file, state_file = setup_paths
        now_iso = datetime.now(timezone.utc).isoformat()
        sample = [{
            "id": "raw-1",
            "timestamp": now_iso,
            "raw_text": "BUY GOLD 2045.00 SL: 2035.00 TP: 2065.00"
        }]
        log_file.write_text(json.dumps(sample), encoding="utf-8")

        adapter = SignalsAdapter(log_file, state_file)
        signals = adapter.read_new()
        assert len(signals) == 1
        assert signals[0].symbol == "XAUUSD"
        assert signals[0].side == Side.BUY
        assert signals[0].entry == 2045.0
        assert signals[0].sl == 2035.0
        assert signals[0].tp == 2065.0

    def test_parse_radin_vip_abbreviated_signal(self, setup_paths):
        log_file, state_file = setup_paths
        now_iso = datetime.now(timezone.utc).isoformat()
        sample = [{
            "id": "radin-1",
            "timestamp": now_iso,
            "raw_text": "32 و 42 فروش استاپ 52 تی پی 22 ، 12 ، 4002"
        }]
        log_file.write_text(json.dumps(sample), encoding="utf-8")

        adapter = SignalsAdapter(log_file, state_file)
        signals = adapter.read_new()
        assert len(signals) == 1
        assert signals[0].symbol == "XAUUSD"
        assert signals[0].side == Side.SELL
        assert signals[0].entry == 4037.0
        assert signals[0].sl == 4052.0
        assert signals[0].tp == 4022.0

    def test_b243_expand_abbreviated_price_3_digit_and_century(self):
        # تست تبدیل قیمت ۳ رقمی به هزاره جاری (مثلاً 735 برای طلای 2730)
        assert SignalsAdapter._expand_abbreviated_price("735", 2730.0) == 2735.0
        assert SignalsAdapter._expand_abbreviated_price("725.5", 2730.0) == 2725.5
        assert SignalsAdapter._expand_abbreviated_price("755", 2730.0) == 2755.0
        # تست شکست هزاره (Rollover)
        assert SignalsAdapter._expand_abbreviated_price("990", 3005.0) == 2990.0
        assert SignalsAdapter._expand_abbreviated_price("15", 2990.0) == 3015.0
        # تست قیمت ۲ رقمی استاندارد و شکست سده (Century Rollover)
        assert SignalsAdapter._expand_abbreviated_price("35", 2730.0) == 2735.0
        assert SignalsAdapter._expand_abbreviated_price("98", 2701.0) == 2698.0
        assert SignalsAdapter._expand_abbreviated_price("02", 2699.0) == 2702.0
        # قیمت ۴ رقمی بدون تغییر
        assert SignalsAdapter._expand_abbreviated_price("2735.5", 2730.0) == 2735.5

    def test_b243_parse_3_digit_persian_signal(self, setup_paths):
        log_file, state_file = setup_paths
        now_iso = datetime.now(timezone.utc).isoformat()
        sample = [{
            "id": "sig-3digit-1",
            "timestamp": now_iso,
            "raw_text": "خرید طلا 735 حد ضرر 725 حد سود 755",
        }]
        log_file.write_text(json.dumps(sample), encoding="utf-8")

        adapter = SignalsAdapter(log_file, state_file)
        signals = adapter.read_new(current_price=2730.0)
        assert len(signals) == 1
        sig = signals[0]
        assert sig.symbol == "XAUUSD"
        assert sig.side == Side.BUY
        assert sig.entry == 2735.0
        assert sig.sl == 2725.0
        assert sig.tp == 2755.0
