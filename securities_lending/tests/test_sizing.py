import json
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from securities_lending.calculation import size_order
from securities_lending.config import DEFAULTS, ROOT
from securities_lending.wind import IndustryProvider, wind_executable
from securities_lending.wind_worker import fetch_market


class SizingTests(unittest.TestCase):
    def test_hundred_share_floor_and_unused_amount(self):
        result = size_order("5000000", "1400.25", 20000)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["executable_shares"], 3500)
        self.assertEqual(Decimal(result["actual_nominal"]), Decimal("4900875.00"))
        self.assertEqual(Decimal(result["unused_nominal"]), Decimal("99125.00"))

    def test_exact_decimal_boundary(self):
        self.assertEqual(size_order("29", "0.29", 100)["executable_shares"], 100)
        self.assertEqual(size_order("28.999999", "0.29", 100)["status"], "below_lot")

    def test_capacity_rounded_and_oversized_demand_not_silently_capped(self):
        result = size_order(100000, 10, 1999)
        self.assertEqual(result["maximum_shares"], 1900)
        self.assertEqual(result["requested_shares"], 10000)
        self.assertIsNone(result["executable_shares"])
        self.assertEqual(result["status"], "insufficient")
        self.assertIn("1,900", result["message"])

    def test_rounded_demand_at_capacity_is_valid(self):
        result = size_order(19999, 10, 1999)
        self.assertEqual(result["executable_shares"], 1900)
        self.assertEqual(result["unused_nominal"], "999")

    def test_zero_and_fractional_inventory(self):
        for available in (0, 99, "99.9"):
            result = size_order(10000, 10, available)
            self.assertEqual(result["maximum_shares"], 0)
            self.assertEqual(result["status"], "insufficient")

    def test_missing_and_partial_inventory_cannot_confirm_capacity(self):
        for quantity, complete in ((None, True), (1500, False)):
            result = size_order(10000, 10, quantity, complete)
            self.assertEqual(result["status"], "unknown_inventory")
            self.assertIsNone(result["maximum_shares"])
            self.assertIsNone(result["executable_shares"])

    def test_invalid_target_and_missing_price(self):
        for target in ("-1", "NaN", "Infinity", "bad", "0", "1e15", True):
            self.assertEqual(size_order(target, 10, 1000)["status"], "invalid")
        for price in (None, "NaN", "Infinity", 0, -1):
            result = size_order(10000, price, 1000)
            self.assertEqual(result["status"], "no_price")
            self.assertIsNone(result["requested_shares"])

    def test_sizing_invariants_over_multiple_prices_and_capacities(self):
        for price in ("0.29", "11.24", "200.18", "1400.25"):
            for amount in ("1000", "100000", "5000000"):
                for available in (0, 199, 20000, 1000000):
                    result = size_order(amount, price, available)
                    shares = result["requested_shares"]
                    self.assertEqual(shares % 100, 0)
                    self.assertLessEqual(Decimal(price) * shares, Decimal(amount))
                    self.assertGreater(Decimal(price) * (shares + 100), Decimal(amount))
                    if result["status"] == "ok":
                        self.assertLessEqual(result["executable_shares"], available)


class QuoteTests(unittest.TestCase):
    def fake(self, data, codes=None):
        return SimpleNamespace(start=lambda **kwargs: SimpleNamespace(ErrorCode=0),
            wsq=lambda *args: SimpleNamespace(ErrorCode=0, Fields=["RT_LAST"], Codes=codes or ["000001.SZ"], Data=[data], Times=["2026-10-14 10:01:02"]),
            wss=lambda *args: SimpleNamespace(ErrorCode=0, Codes=["000001.SZ"], Data=[["银行"]]))

    def request(self):
        return {"quote_codes": ["000001.SZ"], "industry_codes": ["000001.SZ"], "field": "industry_sw", "options": "industryType=1"}

    def test_quote_and_industry_in_one_wind_session(self):
        response = fetch_market(self.request(), self.fake([12.17]))
        self.assertEqual(response["quotes"]["000001.SZ"]["price"], "12.17")
        self.assertEqual(response["industries"]["000001.SZ"], "银行")
        self.assertEqual(response["quotes"]["000001.SZ"]["wind_returned_at"], "2026-10-14 10:01:02")

    def test_quotes_are_mapped_by_returned_codes(self):
        request = self.request()
        request["quote_codes"].append("600519.SH")
        response = fetch_market(request, self.fake([1400.25, 12.17], ["600519.SH", "000001.SZ"]))
        self.assertEqual(response["quotes"]["000001.SZ"]["price"], "12.17")

    def test_invalid_price_does_not_hide_industry(self):
        for value in (None, float("nan"), float("inf"), 0, -1, "bad", True):
            response = fetch_market(self.request(), self.fake([value]))
            self.assertEqual(response["quotes"], {})
            self.assertEqual(response["industries"]["000001.SZ"], "银行")
            self.assertTrue(response["warnings"])

    def test_industry_failure_does_not_hide_valid_price(self):
        wind = self.fake([12.17])
        wind.wss = lambda *args: SimpleNamespace(ErrorCode=-123)
        response = fetch_market(self.request(), wind)
        self.assertIn("000001.SZ", response["quotes"])
        self.assertEqual(response["industries"], {})

    def test_latest_quotes_are_never_reused_after_failure(self):
        root = ROOT / "data" / "test_tmp"
        root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=root) as folder:
            provider = IndustryProvider(Path(folder))
            result = {"quotes": {"000001.SZ": {"price": "12.17"}}, "industries": {}, "warnings": [], "error": None}
            config = {**DEFAULTS, "wind_enabled": True}
            with patch("securities_lending.wind.subprocess.run", return_value=SimpleNamespace(returncode=0, stdout=json.dumps(result))) as run:
                provider.market(["000001.SZ"], [], "2026-10-14", config)
                provider.market(["000001.SZ"], [], "2026-10-14", config)
                self.assertEqual(run.call_count, 2)
            with patch("securities_lending.wind.subprocess.run", side_effect=OSError("offline")):
                _, quotes, warnings = provider.market(["000001.SZ"], [], "2026-10-14", config)
                self.assertEqual(quotes, {})
                self.assertTrue(warnings)

    def test_pythonw_uses_console_python_for_json_worker(self):
        self.assertEqual(Path(wind_executable({"wind_python": "D:/conda/envs/swhy_delta1/pythonw.exe"})).name, "python.exe")


if __name__ == "__main__":
    unittest.main()
