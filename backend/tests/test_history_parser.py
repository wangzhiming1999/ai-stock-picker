import unittest

from app.services.data_service import _parse_qq_history_payload


class TencentHistoryParserTests(unittest.TestCase):
    def test_parses_qfq_day_rows(self) -> None:
        payload = {
            "data": {
                "sh600519": {
                    "qfqday": [
                        ["2026-09-04", "1450", "1460.5", "1470", "1440", "12000"],
                        ["2026-09-07", "1460", "1480", "1490", "1455", "15000"],
                    ]
                }
            }
        }
        result = _parse_qq_history_payload(payload, "sh600519", 120)
        self.assertEqual(result.dates, ["2026-09-04", "2026-09-07"])
        self.assertEqual(result.closes, [1460.5, 1480.0])
        self.assertEqual(result.volumes, [12000.0, 15000.0])

    def test_parses_open_high_low_for_pattern_rules(self) -> None:
        """形态识别（揉搓线/断头铡刀）依赖日线 OHLC，不能只留收盘价。"""
        payload = {
            "data": {
                "sh600519": {
                    "qfqday": [["2026-09-04", "1450", "1460.5", "1470", "1440", "12000"]]
                }
            }
        }
        result = _parse_qq_history_payload(payload, "sh600519", 120)
        self.assertEqual(result.opens, [1450.0])
        self.assertEqual(result.highs, [1470.0])
        self.assertEqual(result.lows, [1440.0])

    def test_missing_ohlc_falls_back_to_close(self) -> None:
        payload = {
            "data": {
                "sh600519": {
                    "qfqday": [["2026-09-04", "", "1460.5", "0", "", "12000"]]
                }
            }
        }
        result = _parse_qq_history_payload(payload, "sh600519", 120)
        self.assertEqual(result.opens, [1460.5])
        self.assertEqual(result.highs, [1460.5])
        self.assertEqual(result.lows, [1460.5])

    def test_invalid_row_is_skipped_without_dropping_payload(self) -> None:
        payload = {
            "data": {
                "sh600519": {
                    "qfqday": [
                        ["2026-09-03", "bad", "0", "0", "0", "0"],
                        ["2026-09-04", "1450", "1460.5", "1470", "1440", "12000"],
                    ]
                }
            }
        }
        result = _parse_qq_history_payload(payload, "sh600519", 120)
        self.assertEqual(result.dates, ["2026-09-04"])
        self.assertEqual(result.closes, [1460.5])

    def test_invalid_payload_returns_none(self) -> None:
        self.assertIsNone(_parse_qq_history_payload({"data": {}}, "sh600519", 120))


if __name__ == "__main__":
    unittest.main()
