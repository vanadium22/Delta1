import csv
import io
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PySide6.QtCore import Qt

from securities_lending.calculation import size_order, source_coverage
from securities_lending.config import DEFAULTS, ROOT
from securities_lending.exporting import clipboard_text
from securities_lending.service import InventoryService
from securities_lending.tests import test_desktop as native_tests
from securities_lending.wind import IndustryProvider
from securities_lending.wind_worker import fetch_securities


class CoverageTests(unittest.TestCase):
    def coverage(self, own, other, demand, price="10"):
        rows = [{"quantity": Decimal(own), "source": " 互换 "}, {"quantity": Decimal(other), "source": "甲台"}]
        calc = size_order(None, price, Decimal(own) + Decimal(other), requested_shares=demand)
        return calc, source_coverage(rows, calc)

    def test_own_combined_other_and_insufficient(self):
        for demand, status, shortage in [(1000, "own", None), (1500, "combined", None), (2100, "insufficient", 100)]:
            calc, coverage = self.coverage(1200, 800, demand)
            self.assertEqual(coverage["status"], status)
            self.assertEqual(coverage["shortage_shares"], shortage)
            self.assertEqual(calc["maximum_shares"], 2000)
            self.assertEqual(Decimal(calc["maximum_nominal"]), 20000)
        self.assertEqual(self.coverage(200, 1800, 1000)[1]["status"], "other")

    def test_only_exact_swap_is_own_and_fractional_rows_aggregate_first(self):
        rows = [{"source": source, "quantity": Decimal("57.5")} for source in ("互换", "互换", "互换券源", "", "其他")]
        result = source_coverage(rows, size_order(None, 10, "287.5", requested_shares=200))
        self.assertEqual(result["own_shares"], 100)
        self.assertEqual(result["other_shares"], 100)
        self.assertEqual(result["status"], "combined")

    def test_missing_quantity_never_confirms_capacity(self):
        rows = [{"source": "互换", "quantity": 1000}, {"source": "甲台", "quantity": None}]
        calc = size_order(None, 10, 1000, False, requested_shares=100)
        result = source_coverage(rows, calc)
        self.assertEqual(result["status"], "unknown")
        self.assertEqual(result["own_shares"], 1000)
        self.assertIsNone(result["other_shares"])
        self.assertIsNone(calc["maximum_shares"])

    def test_share_order_does_not_need_price_for_quantity_but_cannot_estimate(self):
        calc, coverage = self.coverage(1200, 800, 1500, price=None)
        self.assertEqual(calc["status"], "ok")
        self.assertEqual(coverage["status"], "combined")
        self.assertIsNone(calc["actual_nominal"])
        self.assertIsNone(calc["maximum_nominal"])
        self.assertIsNone(calc["target_nominal"])

    def test_share_orders_are_not_silently_rounded_or_capped(self):
        for demand in (99, 101, "100.1", 0, -100, True, "NaN", "1e100000"):
            result = size_order(None, 10, 2000, requested_shares=demand)
            self.assertEqual(result["status"], "invalid", demand)
            self.assertIsNone(result["executable_shares"])
        result = size_order(None, 10, 1999, requested_shares=2000)
        self.assertEqual(result["requested_shares"], 2000)
        self.assertEqual(result["maximum_shares"], 1900)
        self.assertEqual(result["status"], "insufficient")


