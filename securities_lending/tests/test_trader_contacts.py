import csv
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QDialog

from securities_lending.config import ROOT
from securities_lending.desktop_contacts import ContactsDialog
from securities_lending.trader_contacts import contact_for, contacts_path, load_contacts, save_contacts, validate_contacts
from securities_lending.tests.test_desktop import DesktopCase


class ContactMappingTests(unittest.TestCase):
    def setUp(self):
        root = ROOT / "data" / "test_tmp"
        root.mkdir(parents=True, exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=root)
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.path = contacts_path(self.root, False)
        self.book, error = load_contacts(self.path)
        self.assertFalse(error)

    def test_exact_industry_matches_and_uncertain_categories_stay_blank(self):
        self.assertEqual(contact_for(" 电子 ", self.book)["desk"], "电子/软件/汽车")
        self.assertEqual(contact_for("机械设备", self.book)["desk"], "机械/硬件")
        self.assertEqual(contact_for("煤炭", self.book)["desk"], "周期")
        self.assertEqual(contact_for("食品饮料", self.book)["desk"], "消费")
        for industry in ("银行", "医药生物", "电力设备", "计算机", "电子 / 计算机", "未知电子", "", None):
            self.assertEqual(contact_for(industry, self.book)["traders"], [])
        self.assertIn("暂读", self.book["note"])
        self.assertFalse(self.path.exists())

    def test_edit_persistence_and_demo_isolation(self):
        self.book["desks"]["新增交易台"] = ["@测试甲", "测试乙"]
        self.book["industries"]["银行"] = "新增交易台"
        self.book["group"] = "修改后的群"
        saved = save_contacts(self.path, self.book)
        loaded, error = load_contacts(self.path)
        self.assertFalse(error)
        self.assertEqual(saved, loaded)
        self.assertEqual(contact_for("银行", loaded)["traders"], ["测试甲", "测试乙"])
        demo_path = contacts_path(self.root, True)
        demo, _ = load_contacts(demo_path)
        self.assertNotEqual(demo["group"], loaded["group"])
        save_contacts(demo_path, demo)
        self.assertEqual(load_contacts(self.path)[0], loaded)

    def test_corrupt_or_duplicate_json_does_not_fall_back_to_draft(self):
        for text in ('{"bad":', '{"schema_version": 1, "group": "甲", "group": "乙"}'):
            self.path.write_text(text, encoding="utf-8")
            book, error = load_contacts(self.path)
            self.assertIn("读取失败", error)
            self.assertEqual(contact_for("电子", book)["traders"], [])
            self.assertEqual(book["group"], "")

    def test_invalid_mapping_does_not_overwrite_existing_file(self):
        save_contacts(self.path, self.book)
        original = self.path.read_bytes()
        self.book["industries"]["银行"] = "不存在的交易台"
        with self.assertRaisesRegex(ValueError, "不存在"):
            save_contacts(self.path, self.book)
        self.assertEqual(self.path.read_bytes(), original)

    def test_blank_mapping_and_empty_traders_are_allowed(self):
        self.book["industries"]["银行"] = ""
        self.book["desks"]["消费"] = []
        book = validate_contacts(self.book)
        self.assertEqual(contact_for("银行", book)["traders"], [])
        self.assertEqual(contact_for("食品饮料", book)["desk"], "")

    def test_invalid_types_and_normalized_duplicates_rejected(self):
        for key, value in (("group", []), ("schema_version", True), ("desks", []), ("industries", [])):
            book = dict(self.book, **{key: value})
            with self.assertRaises(ValueError):
                validate_contacts(book)
        self.book["industries"][" 电子 "] = "周期"
        with self.assertRaisesRegex(ValueError, "重复"):
            validate_contacts(self.book)


