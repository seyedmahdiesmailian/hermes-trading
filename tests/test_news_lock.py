"""b31 — news_lock must work with the calendar shape PRODUCTION writes.

get_upcoming_events() returns {'source','high_impact':[...],'medium_impact':
[...],...} — no 'events' key. evaluate_news_lock used to read only
'events'/'calendar_summary', fell through to the dict itself, failed the
list check and returned None for every production input: the guard that is
supposed to tighten SL before high-impact news never existed in practice.
"""
import sys
import unittest
from datetime import datetime, timedelta, timezone

sys.path.insert(0, '/home/ai/hermes-trading')

from engines.legacy_guards import evaluate_news_lock, NEWS_LOCK_MINUTES_BEFORE


def _ev(minutes_ahead: float, impact="high", currency="USD", title="FOMC"):
    t = datetime.now(timezone.utc) + timedelta(minutes=minutes_ahead)
    return {"title": title, "currency": currency, "impact": impact,
            "date": t.isoformat(), "time": "", "forecast": "", "previous": ""}


def _production_calendar(events):
    """Exact shape of get_upcoming_events() output."""
    return {"source": "forexfactory", "high_impact": events,
            "medium_impact": [], "total_events": len(events),
            "fetched_at": datetime.now(timezone.utc).isoformat()}


class NewsLockProductionShapeTests(unittest.TestCase):
    def _sell(self):
        return {"side": "SELL", "entry_price": 4450.0, "sl": 4460.0, "atr": 5.0}

    def test_fires_with_production_shape(self):
        cal = _production_calendar([_ev(10)])
        g = evaluate_news_lock(self._sell(), 4450.0, cal)
        self.assertIsNotNone(g, "news_lock must fire on the get_upcoming_events shape")
        self.assertEqual(g["action"], "move_stop_to_breakeven")
        self.assertIn("news_lock", g["reason"])
        # SELL at 4450, ATR 5 → new SL = 4452.5 (tighter than 4460)
        self.assertAlmostEqual(g["new_sl"], 4452.5)

    def test_fires_with_raw_events_shape(self):
        cal = {"events": [_ev(10)]}
        self.assertIsNotNone(evaluate_news_lock(self._sell(), 4450.0, cal))

    def test_fires_with_bare_list(self):
        self.assertIsNotNone(evaluate_news_lock(self._sell(), 4450.0, [_ev(10)]))

    def test_outside_window_no_lock(self):
        cal = _production_calendar([_ev(NEWS_LOCK_MINUTES_BEFORE + 40)])
        self.assertIsNone(evaluate_news_lock(self._sell(), 4450.0, cal))

    def test_past_event_no_lock(self):
        cal = _production_calendar([_ev(-15)])  # already happened
        self.assertIsNone(evaluate_news_lock(self._sell(), 4450.0, cal))

    def test_low_impact_no_lock(self):
        cal = _production_calendar([_ev(10, impact="medium")])
        self.assertIsNone(evaluate_news_lock(self._sell(), 4450.0, cal))

    def test_irrelevant_currency_no_lock(self):
        cal = _production_calendar([_ev(10, currency="NZD")])
        self.assertIsNone(evaluate_news_lock(self._sell(), 4450.0, cal))

    def test_never_loosens_stop(self):
        """A SELL already tighter than the lock distance must be untouched."""
        tight = {"side": "SELL", "entry_price": 4450.0, "sl": 4451.0, "atr": 5.0}
        cal = _production_calendar([_ev(10)])
        self.assertIsNone(evaluate_news_lock(tight, 4450.0, cal))

    def test_empty_calendar_no_lock(self):
        self.assertIsNone(evaluate_news_lock(self._sell(), 4450.0,
                                             _production_calendar([])))
        self.assertIsNone(evaluate_news_lock(self._sell(), 4450.0, None))


if __name__ == '__main__':
    unittest.main()
