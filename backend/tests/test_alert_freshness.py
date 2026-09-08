import datetime as dt
import unittest
from types import SimpleNamespace

from app.services.alert_service import _is_quote_usable


CN = dt.timezone(dt.timedelta(hours=8))


class AlertFreshnessTests(unittest.TestCase):
    def test_rejects_old_quote_during_market_hours(self) -> None:
        now = dt.datetime(2026, 9, 7, 10, 0, tzinfo=CN)
        quote = SimpleNamespace(quote_time="2026-09-07T09:55:00+08:00")
        self.assertFalse(_is_quote_usable(quote, now))

    def test_accepts_recent_quote_during_market_hours(self) -> None:
        now = dt.datetime(2026, 9, 7, 10, 0, tzinfo=CN)
        quote = SimpleNamespace(quote_time="2026-09-07T09:59:30+08:00")
        self.assertTrue(_is_quote_usable(quote, now))

    def test_accepts_same_day_close_after_market(self) -> None:
        now = dt.datetime(2026, 9, 7, 15, 30, tzinfo=CN)
        quote = SimpleNamespace(quote_time="2026-09-07T15:00:00+08:00")
        self.assertTrue(_is_quote_usable(quote, now))


if __name__ == "__main__":
    unittest.main()