class IdentificationTests(unittest.TestCase):
    def setUp(self):
        root = ROOT / "data" / "test_tmp"
        root.mkdir(parents=True, exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=root)
        self.addCleanup(self.tmp.cleanup)
        self.service = InventoryService(Path(self.tmp.name), demo=True)
        self.service.load_today()

    def test_each_input_has_identity_and_inventory_feedback(self):
        result = self.service.query("贵州茅台 浦发银行 000858 未知名字 999999")
        rows = [group["securities"][0] for group in result["results"]]
        self.assertEqual([row["inventory_status"] for row in rows], ["available", "absent", "zero", "unknown", "absent"])
        self.assertEqual(rows[1]["code"], "600000.SH")
        self.assertTrue(rows[1]["identified"])
        self.assertFalse(rows[3]["identified"])
        self.assertFalse(rows[4]["identified"])
        self.assertEqual(result["summary"]["matched"], 2)

    def test_inventory_unavailable_is_never_no_stock(self):
        self.service.records = []
        self.service.state["state"] = "unavailable"
        row = self.service.query("600000")["results"][0]["securities"][0]
        self.assertTrue(row["identified"])
        self.assertEqual(row["inventory_status"], "unknown")
        self.assertIsNone(row["calculation"]["maximum_shares"])
        self.assertIsNone(row["coverage"]["own_shares"])

    def test_wind_identity_code_and_name_and_fresh_prices(self):
        self.service.demo = False
        identities = {"600000.SH": {"name": "浦发银行", "source": "fake Wind"}}
        with patch.object(self.service.provider, "resolve", return_value=(identities, [])), patch.object(self.service.provider, "market", side_effect=[({}, {"600000.SH": {"price": "10"}}, []), ({}, {"600000.SH": {"price": "20"}}, [])]) as market:
            first = self.service.query("浦发银行 600000", input_targets={"浦发银行": "10000"})
            second = self.service.query("600000", {"600000.SH": "10000"})
        self.assertEqual(first["results"][0]["securities"][0]["name"], "浦发银行")
        self.assertEqual(first["results"][0]["securities"][0]["calculation"]["requested_shares"], 1000)
        self.assertEqual(second["results"][0]["securities"][0]["calculation"]["requested_shares"], 500)
        self.assertEqual(market.call_count, 2)

    def test_name_ambiguity_does_not_assign_amount(self):
        self.service.demo = False
        identities = {code: {"name": name, "source": "fake Wind"} for code, name in [("600000.SH", "测试银行甲"), ("600001.SH", "测试银行乙")]}
        with patch.object(self.service.provider, "resolve", return_value=(identities, [])), patch.object(self.service.provider, "market") as market:
            with self.assertRaisesRegex(ValueError, "匹配 2"):
                self.service.query("测试银行", input_targets={"测试银行": "10000"})
            market.assert_not_called()

    def test_name_matches_include_every_source_for_the_resolved_code(self):
        self.service.records[1]["name"] = "贵州茅台别名"
        row = self.service.query("贵州茅台")["results"][0]["securities"][0]
        self.assertEqual(row["quantity"], 20000)
        self.assertEqual(len(row["rows"]), 2)

    def test_wind_alias_resolves_back_to_existing_inventory(self):
        self.service.demo = False
        identity = {"600519.SH": {"name": "茅台新名", "source": "fake Wind"}}
        with patch.object(self.service.provider, "resolve", return_value=(identity, [])), patch.object(self.service.provider, "market", return_value=({}, {}, [])):
            row = self.service.query("茅台新名", share_targets={"600519.SH": "15000"})["results"][0]["securities"][0]
        self.assertEqual(row["inventory_status"], "available")
        self.assertEqual(row["quantity"], 20000)
        self.assertEqual(row["coverage"]["status"], "combined")

    def test_wind_can_fill_missing_name_without_dropping_inventory(self):
        self.service.demo = False
        for row in self.service.records:
            if row["code"] == "600519.SH":
                row["name"] = ""
        identity = {"600519.SH": {"name": "贵州茅台", "source": "fake Wind"}}
        with patch.object(self.service.provider, "resolve", return_value=(identity, [])) as resolve, patch.object(self.service.provider, "market", return_value=({}, {}, [])):
            row = self.service.query("600519")["results"][0]["securities"][0]
        self.assertEqual(resolve.call_args.args[0], {"600519.SH"})
        self.assertEqual(row["name"], "贵州茅台")
        self.assertEqual(row["identity_source"], "fake Wind")
        self.assertEqual(row["quantity"], 20000)

    def test_amount_share_conflict_rejected_and_batch_amount_replaces_shares(self):
        with self.assertRaisesRegex(ValueError, "不能同时"):
            self.service.query("600519", {"600519.SH": "10000"}, share_targets={"600519.SH": "100"})
        result = self.service.query("600519", input_targets={"600519": "5000000"}, share_targets={"600519.SH": "100"})
        self.assertEqual(result["share_targets"], {})
        self.assertEqual(result["results"][0]["matches"][0]["calculation"]["requested_shares"], 3500)

    def test_export_carries_identification_and_capacity_evidence(self):
        result = self.service.query("600519", share_targets={"600519.SH": "15000"})
        copied = list(csv.DictReader(io.StringIO(clipboard_text(result["results"][0]["matches"], result["status"])), delimiter="\t"))
        row = copied[0]
        self.assertEqual(row["需求输入方式"], "股数")
        self.assertEqual(row["输入要求股数"], "15000")
        self.assertEqual(row["自有最大可融（股）"], "12000")
        self.assertEqual(row["其他来源最大可融（股）"], "8000")
        self.assertEqual(row["自有缺口（股）"], "3000")
        self.assertIn("可补足", row["券源覆盖判断"])
        self.assertEqual(Decimal(row["最大可融估算金额（元）"]), Decimal("28005000"))


