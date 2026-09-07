import unittest

from app.services.data_service import _parse_qq_quote_time


class QuoteTimeParsingTests(unittest.TestCase):
    def test_parses_tencent_timestamp_as_china_time(self) -> None:
        self.assertEqual(_parse_qq_quote_time("20260907102345"), "2026-09-07T10:23:45+08:00")

    def test_invalid_timestamp_does_not_drop_the_quote(self) -> None:
        self.assertIsNone(_parse_qq_quote_time("bad-value"))


if __name__ == "__main__":
    unittest.main()
