from datetime import datetime, timezone

import pytest

from mt5_xau_runtime import _build_exit_analysis


def test_exit_analysis_sums_by_type():
    classified = [
        {"exit_type": "sl", "pnl": -2.0, "managed": False},
        {"exit_type": "sl", "pnl": -1.5, "managed": False},
        {"exit_type": "tp", "pnl": 5.0, "managed": False},
        {"exit_type": "partial", "pnl": 1.0, "managed": True},
        {"exit_type": "partial", "pnl": -0.5, "managed": True},
    ]

    out = _build_exit_analysis(classified)

    assert out["sl"]["count"] == 2
    assert out["sl"]["total_pnl"] == -3.5
    assert out["tp"]["count"] == 1
    assert out["tp"]["total_pnl"] == 5.0
    assert out["partial"]["count"] == 2
    assert out["partial"]["total_pnl"] == 0.5
    assert out["total_closed"] == 5


def test_exit_analysis_empty_returns_zeros():
    out = _build_exit_analysis([])
    assert out["total_closed"] == 0
    assert out["sl"]["count"] == 0
    assert out["tp"]["count"] == 0
    assert out["partial"]["count"] == 0


def test_exit_analysis_flags_sl_dominant():
    classified = [
        {"exit_type": "sl", "pnl": -2.0, "managed": False},
        {"exit_type": "sl", "pnl": -3.0, "managed": False},
        {"exit_type": "sl", "pnl": -1.0, "managed": False},
        {"exit_type": "tp", "pnl": 4.0, "managed": False},
    ]

    out = _build_exit_analysis(classified)

    assert out["sl_dominant"] is True
    assert out["sl_ratio"] == 0.75
    assert out["avg_sl_loss"] == -2.0


def test_exit_analysis_managed_exits_added_value():
    classified = [
        {"exit_type": "partial", "pnl": 2.0, "managed": True},
        {"exit_type": "partial", "pnl": 1.5, "managed": True},
        {"exit_type": "partial", "pnl": -0.3, "managed": True},
        {"exit_type": "sl", "pnl": -4.0, "managed": False},
    ]

    out = _build_exit_analysis(classified)

    assert out["managed_total_pnl"] == 3.2
    assert out["managed_win_ratio"] == pytest.approx(2 / 3, abs=0.01)
    assert out["sl"]["count"] == 1