class WindIdentityTests(unittest.TestCase):
    def fake(self):
        return SimpleNamespace(start=lambda **kw: SimpleNamespace(ErrorCode=0),
            wss=lambda *args: SimpleNamespace(ErrorCode=0, Codes=["600000.SH", "999999.SH", "600519.SH"], Data=[["浦发银行", None, "贵州茅台"]]),
            wset=lambda *args: SimpleNamespace(ErrorCode=0, Fields=["sec_name", "wind_code"], Data=[["浦发银行", "工商银行", "工商银行测试", "非法"], ["600000.SH", "601398.SH", "600001.SH", "BAD"]]))

    def test_codes_map_by_returned_code_not_order_and_ignore_unrequested(self):
        response = fetch_securities({"codes": ["999999.SH", "600000.SH"]}, self.fake())
        self.assertEqual(list(response["securities"]), ["600000.SH"])
        self.assertEqual(response["securities"]["600000.SH"]["name"], "浦发银行")

    def test_name_lookup_uses_fields_and_prefers_exact_name(self):
        response = fetch_securities({"codes": [], "names": ["工商银行"], "day": "2026-10-15"}, self.fake())
        self.assertEqual(list(response["securities"]), ["601398.SH"])

    def test_failure_is_inconclusive_and_does_not_erase_other_identity(self):
        wind = self.fake()
        wind.wset = lambda *args: SimpleNamespace(ErrorCode=-1)
        result = fetch_securities({"codes": ["600000.SH"], "names": ["不存在"], "day": "2026-10-15"}, wind)
        self.assertIn("600000.SH", result["securities"])
        self.assertTrue(result["warnings"])

    def test_worker_timeout_and_disabled_wind_never_invent_identity(self):
        provider = IndustryProvider(ROOT / "data" / "test_tmp")
        with patch("securities_lending.wind.subprocess.run", side_effect=OSError("offline")) as run:
            securities, warnings = provider.resolve(["600000.SH"], [], "2026-10-15", DEFAULTS)
            self.assertEqual(securities, {})
            self.assertIn("未识别不代表", "".join(warnings))
            self.assertEqual(run.call_count, 1)
        with patch("securities_lending.wind.subprocess.run") as run:
            securities, warnings = provider.resolve(["600000.SH"], [], "2026-10-15", {**DEFAULTS, "wind_enabled": False})
            run.assert_not_called()
            self.assertEqual(securities, {})


class AvailabilityDesktopTests(native_tests.DesktopCase):
    def test_shares_auto_refresh_and_own_coverage(self):
        self.query("600519")
        self.window.mode_editors["600519.SH"].setCurrentIndex(1)
        self.edit("600519.SH", "15000")
        self.assertFalse(self.window.export_ready())
        self.wait(lambda: not self.window.busy and self.window.items and self.window.items[0]["calculation"]["status"] == "ok")
        self.assertEqual(self.window.items[0]["coverage"]["status"], "combined")
        self.assertEqual(self.window.items[0]["calculation"]["requested_shares"], 15000)
        self.assertIn("可补足", self.window.table.item(0, 8).text())
        self.assertTrue(self.window.editors["600519.SH"].hasFocus())
        self.assertTrue(self.window.export_ready())

    def test_mode_change_clears_old_value_and_empty_input_clears_verdict(self):
        self.query("600519")
        self.edit("600519.SH", "500")
        self.window.mode_editors["600519.SH"].setCurrentIndex(1)
        self.assertEqual(self.window.editors["600519.SH"].text(), "")
        self.calculate()
        self.assertEqual(self.window.items[0]["calculation"]["status"], "empty")
        self.assertEqual(self.window.items[0]["coverage"]["status"], "empty")

    def test_unknown_name_stays_visible_and_no_inventory_highlighted(self):
        self.query("浦发银行 000858 未知名称")
        self.assertEqual(self.window.table.rowCount(), 3)
        for row in (0, 1):
            self.assertIn("库存没有", self.window.table.item(row, 8).text())
            self.assertEqual(self.window.table.item(row, 0).background().color().name(), "#fff0ed")
        self.assertIn("未确认", self.window.table.item(2, 0).text())
        self.assertIn("未确认", self.window.items[2]["inventory_message"])

    def test_refresh_failure_cannot_leave_own_coverage_success(self):
        self.query("600519")
        self.edit("600519.SH", "500")
        self.service.demo = False
        with patch.object(self.service.provider, "market", return_value=({}, {}, ["offline"])):
            self.calculate()
        self.assertEqual(self.window.items[0]["coverage"]["status"], "no_price")
        self.assertNotIn("足额覆盖", self.window.table.item(0, 8).text())

    def test_splitter_can_enlarge_details_and_highlight_numeric_cells(self):
        self.query("600519")
        self.window.resize(1240, 660)
        self.window.splitter.setSizes([190, 260])
        self.app.processEvents()
        self.assertGreater(self.window.detail_panel.height(), 190)
        self.assertGreaterEqual(self.window.table.viewport().height(), 100)
        self.assertTrue(self.window.detail_table.item(0, 2).font().bold())
        self.assertEqual(self.window.table.item(0, 2).data(Qt.ItemDataRole.UserRole), True)


if __name__ == "__main__":
    unittest.main()
