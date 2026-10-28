"""Side-by-side target and possible back-to-back positions from a saved report."""
from __future__ import annotations

import json
import uuid
from collections import Counter
from decimal import Decimal, InvalidOperation, localcontext

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QDialog, QDialogButtonBox,
                              QHBoxLayout, QHeaderView, QLineEdit, QListWidget, QListWidgetItem,
                              QSplitter, QTableWidget, QVBoxLayout, QWidget)

from .bookkeeping_report import (report_backlinks, report_back_to_back_candidates,
                                 sum_candidate_quantities)
from .bookkeeping import _identity
from .bookkeeping_widgets import (BackToBackDialog, BookkeepingDialog, make_item,
                                  report_display, report_ref, require_unique_position)
from .desktop_widgets import button, label
from .storage import timestamp

COMMON_DESKS = ("境内期权交易台", "策略部交易台", "维稳交易台")


def column_value(columns, row, names):
    for name in names:
        indexes = [i for i, column in enumerate(columns) if column["name"] == name]
        if len(indexes) == 1:
            value = row["values"][indexes[0]]
            return "" if value is None else str(value)
        if len(indexes) > 1:
            return ""
    return ""


def quantity_text(quantity):
    if not quantity.get("complete"):
        return f"不完整（缺 {quantity.get('missing_count', 0)}）"
    return str(quantity.get("value") if quantity.get("value") is not None else "—")


def comparison(value):
    return {"same": "相同", "different": "不同", "missing": "缺失"}.get(value, "—")


def quantity_difference(target, selected):
    if not target.get("complete") or not selected.get("complete"):
        return "数量不完整，无法比较"
    try:
        left, right = Decimal(str(target["value"])), Decimal(str(selected["value"]))
        integers = max(1, left.adjusted() + 1, right.adjusted() + 1)
        decimals = max(0, -left.as_tuple().exponent, -right.as_tuple().exponent)
        with localcontext() as context:
            context.prec = max(28, integers + decimals + 3)
            delta = right - left
        if not delta:
            return "与目标相等"
        return "较目标" + ("多 " if delta > 0 else "少 ") + format(delta.copy_abs(), "f")
    except (InvalidOperation, ValueError, TypeError):
        return "数量不完整，无法比较"


class DeskPicker(QDialog):
    def __init__(self, names, selected, parent=None):
        super().__init__(parent)
        self.setWindowTitle("选择内部交易台")
        self.resize(580, 620)
        layout = QVBoxLayout(self)
        layout.addWidget(label("选择内部交易台", "dialogTitle"))
        layout.addWidget(label("仅勾选的交易对手参与候选搜索。常用交易台及名称含“交易台”或以“台”结尾的项目仅作初始预选，请自行核对。", "muted", True))
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索交易对手")
        self.search.setClearButtonEnabled(True)
        layout.addWidget(self.search)
        self.list = QListWidget()
        for name in sorted(set(names) | set(selected),
                           key=lambda value: (COMMON_DESKS.index(value) if value in COMMON_DESKS else len(COMMON_DESKS), value.casefold())):
            item = QListWidgetItem(name)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if name in selected else Qt.CheckState.Unchecked)
            self.list.addItem(item)
        self.search.textChanged.connect(self._filter)
        layout.addWidget(self.list, 1)
        actions = QDialogButtonBox()
        actions.addButton("取消", QDialogButtonBox.ButtonRole.RejectRole)
        actions.addButton("应用名单", QDialogButtonBox.ButtonRole.AcceptRole)
        actions.accepted.connect(self.accept)
        actions.rejected.connect(self.reject)
        layout.addWidget(actions)

    def _filter(self, value):
        for i in range(self.list.count()):
            item = self.list.item(i)
            item.setHidden(value.casefold().strip() not in item.text().casefold())

    def selected(self):
        return [self.list.item(i).text() for i in range(self.list.count())
                if self.list.item(i).checkState() == Qt.CheckState.Checked]


