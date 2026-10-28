"""Explicit per-sheet preset mappings against synthetic workbooks."""
import json
import os
import tempfile
import time
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QDialog

from script_making.desktop import Window
from script_making.desktop_theme import STYLE
from script_making.desktop_widgets import PresetMappingDialog
from script_making.service import ReportService
from script_making.storage import filename, save_files
from script_making.tests.test_reports import fixture


class PerSheetMappingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setStyle("Fusion")
        cls.app.setStyleSheet(STYLE)

    def setUp(self):
        self.cache = Path(__file__).resolve().parents[1] / "cache" / "preset-map-tests"
        self.cache.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=self.cache)
        self.root = Path(self.temp.name)
        self.service = ReportService(self.root / "app")
        source = self.root / "inputs"
        swap = fixture(source / filename("swap", "2000-01-07"),
                       headers=["交易确认书编号", "标的物代码", "标的名义本金额", "开仓操作人员"],
                       rows=[["S1", "000001.SZ", 1, "201464"], ["S2", "600000.SH", 0, "201464"]])
        review = fixture(source / filename("review", "2000-01-07"), "簿记要素",
                         headers=["协议编号", "交易对手", "标的代码", "标的", "交易达成日", "交易起始日", "名义金额", "操作人员"],
                         rows=[["R1", "甲", "000001.SZ", "样本甲", "2000-01-01", "2000-01-02", .1, "201464"],
                               ["R2", "乙", "600000.SH", "样本乙", "2000-01-01", "2000-01-02", .100000001, "201464"],
                               ["R3", "丙", "000002.SZ", "样本丙", "2000-01-01", "2000-01-02", 1, "2014640"],
                               ["R4", "丁", "000003.SZ", "样本丁", "2000-01-01", "2000-01-02", 5, "222222"],
                               ["R5", "戊", "000004.SZ", "样本戊", "2000-01-01", "2000-01-02", None, "201464"]])
        save_files(self.service.settings.data_path(), {"swap": swap, "review": review}, "2000-01-07", "合成测试")
        self.window = Window(self.service, auto_start=False)
        self.window.show()
        self.window.refresh_catalog()
        self.wait_idle()

    def wait_idle(self):
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            self.app.processEvents()
            if self.window.worker is None and not self.window.debounce.isActive() and not self.window._syncing:
                self.app.processEvents()
                if self.window.worker is None and not self.window.debounce.isActive():
                    return
            time.sleep(.01)
        self.fail("桌面筛选任务未结束")

    def tearDown(self):
        self.wait_idle()
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()
        assert self.root.resolve().is_relative_to(self.cache.resolve())
        self.temp.cleanup()

    def select_in_dialog(self, amount, owner):
        def choose():
            dialog = QApplication.activeModalWidget()
            self.assertIsInstance(dialog, PresetMappingDialog)
            dialog.combos["amount"].setCurrentIndex(dialog.combos["amount"].findData(amount))
            dialog.combos["owner"].setCurrentIndex(dialog.combos["owner"].findData(owner))
            dialog.validate()
        QTimer.singleShot(0, choose)
        self.window.open_preset_mapping()
        self.wait_idle()

    def test_review_mapping_keeps_presets_and_both_quick_underlying_aliases(self):
        self.window.switch_kind("review")
        self.wait_idle()
        self.assertEqual(self.window.result["matched"], 5)
        self.assertTrue(self.window.preset_mapping_button.isEnabled())
        self.assertFalse(self.window.preset_amount.isEnabled())
        self.assertFalse(self.window.preset_owner.isEnabled())
        for button in (self.window.preset_owner, self.window.preset_mapping_button):
            self.assertNotIn("201464", button.text())
            self.assertNotIn("201464", button.toolTip())
        self.assertTrue(self.window.quick_buttons["标的物代码"].isEnabled())
        self.assertTrue(self.window.quick_buttons["标的物名称"].isEnabled())
        self.window.quick_buttons["标的物代码"].click()
        self.assertEqual(self.window.filters[-1].column.currentData(), "c2")
        self.window.quick_buttons["标的物名称"].click()
        self.assertEqual(self.window.filters[-1].column.currentData(), "c3")
        self.select_in_dialog("c6", "c7")
        self.assertEqual(self.window.result["matched"], 3)
        self.assertIn("名义金额", self.window.preset_amount.text())
        self.assertTrue(self.window.preset_amount.isChecked())
        self.assertFalse(self.window.preset_owner.isChecked())
        self.assertIn("需筛类型", self.window.preset_owner.text())
        self.assertIn("不判断", self.window.preset_owner.toolTip())
        self.window.preset_owner.click()
        self.wait_idle()
        self.assertEqual([row["values"][0] for row in self.window.result["rows"]], ["R2"])
        self.assertEqual(self.window._preset_mappings(), {"amount": {"id": "c6", "name": "名义金额"},
                                                          "owner": {"id": "c7", "name": "操作人员"}})
        # Switching sheets does not leak mappings into the other report.
        self.window.switch_kind("swap")
        self.wait_idle()
        self.assertEqual(self.window._preset_mappings(), {})
        self.window.switch_kind("review")
        self.wait_idle()
        self.assertEqual([row["values"][0] for row in self.window.result["rows"]], ["R2"])

    def test_saved_mapping_survives_restart_with_current_sheet(self):
        self.window.switch_kind("review")
        self.wait_idle()
        self.select_in_dialog("c6", "c7")
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()
        self.window = Window(self.service, auto_start=False)
        self.window.show()
        self.window.refresh_catalog()
        self.wait_idle()
        self.window.switch_kind("review")
        self.wait_idle()
        self.assertEqual(self.window.result["matched"], 3)
        self.assertTrue(self.window.preset_amount.isEnabled())
        self.assertTrue(self.window.preset_owner.isEnabled())
        self.assertFalse(self.window.preset_owner.isChecked())

    def test_changed_column_name_never_falls_back_without_explicit_choice(self):
        self.window.preferences.setValue(self.window._preset_mapping_key(), json.dumps({
            "amount": {"id": "c2", "name": "原始金额"}}, ensure_ascii=False))
        self.window._update_quick_controls()
        self.window.query()
        self.wait_idle()
        self.assertFalse(self.window.preset_amount.isEnabled())
        self.assertIn("需重配", self.window.preset_amount.text())
        self.assertIn("重新选择", self.window.preset_amount.toolTip())
        # Despite a correctly named auto column, an invalid manual mapping is not guessed.
        self.assertEqual(self.window.result["matched"], 2)
        dialog = PresetMappingDialog(self.window.columns, self.window._preset_mappings(), self.window)
        dialog.validate()
        self.assertNotEqual(dialog.result(), QDialog.DialogCode.Accepted)
        self.assertIn("重新选择", dialog.error.text())
        dialog.combos["amount"].setCurrentIndex(0)
        dialog.validate()
        self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
        self.assertEqual(dialog.mappings, {})
        self.select_in_dialog(None, None)
        self.assertTrue(self.window.preset_amount.isEnabled())
        self.assertEqual(self.window.result["matched"], 1)

    def test_duplicate_names_are_disambiguated_and_manual_id_is_exact(self):
        columns = [{"id": "c1", "name": "金额", "type": "number"},
                   {"id": "c7", "name": "金额", "type": "number"},
                   {"id": "c9", "name": "人员", "type": "text"}]
        dialog = PresetMappingDialog(columns, {}, self.window)
        captions = [dialog.combos["amount"].itemText(i) for i in range(dialog.combos["amount"].count())]
        self.assertIn("金额  （Excel B 列）", captions)
        self.assertIn("金额  （Excel H 列）", captions)
        dialog.combos["amount"].setCurrentIndex(dialog.combos["amount"].findData("c7"))
        dialog.validate()
        self.assertEqual(dialog.mappings["amount"], {"id": "c7", "name": "金额"})

    def test_mapping_wont_exceed_the_existing_condition_limit(self):
        self.window.switch_kind("review")
        self.wait_idle()
        self.window._remove_filters()
        for _ in range(30):
            self.assertIsNotNone(self.window.add_filter(schedule=False))
        self.select_in_dialog("c6", "c7")
        self.assertEqual(self.window._preset_mappings(), {})
        self.assertIn("30", self.window.statusBar().currentMessage())
        self.assertFalse(self.window.preset_amount.isEnabled())


if __name__ == "__main__":
    unittest.main()
