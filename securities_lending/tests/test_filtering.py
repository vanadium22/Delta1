import csv
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from securities_lending.filtering import InventoryFilters
from securities_lending.service import InventoryService
from securities_lending.tests.test_desktop import DesktopCase


def items(response):
    return [item for group in response["results"] for item in group["securities"]]


class FilterServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.service = InventoryService(Path(self.tmp.name), demo=True)
        self.service.load_today()

    def test_industry_and_inclusive_decimal_amount_filter_use_current_value(self):
        response = self.service.query("", filters=InventoryFilters("银行", "973.6", "973.6"))
        self.assertEqual([item["code"] for item in items(response)], ["000001.SZ"])
        self.assertEqual(items(response)[0]["inventory_market_value"], Decimal("9736000"))
        self.assertEqual(response["summary"]["matched"], 1)
        self.assertEqual(response["summary"]["quantity"], 800000)
        self.assertEqual(response["screening"]["candidates"], 7)
        self.assertEqual(self.service.query("", filters=InventoryFilters("银行", maximum_wan="1000"))["summary"]["matched"], 1)
        self.assertEqual(self.service.query("", filters=InventoryFilters("银行", minimum_wan="1000"))["summary"]["matched"], 1)

    def test_partial_keyword_keeps_all_sources_and_does_not_search_outside_inventory(self):
        self.service.records[1]["name"] = "茅台别名"
        response = self.service.query("别名 60051", filters=InventoryFilters())
        self.assertEqual(len(items(response)), 1)
        stock = items(response)[0]
        self.assertEqual(stock["quantity"], 20000)
        self.assertEqual(len(stock["rows"]), 2)
        self.assertEqual(self.service.query("浦发银行", filters=InventoryFilters())["summary"]["matched"], 0)
        self.assertEqual(self.service.query("SH600519", filters=InventoryFilters())["summary"]["matched"], 1)

    def test_zero_and_incomplete_inventory_remain_distinct(self):
        self.service.records[0]["quantity"] = None
        response = self.service.query("", filters=InventoryFilters(available_only=True))
        codes = {item["code"] for item in items(response)}
        self.assertNotIn("000858.SZ", codes)
        self.assertNotIn("600519.SH", codes)
        response = self.service.query("", filters=InventoryFilters(minimum_wan="0", maximum_wan="0"))
        self.assertEqual([item["code"] for item in items(response)], ["000858.SZ"])
        self.assertEqual(response["screening"]["unpriced"], 1)

    def test_missing_price_does_not_fall_back_to_sheet_amount_and_requeries_each_time(self):
        self.service.demo = False
        quote = {"000001.SZ": {"price": "12.17", "source": "mock"}}
        with patch.object(self.service.provider, "market", side_effect=[({}, quote, []), ({}, {}, ["offline"])]) as market:
            first = self.service.query("000001", filters=InventoryFilters(minimum_wan="900"))
            second = self.service.query("000001", filters=InventoryFilters(minimum_wan="900"))
        self.assertEqual(len(items(first)), 1)
        self.assertEqual(items(second), [])
        self.assertEqual(second["screening"]["unpriced"], 1)
        self.assertEqual(market.call_count, 2)
        with patch.object(self.service.provider, "market", return_value=({}, {}, [])):
            unbounded = self.service.query("000001", filters=InventoryFilters())
        self.assertEqual(len(items(unbounded)), 1)
        self.assertIsNone(items(unbounded)[0]["inventory_market_value"])

    def test_wind_fills_missing_industry_before_filtering_without_mutating_records(self):
        self.service.demo = False
        self.service.records[0]["industry"] = ""
        self.service.records[1]["industry"] = ""
        self.service.records[2]["industry"] = ""
        with patch.object(self.service.provider, "resolve") as resolve, patch.object(
            self.service.provider, "market", return_value=({"600519.SH": "食品饮料"}, {}, [])
        ):
            response = self.service.query("", filters=InventoryFilters("食品"))
        self.assertEqual({item["code"] for item in items(response)}, {"600519.SH", "000858.SZ"})
        self.assertEqual(len(items(response)[0]["rows"]), 2)
        self.assertEqual(response["screening"]["unknown_industry"], 1)
        self.assertEqual(self.service.records[0]["industry"], "")
        resolve.assert_not_called()

    def test_full_inventory_is_not_limited_to_one_hundred_input_symbols(self):
        template = self.service.records[0]
        self.service.records = [{**template, "code": f"{600100 + i}.SH", "name": f"测试{i}", "quantity": Decimal(100)} for i in range(105)]
        response = self.service.query("", filters=InventoryFilters())
        self.assertEqual(len(items(response)), 105)
        self.assertEqual(response["summary"]["matched"], 105)
        with self.assertRaisesRegex(ValueError, "最多查询 100"):
            self.service.query(" ".join(row["code"] for row in self.service.records))

    def test_invalid_range_is_rejected_and_empty_results_stay_empty(self):
        for lower, upper in [("-1", ""), ("bad", ""), ("NaN", ""), ("", "Infinity"), ("20", "10")]:
            with self.subTest(lower=lower, upper=upper), self.assertRaises(ValueError):
                InventoryFilters(minimum_wan=lower, maximum_wan=upper)
        response = self.service.query("", filters=InventoryFilters("不存在的行业"))
        self.assertEqual(items(response), [])
        self.assertEqual(response["summary"]["matched"], 0)
        with self.assertRaisesRegex(ValueError, "请输入"):
            self.service.query("")


