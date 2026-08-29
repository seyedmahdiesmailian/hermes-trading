import unittest
from engines.backtest import backtest_ohlc


class BacktestEngineTests(unittest.TestCase):
    def test_long_trade_hits_stop_before_target(self):
        rows = [
            {"time": 1, "open": 100, "high": 101, "low": 99, "close": 100},
            {"time": 2, "open": 100, "high": 101, "low": 94, "close": 96},
        ]
        result = backtest_ohlc(rows, lambda row: {"side": "BUY", "entry": 100, "sl": 95, "tp": 110} if row["time"] == 1 else None)
        self.assertEqual(result["trades"], 1)
        self.assertEqual(result["wins"], 0)
        self.assertEqual(result["losses"], 1)
        self.assertEqual(result["trade_log"][0]["exit_reason"], "sl")

    def test_no_signal_creates_no_trade(self):
        rows = [{"time": 1, "open": 100, "high": 101, "low": 99, "close": 100}]
        result = backtest_ohlc(rows, lambda row: None)
        self.assertEqual(result["trades"], 0)
        self.assertEqual(result["wins"], 0)

    def test_spread_makes_be_a_small_loss_not_free(self):
        # same setup as BE-scratch test, but with spread: BE exit nets slightly negative
        rows = [
            {"time": 1, "open": 100, "high": 100.5, "low": 99, "close": 100},
            {"time": 2, "open": 100, "high": 103, "low": 99, "close": 102},
            {"time": 3, "open": 100, "high": 100.2, "low": 99.5, "close": 100},
        ]
        result = backtest_ohlc(
            rows,
            lambda row: {"side": "BUY", "entry": 100, "sl": 95, "tp": 110} if row["time"] == 1 else None,
            breakeven_at_r=0.5,
            spread=0.20,
        )
        self.assertEqual(result["trade_log"][0]["exit_reason"], "be")
        self.assertEqual(result["trade_log"][0]["pnl"], -0.2)  # round-trip = exactly 1 spread
        # BE exit costing only the spread is a scratch, not a loss
        self.assertEqual(result["losses"], 0)
        self.assertEqual(result["scratches"], 1)

    def test_be_move_effective_next_bar_not_same_bar(self):
        # bar 2 both touches +0.5R AND would hit BE stop same bar → old code
        # moved SL and stopped out in the same bar (fake scratch); new code
        # moves BE effective next bar, so bar 2 cannot stop out via BE.
        rows = [
            {"time": 1, "open": 100, "high": 100.5, "low": 99, "close": 100},
            {"time": 2, "open": 100, "high": 102.5, "low": 99.4, "close": 100},  # +0.5R touch, deep pullback
            {"time": 3, "open": 100, "high": 101, "low": 99, "close": 100.5},   # would hit BE stop now
        ]
        result = backtest_ohlc(
            rows,
            lambda row: {"side": "BUY", "entry": 100, "sl": 95, "tp": 110} if row["time"] == 1 else None,
            breakeven_at_r=0.5,
        )
        # bar 2: BE move decided at close, stop still original 95 → survives
        # bar 3: BE stop active at 100 → stopped out as scratch
        self.assertEqual(result["trade_log"][0]["exit_reason"], "be")
        self.assertEqual(result["trade_log"][0]["exit_index"], 2)

    def test_original_sl_precedence_over_same_bar_tp1(self):
        # bar wicks BOTH below SL and above TP1 → SL wins (conservative)
        rows = [
            {"time": 1, "open": 100, "high": 100.5, "low": 99, "close": 100},
            {"time": 2, "open": 100, "high": 105, "low": 94, "close": 100},
        ]
        result = backtest_ohlc(
            rows,
            lambda row: {"side": "BUY", "entry": 100, "sl": 95, "tp": 110} if row["time"] == 1 else None,
            partial_tp1_share=0.5,
        )
        self.assertEqual(result["trade_log"][0]["exit_reason"], "sl")
        self.assertEqual(result["trade_log"][0]["pnl"], -5.0)

    def test_one_position_at_a_time(self):
        # 3 consecutive signals while a trade is open → only the first is taken
        rows = [
            {"time": 1, "open": 100, "high": 108, "low": 99, "close": 100},
            {"time": 2, "open": 100, "high": 101, "low": 99, "close": 100},
            {"time": 3, "open": 100, "high": 101, "low": 99, "close": 100},
            {"time": 4, "open": 100, "high": 101, "low": 99, "close": 100},
            {"time": 5, "open": 100, "high": 108, "low": 99, "close": 100},
        ]
        result = backtest_ohlc(
            rows,
            lambda row: {"side": "BUY", "entry": 100, "sl": 95, "tp": 110} if row["time"] in (1, 2, 3) else None,
        )
        self.assertEqual(result["trades"], 1)

    def test_min_rr_gate_blocks_poor_geometry(self):
        rows = [{"time": 1, "open": 100, "high": 101, "low": 99, "close": 100}]
        sig = lambda row: {"side": "BUY", "entry": 100, "sl": 95, "tp": 106}  # RR = 1.2
        self.assertEqual(backtest_ohlc(rows, sig, min_rr=1.5)["trades"], 0)
        self.assertEqual(backtest_ohlc(rows, sig, min_rr=1.0)["trades"], 1)

    def test_breakeven_move_converts_full_loss_to_scratch(self):
        # +0.6R move then reversal to entry: BE move saves the trade
        rows = [
            {"time": 1, "open": 100, "high": 100.5, "low": 99, "close": 100},
            {"time": 2, "open": 100, "high": 103, "low": 99, "close": 102},  # +0.6R → BE move
            {"time": 3, "open": 100, "high": 100.2, "low": 99.5, "close": 100},  # hit BE stop
        ]
        result = backtest_ohlc(
            rows,
            lambda row: {"side": "BUY", "entry": 100, "sl": 95, "tp": 110} if row["time"] == 1 else None,
            breakeven_at_r=0.5,
        )
        self.assertEqual(result["trades"], 1)
        self.assertEqual(result["wins"], 0)
        self.assertEqual(result["losses"], 0)  # scratch, not a full -5 loss
        self.assertEqual(result["trade_log"][0]["exit_reason"], "be")
        self.assertEqual(result["net_pnl"], 0.0)


if __name__ == "__main__":
    unittest.main()