class TargetPicker(QDialog):
    """Require the user to confirm a target proposed from a different sheet."""

    def __init__(self, proposals, columns, parent=None):
        super().__init__(parent)
        self.proposals = proposals
        self.selected_row = None
        self.setWindowTitle("确认目标合约")
        self.resize(1050, 580)
        layout = QVBoxLayout(self)
        layout.addWidget(label("确认目标合约", "dialogTitle"))
        layout.addWidget(label(f"根据当前表「{proposals['source_field']}」与存续表「{proposals['target_field']}」相等查找；请选择并确认目标后，再查找背对。", "muted", True))
        if proposals.get("underlying_hint") and not proposals.get("underlying_matched"):
            layout.addWidget(label("当前行的标的未在候选中精确对应，请核对标的后选择。", "notice", True))
        self.table = CandidateDialog._table(["合约编号", "确认书编号", "交易对手", "标的代码", "标的名称", "Excel 行"])
        for row in proposals["rows"]:
            values = [column_value(columns, row, ("合约编号",)),
                      column_value(columns, row, ("交易确认书编号",)),
                      column_value(columns, row, ("交易对手名称",)),
                      column_value(columns, row, ("标的物代码",)),
                      column_value(columns, row, ("标的物名称",)), row["excel_row"]]
            CandidateDialog._append(self.table, values, row)
        self.table.cellDoubleClicked.connect(lambda *_: self.confirm())
        layout.addWidget(self.table, 1)
        self.error = label("", "error", True)
        self.error.hide()
        layout.addWidget(self.error)
        actions = QDialogButtonBox()
        actions.addButton("取消", QDialogButtonBox.ButtonRole.RejectRole)
        actions.addButton("确定目标", QDialogButtonBox.ButtonRole.AcceptRole)
        actions.accepted.connect(self.confirm)
        actions.rejected.connect(self.reject)
        layout.addWidget(actions)

    def confirm(self):
        self.selected_row = CandidateDialog._selected_row(self.table)
        if self.selected_row is None:
            self.error.setText("请先选中一条目标明细。")
            self.error.show()
            return
        self.accept()


