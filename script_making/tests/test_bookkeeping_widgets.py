"""Real Qt actions over isolated manual records and synthetic report rows."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QItemSelectionModel, QSettings
from PySide6.QtWidgets import QApplication, QInputDialog, QMessageBox

from script_making.bookkeeping import BookkeepingStore
from script_making.bookkeeping_report import report_backlinks, report_target_candidates
from script_making.bookkeeping_widgets import BackToBackDialog, BookkeepingDialog, report_display, report_ref
from script_making.candidate_widgets import CandidateDialog, TargetPicker, quantity_difference
from script_making.desktop_theme import STYLE


HEADERS = ["合约编号", "交易确认书编号", "交易对手名称", "标的物代码", "标的物名称",
           "标的名义数量", "交易达成日", "起始日", "开仓操作人员", "我方资产方向",
           "关联背靠背合约", "关联背靠背确认书编号"]


def sample_table():
    rows = [
        ["A", "CONF-A", "示例客户", "000001.SZ", "示例甲", 100, "2026-10-01", "2026-10-02", "U1", "多头", "B", "CONF-B"],
        ["A", "CONF-A", "示例客户", "600000.SH", "示例乙", 50, "2026-10-01", "2026-10-02", "U1", "多头", 0, 0],
        ["B", "CONF-B", "境内期权交易台", "000001.SZ", "示例甲", 60, "2026-10-01", "2026-10-02", "U1", "空头", "", ""],
        ["C", "CONF-C", "策略部交易台", "000001.SZ", "示例甲", 50, "2026-10-01", "2026-10-03", "U2", "空头", "", ""],
        ["D", "CONF-D", "境内期权交易台", "600000.SH", "示例乙", 55, "2026-10-01", "2026-10-02", "U1", "空头", "", ""],
        ["E", "CONF-E", "其他客户", "000001.SZ", "示例甲", 100, "2026-10-01", "2026-10-02", "U1", "空头", "", ""],
        [None, None, "境内期权交易台", "600000.SH", "示例乙", 5, "2026-10-01", "2026-10-02", "U1", "空头", "", ""],
    ]
    return {"columns": [{"id": f"c{i}", "name": name, "type": "text"} for i, name in enumerate(HEADERS)],
            "rows": rows, "source_rows": list(range(2, len(rows) + 2))}


class BookkeepingWidgetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setStyle("Fusion")
        cls.app.setStyleSheet(STYLE)

    def setUp(self):
        cache = Path(__file__).resolve().parents[1] / "cache" / "bookkeeping-qt-tests"
        cache.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=cache)
        self.root = Path(self.temp.name)
        self.store = BookkeepingStore(self.root / "records.sqlite3")
        self.table = sample_table()
        self.row = {"excel_row": 2, "values": self.table["rows"][0]}
        self.source = {"date": "2026-10-27", "filename": "synthetic.xlsx", "sheet": "存续合约估值"}
        self.ref = report_ref(self.table["columns"], self.row, self.source)
        self.preferences = QSettings(str(self.root / "ui.ini"), QSettings.Format.IniFormat)

    def tearDown(self):
        self.app.processEvents()
        self.temp.cleanup()

    def test_existing_report_row_opens_close_form_and_saves_exact_values(self):
        dialog = BookkeepingDialog(self.store, self.ref, report_backlinks(self.table, self.row))
        self.assertEqual(dialog.action.currentData(), "close")
        self.assertEqual(dialog.fields["contract_no"].text(), "A")
        self.assertEqual(dialog.fields["underlying_code"].text(), "000001.SZ")
        self.assertEqual(dialog.fields["amount"].text(), "")
        self.assertEqual(dialog.fields["quantity"].text(), "")
        dialog.fields["quantity"].setText("1,234.500000000001")
        dialog.fields["amount"].setText("0.100000000000001")
        dialog.save()
        self.assertEqual(len(self.store.list_records()), 1, dialog.error.text())
        record = self.store.list_records()[0]
        self.assertEqual(record["quantity"], "1,234.500000000001")
        self.assertEqual(record["amount"], "0.100000000000001")
        self.assertEqual(record["source"]["excel_row"], 2)
        self.assertEqual(len(record["source"]["fields"]), len(HEADERS))
        dialog.note.setPlainText("更新备注")
        dialog.save()
        self.assertEqual(self.store.get_record(record["id"])["version"], 2)
        dialog.close()

    def test_unknown_none_manual_links_are_distinct_and_bidirectional(self):
        claims, summary = report_display(report_backlinks(self.table, self.row), self.source)
        dialog = BackToBackDialog(self.store, self.ref, claims, summary)
        self.assertIn("未确认", dialog.status.text())
        self.assertFalse(self.store.path.exists())
        self.assertGreaterEqual(dialog.table.rowCount(), 2)
        dialog.table.selectRow(0)
        dialog.link_report_row()
        self.assertEqual(self.store.get_back_to_back(self.ref)["status"], "linked", dialog.error.text())
        other = report_ref(self.table["columns"], {"excel_row": 4, "values": self.table["rows"][2]}, self.source)
        self.assertEqual(self.store.get_back_to_back(other)["status"], "linked")
        dialog.table.selectRow(0)
        dialog.unlink()
        self.assertEqual(self.store.get_back_to_back(self.ref)["status"], "unknown")
        dialog.set_status("none")
        self.assertEqual(self.store.get_back_to_back(self.ref)["status"], "none")
        dialog.close()

    def test_new_record_without_number_gets_local_id_and_can_be_completed(self):
        dialog = BookkeepingDialog(self.store)
        self.assertEqual(dialog.action.currentData(), "open")
        dialog.fields["underlying_code"].setText("000001.SZ")
        dialog.fields["quantity"].setText("10")
        dialog.save()
        first = self.store.list_records()[0]
        self.assertTrue(first["local_id"])
        dialog.fields["contract_no"].setText("NEW-A")
        dialog.save()
        updated = self.store.get_record(first["id"])
        self.assertEqual(updated["local_id"], first["local_id"])
        self.assertEqual(updated["contract_no"], "NEW-A")
        dialog.close()

    def test_discard_prompt_preserves_unsaved_form(self):
        dialog = BookkeepingDialog(self.store)
        dialog.fields["quantity"].setText("100")
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.No):
            dialog.new_record()
            self.assertEqual(dialog.fields["quantity"].text(), "100")
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
            dialog.new_record()
            self.assertEqual(dialog.fields["quantity"].text(), "")
        dialog.close()

    def test_close_based_on_existing_record_creates_a_separate_entry(self):
        original = self.store.save_record({"action": "open", "trade_date": "2026-10-27",
                    "contract_no": "A", "underlying_code": "000001.SZ", "quantity": "100"})
        dialog = BookkeepingDialog(self.store)
        dialog.records.selectRow(0)
        dialog.load_row(0, 0)
        self.assertFalse(dialog.action.isEnabled())
        dialog.close_from_record()
        self.assertEqual(dialog.action.currentData(), "close")
        self.assertEqual(dialog.fields["quantity"].text(), "")
        dialog.fields["quantity"].setText("40")
        dialog.save()
        records = self.store.list_records()
        self.assertEqual(len(records), 2, dialog.error.text())
        self.assertEqual(self.store.get_record(original["id"])["action"], "open")
        close = next(record for record in records if record["action"] == "close")
        self.assertEqual(close["quantity"], "40")
        self.assertEqual(close["source"]["based_on_record_id"], original["id"])
        dialog.close()

    def test_target_and_candidate_records_share_an_explicit_operation_group(self):
        group = {"id": "synthetic-group", "name": "示例一并平仓"}
        target = BookkeepingDialog(self.store, self.ref, group_context=group)
        target.fields["quantity"].setText("100")
        target.save()
        self.assertTrue(target.record_id, target.error.text())
        target.close()
        candidate_row = {"excel_row": 4, "values": self.table["rows"][2]}
        candidate = BookkeepingDialog(self.store, report_ref(self.table["columns"], candidate_row, self.source),
                                      group_context=group)
        candidate.fields["quantity"].setText("60")
        candidate.save()
        self.assertTrue(candidate.record_id, candidate.error.text())
        candidate.close()
        records = self.store.list_records("示例一并平仓")
        self.assertEqual(len(records), 2)
        self.assertEqual({record["group_id"] for record in records}, {"synthetic-group"})
        self.assertEqual({record["quantity"] for record in records}, {"100", "60"})
        review = BookkeepingDialog(self.store)
        self.assertIn("示例一并平仓", [review.group.itemText(i) for i in range(review.group.count())])
        review.close()

    def test_group_can_be_created_and_selected_without_changing_other_records(self):
        dialog = BookkeepingDialog(self.store)
        with patch.object(QInputDialog, "getText", return_value=("测试组", True)):
            dialog.create_group()
        self.assertEqual(dialog.group.currentText(), "测试组")
        with patch.object(QInputDialog, "getText", return_value=("测试组", True)):
            dialog.create_group()
        self.assertIn("同名", dialog.error.text())
        self.assertEqual(dialog.group.count(), 2)
        dialog.fields["quantity"].setText("10")
        dialog.save()
        self.assertEqual(self.store.list_records()[0]["group_name"], "测试组")
        dialog.close()

    def test_report_claims_preserve_all_matching_rows_and_unmatched_id(self):
        result = report_backlinks(self.table, self.row)
        claims, summary = report_display(result, self.source)
        self.assertEqual(len(claims), 2)
        self.assertIn("分别展示", summary)
        self.assertTrue(all(claim["ref"]["underlying_code"] == "000001.SZ" for claim in claims))
        self.assertEqual(claims[0]["ref"]["source"]["excel_row"], 4)
        empty = {"excel_row": 3, "values": self.table["rows"][1]}
        claims, summary = report_display(report_backlinks(self.table, empty), self.source)
        self.assertEqual(claims, [])
        self.assertIn("不代表", summary)

    def test_candidates_separate_target_and_all_internal_desks(self):
        dialog = CandidateDialog(self.store, self.table, self.row, self.source, self.preferences)
        self.assertEqual(dialog.target_table.rowCount(), 2)
        self.assertEqual(dialog.candidates.rowCount(), 2)
        self.assertIn("110", dialog.candidate_summary.text())
        second = dialog.candidates.model().index(1, 0)
        dialog.candidates.selectionModel().select(second, QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows)
        self.assertIn("已选 2 组合计 110", dialog.candidate_summary.text())
        self.assertIn("较目标多 10", dialog.candidate_summary.text())
        self.assertNotIn("其他客户", [dialog.candidates.item(i, 0).text() for i in range(dialog.candidates.rowCount())])
        self.assertFalse(self.store.path.exists())
        dialog.confirm_link()
        self.assertEqual(self.store.get_back_to_back(self.ref)["status"], "linked", dialog.error.text())
        self.assertIn("已关联 1 笔", dialog.manual_status.text())
        self.assertEqual(dialog.candidates.item(0, 2).text(), "已确认")
        self.assertEqual(dialog.candidates.item(1, 2).text(), "未确认")
        dialog.select_underlying(1, 0)
        self.assertEqual(dialog.candidates.rowCount(), 1)
        self.assertIn("缺合约编号", dialog.candidate_summary.text())
        dialog.desks = ["境内期权交易台"]
        dialog.refresh()
        self.assertEqual(dialog.candidates.rowCount(), 1)
        dialog.close()

    def test_candidate_window_uses_the_same_group_for_target_and_candidate_booking(self):
        dialog = CandidateDialog(self.store, self.table, self.row, self.source, self.preferences)
        with patch("script_making.candidate_widgets.BookkeepingDialog") as booking:
            dialog.book_target()
            dialog.book_candidate()
            first, second = booking.call_args_list
            self.assertEqual(first.args[5], second.args[5])
            self.assertTrue(first.args[5]["id"])
            self.assertEqual(first.args[1]["contract_no"], "A")
            self.assertEqual(second.args[1]["contract_no"], "B")
        dialog.close()

    def test_exact_quantity_difference_and_incomplete_values(self):
        target = {"complete": True, "value": "123456789012345678901234567890.123456789"}
        selected = {"complete": True, "value": "123456789012345678901234567890.123456790"}
        self.assertEqual(quantity_difference(target, selected), "较目标多 0.000000001")
        self.assertEqual(quantity_difference(target, {"complete": False, "value": None}), "数量不完整，无法比较")

    def test_cross_report_target_requires_user_selection(self):
        source = {"columns": [{"id": "c0", "name": "协议编号"}, {"id": "c1", "name": "标的"}],
                  "rows": [["CONF-A", "000001.SZ"]], "source_rows": [2]}
        proposals = report_target_candidates(source, {"excel_row": 2, "values": source["rows"][0]}, self.table)
        dialog = TargetPicker(proposals, self.table["columns"])
        dialog.confirm()
        self.assertIsNone(dialog.selected_row)
        self.assertIn("选中", dialog.error.text())
        dialog.table.selectRow(0)
        dialog.confirm()
        self.assertEqual(dialog.selected_row["values"][0], "A")

    def test_missing_columns_and_empty_desks_give_actionable_message(self):
        bad = sample_table()
        bad["columns"][3]["name"] = "缺失标的字段"
        dialog = CandidateDialog(self.store, bad, self.row, self.source, self.preferences)
        self.assertIn("标的", dialog.error.text())
        dialog.close()
        self.preferences.setValue("bookkeeping/internal_desks", "[]")
        dialog = CandidateDialog(self.store, self.table, self.row, self.source, self.preferences)
        self.assertIn("先选择", dialog.error.text())
        self.assertEqual(dialog.target_table.rowCount(), 2)
        self.assertIn("尚未查找", dialog.candidate_summary.text())
        dialog.close()

    def test_duplicate_contract_and_underlying_cannot_create_or_claim_a_link(self):
        duplicate = sample_table()
        duplicate["rows"].append(list(duplicate["rows"][0]))
        duplicate["source_rows"].append(9)
        dialog = CandidateDialog(self.store, duplicate, self.row, self.source, self.preferences)
        dialog.confirm_link()
        self.assertIn("多条日报明细", dialog.error.text())
        self.assertFalse(self.store.path.exists())
        ref = dialog._row_ref(self.row)
        back = BackToBackDialog(self.store, ref)
        self.assertIn("多条日报明细", back.status.text())
        back.set_status("none")
        self.assertIn("多条日报明细", back.error.text())
        self.assertFalse(self.store.path.exists())
        back.close()
        dialog.close()

    def test_empty_zero_or_error_in_report_is_not_a_contract_identity(self):
        rows = {"excel_row": 2, "values": [0, "#N/A", "示例", "000001.SZ", "", 1, "", "", "", "", "", ""]}
        ref = report_ref(self.table["columns"], rows, self.source)
        self.assertEqual(ref["contract_no"], "")
        self.assertEqual(ref["confirmation_no"], "")
        self.assertEqual(ref["underlying_code"], "000001.SZ")


if __name__ == "__main__":
    unittest.main()