class FilterDesktopTests(DesktopCase):
    def screen(self):
        QTest.mouseClick(self.window.query_button, Qt.MouseButton.LeftButton)
        self.wait(lambda: self.window.response is not None and not self.window.busy)

    def test_default_search_and_combined_filter_export(self):
        self.assertEqual(self.window.search_mode.currentData(), "symbols")
        self.assertTrue(self.window.filter_panel.isHidden())
        self.query("600519")
        self.window.search_mode.setCurrentIndex(1)
        self.assertIsNone(self.window.response)
        self.window.symbols.clear()
        self.window.industry_filter.setCurrentText("银行")
        self.window.minimum_filter.setText("973.6")
        self.window.maximum_filter.setText("973.6")
        self.window.available_filter.setChecked(True)
        self.screen()
        self.assertEqual([item["code"] for item in self.window.items], ["000001.SZ"])
        self.assertIn("1 / 7", self.window.filter_hint.text())
        self.assertEqual(self.window.metrics[0].text(), "1")
        exported = Path(self.tmp.name) / "filtered.csv"
        self.window.export_to(exported)
        with exported.open(encoding="utf-8-sig") as stream:
            rows = list(csv.DictReader(stream))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["证券代码"], "000001.SZ")

    def test_filter_changes_clear_stale_results_reset_and_invalid_range(self):
        self.window.search_mode.setCurrentIndex(1)
        self.screen()
        self.window.minimum_filter.setText("20")
        self.assertIsNone(self.window.response)
        self.assertFalse(self.window.export_button.isEnabled())
        self.window.maximum_filter.setText("10")
        with patch.object(self.service, "query") as query:
            self.window.query()
        query.assert_not_called()
        self.assertIn("下限不能大于上限", self.window.notice.text())
        QTest.mouseClick(self.window.reset_filters_button, Qt.MouseButton.LeftButton)
        self.assertEqual(self.window.minimum_filter.text(), "")
        self.assertEqual(self.window.maximum_filter.text(), "")
        self.screen()
        self.assertEqual(len(self.window.items), 7)
        self.window.search_mode.setCurrentIndex(0)
        self.assertTrue(self.window.filter_panel.isHidden())
        self.query("平安银行")
        self.assertEqual(len(self.window.items), 1)

    def test_recalculation_uses_applied_filters_and_preserves_input(self):
        self.window.search_mode.setCurrentIndex(1)
        self.window.industry_filter.setCurrentText("银行")
        self.screen()
        editor = self.window.editors["000001.SZ"]
        editor.setFocus()
        QTest.keyClicks(editor, "100")
        self.assertFalse(self.window.export_button.isEnabled())
        QTest.mouseClick(self.window.calculate_button, Qt.MouseButton.LeftButton)
        self.wait(lambda: not self.window.busy)
        self.assertEqual({item["code"] for item in self.window.items}, {"000001.SZ", "600036.SH"})
        self.assertEqual(self.window.editors["000001.SZ"].text(), "100")
        self.assertEqual(self.window.items[0]["calculation"]["status"], "ok")
        self.assertIn("screening", self.window.response)
        self.assertTrue(self.window.export_button.isEnabled())

    def test_filter_retry_and_small_window_layout(self):
        self.window.search_mode.setCurrentIndex(1)
        self.window.industry_filter.setCurrentText("银行")
        with patch.object(self.service, "query", side_effect=RuntimeError("temporary")):
            self.window.query()
            self.wait(lambda: not self.window.busy)
        self.assertIn("筛选失败", self.window.filter_hint.text())
        self.window.retry_action()
        self.wait(lambda: not self.window.busy)
        self.assertEqual(len(self.window.items), 2)
        for size in ((1920, 1080), (1280, 720), (940, 560)):
            self.window.resize(*size)
            self.app.processEvents()
            self.assertLessEqual(self.window.height(), size[1], size)
            self.assertGreaterEqual(self.window.table.viewport().height(), 100, size)
            self.assertLessEqual(self.window.reset_filters_button.geometry().right(), self.window.filter_panel.width(), size)

    def test_excluded_prices_can_retry_and_empty_filter_is_not_a_connection_failure(self):
        self.service.demo = False
        self.window.search_mode.setCurrentIndex(1)
        self.window.minimum_filter.setText("100")
        with patch.object(self.service.provider, "market", return_value=({}, {}, ["offline"])):
            self.screen()
        self.assertEqual(self.window.items, [])
        self.assertIn("7 只缺少有效价格", self.window.filter_hint.text())
        self.assertFalse(self.window.retry_button.isHidden())
        self.window.symbols.setText("不存在的标的")
        self.screen()
        self.assertEqual(self.window.wind_label.property("tone"), "neutral")
        self.assertTrue(self.window.retry_button.isHidden())

    def test_more_than_one_hundred_filtered_stocks_can_recalculate(self):
        template = self.service.records[0]
        self.service.records = [{**template, "code": f"{600100 + i}.SH", "name": f"测试{i}", "quantity": Decimal(100)} for i in range(105)]
        self.window.search_mode.setCurrentIndex(1)
        self.screen()
        self.assertEqual(len(self.window.items), 105)
        self.window.mode_editors["600100.SH"].setCurrentIndex(1)
        QTest.keyClicks(self.window.editors["600100.SH"], "100")
        QTest.mouseClick(self.window.calculate_button, Qt.MouseButton.LeftButton)
        self.wait(lambda: not self.window.busy)
        self.assertEqual(len(self.window.items), 105)
        self.assertEqual(self.window.items[0]["calculation"]["status"], "ok")
        self.assertEqual(self.window.editors["600100.SH"].text(), "100")


if __name__ == "__main__":
    unittest.main()