class CandidateDialog(QDialog):
    def __init__(self, store, table, selected_row, source, preferences, parent=None):
        super().__init__(parent)
        self.store, self.table_data, self.selected_row = store, table, selected_row
        self.source, self.preferences = source, preferences
        self.identity_counts = self._identity_counts()
        self.selected_ref = report_ref(table["columns"], selected_row, source)
        self.contract_id = self.selected_ref.get("contract_no", "")
        group_id = uuid.uuid4().hex
        self.group_context = {"id": group_id, "name": "开平组 " + timestamp().replace("T", " ")[:16] + " · " + group_id[:6]}
        self.current_data, self.selected_group = None, None
        self.setWindowTitle("查找背对候选")
        self.resize(1450, 820)
        self.setMinimumSize(1050, 700)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(10)
        heading = QHBoxLayout()
        title = QVBoxLayout()
        title.addWidget(label("查找背对候选", "dialogTitle"))
        title.addWidget(label("先选定目标合约，再按相同标的和所选交易台查找。候选需由你核对确认。", "muted", True))
        heading.addLayout(title, 1)
        self.desk_button = button("选择交易台", self.choose_desks)
        heading.addWidget(self.desk_button)
        layout.addLayout(heading)
        self.desk_note = label("", "notice", True)
        layout.addWidget(self.desk_note)
        panels = QSplitter(Qt.Orientation.Horizontal)
        target = QWidget()
        target_layout = QVBoxLayout(target)
        target_layout.setContentsMargins(0, 0, 8, 0)
        target_layout.addWidget(label("目标合约", "sectionTitle"))
        self.target_title = label(self.contract_id or "当前行没有合约编号", "muted", True)
        self.target_title.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        target_layout.addWidget(self.target_title)
        self.manual_status = label("人工背对：未确认", "muted", True)
        target_layout.addWidget(self.manual_status)
        target_layout.addWidget(label("目标合约的标的", "muted"))
        self.target_table = self._table(["标的代码", "标的名称", "目标数量", "明细行数"])
        self.target_table.cellClicked.connect(self.select_underlying)
        target_layout.addWidget(self.target_table, 2)
        target_layout.addWidget(label("目标标的明细 · 可选择具体行", "muted"))
        self.target_rows = self._table(["Excel 行", "数量", "交易达成日", "起始日", "开仓人员", "方向"])
        self.target_rows.cellClicked.connect(self._target_row_changed)
        target_layout.addWidget(self.target_rows, 2)
        target_actions = QHBoxLayout()
        target_actions.addWidget(button("登记目标平仓", self.book_target))
        target_actions.addWidget(button("查看已关联 / 日报声明", self.show_target_links))
        target_layout.addLayout(target_actions)
        panels.addWidget(target)
        candidate = QWidget()
        candidate_layout = QVBoxLayout(candidate)
        candidate_layout.setContentsMargins(8, 0, 0, 0)
        candidate_layout.addWidget(label("背对候选合约", "sectionTitle"))
        self.candidate_summary = label("", "muted", True)
        candidate_layout.addWidget(self.candidate_summary)
        candidate_layout.addWidget(label("候选合约 · 可用 Ctrl / Shift 多选并比较合计", "muted", True))
        self.candidates = self._table(["交易台", "合约编号", "人工关联", "候选数量", "数量比较", "达成日", "起始日", "人员", "方向", "行数"])
        self.candidates.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.candidates.cellClicked.connect(self.select_candidate)
        self.candidates.itemSelectionChanged.connect(self.update_candidate_summary)
        candidate_layout.addWidget(self.candidates, 2)
        candidate_layout.addWidget(label("候选明细 · 可选择具体行", "muted"))
        self.candidate_rows = self._table(["Excel 行", "数量", "交易达成日", "起始日", "开仓人员", "方向"])
        candidate_layout.addWidget(self.candidate_rows, 2)
        candidate_actions = QHBoxLayout()
        candidate_actions.addWidget(button("登记候选平仓", self.book_candidate))
        candidate_actions.addWidget(button("确认关联当前两行", self.confirm_link, "primary"))
        candidate_layout.addLayout(candidate_actions)
        panels.addWidget(candidate)
        panels.setStretchFactor(0, 1)
        panels.setStretchFactor(1, 2)
        panels.setSizes([470, 900])
        layout.addWidget(panels, 1)
        self.error = label("", "error", True)
        self.error.hide()
        layout.addWidget(self.error)
        bottom = QHBoxLayout()
        bottom.addWidget(label("候选不代表已确认背对。数量合计仅覆盖当前所选交易台的候选，可能多于或少于目标。", "muted", True), 1)
        bottom.addWidget(button("关闭", self.accept))
        layout.addLayout(bottom)
        self.counterpart_names = self._counterpart_names()
        self.desks, self._automatic_desks = self._load_desks()
        self.refresh()

    @staticmethod
    def _table(headers):
        table = QTableWidget(0, len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setAlternatingRowColors(True)
        table.verticalHeader().hide()
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        table.horizontalHeader().setStretchLastSection(True)
        return table

    def _counterpart_names(self):
        columns = self.table_data["columns"]
        names = []
        for name in ("交易对手名称", "交易对手"):
            indexes = [i for i, column in enumerate(columns) if column["name"] == name]
            if len(indexes) == 1:
                names = sorted({str(row[indexes[0]]).strip() for row in self.table_data["rows"]
                                if row[indexes[0]] is not None and str(row[indexes[0]]).strip()})
                break
            if len(indexes) > 1:
                break
        return names

    def _identity_counts(self):
        columns = self.table_data["columns"]
        contract = [i for i, item in enumerate(columns) if item["name"] == "合约编号"]
        underlying = [i for i, item in enumerate(columns) if item["name"] == "标的物代码"]
        if len(contract) != 1 or len(underlying) != 1:
            return Counter()
        return Counter((_identity(row[contract[0]]), _identity(row[underlying[0]]))
                       for row in self.table_data["rows"]
                       if _identity(row[contract[0]]) and _identity(row[underlying[0]]))

    def _row_ref(self, row):
        ref = report_ref(self.table_data["columns"], row, self.source)
        key = (_identity(ref.get("contract_no")), _identity(ref.get("underlying_code")))
        if all(key):
            ref["source"]["identity_matches"] = self.identity_counts.get(key, 0)
        return ref

    def _load_desks(self):
        value = self.preferences.value("bookkeeping/internal_desks")
        if value is not None:
            try:
                selected = json.loads(value)
                if isinstance(selected, list) and all(isinstance(x, str) for x in selected):
                    return selected, False
            except (TypeError, ValueError):
                pass
        return [name for name in self.counterpart_names if name in COMMON_DESKS or "交易台" in name or name.endswith("台")], True

    def choose_desks(self):
        dialog = DeskPicker(self.counterpart_names, self.desks, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.desks = dialog.selected()
            self._automatic_desks = False
            self.preferences.setValue("bookkeeping/internal_desks", json.dumps(self.desks, ensure_ascii=False))
            self.preferences.sync()
            self.refresh()

    def refresh(self):
        origin = "按名称预选，请核对" if self._automatic_desks else "你已选择"
        self.desk_note.setText(f"内部交易台：{len(self.desks)} 个（{origin}）。可点「选择交易台」修改，候选只在名单内查找。")
        self.error.hide()
        self.target_table.setRowCount(0)
        self.target_rows.setRowCount(0)
        self.candidates.setRowCount(0)
        self.candidate_rows.setRowCount(0)
        self.selected_group = None
        try:
            self.current_data = report_back_to_back_candidates(self.table_data, self.contract_id, self.desks)
        except Exception as exc:
            self._failure(exc)
            return
        data = self.current_data
        if data["state"] != "ok":
            reasons = {"invalid_contract": "当前行没有有效合约编号，请选择有合约编号的目标。",
                       "target_not_found": "当前报表中未找到目标合约。",
                       "missing_columns": "当前报表缺少查找所需列或存在同名列。",
                       "missing_desks": "请先选择至少一个内部交易台。"}
            details = "；".join(f"{item['field']}（{'缺失' if item['reason'] == 'missing' else '同名列不唯一'}）"
                               for item in data.get("issues", []))
            self._failure(ValueError(reasons.get(data["state"], "当前报表无法查找候选。") + (" " + details if details else "")))
            if not data.get("underlyings"):
                return
        for index, item in enumerate(data["underlyings"]):
            first = item["target_rows"][0]
            name = column_value(data["columns"], first, ("标的物名称", "标的名称"))
            self._append(self.target_table, [item["code"], name, quantity_text(item["target_quantity"]), len(item["target_rows"])], index)
        wanted = self.selected_ref.get("underlying_code")
        selected = next((i for i, item in enumerate(data["underlyings"]) if item["code"] == wanted), 0)
        if self.target_table.rowCount():
            self.target_table.selectRow(selected)
            self.select_underlying(selected, 0)
        else:
            self.candidate_summary.setText("目标合约没有可识别的标的代码。")

    @staticmethod
    def _append(table, values, data):
        index = table.rowCount()
        table.insertRow(index)
        for column, value in enumerate(values):
            table.setItem(index, column, make_item(value, data if column == 0 else None))

    def _details(self, widget, rows):
        widget.setRowCount(0)
        columns = self.table_data["columns"]
        for row in rows:
            values = [row["excel_row"],
                      column_value(columns, row, ("标的名义数量",)),
                      column_value(columns, row, ("交易达成日",)),
                      column_value(columns, row, ("起始日",)),
                      column_value(columns, row, ("开仓操作人员",)),
                      column_value(columns, row, ("我方资产方向",))]
            self._append(widget, values, row)
        if rows:
            widget.selectRow(0)

    def select_underlying(self, row, _column):
        if not self.current_data or row < 0:
            return
        data = self.current_data["underlyings"][row]
        self.selected_group = data
        self._details(self.target_rows, data["target_rows"])
        wanted = self.selected_row.get("excel_row")
        for i, record in enumerate(data["target_rows"]):
            if record["excel_row"] == wanted:
                self.target_rows.selectRow(i)
                break
        self.candidates.blockSignals(True)
        self.candidates.setRowCount(0)
        self.candidate_rows.setRowCount(0)
        for group in data["candidates"]:
            quantity = group["quantity"]
            compare = group["comparisons"]
            self._append(self.candidates, [group["counterparty"], group["contract_id"], "未确认", quantity_text(quantity),
                                         comparison(compare.get("quantity")), comparison(compare.get("trade_date")),
                                         comparison(compare.get("start_date")), comparison(compare.get("operator")),
                                         comparison(compare.get("direction")), len(group["rows"])], group)
        self.candidates.blockSignals(False)
        if self.candidates.rowCount():
            self.candidates.selectRow(0)
            self.select_candidate(0, 0)
        self.update_candidate_summary()
        self._target_row_changed()

    def update_candidate_summary(self):
        data = self.selected_group
        if not data:
            return
        if self.current_data["state"] != "ok":
            self.candidate_summary.setText(f"目标 {data['code']}：数量 {quantity_text(data['target_quantity'])}；候选尚未查找，请检查上方提示。")
            return
        groups = data["candidates"]
        overall = quantity_text(sum_candidate_quantities(groups)) if groups else "无候选"
        summary = f"目标 {data['code']}：数量 {quantity_text(data['target_quantity'])}；全部候选 {len(groups)} 组合计 {overall}。"
        selected = [self.candidates.item(index.row(), 0).data(Qt.ItemDataRole.UserRole)
                    for index in self.candidates.selectionModel().selectedRows()]
        if selected:
            subtotal = sum_candidate_quantities(selected)
            summary += f" 已选 {len(selected)} 组合计 {quantity_text(subtotal)}（{quantity_difference(data['target_quantity'], subtotal)}）。"
        if data.get("unusable_candidate_rows"):
            summary += f" 另有 {len(data['unusable_candidate_rows'])} 条同标的候选缺合约编号，需查看源表。"
        if not groups:
            summary += " 当前未找到候选。"
        self.candidate_summary.setText(summary)

    def _target_row_changed(self, *_):
        row = self._selected_row(self.target_rows)
        if row:
            self.selected_ref = self._row_ref(row)
            self._show_manual_status()

    def _show_manual_status(self):
        try:
            require_unique_position(self.selected_ref)
            result = self.store.get_back_to_back(self.selected_ref)
            if result.get("requires_underlying"):
                self.manual_status.setText("人工背对：需填写标的代码才能确认")
            elif result["status"] == "linked":
                self.manual_status.setText(f"人工背对：已关联 {len(result['counterparts'])} 笔")
            else:
                self.manual_status.setText("人工背对：" + ("明确无需背对" if result["status"] == "none" else "未确认"))
            counterparts = result.get("counterparts", [])
            for row in range(self.candidates.rowCount()):
                group = self.candidates.item(row, 0).data(Qt.ItemDataRole.UserRole)
                confirmations = {_identity(column_value(self.table_data["columns"], item, ("交易确认书编号",)))
                                 for item in group["rows"]}
                def matches(entry):
                    ref = entry["ref"]
                    contract = _identity(ref.get("contract_no"))
                    confirmation = _identity(ref.get("confirmation_no"))
                    return (_identity(ref.get("underlying_code")) == _identity(self.selected_group["code"])
                            and (contract == _identity(group["contract_id"]) if contract
                                 else bool(confirmation and confirmation in confirmations)))
                confirmed = any(matches(entry) for entry in counterparts)
                self.candidates.item(row, 2).setText("已确认" if confirmed else "未确认")
        except Exception as exc:
            self.manual_status.setText("人工背对：无法确认（" + str(exc) + "）")

    @staticmethod
    def _selected_row(widget):
        row = widget.currentRow()
        return widget.item(row, 0).data(Qt.ItemDataRole.UserRole) if row >= 0 else None

    def select_candidate(self, row, _column):
        if row < 0:
            return
        item = self.candidates.item(row, 0)
        if item:
            self._details(self.candidate_rows, item.data(Qt.ItemDataRole.UserRole)["rows"])

    def _failure(self, exc):
        self.error.setText(str(exc) or "查找未完成，请检查报表字段。")
        self.error.show()

    def _record_dialog(self, row):
        ref = self._row_ref(row)
        back = report_backlinks(self.table_data, row)
        BookkeepingDialog(self.store, ref, back, self, self.identity_counts, self.group_context).exec()
        self._show_manual_status()

    def book_target(self):
        row = self._selected_row(self.target_rows)
        if row:
            self._record_dialog(row)

    def book_candidate(self):
        row = self._selected_row(self.candidate_rows)
        if row:
            self._record_dialog(row)

    def show_target_links(self):
        row = self._selected_row(self.target_rows)
        if not row:
            return
        ref = self._row_ref(row)
        claims, summary = report_display(report_backlinks(self.table_data, row), self.source, self.identity_counts)
        BackToBackDialog(self.store, ref, claims, summary, self).exec()
        self._show_manual_status()

    def confirm_link(self):
        target_row = self._selected_row(self.target_rows)
        candidate_row = self._selected_row(self.candidate_rows)
        if not target_row or not candidate_row:
            self._failure(ValueError("请分别选中目标明细和候选明细。"))
            return
        # A repeated contract+underlying pair cannot be safely persisted as a unique position.
        try:
            left = self._row_ref(target_row)
            right = self._row_ref(candidate_row)
            require_unique_position(left)
            require_unique_position(right)
            self.store.link_contracts(left, right)
            self.error.hide()
            self._target_row_changed()
            self.candidate_summary.setText(self.candidate_summary.text() + " 已确认关联选中两行。")
        except Exception as exc:
            self._failure(exc)
