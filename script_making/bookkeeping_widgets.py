"""Local manual booking and explicitly confirmed back-to-back links."""
from __future__ import annotations

import copy
import uuid
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QComboBox, QDialog,
                              QFormLayout, QGridLayout, QHBoxLayout, QHeaderView,
                              QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QPushButton, QInputDialog,
                              QSplitter, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from .desktop_widgets import button, label
from .bookkeeping import _identity
from .bookkeeping_report import _identifier
from .storage import timestamp, today

FIELDS = (
    ("contract_no", "合约编号"), ("confirmation_no", "交易确认书编号"),
    ("counterparty", "交易对手"), ("underlying_code", "标的代码"),
    ("underlying_name", "标的名称"), ("direction", "方向"),
    ("quantity", "本次数量"), ("amount", "本次金额"),
    ("price", "本次价格"), ("unit", "数量 / 金额单位"),
)
STATUS = {"unknown": "未确认", "none": "明确无需背对", "linked": "已关联"}


def contract_ref(record):
    result = {key: record.get(key, "") for key in
            ("contract_no", "confirmation_no", "local_id", "counterparty", "underlying_code",
             "underlying_name", "direction", "unit", "note", "source")}
    result["source"] = result["source"] or {}
    return result


def report_ref(columns, row, source=None):
    """Preserve the selected Excel row and avoid guessing duplicate headers."""
    values = row["values"]
    result = {}
    for key, aliases in (("contract_no", ("合约编号",)),
                         ("confirmation_no", ("交易确认书编号",)),
                         ("counterparty", ("交易对手名称", "交易对手")),
                         ("underlying_code", ("标的物代码", "标的代码", "标的")),
                         ("underlying_name", ("标的物名称", "标的名称")),
                         ("direction", ("我方资产方向",))):
        for name in aliases:
            indexes = [i for i, column in enumerate(columns) if column["name"] == name]
            if len(indexes) == 1:
                value = values[indexes[0]]
                result[key] = ((_identifier(value)[0] or "") if key in ("contract_no", "confirmation_no", "underlying_code")
                               else "" if value is None else str(value).strip())
                break
            if len(indexes) > 1:
                break
    result["source"] = {**(source or {}), "excel_row": row["excel_row"],
                        "fields": [{"column_id": column["id"], "name": column["name"], "value": values[i]}
                                   for i, column in enumerate(columns)]}
    return result


def report_display(backlinks, source=None, identity_counts=None):
    """Turn exact report references into visible source claims, not manual links."""
    if not backlinks:
        return [], "当前记录没有可核验的日报背对字段。"
    columns = backlinks.get("columns", [])
    claims, notices = [], []
    for item in backlinks.get("fields", []):
        state, value = item.get("state"), item.get("target_id")
        if value:
            target_key = "contract_no" if item["target_field"] == "合约编号" else "confirmation_no"
            matches = item.get("matches", [])
            descriptions = {"matched": f"当前报表精确匹配 {len(matches)} 行",
                            "not_found": "当前报表未找到该编号",
                            "target_missing": "当前工作表没有目标编号列",
                            "target_ambiguous": "目标编号列有重名，未自动匹配"}
            description = item["source_field"] + "：" + descriptions.get(state, "未能核验")
            if item.get("self_reference"):
                description += "；指向本合约，请核对"
            if matches:
                for match in matches:
                    target = report_ref(columns, match, source)
                    target[target_key] = value
                    key = (_identity(target.get("contract_no")), _identity(target.get("underlying_code")))
                    if identity_counts is not None and all(key):
                        target["source"]["identity_matches"] = identity_counts.get(key, 0)
                    claims.append({"ref": target, "description": description + f" · Excel 第 {match['excel_row']} 行"})
            else:
                claims.append({"ref": {target_key: value}, "description": description})
        elif state == "source_ambiguous":
            notices.append(item["source_field"] + "存在同名列，未自动判断")
    if claims:
        summary = "日报字段中的关联编号与人工关联分别展示。"
    else:
        summary = "日报未提供可识别的背对编号；不代表已确认没有背对。"
    if notices:
        summary += " " + "；".join(notices) + "。"
    return claims, summary


