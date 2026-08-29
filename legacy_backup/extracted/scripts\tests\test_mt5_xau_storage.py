from pathlib import Path

from mt5_xau_storage import (
    append_execution_log,
    ensure_xau_plan_dirs,
    load_current_plan,
    save_current_plan,
)


def test_ensure_xau_plan_dirs_creates_expected_structure(tmp_path):
    paths = ensure_xau_plan_dirs(tmp_path)
    assert paths["base_dir"].exists()
    assert paths["plan_history_dir"].exists()
    assert paths["runtime_state_path"].parent.exists()


def test_load_current_plan_returns_none_when_missing(tmp_path):
    assert load_current_plan(tmp_path) is None


def test_save_current_plan_writes_current_plan_file(tmp_path):
    plan = {"symbol": "XAUUSD", "bias": "bullish", "plan_id": "p1"}
    save_current_plan(tmp_path, plan)
    loaded = load_current_plan(tmp_path)
    assert loaded["symbol"] == "XAUUSD"
    assert loaded["plan_id"] == "p1"


def test_save_current_plan_archives_previous_plan(tmp_path):
    save_current_plan(tmp_path, {"symbol": "XAUUSD", "bias": "bullish", "plan_id": "p1"})
    save_current_plan(tmp_path, {"symbol": "XAUUSD", "bias": "bearish", "plan_id": "p2"})
    history_dir = ensure_xau_plan_dirs(tmp_path)["plan_history_dir"]
    archived = list(history_dir.glob('*.json'))
    assert archived
    assert load_current_plan(tmp_path)["plan_id"] == "p2"


def test_append_execution_log_creates_csv_and_appends_rows(tmp_path):
    row1 = {"plan_id": "p1", "action": "market_order", "side": "BUY"}
    row2 = {"plan_id": "p1", "action": "wait", "side": "BUY"}
    append_execution_log(tmp_path, row1)
    append_execution_log(tmp_path, row2)
    log_path = ensure_xau_plan_dirs(tmp_path)["execution_log_path"]
    content = log_path.read_text(encoding='utf-8')
    assert "market_order" in content
    assert "wait" in content