class ContactDesktopTests(DesktopCase):
    def test_missing_industry_shows_all_desks_and_clears_with_results(self):
        self.query("600519")
        self.assertTrue(self.window.fallback_contacts.isHidden())
        self.window.items[0]["industry"] = ""
        self.window.update_contacts()
        self.assertFalse(self.window.fallback_contacts.isHidden())
        text = self.window.fallback_contacts.toPlainText()
        self.assertIn(self.window.contacts["group"], text)
        for desk, names in self.window.contacts["desks"].items():
            self.assertIn(desk, text)
            for name in names:
                self.assertIn("@" + name, text)
        self.window.contacts["group"] = "更新后的群"
        self.window.update_contacts()
        self.assertIn("更新后的群", self.window.fallback_contacts.toPlainText())
        self.window.items[0]["industry"] = "有行业但未映射"
        self.window.update_contacts()
        self.assertTrue(self.window.fallback_contacts.isHidden())
        self.window.items[0]["industry"] = None
        self.window.update_contacts()
        self.window.clear_results()
        self.assertTrue(self.window.fallback_contacts.isHidden())

    def test_contact_column_is_next_to_industry_unknown_is_empty(self):
        self.query("600519 000001")
        header = self.window.table.horizontalHeader()
        self.assertEqual(header.visualIndex(9), header.visualIndex(1) + 1)
        self.assertIn("@", self.window.table.item(0, 9).text())
        self.assertEqual(self.window.table.item(1, 9).text(), "")
        self.assertIn("D1&股票交流群", self.window.contact_group.text())
        self.assertIn("暂读", self.window.contact_group.text())
        self.assertIn("询券交易台：消费", self.window.detail.toPlainText())

    def test_save_dialog_updates_current_results_export_and_preserves_pending_input(self):
        self.query("600519")
        self.edit("600519.SH", "500")
        self.window.auto_calculate.stop()
        before = deepcopy(self.window.items[0]["calculation"])

        def edit_dialog(dialog):
            dialog.group.setText("测试询券群")
            for row in range(dialog.desks.rowCount()):
                if dialog.desks.item(row, 0).text() == "消费":
                    dialog.desks.item(row, 1).setText("@测试甲，测试乙")
            dialog.note.setText("用户维护的测试联系表")
            dialog.save()
            self.assertFalse(dialog.error.text())
            return dialog.result()

        with patch("securities_lending.desktop.ContactsDialog.exec", new=edit_dialog), patch.object(self.service, "query") as query:
            QTest.mouseClick(self.window.contacts_button, Qt.MouseButton.LeftButton)
            query.assert_not_called()
        self.assertEqual(self.window.items[0]["calculation"], before)
        self.assertEqual(self.window.editors["600519.SH"].text(), "500")
        self.assertFalse(self.window.export_button.isEnabled())
        self.assertEqual(self.window.table.item(0, 9).text(), "@测试甲\n@测试乙")
        self.assertIn("测试询券群", self.window.detail.toPlainText())
        saved, error = load_contacts(self.window.contacts_path)
        self.assertFalse(error)
        self.assertEqual(saved["group"], "测试询券群")
        self.calculate()
        self.assertEqual(self.window.table.item(0, 9).text(), "@测试甲\n@测试乙")
        path = Path(self.tmp.name) / "contacts.csv"
        self.window.export_to(path)
        with path.open(encoding="utf-8-sig") as stream:
            row = next(csv.DictReader(stream))
        self.assertEqual(row["询券联系人（群内@）"], "测试甲、测试乙")
        self.assertEqual(row["询券微信群"], "测试询券群")
        self.assertEqual(row["联系表备注"], "用户维护的测试联系表")
        self.assertEqual(row["校验通过股数"], "3500")

    def test_dialog_cancel_or_save_failure_does_not_apply_changes(self):
        book = deepcopy(self.window.contacts)
        dialog = ContactsDialog(book, self.window.contacts_path, self.window)
        dialog.group.setText("未保存群名")
        with patch("securities_lending.trader_contacts.atomic_json", side_effect=OSError("写入受限")):
            dialog.save()
        self.assertIn("写入受限", dialog.error.text())
        self.assertNotEqual(dialog.result(), QDialog.DialogCode.Accepted)
        self.assertEqual(self.window.contacts, book)
        self.assertFalse(self.window.contacts_path.exists())
        dialog.reject()
        self.assertEqual(dialog.book, book)

    def test_dialog_rejects_unknown_desk_and_duplicate_industry(self):
        dialog = ContactsDialog(self.window.contacts, self.window.contacts_path, self.window)
        dialog.industries.item(0, 1).setText("未定义的交易台")
        dialog.save()
        self.assertIn("不存在", dialog.error.text())
        dialog.industries.item(1, 0).setText(dialog.industries.item(0, 0).text())
        dialog.save()
        self.assertIn("重复", dialog.error.text())
        self.assertFalse(self.window.contacts_path.exists())
        dialog.reject()


if __name__ == "__main__":
    unittest.main()
