import sqlite3

from PySide6.QtCore import QThread, QTimer, Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (QApplication, QDialog, QFileDialog, QGridLayout, QHBoxLayout,
    QListWidget, QListWidgetItem, QMainWindow, QStackedWidget, QTabWidget, QVBoxLayout, QWidget)

from script_making.desktop_theme import STYLE

from .model import LEGS, calculate, date_time, now, number
from .widgets import (GROUP_FIELDS, PLAN_FIELDS, FormDialog, ImportDialog, Table, TradeEditor, audit_display,
                      button, card, fmt, label, trade_display, trade_table)


LEDGER_STYLE = """
QLabel#metricValue { font-size: 22px; font-weight: 700; color: #15354e; }
QLabel#gain { font-size: 22px; font-weight: 700; color: #a73440; }
QLabel#loss { font-size: 22px; font-weight: 700; color: #197363; }
QLabel#groupTitle { font-size: 21px; font-weight: 700; }
QLabel#sectionTitle { color: #223d56; }
QFrame#card QLabel { border: none; background: transparent; }
QTabWidget::pane { border: 1px solid #dfe6ef; background: #fbfcfe; border-radius: 5px; }
QTabBar::tab { color: #53738b; padding: 8px 14px; margin-right: 2px; background: #eaf0f6; }
QTabBar::tab:selected { color: #146a64; background: white; font-weight: 700; }
QListWidget::item:selected { background: #daeee9; color: #14514e; border-radius: 5px; }
QLineEdit { padding: 4px 6px; }
QLineEdit[readOnly="true"] { background: #f2f6f9; color: #435a70; }
QTableWidget#positions::item { padding: 3px 6px; }
QTableWidget#positions QHeaderView::section { padding: 8px 5px; }
"""
LEG_NAMES = dict(zip(LEGS, ('ETF', '股指期货', '跟踪指数')))


class Task(QThread):
    def __init__(self, operation, parent):
        super().__init__(parent)
        self.operation = operation
        self.result = None
        self.error = None

    def run(self):
        try:
            self.result = self.operation()
        except Exception as exc:
            self.error = str(exc)