def require_unique_position(ref):
    count = (ref.get("source") or {}).get("identity_matches")
    if isinstance(count, int) and count > 1:
        raise ValueError("同一合约编号和标的代码对应多条日报明细，无法唯一识别；请先核对后再设置背对。")


def ref_label(ref):
    identity = ref.get("contract_no") or ref.get("confirmation_no") or ("本地记录 " + str(ref.get("local_id", ""))[:8])
    context = " / ".join(str(ref.get(key) or "") for key in ("counterparty", "underlying_code", "underlying_name"))
    context = " / ".join(part for part in context.split(" / ") if part)
    return identity + (" · " + context if context else "")


def make_item(value, data=None):
    item = QTableWidgetItem("" if value is None else str(value))
    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
    if data is not None:
        item.setData(Qt.ItemDataRole.UserRole, data)
    return item


class BackToBackDialog(QDialog):
    """Display source assertions separately from explicit, local manual links."""

    def __init__(self, store, ref, source_matches=None, source_summary="", parent=None):
        super().__init__(parent)
        self.store, self.ref = store, dict(ref)
        self.source_matches = source_matches or []
        self.setWindowTitle("背对合约")
        self.resize(900, 660)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(10)
        layout.addWidget(label("背对合约", "dialogTitle"))
        layout.addWidget(label(ref_label(ref), "muted", True))
        self.status = label("", "notice", True)
        layout.addWidget(self.status)
        layout.addWidget(label(source_summary or "日报字段未核验；人工状态由你确认。", "muted", True))
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["来源", "对方合约 / 确认书", "对方 / 标的", "说明"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().hide()
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table, 1)
        actions = QHBoxLayout()
        actions.addWidget(button("标记未确认", lambda: self.set_status("unknown")))
        actions.addWidget(button("确认无需背对", lambda: self.set_status("none")))
        self.unlink_button = button("解除选中关联", self.unlink)
        actions.addWidget(self.unlink_button)
        actions.addWidget(button("复制选中编号", self.copy_number))
        actions.addWidget(button("关联选中日报行", self.link_report_row))
        actions.addStretch()
        layout.addLayout(actions)
        layout.addWidget(label("手工关联另一笔", "sectionTitle"))
        self.target_choice = QComboBox()
        self.target_choice.addItem("填写对方合约编号或确认书编号", None)
        try:
            for record in self.store.list_records():
                target = contract_ref(record)
                self.target_choice.addItem(ref_label(target), target)
        except Exception as exc:
            self.target_choice.setToolTip(str(exc))
        layout.addWidget(self.target_choice)
        fields = QGridLayout()
        fields.setHorizontalSpacing(10)
        fields.setVerticalSpacing(8)
        self.target_contract = QLineEdit()
        self.target_confirmation = QLineEdit()
        self.target_party = QLineEdit()
        self.target_underlying = QLineEdit()
        self.link_note = QLineEdit()
        for index, (caption, control) in enumerate((("对方合约编号", self.target_contract),
                                                    ("对方确认书编号", self.target_confirmation),
                                                    ("对方交易对手（选填）", self.target_party),
                                                    ("对方标的代码", self.target_underlying),
                                                    ("关联备注（选填）", self.link_note))):
            fields.addWidget(label(caption), index // 2 * 2, index % 2)
            fields.addWidget(control, index // 2 * 2 + 1, index % 2)
        layout.addLayout(fields)
        self.target_choice.currentIndexChanged.connect(self._target_mode)
        self._target_mode()
        self.error = label("", "error", True)
        self.error.hide()
        layout.addWidget(self.error)
        footer = QHBoxLayout()
        footer.addWidget(label("日报声明与手工关联分开显示；未确认不等于没有背对。", "muted", True), 1)
        footer.addWidget(button("关联背对", self.link, "primary"))
        footer.addWidget(button("关闭", self.accept))
        layout.addLayout(footer)
        self.refresh()

    def _target_mode(self, *_):
        manual = self.target_choice.currentData() is None
        for control in (self.target_contract, self.target_confirmation, self.target_party, self.target_underlying):
            control.setEnabled(manual)

    def _failure(self, exc):
        self.error.setText(str(exc) or "操作未完成，请检查本地记录。")
        self.error.show()

    def refresh(self):
        try:
            try:
                require_unique_position(self.ref)
            except ValueError as exc:
                info = {"status": "unknown", "counterparts": []}
                status = str(exc)
            else:
                info = self.store.get_back_to_back(self.ref)
                status = "人工确认：" + STATUS.get(info["status"], info["status"])
            if info.get("requires_underlying"):
                status += f" · 需填写标的代码才能确认，共有 {len(info.get('candidates', []))} 个候选。"
            self.status.setText(status)
            self.table.setRowCount(0)
            for entry in info["counterparts"]:
                target = entry["ref"]
                self._append("人工关联", target, entry.get("note", ""), ("manual", target))
            for entry in self.source_matches:
                target = entry.get("ref", {})
                self._append("日报字段", target, entry.get("description", ""), ("report", target))
            for candidate in info.get("candidates", []):
                self._append("身份候选", candidate, "请先核对标的代码；不是背对关系", ("candidate", candidate))
            self.unlink_button.setEnabled(bool(info["counterparts"]))
            self.error.hide()
        except Exception as exc:
            self._failure(exc)

    def _append(self, source, target, note, data):
        row = self.table.rowCount()
        self.table.insertRow(row)
        identity = target.get("contract_no") or target.get("confirmation_no") or target.get("local_id") or "—"
        context = " / ".join(str(target.get(k) or "") for k in ("counterparty", "underlying_code", "underlying_name"))
        context = " / ".join(x for x in context.split(" / ") if x)
        for index, value in enumerate((source, identity, context or "—", note)):
            self.table.setItem(row, index, make_item(value, data if index == 0 else None))

    def set_status(self, state):
        try:
            require_unique_position(self.ref)
            self.store.set_back_status(self.ref, state)
            self.refresh()
        except Exception as exc:
            self._failure(exc)

    def link(self):
        target = self.target_choice.currentData()
        if target is None:
            target = {"contract_no": self.target_contract.text().strip(),
                      "confirmation_no": self.target_confirmation.text().strip(),
                      "counterparty": self.target_party.text().strip(),
                      "underlying_code": self.target_underlying.text().strip()}
        try:
            require_unique_position(self.ref)
            require_unique_position(target)
            self.store.link_contracts(self.ref, target, note=self.link_note.text().strip())
            self.target_contract.clear()
            self.target_confirmation.clear()
            self.target_party.clear()
            self.target_underlying.clear()
            self.link_note.clear()
            self.refresh()
        except Exception as exc:
            self._failure(exc)

    def link_report_row(self):
        selected = self._selected()
        if not selected or selected[0] != "report":
            self._failure(ValueError("请先选择一条日报字段匹配的行。"))
            return
        try:
            require_unique_position(self.ref)
            require_unique_position(selected[1])
            self.store.link_contracts(self.ref, selected[1], note=self.link_note.text().strip())
            self.refresh()
        except Exception as exc:
            self._failure(exc)

    def _selected(self):
        row = self.table.currentRow()
        return self.table.item(row, 0).data(Qt.ItemDataRole.UserRole) if row >= 0 else None

    def unlink(self):
        selected = self._selected()
        if not selected or selected[0] != "manual":
            self._failure(ValueError("请选择一条人工关联；日报原始字段不会被修改。"))
            return
        try:
            require_unique_position(self.ref)
            self.store.unlink_contracts(self.ref, selected[1])
            self.refresh()
        except Exception as exc:
            self._failure(exc)

    def copy_number(self):
        selected = self._selected()
        if selected:
            ref = selected[1]
            value = ref.get("contract_no") or ref.get("confirmation_no") or ref.get("local_id") or ""
            QApplication.clipboard().setText(str(value))


class BookkeepingDialog(QDialog):
    """Edit manual records independently of the Excel files and trading systems."""

    def __init__(self, store, report_ref=None, report_results=None, parent=None, identity_counts=None, group_context=None):
        super().__init__(parent)
        self.store = store
        self.report_ref = dict(report_ref or {})
        self.source_matches, self.source_summary = report_display(report_results, self.report_ref.get("source"), identity_counts)
        self.record_id = self.version = None
        self.local_id = ""
        self.source = self.report_ref.get("source") or {}
        self._baseline = None
        self._loading = False
        self.setWindowTitle("人工簿记")
        self.resize(1150, 740)
        self.setMinimumSize(980, 650)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(22, 18, 22, 18)
        outer.setSpacing(10)
        title = QHBoxLayout()
        heading = QVBoxLayout()
        heading.addWidget(label("人工簿记", "dialogTitle"))
        heading.addWidget(label("新开记录，或选中日报中的存续合约登记平仓。", "muted", True))
        title.addLayout(heading, 1)
        title.addWidget(button("新建记录", self.new_record))
        outer.addLayout(title)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 10, 0)
        list_heading = QHBoxLayout()
        list_heading.addWidget(label("本地记录", "sectionTitle"))
        list_heading.addStretch()
        list_heading.addWidget(button("以选中记录平仓", self.close_from_record))
        left_layout.addLayout(list_heading)
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索合约、对手、标的或背对编号")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.refresh_list)
        left_layout.addWidget(self.search)
        self.records = QTableWidget(0, 5)
        self.records.setHorizontalHeaderLabels(["日期", "操作", "合约 / 确认书", "操作组", "背对"])
        self.records.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.records.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.records.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.records.setAlternatingRowColors(True)
        self.records.verticalHeader().hide()
        for index in (0, 1, 3, 4):
            self.records.horizontalHeader().setSectionResizeMode(index, QHeaderView.ResizeMode.ResizeToContents)
        self.records.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.records.cellClicked.connect(self.load_row)
        left_layout.addWidget(self.records, 1)
        splitter.addWidget(left)
        right = QWidget()
        form_layout = QVBoxLayout(right)
        form_layout.setContentsMargins(10, 0, 0, 0)
        self.caption = label("新建记录", "sectionTitle")
        form_layout.addWidget(self.caption)
        self.source_label = label("手工新建", "muted", True)
        form_layout.addWidget(self.source_label)
        top = QHBoxLayout()
        top.addWidget(label("操作"))
        self.action = QComboBox()
        self.action.addItem("新开", "open")
        self.action.addItem("平仓", "close")
        top.addWidget(self.action, 1)
        top.addWidget(label("交易日期"))
        self.trade_date = QLineEdit(today().isoformat())
        self.trade_date.setPlaceholderText("YYYY-MM-DD")
        top.addWidget(self.trade_date, 1)
        form_layout.addLayout(top)
        group_line = QHBoxLayout()
        group_line.addWidget(label("操作组"))
        self.group = QComboBox()
        self.group.addItem("不分组", None)
        try:
            for record in self.store.list_records():
                if record.get("group_id") and record.get("group_name"):
                    self._add_group(record["group_id"], record["group_name"])
        except Exception:
            pass  # The record list displays a readable error below.
        group_line.addWidget(self.group, 1)
        group_line.addWidget(button("新建组", self.create_group))
        form_layout.addLayout(group_line)
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(5)
        self.fields = {}
        for index, (key, title) in enumerate(FIELDS):
            field = QLineEdit()
            field.setClearButtonEnabled(True)
            self.fields[key] = field
            grid.addWidget(label(title), index // 2 * 2, index % 2)
            grid.addWidget(field, index // 2 * 2 + 1, index % 2)
        form_layout.addLayout(grid)
        form_layout.addWidget(label("备注"))
        self.note = QPlainTextEdit()
        self.note.setMaximumHeight(65)
        form_layout.addWidget(self.note)
        self.source_hint = label("来源快照随记录保留；本次数量、金额和价格由你填写。", "muted", True)
        form_layout.addWidget(self.source_hint)
        self.error = label("", "error", True)
        self.error.hide()
        form_layout.addWidget(self.error)
        form_layout.addStretch()
        commands = QHBoxLayout()
        self.back_button = button("查看 / 设置背对", self.open_back)
        commands.addWidget(self.back_button)
        commands.addStretch()
        commands.addWidget(button("保存记录", self.save, "primary"))
        form_layout.addLayout(commands)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 3)
        splitter.setSizes([430, 650])
        outer.addWidget(splitter, 1)
        bottom = QHBoxLayout()
        bottom.addWidget(label("保存为本地人工记录。", "muted"), 1)
        bottom.addWidget(button("关闭", self.close))
        outer.addLayout(bottom)
        self._fill(self.report_ref, new=True)
        if report_ref:
            self.action.setCurrentIndex(self.action.findData("close"))
        if group_context:
            self._select_group(group_context.get("id", ""), group_context.get("name", ""))
        self._baseline = self._values()
        self.refresh_list()

    def _values(self):
        values = {key: widget.text().strip() for key, widget in self.fields.items()}
        group = self.group.currentData() or {}
        values.update(action=self.action.currentData(), trade_date=self.trade_date.text().strip(),
                      note=self.note.toPlainText().strip(), local_id=self.local_id, source=self.source,
                      group_id=group.get("id", ""), group_name=group.get("name", ""))
        return values

    def _add_group(self, group_id, name):
        if not group_id or not name:
            return 0
        for index in range(1, self.group.count()):
            if (self.group.itemData(index) or {}).get("id") == group_id:
                return index
        self.group.addItem(name, {"id": group_id, "name": name})
        return self.group.count() - 1

    def _select_group(self, group_id, name):
        self.group.setCurrentIndex(self._add_group(group_id, name))

    def create_group(self):
        name, accepted = QInputDialog.getText(self, "新建操作组", "组名称",
                                               text="开平组 " + timestamp().replace("T", " ")[:16])
        if accepted and name.strip():
            name = name.strip()
            if any((self.group.itemData(i) or {}).get("name", "").casefold() == name.casefold()
                   for i in range(1, self.group.count())):
                self._failure(ValueError("已有同名操作组，请选择已有组或使用其他名称。"))
                return
            self._select_group(uuid.uuid4().hex, name)
            self.error.hide()

    def _dirty(self):
        return self._baseline is not None and self._values() != self._baseline

    def _confirm_discard(self):
        if not self._dirty():
            return True
        return QMessageBox.question(self, "未保存的修改", "当前内容尚未保存，放弃修改吗？",
                                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                    QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes

    def _fill(self, record, new=False):
        self._loading = True
        self.record_id = None if new else record.get("id")
        self.version = None if new else record.get("version")
        self.local_id = record.get("local_id", "")
        self.source = record.get("source") or {}
        for key, widget in self.fields.items():
            widget.setText(str(record.get(key) or ""))
        self.note.setPlainText(str(record.get("note") or ""))
        self.trade_date.setText(str(record.get("trade_date") or today().isoformat()))
        self.action.setCurrentIndex(max(0, self.action.findData(record.get("action", "open"))))
        self.action.setEnabled(new)
        self._select_group(record.get("group_id", ""), record.get("group_name", ""))
        self.caption.setText("新建记录" if new else "编辑本地记录")
        if self.source.get("sheet") or self.source.get("date"):
            self.source_label.setText(f"来源：{self.source.get('date', '')} · {self.source.get('sheet', '')} · Excel 第 {self.source.get('excel_row', '—')} 行")
        elif self.source.get("based_on_record_id"):
            self.source_label.setText("依据已有人工记录")
        else:
            self.source_label.setText("手工新建")
        self.error.hide()
        self._loading = False
        self._baseline = self._values()

    def new_record(self):
        if self._confirm_discard():
            self.report_ref, self.source_matches = {}, []
            self.source_summary = "当前记录没有可核验的日报背对字段。"
            self.records.clearSelection()
            self._fill({}, new=True)

    def close_from_record(self):
        row = self.records.currentRow()
        if row < 0:
            self._failure(ValueError("请先在左侧选择一条已有记录。"))
            return
        if not self._confirm_discard():
            return
        try:
            record_id = self.records.item(row, 0).data(Qt.ItemDataRole.UserRole)
            record = self.store.get_record(record_id)
            if not record:
                raise ValueError("记录不存在，请刷新列表。")
            source = copy.deepcopy(record.get("source") or {})
            source["based_on_record_id"] = record_id
            values = {key: record.get(key, "") for key in
                      ("contract_no", "confirmation_no", "local_id", "counterparty", "underlying_code",
                       "underlying_name", "direction", "unit")}
            values.update(action="close", source=source)
            self.report_ref, self.source_matches = {}, []
            self.source_summary = "请从日报查询中选中原合约，以核验该日报的背对字段。"
            self.records.clearSelection()
            self._fill(values, new=True)
            self.caption.setText("依据已有记录新建平仓")
        except Exception as exc:
            self._failure(exc)

    def refresh_list(self, *_):
        try:
            records = self.store.list_records(self.search.text().strip())
            self.records.setRowCount(0)
            for row, record in enumerate(records):
                self.records.insertRow(row)
                identity = record.get("contract_no") or record.get("confirmation_no") or "待补编号"
                count = (record.get("source") or {}).get("identity_matches", 0)
                status = "身份不唯一" if isinstance(count, int) and count > 1 else STATUS.get(record.get("back_to_back", {}).get("status", "unknown"), "未确认")
                values = (record.get("trade_date", ""), "新开" if record.get("action") == "open" else "平仓",
                          identity, record.get("group_name") or "—", status)
                for column, value in enumerate(values):
                    self.records.setItem(row, column, make_item(value, record["id"] if column == 0 else None))
                if record["id"] == self.record_id:
                    self.records.selectRow(row)
        except Exception as exc:
            self._failure(exc)

    def _failure(self, exc):
        self.error.setText(str(exc) or "操作未完成，请检查本地记录。")
        self.error.show()

    def load_row(self, row, _column):
        record_id = self.records.item(row, 0).data(Qt.ItemDataRole.UserRole)
        if record_id == self.record_id:
            return
        if not self._confirm_discard():
            self.refresh_list()
            return
        try:
            record = self.store.get_record(record_id)
            if not record:
                raise ValueError("记录不存在，请刷新列表。")
            self.report_ref, self.source_matches = {}, []
            self.source_summary = "请从日报查询中选中原合约，以核验该日报的背对字段。"
            self._fill(record)
        except Exception as exc:
            self._failure(exc)

    def save(self):
        try:
            record = self.store.save_record(self._values(), record_id=self.record_id,
                                            expected_version=self.version)
            self._fill(record)
            self.refresh_list()
            self.caption.setText("记录已保存")
        except Exception as exc:
            self._failure(exc)

    def open_back(self):
        ref = contract_ref(self._values())
        if not any(ref.get(key) for key in ("contract_no", "confirmation_no", "local_id")):
            self._failure(ValueError("请先填写合约编号或确认书编号；新开合约尚无编号时先保存记录。"))
            return
        BackToBackDialog(self.store, ref, self.source_matches, self.source_summary, self).exec()
        self.refresh_list()

    def closeEvent(self, event):
        if self._confirm_discard():
            event.accept()
        else:
            event.ignore()

    def reject(self):
        if self._confirm_discard():
            super().reject()
