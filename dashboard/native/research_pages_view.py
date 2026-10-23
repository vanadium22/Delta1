"""Local App projections of the shared three-page indicator contract.

No formula, representative selection or quote collection lives in this module.
Only the selected catalogue group and bounded detail page are evaluated.
"""
from html import escape
import json
import uuid

import pandas as pd
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QComboBox, QPushButton, QListWidget, QListWidgetItem, QSplitter, QGridLayout,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView, QTextBrowser,
    QTabWidget, QScrollArea)

from .card_views import number, stamp, scroll_widget, chart_font
from .widgets import Panel, Chart
from .theme import MUTED,ACCENT
from dashboard.indicator_ui import input_label, input_options, family_title, families, resolve_variant


PAGE_TITLES = {'basis': '期现', 'calendar': '同品种跨期', 'cross': '跨品种'}
STATUS_TITLES = {'implemented':'已实现', 'not_implemented':'尚未实现', 'missing_input':'缺真实输入',
    'missing_entity':'缺可用实体', 'not_applicable':'不适用', 'old_history':'最后有效历史',
    'intraday_estimate':'盘中估计', 'daily_reference':'日终参考', 'input_version_changed':'数据版本已变化'}


def capture(model, request, selection=None, display=False):
    # One frame uses a single immutable history publication and receipt cutoff.
    repo=model.configure_repository(False)
    frozen=repo.freeze()
    model._app_capture_frozen=frozen;model._app_capture_live_loaded=False
    try:return _capture(model,request,selection,display)
    except Exception as exc:
        from dashboard.refresh_evidence import utc_now
        model.refresh_trace={**getattr(model,'refresh_trace',{}),'calculation_failed_at':utc_now(),'error_type':type(exc).__name__}
        raise
    finally:
        model.__dict__.pop('_app_capture_frozen',None)
        model.__dict__.pop('_app_capture_live_loaded',None)


def _capture(model, request, selection=None, display=False):
    """Capture the old overview and new research result from the same model."""
    from dashboard.indicator_workspace import evaluate, save_preferences
    from dashboard.numeric_evidence import cache_scope
    model.numeric_cache_scope=cache_scope(model.config)
    from dashboard.refresh_evidence import begin,calculated
    trace=begin(model)
    if display:
        from dashboard.display_state import display_snapshot
        state = display_snapshot(model, request)
    else:
        state = model.snapshot(request)
    research = None if getattr(model,'indicator_v6_active',False) else evaluate(model, selection,now=state['as_of'])
    state['research_pages'] = research
    request_id = (selection or {}).get('request_id')
    if request_id and request_id != getattr(model, 'saved_indicator_request', None):
        save_preferences(model.local_root, research['selection'])
        model.saved_indicator_request = request_id
    state=calculated(model,state,trace)
    from dashboard.app_preview import save
    try:save(model.config,state)
    except OSError:pass
    return state


def text(value):
    if value is None:
        return '—'
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, ensure_ascii=False, default=str)
    return str(value)


def metric_of(entity):
    metrics = entity.get('metrics') or []
    return metrics[0] if metrics else {}


def metric_role(metric, group, page):
    """Use explicit backend roles; pair projections never infer old comparisons as primary."""
    role = metric.get('role') or (group.get('metric_roles') or {}).get(metric.get('id'))
    if role:
        return role
    if page == 'basis':
        return 'primary' if metric.get('id') in primary_ids(group) else 'auxiliary'
    return 'auxiliary'


def primary_ids(group):
    value = group.get('primary')
    return list(value) if isinstance(value, (list, tuple, set)) else [value] if value else []


def primary_metric(entity, group, page):
    metrics = entity.get('metrics') or []
    effective=entity.get('primary')
    if isinstance(effective,dict) and effective.get('id'):
        return effective
    ids=primary_ids(group)
    selected = next((metric for key in ids for metric in metrics if metric.get('id') == key
                     and (page == 'basis' or metric_role(metric, group, page) == 'primary')), None)
    if selected is not None:
        return selected
    if page == 'basis':
        return metric_of(entity)
    return dict(id=next(iter(ids),None), value=None, unit=group.get('unit', ''), role='primary',
        data_status='missing_input', reason='未收到合约对主指标；原单腿比较保留在辅助解释中。',
        formula_version=group.get('formula_version'))


def construction_label(construction):
    if isinstance(construction, dict):
        return str(construction.get('label') or construction.get('title') or construction.get('description') or
                   construction.get('formula') or '双腿构造见详情')
    return str(construction or '双腿构造与同步条件见详情')


def construction_html(construction):
    if not isinstance(construction, dict):
        return '<p>' + escape(construction_label(construction)) + '</p>'
    labels = {'label':'构造', 'title':'构造', 'description':'定义', 'formula':'双腿公式',
        'construction':'双腿公式', 'ratio':'手数比 h 的取法', 'weight':'匹配容量权重',
        'legs':'双腿', 'hedge_ratio':'手数比 h', 'h':'手数比 h',
        'volume_weight':'成交量权重', 'oi_weight':'持仓量权重', 'weights':'权重',
        'synchronization':'同步条件', 'sync_policy':'同步条件', 'formula_version':'公式版本',
        'direction':'方向', 'unit':'单位', 'meaning':'含义', 'limitations':'限制',
        'left':'A 腿', 'right':'B 腿', 'h_actual':'实际手数比 h',
        'volume_weights':'成交量权重', 'oi_weights':'持仓量权重', 'source_times':'各腿源时',
        'historical':'日终参数（按所列源时）', 'current':'盘中参数（按所列源时）',
        'time':'参数源时', 'metric_value_time':'指标数值源时', 'context':'使用范围',
        'ratio_source_time':'h 的参考源时', 'ratio_source_date':'h 的参考交易日',
        'effective_h':'实际手数比 h', 'matched_volume':'匹配成交量代理',
        'matched_oi':'匹配持仓量代理', 'previous_matched_oi':'前日匹配持仓量代理',
        'weight_sum':'有效权重合计', 'baseline_n':'历史基准日数', 'baseline_start':'基准起始',
        'baseline_end':'基准结束', 'numerator':'当前分子', 'denominator':'历史基准分母',
        'sample_n':'同步样本数', 'segment_start':'采集段起始', 'segment_end':'采集段结束',
        'boundary':'同刻分钟边界', 'approximation':'分钟边界近似', 'minute_count':'每日基准分钟数',
        'ratio_source_times':'h 的各腿参考源时', 'scope':'观测口径'}
    return '<table>' + ''.join('<tr><td style="padding:5px 18px 5px 0;color:#a9b5c3">'+escape(labels.get(key,key))+
        '</td><td style="padding:5px 0">'+(construction_html(value) if isinstance(value,dict) and value else
            '—' if isinstance(value,dict) else escape(text(value)))+'</td></tr>' for key,value in construction.items())+'</table>'


