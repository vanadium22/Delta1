"""Exercise quick filters and presets using synthetic workbooks only."""
import os
import tempfile
import time
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication

from script_making.desktop import Window
from script_making.desktop_theme import STYLE
from script_making.desktop_widgets import FilterRow
from script_making.service import ReportService
from script_making.storage import filename, save_files
from script_making.tests.test_reports import fixture


class QuickFilterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setStyle("Fusion")
        cls.app.setStyleSheet(STYLE)

    def setUp(self):
        self.cache = Path(__file__).resolve().parents[1] / "cache" / "shortcut-tests"
        self.cache.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=self.cache)
        self.root = Path(self.temp.name)
        self.service = ReportService(self.root / "app")
        headers = ["交易确认书编号", "合约编号", "标的物代码", "标的物名称", "交易对手名称",
                   "交易达成日", "起始日", "标的名义本金额", "开仓操作人员"]
        rows = [["A", "SWAP-A", "100000.SZ", "示例甲", "对手甲", "2000-01-01", "2000-01-02", .1, "201464"],
                ["B", "SWAP-B", "000001.SZ", "示例乙", "对手乙", "2000-01-01", "2000-01-02", .100000001, "201464"],
                ["C", "SWAP-C", "600000.SH", "示例丙", "对手丙", "2000-01-01", "2000-01-02", .2, "998877"],
                ["D", "SWAP-D", "300750.SZ", "示例丁", "对手丁", "2000-01-01", "2000-01-02", 1, "201464"],
                ["E", "SWAP-E", "000002.SZ", "示例戊", "对手戊", "2000-01-01", "2000-01-02", .05, "998877"],
                ["F", "SWAP-F", "000099.SZ", "示例己", "对手己", "2000-01-01", "2000-01-02", 5, "2014640"],
                ["G", "SWAP-G", "000003.SZ", "示例庚", "对手庚", "2000-01-01", "2000-01-02", None, "201464"]]
        source = self.root / "input"
        sources = {"swap": fixture(source / filename("swap", "2000-01-07"), headers=headers, rows=rows),
                   "review": fixture(source / filename("review", "2000-01-07"), "簿记要素")}
        save_files(self.service.settings.data_path(), sources, "2000-01-07", "合成测试")
        self.window = Window(self.service, auto_start=False)
        self.window.show()
        self.app.processEvents()

    def wait_idle(self):
        deadline = time.monotonic() + 20
        seen = []
        while time.monotonic() < deadline:
            self.app.processEvents()
            if self.window.result is not None:
                seen.append(self.window.result["matched"])
            if self.window.worker is None and not self.window.debounce.isActive() and not self.window._syncing:
                self.app.processEvents()
                if self.window.worker is None and not self.window.debounce.isActive():
                    return seen
            time.sleep(.01)
        self.fail("桌面筛选任务未结束")

    def load(self):
        self.window.refresh_catalog()
        seen = self.wait_idle()
        self.assertIsNotNone(self.window.result, self.window.error.text())
        return seen

    def tearDown(self):
        self.wait_idle()
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()
        assert self.root.resolve().is_relative_to(self.cache.resolve())
        self.temp.cleanup()

    def identifiers(self):
        return [row["values"][0] for row in self.window.result["rows"]]

    def test_default_preset_is_strict_and_first_result_is_filtered(self):
        seen = self.load()
        self.assertTrue(self.window.preset_amount.isChecked())
        self.assertFalse(self.window.preset_owner.isChecked())
        self.assertNotIn(7, seen, "开启默认条件时不得展示未筛选结果")
        self.assertEqual(self.identifiers(), ["B", "C", "D", "F"])
        self.window.preset_owner.click()
        self.wait_idle()
        self.assertEqual(self.identifiers(), ["B", "D"])
        self.window.preset_amount.click()
        self.wait_idle()
        self.assertEqual(self.identifiers(), ["A", "B", "D", "G"])
        self.window.clear_filters()
        self.wait_idle()
        self.assertFalse(self.window.preset_amount.isChecked())
        self.assertFalse(self.window.preset_owner.isChecked())
        self.assertEqual(self.window.result["matched"], 7)

    def test_each_quick_button_targets_the_named_column(self):
        self.load()
        names = ["标的物代码", "标的物名称", "交易对手名称", "交易确认书编号", "合约编号", "交易达成日", "起始日"]
        for name in names:
            with self.subTest(column=name):
                before = len(self.window.filters)
                self.window.quick_buttons[name].click()
                self.assertEqual(len(self.window.filters), before + 1)
                row = self.window.filters[-1]
                self.assertEqual(row.column.currentText(), name)
                self.assertEqual(row.value.text(), "")
        self.wait_idle()

    def test_multiple_tickers_and_existing_or_group_combine_with_presets(self):
        self.load()
        self.window.quick_buttons["标的物代码"].click()
        row = self.window.filters[-1]
        row.value.setText("000001.SZ； 600000.SH")
        self.wait_idle()
        self.assertEqual(self.identifiers(), ["B", "C"])
        row.join.setCurrentIndex(row.join.findData("any"))
        self.window.quick_buttons["标的物名称"].click()
        other = self.window.filters[-1]
        other.join.setCurrentIndex(other.join.findData("any"))
        other.value.setText("示例丁")
        self.wait_idle()
        self.assertEqual(self.identifiers(), ["B", "C", "D"])
        self.window.preset_owner.click()
        self.wait_idle()
        self.assertEqual(self.identifiers(), ["B", "D"])

    def test_missing_columns_do_not_filter_the_review_sheet(self):
        self.load()
        self.window.preset_owner.click()
        self.wait_idle()
        self.window.switch_kind("review")
        self.wait_idle()
        self.assertFalse(self.window.preset_amount.isEnabled())
        self.assertFalse(self.window.preset_owner.isEnabled())
        self.assertTrue(self.window.preset_amount.toolTip())
        self.assertTrue(self.window.preset_owner.toolTip())
        self.assertEqual(self.window.result["matched"], 2)
        self.window.switch_kind("swap")
        self.wait_idle()
        self.assertTrue(self.window.preset_amount.isEnabled())
        self.assertTrue(self.window.preset_owner.isEnabled())
        self.assertEqual(self.identifiers(), ["B", "D"])

    def test_duplicate_column_is_not_silently_chosen(self):
        source = self.root / "duplicate" / filename("swap", "2000-01-10")
        fixture(source, headers=["交易确认书编号", "标的名义本金额", "标的名义本金额"],
                rows=[["A", 1, 0], ["B", 0, 1]])
        self.service.import_files([source])
        self.window.refresh_catalog(preferred="2000-01-10")
        self.wait_idle()
        self.assertEqual(self.window.result["matched"], 2)
        self.assertFalse(self.window.preset_amount.isEnabled())
        self.assertIn("多个", self.window.preset_amount.toolTip())
        row = self.window.filters[0]
        labels = [row.column.itemText(i) for i in range(row.column.count())]
        self.assertIn("标的名义本金额（Excel B 列）", labels)
        self.assertIn("标的名义本金额（Excel C 列）", labels)

    def test_underlying_help_matches_format_and_operation(self):
        row = FilterRow([{"id": "c0", "name": "标的代码", "type": "text"},
                         {"id": "c1", "name": "标的代码", "type": "text"}])
        self.assertIn("满足任一", row.value.toolTip())
        row.op.setCurrentIndex(row.op.findData("eq"))
        self.assertIn("单个完整值", row.value.toolTip())
        self.assertEqual(row.value.placeholderText(), "输入完整值")
        row.deleteLater()


if __name__ == "__main__":
    unittest.main()
