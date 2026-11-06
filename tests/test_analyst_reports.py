"""Regression tests for analyst report source adapters.

Run with: python -m unittest discover -s tests
"""
import unittest
from datetime import date
from unittest.mock import Mock, patch

from analyst_reports import (
    get_analyst_reports, get_naver_mobile_reports,
    get_naver_reports, parse_naver_research
)


class AnalystReportTests(unittest.TestCase):
    def test_v2_documented_report_fields(self):
        today = date.today().isoformat()
        row = {"nid": 987654, "title": "삼성전자: 실적 전망",
               "writeDate": today, "brokerName": "가상증권",
               "analystName": "테스트", "goalPrice": 250000,
               "itemCode": "005930"}
        result = parse_naver_research({"items": [row]}, "005930", "삼성전자")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["date"], today)
        self.assertEqual(result[0]["target_price"], "250,000원")
        self.assertIn("/987654", result[0]["url"])

    @patch("analyst_reports.requests.get")
    def test_v2_size_is_ten(self, get):
        resp = Mock()
        resp.json.return_value = {"items": []}
        get.return_value = resp
        self.assertEqual(get_naver_reports("005930", "삼성전자"), [])
        self.assertEqual(get.call_args.kwargs["params"]["size"], 10)

    @patch("analyst_reports.requests.get")
    def test_mobile_integration_researches(self, get):
        today = date.today().strftime("%Y%m%d")
        resp = Mock()
        resp.json.return_value = {
            "researches": [{"id": 5555, "tit": "실적 점검", "bnm": "가상증권", "wdt": today}]
        }
        get.return_value = resp
        rows = get_naver_mobile_reports("005930")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["date"], date.today().isoformat())
        self.assertIn("/research/5555", rows[0]["url"])

    @patch("analyst_reports.get_naver_mobile_reports")
    @patch("analyst_reports.get_naver_reports")
    def test_v2_failure_uses_mobile_fallback(self, primary, secondary):
        from requests import HTTPError, Response
        response = Response()
        response.status_code = 400
        primary.side_effect = HTTPError("invalid size", response=response)
        secondary.return_value = [{
            "date": date.today().isoformat(), "title": "종목 분석",
            "broker": "가상증권", "analyst": "", "target_price": "",
            "url": "https://m.stock.naver.com/domestic/stock/005930/research/1111",
            "source": "Npay 증권 종목요약",
        }]
        frame, error = get_analyst_reports("005930", "삼성전자")
        self.assertEqual(len(frame), 1)
        self.assertEqual(error, "")
        secondary.assert_called_once_with("005930")


if __name__ == "__main__":
    unittest.main()