class ResearchPage(QWidget):
    changed = Signal()

    def __init__(self, page):
        super().__init__()
        self.page = page
        self.selection = None
        self.initialized = False
        self.read_only = False
        self.dirty = False
        self.result = None
        self.catalogue = {}
        self.cards = []
        self.entities = []
        self.offset = 0
        self.last_input = 'basis'
        self.blocked_reason = ''
        body = QVBoxLayout(self)
        body.setContentsMargins(12, 14, 12, 8)
        body.setSpacing(12)
        self.setStyleSheet(('QLabel#researchContext {color:THEME_MUTED;font-size:14px;} '
            'QLabel#researchState {font-size:14px;padding:5px 0;} '
            'QListWidget {font-size:14px;} QLineEdit {min-height:28px;}').replace('THEME_MUTED',MUTED))
        controls = QGridLayout(); controls.setHorizontalSpacing(12)
        self.input = QComboBox()
        self.input.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.input.setMinimumContentsLength(16)
        self.input.setMinimumWidth(280)
        self.family = QComboBox()
        self.family.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.family.setMinimumContentsLength(17)
        for group in families(page):
            self.family.addItem(group['title'], group['family_id'])
        self.more_inputs = QPushButton('更多口径'); self.more_inputs.setCheckable(True)
        self.more_inputs.setToolTip('展开未调整、对数等独立输入；指标公式保持各自口径。')
        self.timing = QComboBox()
        for title, key in (('盘中优先 · 独立估计', 'intraday'), ('完整日终 · close', 'daily'), ('历史日', 'historical')):
            self.timing.addItem(title, key)
        controls.addWidget(QLabel('输入 X'), 0, 0)
        controls.addWidget(QLabel('指标'), 0, 2)
        controls.addWidget(QLabel('观察时点'), 0, 3)
        controls.addWidget(self.input, 1, 0); controls.addWidget(self.more_inputs, 1, 1)
        controls.addWidget(self.family, 1, 2); controls.addWidget(self.timing, 1, 3)
        controls.setColumnStretch(0, 3); controls.setColumnStretch(2, 4); controls.setColumnStretch(3, 2)
        body.addLayout(controls)
        self.populate_inputs()
        utilities = QHBoxLayout()
        self.context = QLabel('选择输入与指标，查看默认代表'); self.context.setObjectName('researchContext');self.context.setWordWrap(True)
        utilities.addWidget(self.context, 1)
        self.directory_toggle = QPushButton('检索全部指标');self.directory_toggle.setCheckable(True)
        self.advanced_toggle = QPushButton('高级筛选');self.advanced_toggle.setCheckable(True)
        utilities.addWidget(self.directory_toggle);utilities.addWidget(self.advanced_toggle)
        body.addLayout(utilities)
        self.advanced = QWidget(); advanced_layout=QVBoxLayout(self.advanced);advanced_layout.setContentsMargins(0,0,0,0)
        filters = QHBoxLayout()
        self.scope = QComboBox()
        self.scope.addItem('默认代表', 'representatives')
        self.scope.addItem('全部适用实体 · 分页', 'all')
        self.scope.addItem('历史合约实体 · 分页', 'history')
        self.scope.addItem('指定具体合约', 'specified')
        self.expiry = QComboBox()
        self.expiry.addItem('同期到期', 'same')
        self.expiry.addItem('所有月份', 'all')
        self.expiry.addItem('异期到期', 'mixed')
        self.expiry.setVisible(page == 'cross')
        self.product = QComboBox()
        self.product.addItem('全部品种', '')
        for root in ('IF', 'IH', 'IC', 'IM'):
            self.product.addItem(root, root)
        for title, widget in (('范围', self.scope), ('品种', self.product)):
            filters.addWidget(QLabel(title)); filters.addWidget(widget)
        filters.addStretch()
        filters.addWidget(self.expiry)
        advanced_layout.addLayout(filters)
        contracts = QHBoxLayout()
        self.left = QLineEdit(); self.left.setPlaceholderText('具体合约 A（可空）')
        self.right = QLineEdit(); self.right.setPlaceholderText('具体合约 B（可空）')
        self.date = QLineEdit(); self.date.setPlaceholderText('历史日 YYYY-MM-DD')
        self.date.setMinimumWidth(190)
        self.participation = QLineEdit(); self.participation.setPlaceholderText('p（0–1，可留空）')
        self.participation.setToolTip('B12参与比例p：输入0到1之间的小数；留空不会假设参与比例。')
        self.participation.setMinimumWidth(175)
        self.apply = QPushButton('应用筛选')
        self.apply.clicked.connect(self.submit)
        for widget in (self.left, self.right, self.date, self.participation, self.apply):
            contracts.addWidget(widget)
        self.right.setEnabled(page != 'basis')
        advanced_layout.addLayout(contracts)
        body.addWidget(self.advanced);self.advanced.hide()
        self.advanced_toggle.toggled.connect(self.advanced.setVisible)
        self.note = QLabel('正在读取指标…');self.note.setObjectName('researchState')
        self.note.setWordWrap(True); body.addWidget(self.note)
        split = QSplitter(Qt.Orientation.Horizontal)
        self.sidebar = QWidget(); sidebar_layout = QVBoxLayout(self.sidebar)
        sidebar_layout.setContentsMargins(0, 0, 8, 0)
        self.search = QLineEdit(); self.search.setPlaceholderText('搜索名称、指标编号或口径')
        sidebar_layout.addWidget(self.search)
        self.directory = QListWidget(); self.directory.setMinimumWidth(250)
        sidebar_layout.addWidget(self.directory, 1)
        split.addWidget(self.sidebar);self.sidebar.hide()
        self.directory_toggle.toggled.connect(self.sidebar.setVisible)
        self.content = QWidget(); content = QVBoxLayout(self.content)
        content.setContentsMargins(0, 0, 0, 0)
        self.heading = QLabel('默认代表'); self.heading.setStyleSheet('font-size:21px;font-weight:600')
        self.heading.setWordWrap(True)
        content.addWidget(self.heading)
        self.construction = QLabel(); self.construction.setWordWrap(True)
        self.construction.setObjectName('researchContext');self.construction.setVisible(page != 'basis')
        content.addWidget(self.construction)
        scroll, self.card_container = scroll_widget()
        self.card_grid = QGridLayout(self.card_container)
        self.card_grid.setContentsMargins(0, 0, 8, 0)
        self.card_grid.setSpacing(10)
        self.cards_scroll=scroll
        scroll.setMinimumHeight(120)
        content.addWidget(scroll, 1)
        navigation = QHBoxLayout()
        self.expand = QPushButton('展开全部适用实体')
        self.expand.clicked.connect(self.expand_all)
        self.representatives = QPushButton('返回默认代表')
        self.representatives.clicked.connect(lambda:self.scope.setCurrentIndex(self.scope.findData('representatives')))
        self.previous = QPushButton('上一页'); self.previous.clicked.connect(lambda: self.move_page(-1))
        self.next = QPushButton('下一页'); self.next.clicked.connect(lambda: self.move_page(1))
        self.page_note = QLabel('')
        self.detail_toggle=QPushButton('展开图表与详情');self.detail_toggle.setCheckable(True)
        for widget in (self.expand, self.representatives, self.previous, self.next, self.page_note):
            navigation.addWidget(widget)
        navigation.addStretch();navigation.addWidget(self.detail_toggle); content.addLayout(navigation)
        self.details = QTabWidget()
        self.details.setMinimumHeight(180)
        self.table = QTableWidget(0, 12)
        self.table.setHorizontalHeaderLabels(['实体 / 具体腿', '指标 / 变体', '值', '单位',
            '各腿源时', '历史截止', '有效 n', '实现状态', '数据状态', '代表依据', '原因', '输入 / 公式版本'])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        for column in range(12):
            self.table.setColumnWidth(column, 210 if column in (0, 1, 4, 10, 11) else 105)
        self.table.itemSelectionChanged.connect(self.draw_entity)
        self.primary_table = self.result_table()
        self.auxiliary_table = self.result_table()
        self.primary_table.itemSelectionChanged.connect(lambda:self.select_role_row('primary'))
        self.auxiliary_table.itemSelectionChanged.connect(lambda:self.select_role_row('auxiliary'))
        self.details.addTab(self.table if page == 'basis' else self.primary_table,
                            '完整结果与源时' if page == 'basis' else '合约对主指标')
        self.chart = Chart('固定实体历史', '', height=250); chart_font(self.chart.plot)
        self.chart.plot.setMinimumHeight(140);self.chart.plot.setMaximumHeight(16777215)
        chart_scroll = QScrollArea(); chart_scroll.setWidgetResizable(True); chart_scroll.setWidget(self.chart)
        self.details.addTab(chart_scroll, '固定合约图表' if page == 'basis' else '合约对主图')
        self.formula = QTextBrowser(); self.details.addTab(self.formula,
            '公式、输入与解释' if page == 'basis' else '双腿构造与公式')
        if page != 'basis':
            self.details.addTab(self.auxiliary_table, '辅助解释 · 原单腿比较')
            self.details.addTab(self.table, '完整契约与源时')
        content.addWidget(self.details, 1);self.details.hide()
        self.detail_toggle.toggled.connect(self.toggle_details)
        split.addWidget(self.content); split.setStretchFactor(1, 1)
        split.setSizes([285, 1050]); body.addWidget(split, 1)
        self.search.textChanged.connect(self.filter_directory)
        self.input.currentIndexChanged.connect(self.input_changed)
        self.family.currentIndexChanged.connect(self.family_changed)
        self.more_inputs.toggled.connect(self.populate_inputs)
        self.directory.currentItemChanged.connect(self.choose_group)
        for widget in (self.scope, self.product, self.expiry):
            widget.currentIndexChanged.connect(self.submit)
        self.timing.currentIndexChanged.connect(self.timing_changed)
        for widget in (self.left, self.right, self.date, self.participation):
            widget.textEdited.connect(self.mark_dirty)
            widget.returnPressed.connect(self.submit)

    def result_table(self):
        table = QTableWidget(0, 6)
        table.setHorizontalHeaderLabels(['合约对 / 具体腿', '指标', '值', '单位', '源时', '有效 n / 状态'])
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        for column,width in enumerate((260,230,130,140,180,190)):table.setColumnWidth(column,width)
        table.horizontalHeader().setStretchLastSection(True)
        return table

    def populate_inputs(self, *_):
        selected = self.input.currentData() or self.last_input
        self.input.blockSignals(True); self.input.clear()
        for option in input_options(self.page, include_advanced=self.more_inputs.isChecked()):
            key = option['input_id']
            label=input_label(key, self.timing.currentData(), page=self.page)
            compact=label
            if key=='future' and self.timing.currentData()=='intraday':
                compact={'basis':'期货最新价 / 日终 close','calendar':'跨期价差 close（盘中最新）',
                         'cross':'对数价比 close（盘中最新）'}[self.page]
            self.input.addItem(compact, key)
            self.input.setItemData(self.input.count()-1,label,Qt.ItemDataRole.ToolTipRole)
        if selected not in ('future','basis','annual','fixed') and self.input.findData(selected)<0:
            self.input.addItem(input_label(selected, self.timing.currentData(),page=self.page),selected)
        if selected == 'fixed':
            self.input.addItem('固定经济口径', 'fixed')
        self.input.setCurrentIndex(max(0,self.input.findData(selected)))
        self.input.blockSignals(False)

    def sync_family_controls(self, group):
        self.family.blockSignals(True)
        self.family.setCurrentIndex(self.family.findData(group.get('family_id')))
        self.family.blockSignals(False)
        self.family.setToolTip(self.family.currentText())
        key=group.get('input_id','basis')
        if key!='fixed':self.last_input=key
        self.input.blockSignals(True)
        if self.input.findData(key)<0:self.input.addItem(input_label(key,self.timing.currentData(),page=self.page),key)
        self.input.setCurrentIndex(self.input.findData(key));self.input.blockSignals(False)
        self.input.setEnabled(key!='fixed' and not self.read_only)
        self.more_inputs.setEnabled(key!='fixed' and not self.read_only)
        self.input.setToolTip('固定口径 · 不随输入 X 改变' if key=='fixed' else input_label(key,self.timing.currentData(),page=self.page))
        if self.page=='cross' and key!='fixed':
            self.input.setToolTip(input_label(key,self.timing.currentData(),page=self.page)+'\n双腿按当前定义构造成对序列；不同指数原始点位不直接相减。')

    def input_changed(self, *_):
        if not self.initialized:return
        if self.input.currentData()!='fixed':self.last_input=self.input.currentData()
        self.select_family_variant(self.family.currentData(),self.input.currentData())

    def family_changed(self, *_):
        if not self.initialized:return
        target=next((group for group in families(self.page) if group['family_id']==self.family.currentData()),{})
        if not target.get('fixed'):
            self.input.blockSignals(True)
            fixed=self.input.findData('fixed')
            if fixed>=0:self.input.removeItem(fixed)
            if self.input.findData(self.last_input)<0:self.input.addItem(input_label(self.last_input,self.timing.currentData(),page=self.page),self.last_input)
            self.input.setCurrentIndex(self.input.findData(self.last_input));self.input.blockSignals(False)
            self.input.setEnabled(True);self.more_inputs.setEnabled(True)
        self.select_family_variant(self.family.currentData(),self.last_input)

    def select_family_variant(self, family, input_id):
        group,reason=resolve_variant(self.page,family,input_id)
        if not group:
            self.invalidate(reason or '该指标不适用于当前输入，请选择其他输入。')
            self.update_context();return
        self.blocked_reason=''
        self.sync_family_controls(group)
        self.directory.blockSignals(True)
        for index in range(self.directory.count()):
            item=self.directory.item(index)
            if item.data(Qt.ItemDataRole.UserRole)==group['variant_id']:
                self.directory.setCurrentItem(item);break
        self.directory.blockSignals(False)
        self.filter_directory(auto_select=False)
        item=self.directory.currentItem()
        if item and item.isHidden():
            self.invalidate('当前指标不在搜索结果中，请清空搜索或选择匹配指标。');return
        self.submit()

    def timing_changed(self, *_):
        self.populate_inputs()
        if self.timing.currentData()=='historical':self.advanced_toggle.setChecked(True)
        self.submit()

    def update_context(self):
        fixed=self.input.currentData()=='fixed'
        parts=[PAGE_TITLES[self.page],self.family.currentText(),
            '固定口径 · 不随输入 X 改变' if fixed else self.input.currentText(),
            self.scope.currentText(),self.timing.currentText()]
        self.context.setText('  ·  '.join(parts))
        self.heading.setText(self.family.currentText() or '默认代表')

    def invalidate(self, reason):
        choice={**self.choice(),'selection_error':reason,'variant_id':None,
            'family_id':self.family.currentData(),'input':self.input.currentData()}
        self.selection={**(self.selection or {}),'page':self.page,
            'pages':{**(self.selection or {}).get('pages',{}),self.page:choice},'request_id':uuid.uuid4().hex}
        self.blocked_reason=reason;self.dirty=True
        self.clear_results();self.note.setText(reason)

    def toggle_details(self, checked):
        self.details.setVisible(checked)
        self.detail_toggle.setText('收起图表与详情' if checked else '展开图表与详情')

    def show_entity(self, entity_id):
        group = self.catalogue.get(self.choice().get('variant_id'), {})
        for index,(entity,metric) in enumerate(self.table_rows):
            if entity.get('entity_id')==entity_id and (self.page=='basis' or metric.get('id')==primary_metric(entity,group,self.page).get('id')):
                self.table.selectRow(index);break
        self.detail_toggle.setChecked(True);self.details.setCurrentIndex(1)

    def select_role_row(self, role):
        table = self.primary_table if role == 'primary' else self.auxiliary_table
        rows = getattr(self, role + '_rows', [])
        if table.currentRow() < 0 or table.currentRow() >= len(rows):return
        wanted = rows[table.currentRow()]
        for index,pair in enumerate(self.table_rows):
            if pair[0].get('entity_id') == wanted[0].get('entity_id') and pair[1].get('id') == wanted[1].get('id'):
                self.table.selectRow(index);self.draw_entity();break

    def fill_role_tables(self, group):
        if self.page == 'basis':return
        for role,table in (('primary',self.primary_table),('auxiliary',self.auxiliary_table)):
            rows = ([(entity,primary_metric(entity,group,self.page)) for entity in self.entities] if role=='primary' else
                [(entity,metric) for entity,metric in self.table_rows
                    if metric.get('id')!=primary_metric(entity,group,self.page).get('id')])
            setattr(self,role+'_rows',rows)
            table.blockSignals(True);table.setRowCount(len(rows))
            for row,(entity,metric) in enumerate(rows):
                status=STATUS_TITLES.get(metric.get('data_status'),metric.get('data_status')) or '—'
                values=[entity.get('title') or entity.get('entity_id'),metric.get('title') or metric.get('id'),
                    number(metric.get('value'),5),metric.get('unit'),stamp(metric.get('time'),True),
                    'n='+text(metric.get('n'))+' · '+status]
                for column,value in enumerate(values):
                    item=QTableWidgetItem(text(value));item.setToolTip(text(metric.get('reason') or value))
                    table.setItem(row,column,item)
            if rows:table.selectRow(0)
            table.blockSignals(False)
        auxiliary_title='日终参考 / 辅助解释' if group.get('family_id') in ('B09','B11') else '辅助解释 · 原单腿比较'
        self.details.setTabText(3,auxiliary_title+' ('+str(len(self.auxiliary_rows))+')')

    def clear_results(self):
        self.table.setRowCount(0); self.entities = []; self.table_rows=[];self.result=None
        self.primary_table.setRowCount(0);self.auxiliary_table.setRowCount(0)
        self.primary_rows=[];self.auxiliary_rows=[];self.construction.clear()
        self.chart_metric=None;self.card_metrics=[];self.chart_history=[]
        self.previous.setEnabled(False);self.next.setEnabled(False);self.page_note.clear()
        self.chart.draw([], key=('pending', uuid.uuid4().hex), note='选择已改变，等待对应结果。')
        self.formula.clear()
        self.clear_cards()

    def clear_cards(self):
        for card in self.cards:
            card.setParent(None); card.deleteLater()
        self.cards = []

    def mark_dirty(self, *_):
        if not self.initialized:
            return
        # Invalidate the ID immediately, even before Enter / Apply is pressed.
        # An old in-flight response must never refill changed contract fields.
        self.selection = {**(self.selection or {}), 'request_id': uuid.uuid4().hex}
        self.dirty = True
        self.clear_results(); self.note.setText('筛选已修改，点击“应用筛选”计算。')

    def request(self):
        return self.selection

    def choice(self):
        value = self.selection or {}
        return value.get('pages', {}).get(self.page, value)

    def filter_directory(self, *_, auto_select=True):
        query = self.search.text().strip().lower()
        visible=[]
        for index in range(self.directory.count()):
            item = self.directory.item(index)
            key=item.data(Qt.ItemDataRole.UserRole)
            item.setHidden(bool(query and query not in (item.text()+' '+key).lower()))
            if not item.isHidden():visible.append(item)
        if not self.initialized or not auto_select:return
        if not visible:
            self.invalidate('没有匹配的指标；请修改或清空搜索。');return
        selected=self.directory.currentItem()
        if not selected or selected.isHidden():
            candidate=next((item for item in visible if self.catalogue[item.data(Qt.ItemDataRole.UserRole)].get('input_id')==self.last_input),visible[0])
            self.directory.setCurrentItem(candidate)
        elif self.blocked_reason:
            self.choose_group(selected,None)

    def choose_group(self, item, _previous):
        if self.initialized and item:
            self.blocked_reason=''
            self.sync_family_controls(self.catalogue.get(item.data(Qt.ItemDataRole.UserRole),{}))
            self.submit()

    def submit(self, *_):
        if not self.initialized or self.read_only:
            return
        item = self.directory.currentItem()
        if not item or item.isHidden():
            self.invalidate('没有匹配的指标；请修改或清空搜索。');return
        variant = item.data(Qt.ItemDataRole.UserRole) if item else None
        group = self.catalogue.get(variant, {})
        if group.get('family_id')!=self.family.currentData():
            self.invalidate('该指标不适用于当前输入，请选择其他输入。');return
        resolved,reason=resolve_variant(self.page,self.family.currentData(),self.input.currentData())
        if not resolved or resolved.get('variant_id')!=variant:
            self.invalidate(reason or '该指标不适用于当前输入，请选择其他输入。');return
        self.offset = 0
        raw_p = self.participation.text().strip()
        try:
            participation = float(raw_p) if raw_p else None
        except ValueError:
            participation = raw_p  # Backend reports invalid input; never assume p.
        choice = {**self.choice(),
            'family_id': group.get('family_id'), 'variant_id': variant,
            'input': group.get('input_id', 'basis'), 'scope': self.scope.currentData(),
            'product': self.product.currentData(), 'root': self.product.currentData(), 'left': self.left.text().strip().upper(),
            'right': self.right.text().strip().upper(), 'timing': self.timing.currentData(),
            'expiry_mode': self.expiry.currentData() if self.page == 'cross' else 'all',
            'date': self.date.text().strip(), 'offset': 0, 'limit': 20,
            'participation': participation,
            'selection_error': None,
        }
        self.selection = {**(self.selection or {}), 'page': self.page, 'active_page': self.page,
            'pages': {**(self.selection or {}).get('pages', {}), self.page: choice},
            'request_id': uuid.uuid4().hex}
        self.dirty = False;self.blocked_reason=''
        if self.scope.currentData()!='representatives':
            self.detail_toggle.setChecked(True);self.details.setCurrentIndex(0)
        self.update_context()
        self.clear_results(); self.note.setText('正在加载所选指标及输入…'); self.changed.emit()

    def expand_all(self):
        self.detail_toggle.setChecked(True);self.details.setCurrentIndex(0)
        if self.scope.currentData() == 'all':
            self.submit()
        else:
            self.scope.setCurrentIndex(self.scope.findData('all'))

    def move_page(self, direction):
        if not self.selection or self.dirty or self.read_only:
            return
        choice = {**self.choice()}
        self.offset = max(0, self.offset + direction * int(choice.get('limit', 20)))
        choice['offset'] = self.offset
        self.selection = {**self.selection, 'pages': {**self.selection.get('pages', {}), self.page: choice},
            'request_id': uuid.uuid4().hex}
        self.clear_results(); self.note.setText('正在读取该页实体…'); self.changed.emit()

    def render(self, research):
        if not research:
            return
        selection = research.get('selection', {})
        page = research.get('pages', {}).get(self.page, {})
        if selection.get('page')==self.page:
            if self.dirty:return
            if self.selection and research.get('request_id')!=self.selection.get('request_id'):return
        groups = page.get('groups', [])
        # Pair identities/roles are page-specific. The global catalogue only
        # describes generic families and cannot define a pair's main value.
        if groups:
            catalog = {group['variant_id']:{key:value for key,value in group.items()
                if key not in ('entities','loaded')} for group in groups}
        else:
            from dashboard.indicator_catalog import catalog as page_catalog
            catalog = {row['variant_id']:row for row in page_catalog(self.page)}
        selected_group=page.get('selected_group') or {}
        if selected_group.get('variant_id'):
            # A timing-dependent headline can change without changing the
            # stable variant ID. Cards, detail selection and chart share it.
            catalog[selected_group['variant_id']]={key:value for key,value in selected_group.items()
                if key not in ('entities','loaded')}
        if catalog != self.catalogue:
            selected = self.choice().get('variant_id') or page.get('selected_variant_id')
            self.directory.blockSignals(True); self.directory.clear()
            self.catalogue = catalog
            for key, group in catalog.items():
                title = family_title(group)+'\n'+input_label(group.get('input_id','fixed'),'daily',page=self.page)
                item = QListWidgetItem(title); item.setData(Qt.ItemDataRole.UserRole, key)
                item.setToolTip(key + '\n' + text(group.get('source_ref')))
                self.directory.addItem(item)
                if key == selected:
                    self.directory.setCurrentItem(item)
            self.directory.blockSignals(False); self.filter_directory(auto_select=False)
        if selection.get('page') != self.page:
            self.initialized = True
            return
        if self.dirty:
            return
        if self.selection and research.get('request_id') != self.selection.get('request_id'):
            return
        old_rows = getattr(self, 'table_rows', [])
        old_index = self.table.currentRow()
        old_identity = ((old_rows[old_index][0].get('entity_id'), old_rows[old_index][1].get('id'))
                        if 0 <= old_index < len(old_rows) else None)
        scroll_position = self.table.verticalScrollBar().value(), self.table.horizontalScrollBar().value()
        self.result = page; self.selection = selection
        choice = self.choice()
        self.scope.blockSignals(True); self.scope.setCurrentIndex(max(0, self.scope.findData(choice.get('scope')))); self.scope.blockSignals(False)
        timing = {'盘中优先':'intraday','日终':'daily','历史日':'historical'}.get(choice.get('timing'),choice.get('timing'))
        self.timing.blockSignals(True); self.timing.setCurrentIndex(max(0, self.timing.findData(timing))); self.timing.blockSignals(False)
        self.product.blockSignals(True); self.product.setCurrentIndex(max(0, self.product.findData(choice.get('root') or choice.get('product', '')))); self.product.blockSignals(False)
        self.expiry.blockSignals(True); self.expiry.setCurrentIndex(max(0, self.expiry.findData(choice.get('expiry_mode','all')))); self.expiry.blockSignals(False)
        self.left.setText(choice.get('left') or ''); self.right.setText(choice.get('right') or ''); self.date.setText(choice.get('date') or '')
        self.participation.setText('' if choice.get('participation') is None else str(choice['participation']))
        variant = choice.get('variant_id') or page.get('selected_variant_id')
        self.directory.blockSignals(True)
        if not variant:self.directory.setCurrentRow(-1)
        for index in range(self.directory.count()):
            if self.directory.item(index).data(Qt.ItemDataRole.UserRole) == variant:
                self.directory.setCurrentRow(index); break
        self.directory.blockSignals(False)
        self.initialized = True
        if choice.get('selection_error') and not variant:
            self.family.blockSignals(True);self.family.setCurrentIndex(self.family.findData(choice.get('family_id')));self.family.blockSignals(False)
            input_id=choice.get('input','basis');self.last_input=input_id
            self.input.blockSignals(True)
            if self.input.findData(input_id)<0:
                self.input.addItem(input_label(input_id,self.timing.currentData(),page=self.page)+'（不适用）',input_id)
                self.input.model().item(self.input.count()-1).setEnabled(False)
            self.input.setCurrentIndex(self.input.findData(input_id));self.input.blockSignals(False)
            self.input.setEnabled(not self.read_only);self.more_inputs.setEnabled(not self.read_only)
            self.blocked_reason=choice['selection_error'];self.dirty=True
            self.clear_results();self.update_context();self.note.setText(self.blocked_reason)
            return
        self.clear_cards()
        group = page.get('selected_group') or next((g for g in groups if g.get('variant_id') == variant), {})
        self.sync_family_controls(group or catalog.get(variant,{}))
        self.populate_inputs();self.update_context()
        if self.page!='basis' and group.get('family_id') in ('B09','B11'):
            self.heading.setText(family_title(group))
        if self.page!='basis':
            self.construction.setText('合约对构造：'+construction_label(group.get('pair_construction')))
            self.construction.setToolTip(text(group.get('explanation')))
        entities = page.get('entities') or group.get('entities') or []
        self.entities = entities
        self.card_metrics=[]
        for index, entity in enumerate(entities):
            metric = primary_metric(entity,group,self.page)
            expiry_note = ' · 异期参考' if self.page == 'cross' and entity.get('expiry_type') == 'mixed' else ''
            card = Panel(); card.layout.setContentsMargins(12, 10, 12, 10)
            card.setMinimumHeight(156)
            name = QLabel(entity.get('title') or entity.get('entity_id') or '无代表')
            name.setWordWrap(True); name.setStyleSheet('font-size:16px;font-weight:600'); card.layout.addWidget(name)
            value = QLabel(number(metric.get('value')) + ' ' + metric.get('unit', group.get('unit', '')))
            value.setObjectName('researchValue')
            value.setStyleSheet('font-size:30px;font-weight:600'); card.layout.addWidget(value)
            state=STATUS_TITLES.get(metric.get('data_status'),metric.get('data_status')) or '状态待核验'
            pair_intraday_family=self.page!='basis' and group.get('family_id') in ('B09','B11')
            detail = QLabel(state+expiry_note+'  ·  n = '+text(metric.get('n'))+'\n源时 '+stamp(metric.get('time'), not pair_intraday_family))
            detail.setWordWrap(True); detail.setStyleSheet(f'font-size:14px;color:{MUTED};'); card.layout.addWidget(detail)
            if pair_intraday_family and metric.get('scope'):
                scope_label=QLabel(str(metric['scope']));scope_label.setWordWrap(True)
                scope_label.setObjectName('researchScope');scope_label.setStyleSheet(f'font-size:13px;color:{MUTED};')
                card.layout.addWidget(scope_label)
            if metric.get('value') is None:
                missing=QLabel(metric.get('reason') or '缺少对应输入，结果留空');missing.setWordWrap(True)
                missing.setStyleSheet(f'font-size:13px;color:{ACCENT};');card.layout.addWidget(missing)
            elif pair_intraday_family and self.timing.currentData()=='intraday' and metric.get('data_status')!='intraday_estimate':
                reason=QLabel('盘中条件未满足：'+str(metric.get('reason') or '未提供有效盘中结果；按所列日期显示日终参考'))
                reason.setObjectName('researchFallbackReason');reason.setWordWrap(True)
                reason.setStyleSheet(f'font-size:13px;color:{ACCENT};');card.layout.addWidget(reason)
            link=QPushButton('图表与详情 →');link.setStyleSheet('font-size:13px;padding:4px 8px;')
            link.clicked.connect(lambda _checked=False,identity=entity.get('entity_id'):self.show_entity(identity))
            card.layout.addWidget(link,0,Qt.AlignmentFlag.AlignRight)
            card.setToolTip(text(entity.get('selection_reason')) + '\n' + text(metric.get('source_times')) + '\n' + text(metric.get('reason')) + '\n' + text(metric.get('visibility_status')))
            # Four or six representative cards; bounded detail pages can have
            # twenty rows and stay in the table below rather than twenty charts.
            if index < (6 if self.page == 'cross' else 4):
                columns = 3 if self.page == 'cross' else 2
                self.card_grid.addWidget(card, index // columns, index % columns); self.cards.append(card);self.card_metrics.append(metric)
            else:
                card.deleteLater()
        rows = [(entity, metric) for entity in entities for metric in entity.get('metrics', [])]
        self.table.setRowCount(len(rows)); self.table_rows = rows
        for row_index, (entity, metric) in enumerate(rows):
            values = [entity.get('entity_id') or text([entity.get('left'), entity.get('right')]),
                metric.get('id') or variant, number(metric.get('value'), 5), metric.get('unit'),
                metric.get('source_times'), metric.get('history_cutoff'), metric.get('n'),
                STATUS_TITLES.get(metric.get('implementation_status'),metric.get('implementation_status')),
                STATUS_TITLES.get(metric.get('data_status'),metric.get('data_status')),
                (entity.get('selection_type') or '') + (' · 异期参考' if self.page == 'cross' and entity.get('expiry_type') == 'mixed' else ''), metric.get('reason'),
                {'inputs': metric.get('input_versions'), 'formula': metric.get('formula_version')}]
            for column, value in enumerate(values):
                item = QTableWidgetItem(text(value)); item.setToolTip(text(value)); self.table.setItem(row_index, column, item)
        self.fill_role_tables(group)
        self.offset = int(page.get('offset', choice.get('offset', 0)))
        total = int(page.get('total', len(entities)))
        self.page_note.setText(f'{self.offset + 1 if entities else 0}–{self.offset + len(entities)} / {total} 个实体')
        self.previous.setEnabled(not self.read_only and self.scope.currentData() != 'representatives' and self.offset > 0)
        self.next.setEnabled(not self.read_only and self.scope.currentData() != 'representatives' and self.offset + len(entities) < total)
        expanded=self.scope.currentData()!='representatives'
        self.previous.setVisible(expanded);self.next.setVisible(expanded);self.representatives.setVisible(expanded)
        self.expand.setVisible(not expanded)
        fixed_note='固定口径 · 不随输入 X 改变。 ' if group.get('input_id')=='fixed' else ''
        if self.page!='basis':fixed_note+='主卡与主图展示合约对自身；原单腿比较在辅助解释中。 '
        missing_count=sum(primary_metric(entity,group,self.page).get('value') is None for entity in entities)
        summary=(f'{missing_count} 个实体缺少有效输入，原因见卡片。' if missing_count else '已加载；源时、有效 n 见卡片。')
        self.note.setText(text(research.get('error') or page.get('selection_error') or fixed_note+summary))
        self.note.setToolTip(text(page.get('selection_status')))
        if rows:
            selected_row = next((index for index, (entity, metric) in enumerate(rows)
                if (entity.get('entity_id'), metric.get('id')) == old_identity), 0)
            self.table.selectRow(selected_row)
            self.draw_entity()
            self.table.verticalScrollBar().setValue(scroll_position[0])
            self.table.horizontalScrollBar().setValue(scroll_position[1])
        else:
            self.formula.setPlainText(text(catalog.get(variant, {})))

    def draw_entity(self):
        row = self.table.currentRow()
        if row < 0 or row >= len(getattr(self, 'table_rows', [])):
            return
        entity, metric = self.table_rows[row]
        group = self.catalogue.get(self.choice().get('variant_id'), {})
        chart_metric = metric if self.page=='basis' else primary_metric(entity,group,self.page)
        self.chart_metric=chart_metric
        if self.page!='basis':
            for role,table in (('primary',self.primary_table),('auxiliary',self.auxiliary_table)):
                role_rows=getattr(self,role+'_rows',[])
                wanted=chart_metric if role=='primary' else metric
                selected=next((index for index,(candidate,value) in enumerate(role_rows)
                    if candidate.get('entity_id')==entity.get('entity_id') and value.get('id')==wanted.get('id')), -1)
                table.blockSignals(True)
                if selected>=0:table.selectRow(selected)
                else:table.clearSelection()
                table.blockSignals(False)
        pair_intraday=(self.page!='basis' and group.get('family_id') in ('B09','B11')
            and chart_metric.get('data_status')=='intraday_estimate')
        history = chart_metric.get('history') or []
        if pair_intraday:
            history=chart_metric.get('current_history') or []
            if not history and chart_metric.get('time') and chart_metric.get('value') is not None:
                history=[{'time':chart_metric['time'],'value':chart_metric['value']}]
        self.chart_history=history
        xs = [pd.Timestamp(point['time']).timestamp() for point in history]
        ys = [point.get('value') if point.get('value') is not None else float('nan') for point in history]
        self.chart.title_label.setText(('合约对主指标 · ' if self.page!='basis' else '')+
            (entity.get('title') or entity.get('entity_id') or '固定实体历史'))
        self.chart.plot.setLabel('left', chart_metric.get('unit', ''))
        frequency = ('1s' if any(0 < b-a < 60 for a,b in zip(xs,xs[1:])) else
            '1m' if pair_intraday or any(0 < b-a < 3600 for a,b in zip(xs,xs[1:])) else '1d')
        chart_note=('合约对自身序列；辅助单腿比较不进入主图。' if self.page!='basis' else '固定实体独立历史；缺失值保留缺口。')
        if pair_intraday:
            chart_note=str(chart_metric.get('scope') or '盘中合约对观测')+'；'+('仅当前观测点，未提供连续盘中轨迹。' if len(history)==1 else '仅展示本盘中分支提供的观测轨迹。')
            observation=chart_metric.get('pair_intraday') or {}
            if chart_metric.get('id')=='B09.same_time' and observation.get('boundary'):
                chart_note+=' 同刻边界 '+stamp(observation['boundary'])[11:]+'。'
            elif observation.get('segment_start') and observation.get('segment_end'):
                chart_note+=' 采集 '+stamp(observation['segment_start'])[11:]+'–'+stamp(observation['segment_end'])[11:]+'。'
        elif self.page!='basis' and group.get('family_id') in ('B09','B11'):
            chart_note='日终参考历史 · '+str(chart_metric.get('scope') or '完整交易日口径')
        self.chart.draw([(chart_metric.get('title', ''), xs, ys)] if history else [],
            key=(entity.get('entity_id'), chart_metric.get('id'), chart_metric.get('variant_id'), chart_metric.get('formula_version'), chart_metric.get('time')),
            frequency=frequency,
            note=chart_note if history else '该主指标未提供可用历史序列。')
        for line in self.chart.lines.values():line.setSymbol('o' if len(history)==1 else None)
        details = {**group, **metric, 'entity': entity.get('entity_id'),
                   'selection_reason': entity.get('selection_reason'),
                   'expiry_type': entity.get('expiry_type'), 'expiry_dates': entity.get('expiry_dates')}
        details.pop('history', None)
        details.pop('entities', None)
        formula = metric.get('formula') or group.get('formula')
        if not formula and self.page=='basis':
            try:
                from .indicator_help import explain_metric
                help_row = {**metric, 'id': metric.get('id') or group.get('primary'),
                            'title': metric.get('title') or group.get('title', ''), 'unit': metric.get('unit', '')}
                details['explanation'] = explain_metric(help_row, self.page, group.get('input_id', 'basis'))
                formula = details['explanation'].get('formula')
            except (KeyError, TypeError, ValueError):
                pass
        if self.page!='basis':
            main=chart_metric
            construction=main.get('pair_construction') or entity.get('pair_construction') or group.get('pair_construction')
            metadata={}
            for source in (group,entity,main):
                if isinstance(source.get('pair_metadata'),dict):metadata.update(source['pair_metadata'])
            if group.get('input_id')=='fixed':
                # Quantity/hedge families do not inherit the fallback basis X
                # construction used when assembling common pair metadata.
                metadata['construction']=main.get('formula') or construction
                metadata['unit']=main.get('unit')
            explanation=main.get('explanation') or group.get('explanation') or main.get('meaning') or '共享契约尚未提供含义说明。'
            direction=main.get('direction') or group.get('direction') or '见双腿构造。'
            limitations=main.get('limitations') or group.get('limitations') or '共享契约尚未提供限制说明；数据可用性见状态与原因。'
            role=metric_role(metric,group,self.page)
            summary='<h2>合约对主指标 · '+escape(main.get('title') or family_title(group))+'</h2>'
            summary+='<p><b>具体双腿：</b>A = '+escape(text(entity.get('left')))+'；B = '+escape(text(entity.get('right')))+'</p>'
            summary+='<p><b>双腿构造：</b>'+escape(construction_label(construction))+'</p>'
            summary+='<p><b>含义：</b>'+escape(text(explanation))+'</p>'
            summary+='<p><b>方向：</b>'+escape(text(direction))+'　<b>单位：</b>'+escape(text(main.get('unit')))+'</p>'
            summary+='<p><b>观测口径：</b>'+escape(text(main.get('scope') or STATUS_TITLES.get(main.get('data_status'),main.get('data_status'))))+'</p>'
            summary+='<p><b>数值源时：</b>'+escape(stamp(main.get('time'),True))+'　<b>状态：</b>'+escape(STATUS_TITLES.get(main.get('data_status'),main.get('data_status')) or '—')+'</p>'
            if main.get('reason'):summary+='<p><b>数据条件：</b>'+escape(text(main['reason']))+'</p>'
            summary+='<p><b>限制：</b>'+escape(text(limitations))+'</p>'
            summary+='<p><b>主公式：</b>'+escape(text(main.get('formula') or '共享结果尚未提供公式。'))+'</p>'
            summary+='<p><b>公式版本：</b>'+escape(text(main.get('formula_version') or group.get('formula_version')))+'</p>'
            if metadata:summary+='<h3>双腿、h、权重与同步规则</h3>'+construction_html(metadata)
            if isinstance(main.get('pair_intraday'),dict):
                summary+='<h3>盘中观测与历史基准</h3>'+construction_html(main['pair_intraday'])
            components=[value for value in entity.get('metrics',[]) if '.pair.' in value.get('id','')]
            if components:
                summary+='<h3>本合约对的构造分量</h3><p>各分量按自身源时列示，缺值保留为空；量与持仓为匹配容量代理。</p><table>'
                summary+='<tr><th align="left">分量</th><th align="left">数值 / 单位</th><th align="left">源时</th></tr>'
                for component in components:
                    summary+='<tr><td style="padding:5px 18px 5px 0">'+escape(component.get('title') or component.get('id') or '')+'</td>'
                    summary+='<td style="padding:5px 18px 5px 0">'+escape(number(component.get('value'),5)+' '+text(component.get('unit')))+'</td>'
                    summary+='<td>'+escape(stamp(component.get('time'),True))+'</td></tr>'
                summary+='</table>'
            summary+='<p><b>各腿源时：</b>'+escape(text(main.get('source_times')))+'</p>'
            if role=='auxiliary':
                auxiliary_label='原单腿比较'
                if group.get('family_id') in ('B09','B11'):
                    auxiliary_label=('日终参考' if metric.get('id') in ('B09','B11') else
                        '盘中分支' if metric.get('id') in ('B09.same_time','B11.sample') else '原单腿比较与构造分量')
                summary+='<hr><h3>辅助解释 · '+auxiliary_label+'</h3><p>'+escape(metric.get('title') or metric.get('id') or '')+'</p>'
                summary+='<p>用于解释双腿，不替代合约对主指标或主图。</p><p>'+escape(text(metric.get('explanation') or metric.get('meaning') or ''))+'</p>'
                summary+='<p><b>辅助公式：</b>'+escape(text(formula or '见完整契约'))+'</p>'
                summary+='<p><b>辅助版本：</b>'+escape(text(metric.get('formula_version')))+'</p>'
            summary+='<h3>完整契约与缺失原因</h3><pre style="white-space:pre-wrap;font-size:14px">'+escape(json.dumps(details,ensure_ascii=False,indent=2,default=str))+'</pre>'
            self.formula.setHtml(summary)
            return
        self.formula.setHtml('<h2>' + escape(metric.get('title') or group.get('title', '公式与输入')) +
            '</h2><p style="font-size:20px">' + escape(formula or '见输入契约与缺失原因') +
            '</p><p>' + escape(metric.get('meaning') or '') +
            '</p><pre style="white-space:pre-wrap;font-size:14px">' +
            escape(json.dumps(details, ensure_ascii=False, indent=2, default=str)) + '</pre>')


def add_research_pages(window, tabs, on_change):
    if not getattr(window,'frozen_payload',None) or window.frozen_payload.get('research_v6'):
        from .research_v6_view import add_pages
        return add_pages(window,tabs)
    window.research_pages = {}
    for key, title in PAGE_TITLES.items():
        page = ResearchPage(key); window.research_pages[key] = page
        tabs.addTab(page, title); page.changed.connect(on_change)
    return window.research_pages


def active_selection(window):
    current = window.pages.currentWidget()
    if isinstance(current, ResearchPage):
        selection = current.request()
        return selection or {'page': current.page, 'request_id': uuid.uuid4().hex}
    # Keep the most recent researched page when the user returns to overview.
    for page in window.research_pages.values():
        if page.selection:
            return page.selection
    return None


def render_pages(window, research):
    for page in window.research_pages.values():
        page.render(research)
    if getattr(window,'state',None) is not None and getattr(window.model,'indicator_v6_active',False):
        window.state['research_v6']={key:page.result for key,page in window.research_pages.items() if page.result}