class LedgerWindow(QMainWindow):
    first_paint = Signal()
    input_ready = Signal()

    def __init__(self, ledger, paths):
        super().__init__()
        self.ledger, self.paths = ledger, paths
        self.group_id = None
        self.config = self.audit = None
        self.rows = []
        self.job = None
        self.painted = False
        self.setWindowTitle('基差交易台账')
        self.resize(1300, 800)
        self.setMinimumSize(940, 660)
        root = QWidget()
        outer = QVBoxLayout(root)
        outer.setContentsMargins(18, 12, 18, 4)
        outer.setSpacing(10)
        toolbar = QHBoxLayout()
        toolbar.addWidget(label('基差交易台账', 'title'))
        toolbar.addStretch()
        self.import_button = button('导入 Excel', self.pick_workbook)
        toolbar.addWidget(self.import_button)
        self.new_button = button('新建交易组', self.create_group, True)
        toolbar.addWidget(self.new_button)
        outer.addLayout(toolbar)

        body = QHBoxLayout()
        body.setSpacing(12)
        side = card()
        side.setFixedWidth(218)
        side_layout = QVBoxLayout(side)
        side_layout.addWidget(label('交易组', 'sectionTitle'))
        self.recent = label('', 'muted')
        self.recent.setWordWrap(True)
        side_layout.addWidget(self.recent)
        self.groups = QListWidget()
        self.groups.setObjectName('groups')
        self.groups.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        side_layout.addWidget(self.groups, 1)
        self.copy_button = button('沿用当前组配置', lambda: self.create_group(True))
        side_layout.addWidget(self.copy_button)
        body.addWidget(side)

        self.panes = QStackedWidget()
        empty = card()
        empty_layout = QVBoxLayout(empty)
        empty_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(label('选择或新建交易组', 'groupTitle'), alignment=Qt.AlignmentFlag.AlignCenter)
        self.panes.addWidget(empty)
        self.panes.addWidget(self.detail_page())
        body.addWidget(self.panes, 1)
        outer.addLayout(body, 1)
        self.setCentralWidget(root)
        self.statusBar().setSizeGripEnabled(False)
        disk = label('本地 SQLite', 'muted')
        disk.setToolTip(str(ledger.path))
        self.statusBar().addPermanentWidget(disk)
        self.groups.currentItemChanged.connect(self.choose_group)
        self.populate_groups()

    def paintEvent(self, event):
        super().paintEvent(event)
        if not self.painted:
            self.painted = True
            self.first_paint.emit()
            QTimer.singleShot(0, self.open_recent)

    def detail_page(self):
        pane = QWidget()
        detail = QVBoxLayout(pane)
        detail.setContentsMargins(0, 0, 0, 0)
        self.title = label('', 'groupTitle')
        self.symbols = label('', 'muted')
        header = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(2)
        titles.addWidget(self.title)
        titles.addWidget(self.symbols)
        header.addLayout(titles, 1)
        self.audit_button = button('导入核对', self.show_audit)
        header.addWidget(self.audit_button)
        self.refresh_button = button('刷新本地行情', self.refresh_quotes)
        header.addWidget(self.refresh_button)
        header.addWidget(button('手填估值', self.manual_marks))
        detail.addLayout(header)

        metrics = QHBoxLayout()
        self.metrics = {}
        for key, caption in (('etf', 'ETF 净仓 · 份'), ('futures', '期货净仓 · 手'), ('realized', '已实现 · 元'),
                             ('floating', '浮动 · 元'), ('total', '总盈亏 · 元')):
            panel = card()
            layout = QVBoxLayout(panel)
            layout.setSpacing(2)
            layout.addWidget(label(caption, 'muted'))
            value = label('—', 'metricValue')
            layout.addWidget(value)
            self.metrics[key] = value
            metrics.addWidget(panel, 1)
        detail.addLayout(metrics)

        self.tabs = QTabWidget()
        trades = QWidget()
        layout = QVBoxLayout(trades)
        self.editor = TradeEditor()
        self.editor.save_requested.connect(self.save_trade)
        layout.addWidget(self.editor)
        actions = QHBoxLayout()
        self.trade_count = label('', 'sectionTitle')
        actions.addWidget(self.trade_count)
        actions.addStretch()
        self.edit_button = button('编辑选中成交', self.edit_trade)
        self.history_button = button('更正记录', self.show_revisions)
        actions.addWidget(self.history_button)
        actions.addWidget(self.edit_button)
        layout.addLayout(actions)
        self.trade_table = trade_table()
        self.trade_table.itemSelectionChanged.connect(self.update_trade_actions)
        self.trade_table.cellDoubleClicked.connect(lambda *_: self.edit_trade())
        layout.addWidget(self.trade_table, 1)
        self.tabs.addTab(trades, '成交流水')
        self.tabs.addTab(self.valuation_page(), '持仓与估值')
        detail.addWidget(self.tabs, 1)
        self.editor_error = label('', 'error')
        self.editor_error.setWordWrap(True)
        self.editor_error.hide()
        detail.addWidget(self.editor_error)
        return pane

    def valuation_page(self):
        pane = QWidget()
        layout = QVBoxLayout(pane)
        layout.addWidget(label('仓位与估值价', 'sectionTitle'))
        self.positions = Table(('品种', '代码', '净仓', '持仓均价', '估值价', '浮动（元）', '价格来源 / 行情时间'),
                               (72, 91, 91, 92, 91, 93, 138))
        self.positions.setObjectName('positions')
        self.positions.verticalHeader().setDefaultSectionSize(51)
        self.positions.setMinimumHeight(200)
        layout.addWidget(self.positions, 1)
        layout.addWidget(label('基差（点）', 'sectionTitle'))
        self.basis_cells = self.metric_grid(layout, (('买基差', '买入成交'), ('卖基差', '卖出成交'),
            ('all', '全部成交'), ('net', '净成交'), ('cost_basis', '持仓成本'), ('market_basis', '持仓市值')))
        title = QHBoxLayout()
        title.addWidget(label('参考底仓与计划', 'sectionTitle'))
        title.addStretch()
        title.addWidget(button('编辑计划', self.edit_plan))
        layout.addLayout(title)
        self.plan_cells = self.metric_grid(layout, (('base_shares', '底仓份额'), ('base_value', '底仓市值 / 元'),
            ('base_lots', '底仓折合手数'), ('plan_lots', '计划手数'), ('plan_value', '计划名义额 / 元'),
            ('plan_shares', '计划折合 ETF 份额')))
        return pane

    @staticmethod
    def metric_grid(layout, fields):
        panel = card()
        grid = QGridLayout(panel)
        cells = {}
        for col, (key, caption) in enumerate(fields):
            grid.addWidget(label(caption, 'muted'), 0, col)
            cells[key] = label('', 'sectionTitle')
            grid.addWidget(cells[key], 1, col)
            grid.setColumnStretch(col, 1)
        layout.addWidget(panel)
        return cells

    def populate_groups(self):
        self.group_rows = self.ledger.groups()
        self.groups.blockSignals(True)
        self.groups.clear()
        for group in self.group_rows:
            when = group['opened'] or ('Excel' if group['imported'] else '')
            item = QListWidgetItem(f"{group['name']}\n{when}  ·  #{group['id']}")
            item.setToolTip(f"{group['etf']}  /  {group['futures']}")
            item.setData(Qt.ItemDataRole.UserRole, group['id'])
            self.groups.addItem(item)
        self.groups.blockSignals(False)
        self.copy_button.setEnabled(bool(self.group_rows))
        recent = self.ledger.recent()
        last = next((group['name'] for group in self.group_rows if group['id'] == recent), '')
        self.recent.setText('最近打开 · ' + last if last else '暂无最近打开的交易组')

    def open_recent(self):
        if self.group_rows and self.group_id is None:
            self.select_group(self.ledger.recent() or self.group_rows[0]['id'])
        QTimer.singleShot(0, self.input_ready.emit)

    def select_group(self, group_id):
        for i, group in enumerate(self.group_rows):
            if group['id'] == group_id:
                self.groups.setCurrentRow(i)
                return

    def choose_group(self, item, _previous):
        if item is None:
            return
        self.group_id = item.data(Qt.ItemDataRole.UserRole)
        self.editor.reset()
        self.editor_error.hide()
        self.tabs.setCurrentIndex(0)
        self.load_group()

    def load_group(self):
        self.config, trades, self.quotes, self.audit = self.ledger.open_group(self.group_id)
        result = calculate(self.config, trades, self.quotes)
        self.rows = result['rows']
        self.title.setText(self.config['name'])
        self.recent.setText('最近打开 · ' + self.config['name'])
        self.symbols.setText(f"{self.config['etf']}  /  {self.config['futures']}   ·   乘数 {self.config['multiplier']}")
        self.audit_button.setVisible(bool(self.audit))
        self.render_result(result)
        posted = sum(row['status'] == 'posted' for row in self.rows)
        self.trade_count.setText(f'组内流水   ·   已入账 {posted}   ·   草稿 {len(trades) - posted}')
        self.trade_table.clearSelection()
        self.trade_table.setCurrentCell(-1, -1)
        self.trade_table.fill([trade_display(row) for row in self.rows])
        self.update_trade_actions()
        self.panes.setCurrentIndex(1)

    def render_result(self, result):
        for key, widget in self.metrics.items():
            if key in ('etf', 'futures'):
                widget.setText(fmt(result[key].quantity, 0))
                widget.setToolTip('持仓均价 ' + fmt(result[key].price, 6 if key == 'etf' else 4))
                continue
            value = result[key]
            widget.setText(fmt(value, missing='待估值'))
            if key == 'realized':
                widget.setToolTip('已扣成交费用 ' + fmt(result['fees']) + ' 元')
            widget.setObjectName('gain' if value and value > 0 else 'loss' if value and value < 0 else 'metricValue')
            widget.style().unpolish(widget)
            widget.style().polish(widget)
        position_rows, quote_tooltips = [], []
        for leg in LEGS:
            position = result.get(leg)
            mark = self.quotes.get(leg)
            source = '待估值'
            tooltip = ''
            if mark:
                source_text = mark['source']
                if mark.get('kind') == 'excel':
                    source_text = 'Excel · ' + source_text.split(' · ', 1)[-1]
                source = f"{source_text}\n{mark['time'] or '原行情时间缺失'}"
                tooltip = f"{mark['source']}\n{mark['time'] or '原行情时间缺失'}"
                if not mark['time'] and mark.get('imported'):
                    tooltip += f"\n读取 {mark['imported']}"
            elif not self.config[leg]:
                source = '未配置'
            position_rows.append((LEG_NAMES[leg], self.config[leg], fmt(position.quantity, 0) if position else '—',
                fmt(position.price, 6 if leg == 'etf' else 4) if position else '—',
                fmt(mark['price'], 6 if leg == 'etf' else 4) if mark else '—',
                fmt(result[leg + '_float'], missing='待估值') if position else '—', source))
            quote_tooltips.append(tooltip or source)
        self.positions.fill(position_rows)
        for i, tooltip in enumerate(quote_tooltips):
            self.positions.item(i, 6).setToolTip(tooltip)
        for key, cell in self.basis_cells.items():
            cell.setText(fmt(result.get(key, result['basis'].get(key)), 4))
        for key, cell in self.plan_cells.items():
            cell.setText(fmt(result.get(key, self.config.get(key)), 0 if key in ('base_shares', 'plan_lots') else 2))

    def create_group(self, reuse=False):
        values = {'opened': now().date().isoformat()}
        if reuse and self.group_rows:
            previous = self.config or self.group_rows[0]
            values.update({key: previous[key] for key in (*LEGS, 'multiplier')})
        dialog = FormDialog('新建交易组', GROUP_FIELDS, values, self.ledger.create, self, submit='创建并录入')
        if dialog.exec():
            self.populate_groups()
            self.select_group(dialog.result_value)
            self.editor.fields['time'].setFocus()

    def edit_plan(self):
        dialog = FormDialog('参考底仓与计划', PLAN_FIELDS, self.config,
                            lambda values: self.ledger.update_plan(self.group_id, values), self)
        if dialog.exec():
            self.load_group()

    def save_trade(self, status):
        row = self.editor.entry or {}
        values = self.editor.values()
        try:
            self.ledger.save_trade(self.group_id, values, status, trade_id=row.get('id'),
                                   version=row.get('version'), reason=values['reason'])
        except (ValueError, sqlite3.Error) as exc:
            self.editor_error.setText(str(exc))
            self.editor_error.show()
            return
        self.editor_error.hide()
        self.editor.reset()
        self.load_group()
        self.trade_table.scrollToBottom()
        self.statusBar().showMessage('成交已入账' if status == 'posted' else '草稿已保存', 5000)

    def selected_trade(self):
        index = self.trade_table.currentRow()
        return self.rows[index] if 0 <= index < len(self.rows) and self.trade_table.selectedItems() else None

    def update_trade_actions(self):
        selected = self.selected_trade()
        self.edit_button.setEnabled(bool(selected))
        self.history_button.setEnabled(bool(selected and selected['version'] > 1 and selected['status'] == 'posted'))

    def edit_trade(self):
        row = self.selected_trade()
        if row:
            self.editor_error.hide()
            self.editor.load(row)
            self.editor.fields['time'].setFocus()

    def show_revisions(self):
        row = self.selected_trade()
        if not row:
            return
        revisions = self.ledger.revisions(self.group_id, row['id'])
        dialog = QDialog(self)
        dialog.setWindowTitle('更正记录')
        dialog.resize(1020, 360)
        layout = QVBoxLayout(dialog)
        revision_table = Table(('版本', '更正原因', '保存时间', '成交时间', '方向', 'ETF 份额', 'ETF 均价',
                                'ETF 金额', '期货手数', '期货价', '费用', '备注'),
                               (66, 170, 176, 140, 90, 99, 101, 107, 90, 90, 90, 130))
        values = []
        for version in [*revisions, row]:
            display = trade_display(version)
            values.append((version['version'], version.get('reason', '当前版本'), version['updated'],
                           *display[:2], *display[3:9], display[-1]))
        revision_table.fill(values)
        layout.addWidget(revision_table)
        dialog.exec()

    def manual_marks(self):
        fields, current = [], {}
        for leg in LEGS:
            symbol = self.config[leg]
            if not symbol:
                continue
            fields.extend(((leg, symbol, '手填估值价'), (leg + '_time', '行情时间', '留空使用保存时间')))
            quote = self.quotes.get(leg)
            if quote and quote.get('kind') == 'manual':
                current.update({leg: quote['price'], leg + '_time': quote['time']})

        def commit(values):
            marks, clear = [], []
            for leg in LEGS:
                if leg not in values:
                    continue
                symbol = self.config[leg]
                price = number(values[leg], symbol + ' 估值价')
                if price is None:
                    clear.append(symbol)
                else:
                    try:
                        timestamp = date_time(values[leg + '_time']) or now().isoformat(sep=' ', timespec='seconds')
                    except ValueError:
                        raise ValueError(f'{symbol} 行情时间请用 YYYY-MM-DD HH:MM') from None
                    marks.append(dict(code=symbol, price=price, time=timestamp, source='手填估值'))
            self.ledger.set_marks(self.group_id, marks, 'manual', clear=clear)

        dialog = FormDialog('手填估值', fields, current, commit, self,
                            hint='手填优先使用。清空某个手填价格可回到已有的本地行情或导入快照。')
        if dialog.exec():
            self.load_group()

    def start_task(self, text, operation, done):
        if self.job:
            return
        self.statusBar().showMessage(text)
        self.refresh_button.setEnabled(False)
        self.import_button.setEnabled(False)
        task = self.job = Task(operation, self)

        def finished():
            self.job = None
            self.import_button.setEnabled(True)
            self.refresh_button.setEnabled(True)
            self.statusBar().clearMessage()
            try:
                if task.error:
                    self.statusBar().showMessage(task.error, 12000)
                else:
                    done(task.result)
            except (OSError, ValueError, sqlite3.Error) as exc:
                self.statusBar().showMessage(str(exc), 12000)
            finally:
                task.deleteLater()

        task.finished.connect(finished)
        task.start()

    def pick_workbook(self):
        path, _ = QFileDialog.getOpenFileName(self, '选择基差交易 Excel', '', 'Excel 工作簿 (*.xlsx *.xlsm)')
        if path:
            from .excel import workbook_preview
            self.start_task('正在读取 Excel 并重算…', lambda: workbook_preview(path), self.preview_workbook)

    def preview_workbook(self, result):
        dialog = ImportDialog(*result, self)
        if dialog.exec():
            ids, skipped = self.ledger.import_groups(dialog.selected())
            if ids:
                self.populate_groups()
                self.select_group(ids[0])
            self.statusBar().showMessage(f'已导入 {len(ids)} 组，重复跳过 {skipped} 组', 8000)

    def show_audit(self):
        if not self.audit:
            return
        dialog = QDialog(self)
        dialog.setWindowTitle('导入时核对记录')
        dialog.resize(1040, 580)
        audit_display(self.audit, QVBoxLayout(dialog))
        dialog.exec()

    def refresh_quotes(self):
        from .quotes import local_closes

        group_id = self.group_id
        codes = sorted({self.config[leg] for leg in LEGS if self.config[leg]})

        def done(result):
            marks, problems = result
            if marks:
                self.ledger.set_marks(group_id, marks, 'local')
                if self.group_id == group_id:
                    self.load_group()
            missing = len(codes) - len(marks)
            message = f'本地收盘价更新 {len(marks)} 项，未找到 {missing} 项'
            self.statusBar().showMessage(message, 10000)
            self.statusBar().setToolTip('\n'.join(problems))

        self.start_task('正在读取共享行情库…', lambda: local_closes(self.paths, codes), done)

    def closeEvent(self, event):
        if self.job and self.job.isRunning():
            self.statusBar().showMessage('正在读取本地文件，完成后可关闭窗口')
            event.ignore()
        else:
            super().closeEvent(event)


def application():
    app = QApplication.instance() or QApplication([])
    app.setFont(QFont('Microsoft YaHei UI', 10))
    app.setStyleSheet(STYLE + LEDGER_STYLE)
    return app
