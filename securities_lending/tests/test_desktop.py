import csv
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from securities_lending.config import ROOT
from securities_lending.desktop import Window, configure_style
from securities_lending.desktop_settings import SettingsDialog
from securities_lending.service import InventoryService


class DesktopCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        configure_style(cls.app)

    def setUp(self):
        root = ROOT / "data" / "test_tmp"
        root.mkdir(parents=True, exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=root)
        self.service = InventoryService(Path(self.tmp.name), demo=True)
        self.window = Window(self.service)
        self.window.show()
        self.wait(lambda: self.service.state["state"] == "ready" and not self.window.busy)

    def tearDown(self):
        self.wait(lambda: not self.window.busy)
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()
        self.tmp.cleanup()

    def wait(self, predicate):
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            self.app.processEvents()
            if predicate():
                return
            # Let Python workers import/parse workbooks on a cold start. A tight
            # QTest.qWait loop can retain the GIL and starve their first import.
            time.sleep(0.01)
        self.fail("Native UI operation timed out")

    def query(self, symbols):
        self.window.symbols.setText(symbols)
        QTest.mouseClick(self.window.query_button, Qt.MouseButton.LeftButton)
        self.wait(lambda: self.window.response is not None and not self.window.busy)

    def edit(self, code, amount):
        editor = self.window.editors[code]
        editor.setFocus()
        editor.selectAll()
        QTest.keyClicks(editor, amount)

    def calculate(self):
        QTest.mouseClick(self.window.calculate_button, Qt.MouseButton.LeftButton)
        self.wait(lambda: self.window.response is not None and not self.window.busy)


class DesktopTests(DesktopCase):
    def test_native_workflow_per_stock_notional_and_insufficient_capacity(self):
        self.query("600519 300750 000001")
        self.assertEqual(self.window.table.rowCount(), 3)
        self.edit("600519.SH", "500")
        self.edit("300750.SZ", "5000")
        self.edit("000001.SZ", "100")
        self.assertFalse(self.window.export_button.isEnabled())
        self.assertEqual(self.window.items[0]["calculation"]["status"], "pending")
        self.calculate()
        items = {item["code"]: item for item in self.window.items}
        self.assertEqual(items["600519.SH"]["calculation"]["executable_shares"], 3500)
        self.assertEqual(items["300750.SZ"]["calculation"]["status"], "insufficient")
        self.assertEqual(items["300750.SZ"]["calculation"]["maximum_shares"], 160000)
        self.assertIn("160,000", self.window.table.item(1, 8).text())
        self.assertEqual(self.window.editors["000001.SZ"].text(), "100")
        self.assertTrue(self.window.export_button.isEnabled())
        exported = Path(self.tmp.name) / "result.csv"
        self.window.export_to(exported)
        with exported.open(encoding="utf-8-sig") as stream:
            rows = list(csv.DictReader(stream))
        self.assertEqual(rows[0]["目标名本（元）"], "5000000")
        self.assertEqual(rows[1]["校验通过股数"], "")
        self.assertEqual(rows[1]["最大可借（股）"], "160000")
        self.assertEqual(rows[0]["数据模式"], "demo")

    def test_price_failure_clears_previous_price_and_size(self):
        self.service.demo = False
        self.window.target_texts["000001.SZ"] = "100"
        quote = {"price": "12.17", "source": "fake Wind", "retrieved_at": "2026-10-14T10:01:00+08:00"}
        with patch.object(self.service.provider, "market", return_value=({}, {"000001.SZ": quote}, [])):
            self.query("000001")
        self.assertEqual(self.window.items[0]["calculation"]["status"], "ok")
        with patch.object(self.service.provider, "market", return_value=({}, {}, ["offline"])):
            self.calculate()
        self.assertIsNone(self.window.items[0]["quote"])
        self.assertEqual(self.window.items[0]["calculation"]["status"], "no_price")
        self.assertEqual(self.window.table.item(0, 7).text(), "—")

    def test_zero_inventory_and_unknown_symbol(self):
        self.window.target_texts["000858.SZ"] = "100"
        self.query("000858 600000 不存在")
        self.assertEqual(self.window.items[0]["calculation"]["status"], "insufficient")
        self.assertEqual(self.window.items[0]["calculation"]["maximum_shares"], 0)
        self.assertEqual(self.window.items[1]["name"], "浦发银行")
        self.assertEqual(self.window.items[1]["inventory_status"], "absent")
        self.assertEqual(self.window.items[2]["identification"], "未确认 · 请核对代码/名称")
        self.assertEqual(self.window.metrics[0].text(), "1")

    def test_margin_tab_follows_selection_and_can_copy_rows(self):
        self.query("600519 000001 600000 不存在")
        window = self.window
        window.detail_tabs.setCurrentIndex(window.margin_tab_index)
        self.assertEqual(window.detail_tabs.tabText(window.margin_tab_index), "两融券单（2 条）")
        self.assertEqual(window.margin_table.rowCount(), 2)
        self.assertEqual(window.margin_table.item(0, 2).text(), "3.20%")
        self.assertEqual(window.margin_table.item(0, 3).text(), "5,000")
        window.margin_table.selectRow(1)
        QTest.mouseClick(window.copy_detail_button, Qt.MouseButton.LeftButton)
        copied = QApplication.clipboard().text()
        self.assertIn("600519.SH\t渠道 B", copied)
        self.assertNotIn("渠道 A", copied)

        window.focus_row(1)
        self.assertEqual(window.detail_tabs.currentIndex(), window.margin_tab_index)
        self.assertEqual(window.detail_tabs.tabText(window.margin_tab_index), "两融券单（0 条）")
        self.assertEqual(window.margin_status.text(), "该标的无两融记录")
        self.assertFalse(window.copy_detail_button.isEnabled())
        window.focus_row(2)
        self.assertEqual(window.margin_table.rowCount(), 1)
        self.assertEqual(window.detail_table.rowCount(), 0)
        window.focus_row(3)
        self.assertIn("标的代码未确认", window.margin_status.text())

    def test_refresh_invalidates_previous_calculations(self):
        self.query("600519")
        QTest.mouseClick(self.window.refresh_button, Qt.MouseButton.LeftButton)
        self.wait(lambda: not self.window.busy)
        self.assertIsNone(self.window.response)
        self.assertEqual(self.window.table.rowCount(), 0)
        self.assertFalse(self.window.export_button.isEnabled())

    def test_settings_rejects_invalid_filename(self):
        dialog = SettingsDialog(self.service.config, self.window)
        dialog.fields["file_glob"].setText("../bad.xlsx")
        dialog.save()
        self.assertTrue(dialog.error.text())
        self.assertNotEqual(self.service.config["file_glob"], "../bad.xlsx")
        dialog.close()


if __name__ == "__main__":
    unittest.main()
