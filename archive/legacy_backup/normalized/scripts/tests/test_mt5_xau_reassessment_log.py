from pathlib import Path

from mt5_xau_storage import append_reassessment_log, ensure_xau_plan_dirs


def test_append_reassessment_log_creates_csv(tmp_path):
    append_reassessment_log(tmp_path, {
        "at": "2026-08-07T09:00:00+00:00",
        "plan_id": "xau-1",
        "event": "reassess",
        "old_bias": "bullish",
        "new_bias": "bearish",
    })
    paths = ensure_xau_plan_dirs(tmp_path)
    text = Path(paths["reassessment_log_path"]).read_text(encoding="utf-8")
    assert "event" in text
    assert "reassess" in text
    assert "bearish" in text
