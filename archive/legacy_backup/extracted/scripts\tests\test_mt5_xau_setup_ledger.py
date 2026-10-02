from mt5_xau_runtime import _build_setup_ledger, _build_setup_guardrails


class TestSetupLedger:
    def test_empty_entries_returns_empty_ledger(self):
        ledger = _build_setup_ledger([], [])
        assert ledger == {}

    def test_groups_by_regime(self):
        classified = [
            {"exit_type": "tp", "pnl": 50.0, "ticket": 1, "time": 100, "managed": False},
            {"exit_type": "sl", "pnl": -20.0, "ticket": 2, "time": 200, "managed": True},
            {"exit_type": "tp", "pnl": 30.0, "ticket": 3, "time": 300, "managed": False},
        ]
        setups = [
            {"ticket": 1, "regime": "pullback_continuation", "alignment": "aligned", "grade": "A"},
            {"ticket": 2, "regime": "pullback_continuation", "alignment": "mixed", "grade": "B"},
            {"ticket": 3, "regime": "breakout_continuation", "alignment": "aligned", "grade": "A"},
        ]
        ledger = _build_setup_ledger(classified, setups)
        # By regime
        pb = ledger.get("regime:pullback_continuation")
        assert pb is not None
        assert pb["wins"] == 1
        assert pb["losses"] == 1
        assert pb["total_pnl"] == 30.0
        bo = ledger.get("regime:breakout_continuation")
        assert bo["wins"] == 1
        assert bo["losses"] == 0

    def test_ticket_not_in_setups_is_skipped(self):
        classified = [
            {"exit_type": "tp", "pnl": 10.0, "ticket": 999, "time": 100, "managed": False},
        ]
        setups = [{"ticket": 1, "regime": "breakout_continuation"}]
        ledger = _build_setup_ledger(classified, setups)
        assert ledger == {}

    def test_multiple_dimensions(self):
        classified = [
            {"exit_type": "sl", "pnl": -10.0, "ticket": 1, "time": 100, "managed": False},
        ]
        setups = [{"ticket": 1, "regime": "range", "alignment": "neutral", "grade": "C"}]
        ledger = _build_setup_ledger(classified, setups)
        assert ledger.get("regime:range") is not None
        assert ledger.get("alignment:neutral") is not None
        assert ledger.get("grade:C") is not None


class TestSetupGuardrails:
    def test_high_loss_setup_is_avoid(self):
        ledger = {
            "regime:range": {"wins": 0, "losses": 3, "total_pnl": -45.0, "samples": 3},
        }
        guardrails = _build_setup_guardrails(ledger)
        assert "avoid" in guardrails
        assert "regime:range" in guardrails["avoid"]

    def test_winning_setup_is_preferred(self):
        ledger = {
            "alignment:aligned": {"wins": 4, "losses": 1, "total_pnl": 120.0, "samples": 5},
        }
        guardrails = _build_setup_guardrails(ledger)
        assert "preferred" in guardrails
        assert "alignment:aligned" in guardrails["preferred"]

    def test_small_sample_not_flagged(self):
        ledger = {
            "grade:B": {"wins": 0, "losses": 1, "total_pnl": -5.0, "samples": 1},
        }
        guardrails = _build_setup_guardrails(ledger)
        # Needs >= 2 samples to trigger avoid
        assert "avoid" not in guardrails
        assert "preferred" not in guardrails
