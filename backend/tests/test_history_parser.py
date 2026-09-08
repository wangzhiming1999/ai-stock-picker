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

    def test_invalid_payload_returns_none(self) -> None:
        self.assertIsNone(_parse_qq_history_payload({"data": {}}, "sh600519", 120))


if __name__ == "__main__":
    unittest.main()
