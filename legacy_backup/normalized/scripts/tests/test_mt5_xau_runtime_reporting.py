from mt5_xau_runtime import should_emit_monitor_report, build_monitor_report_key


def test_should_emit_when_no_previous_report_exists():
    monitor = {"action": "no_trade", "zone": "premium"}
    assert should_emit_monitor_report({}, monitor) is True


def test_should_not_emit_when_action_and_zone_are_unchanged():
    monitor = {"action": "no_trade", "zone": "premium"}
    runtime = {"last_report_key": build_monitor_report_key(monitor)}
    assert should_emit_monitor_report(runtime, monitor) is False


def test_should_emit_when_zone_changes():
    monitor = {"action": "no_trade", "zone": "discount"}
    runtime = {"last_report_key": "no_trade:premium"}
    assert should_emit_monitor_report(runtime, monitor) is True


def test_should_emit_when_action_changes():
    monitor = {"action": "wait_for_trigger", "zone": "long_zone"}
    runtime = {"last_report_key": "no_trade:premium"}
    assert should_emit_monitor_report(runtime, monitor) is True
