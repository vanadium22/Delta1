"""Versioned Excel exchange format for the desktop App."""
from collections import defaultdict
from datetime import datetime, time
from decimal import Decimal
from math import isfinite
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from unicodedata import east_asian_width

from .excel import Preview
from .model import LEGS, NUMBERS, code, group_config, number, trade_data


ABOUT = '台账说明'
IDENTITY = '基差交易台账 · Excel 交换'
VERSION = 1
GROUP = (('group', '组编号'), ('name', '组名'), ('opened', '开组日期'), ('etf', 'ETF 代码'),
         ('futures', '期货合约'), ('multiplier', '合约乘数'), ('index', '跟踪指数'),
         ('base_shares', '参考底仓（份）'), ('plan_lots', '计划手数'))
TRADE = (('group', '组编号'), ('order', '组内顺序'), ('time', '成交时间'), ('direction', '方向'), ('status', '状态'),
         ('shares', 'ETF 份额'), ('etf_input', 'ETF 输入方式'), ('etf_price', 'ETF 均价（元）'), ('amount', 'ETF 金额（元）'),
         ('lots', '期货手数'), ('futures_price', '期货均价（点）'), ('fee', '费用（元）'), ('note', '备注'),
         ('origin', '原成交来源'), ('entry_type', '原记录类型'), ('source_status', '原配对状态'), ('pair', '原配对编号'),
         ('pair_lots', '原配对手数'), ('version', '版本'), ('updated', '保存时间'))
MARK = (('group', '组编号'), ('code', '标的代码'), ('price', '估值价'), ('kind', '价格类型'),
        ('source', '价格来源'), ('time', '价格时间'), ('imported', '快照读取时间'))
HISTORY = (*TRADE, ('reason', '更正原因'))
SHEETS = {'交易组': GROUP, '成交流水': TRADE, '估值快照': MARK, '更正记录': HISTORY}
STATES = {'已入账': 'posted', '草稿': 'draft'}
MODES = {'均价': 'etf_price', '金额': 'amount'}
KINDS = {'手填': 'manual', '本地收盘': 'local', '导入快照': 'excel'}
MARK_NAMES = {v: k for k, v in KINDS.items()}


def is_exchange(workbook):
    return (ABOUT in workbook and workbook[ABOUT]['A1'].value == IDENTITY) or (
        '交易组' in workbook and '成交流水' in workbook and workbook['交易组']['A1'].value == '组编号')


def _rows(workbook, title, *, required=True):
    if title not in workbook and not required:
        return
    if title not in workbook:
        raise ValueError(f'规范工作簿缺少「{title}」')
    layout = SHEETS[title]
    sheet = workbook[title]
    expected = tuple(caption for _, caption in layout)
    iterator = sheet.iter_rows(max_col=len(layout), values_only=True)
    if tuple(next(iterator, ())) != expected:
        raise ValueError(f'「{title}」表头与当前模板不一致')
    for line, values in enumerate(iterator, 2):
        if any(value not in (None, '') for value in values):
            yield f'{title}!{line}', dict(zip((key for key, _ in layout), values))


def _text(value):
    return str(value).strip() if value is not None else ''


def _sequence(value, title):
    result = number(value, title, integer=True)
    if result is None or result > 1_048_575:
        raise ValueError(f'{title}需为有效正整数')
    return int(result)


def _price_time(value):
    if not value:
        return None
    raw = str(value)
    if ':' in raw and '-' not in raw[:10] and 'T' not in raw:
        return time.fromisoformat(raw).isoformat(timespec='seconds')
    parsed = datetime.fromisoformat(raw)
    return raw if len(raw) == 10 else parsed.isoformat(sep=' ', timespec='seconds')


def _decode_trade(values, source):
    status = STATES.get(_text(values['status']))
    mode = _text(values['etf_input'])
    data = dict(values, direction=_text(values['direction']))
    if mode:
        if mode not in MODES:
            raise ValueError('ETF 输入方式使用“均价”或“金额”')
        data['etf_input'] = MODES[mode]
    else:
        if values['etf_price'] not in (None, '') and values['amount'] not in (None, ''):
            raise ValueError('同时填写 ETF 均价和金额时，请标明 ETF 输入方式')
        data.pop('etf_input')
    trade = trade_data(data, status)
    for key in ('origin', 'entry_type', 'source_status', 'pair'):
        if values[key]:
            trade[key] = _text(values[key])
    pair_lots = number(values['pair_lots'], '原配对手数', integer=True)
    if trade.get('pair') and pair_lots is None:
        raise ValueError('原配对编号与原配对手数须同时填写')
    if pair_lots is not None:
        trade['pair_lots'] = pair_lots
    trade['origin'] = trade.get('origin') or source
    trade['import_origin'] = source
    trade['version'] = _sequence(values['version'], '版本') if values['version'] not in (None, '') else 1
    trade['updated'] = _price_time(values['updated'])
    return trade


def parse_exchange(workbook, name, digest, imported):
    if ABOUT not in workbook or workbook[ABOUT]['A1'].value != IDENTITY or str(workbook[ABOUT]['B2'].value) != str(VERSION):
        raise ValueError('规范工作簿版本无法识别，请使用台账导出的模板')
    groups, entries, marks, history = {}, defaultdict(dict), defaultdict(dict), defaultdict(lambda: defaultdict(dict))
    source = ABOUT
    try:
        for source, values in _rows(workbook, '交易组'):
            key = _text(values['group'])
            if not key or key in groups:
                raise ValueError('组编号不能为空，且每组只能定义一次')
            if isinstance(values['opened'], datetime):
                values['opened'] = values['opened'].date()
            groups[key] = (group_config(values), source)
        for sheet in ('成交流水', '更正记录', '估值快照'):
            for source, values in _rows(workbook, sheet, required=sheet == '成交流水'):
                key = _text(values['group'])
                if key not in groups:
                    raise ValueError('组编号未出现在「交易组」中')
                if sheet == '估值快照':
                    cfg = groups[key][0]
                    symbol = code(values['code'])
                    kind = KINDS.get(_text(values['kind']) or '导入快照')
                    price = number(values['price'], '估值价')
                    if not kind or not symbol or symbol not in {cfg[leg] for leg in LEGS} or price is None:
                        raise ValueError('价格类型、代码或估值价无效')
                    if (symbol, kind) in marks[key]:
                        raise ValueError('同组的标的代码和价格类型重复')
                    marks[key][(symbol, kind)] = dict(code=symbol, kind=kind, price=price,
                        source=_text(values['source']) or f'Excel · {source}', time=_price_time(values['time']),
                        imported=_price_time(values['imported']) or imported)
                    continue
                order = _sequence(values['order'], '组内顺序')
                trade = _decode_trade(values, source)
                if sheet == '成交流水':
                    if order in entries[key]:
                        raise ValueError('组内顺序重复')
                    entries[key][order] = trade
                else:
                    current = entries[key].get(order)
                    version = trade['version']
                    reason = _text(values['reason'])
                    if (not current or version >= current['version'] or version in history[key][order]
                            or not reason or not trade['updated'] or trade['status'] != 'posted'):
                        raise ValueError('更正记录须引用现有交易的较早已入账版本，并提供保存时间和更正原因')
                    history[key][order][version] = dict(trade, reason=reason)
    except (TypeError, ValueError) as exc:
        raise ValueError(f'{source} · {exc}') from exc

    result = []
    for key, (cfg, source) in groups.items():
        ordered = sorted(entries[key])
        trades = [entries[key][order] for order in ordered]
        revisions = {position: [r for _, r in sorted(history[key][order].items())]
                     for position, order in enumerate(ordered, 1) if history[key].get(order)}
        quotes = {}
        for leg in LEGS:
            quote = next((marks[key][(cfg[leg], kind)] for kind in ('manual', 'local', 'excel')
                          if (cfg[leg], kind) in marks[key]), None)
            if quote:
                quotes[leg] = quote
        warnings = [f"待核配对 · {trade['origin']}" for trade in trades if trade.get('source_status') == '待核配对']
        audit = dict(file=name, sheet=source, digest=digest, imported=imported, differences=[], legacy=[], warnings=warnings)
        result.append(Preview(f'{digest}:exchange:{key}', cfg, trades, quotes, audit, list(marks[key].values()), revisions))
    return result


def _rows_for_export(groups):
    result = {sheet: [] for sheet in SHEETS}
    for group in groups:
        key = f"G{group['id']}"
        result['交易组'].append(dict(group['config'], group=key))
        order_map = {}
        for order, trade in enumerate(group['trades'], 1):
            order_map[trade['id']] = order
            result['成交流水'].append(_encode_trade(trade, key, order))
        for mark in group['marks']:
            result['估值快照'].append(dict(mark, group=key, kind=MARK_NAMES[mark['kind']]))
        for revision in group['revisions']:
            result['更正记录'].append(_encode_trade(revision, key, order_map[revision['id']]))
    return result


def _encode_trade(trade, group, order):
    return dict(trade, group=group, order=order, etf_input='金额' if trade.get('etf_input') == 'amount' else '均价',
                status='草稿' if trade['status'] == 'draft' else '已入账')


def _write_cell(cell, key, value):
    if value is None or value == '':
        return
    if key in {*NUMBERS, 'multiplier', 'base_shares', 'plan_lots', 'price', 'order', 'version', 'pair_lots'}:
        decimal = Decimal(str(value))
        if decimal == decimal.to_integral_value() and abs(decimal) < 10**15:
            cell.value = int(decimal)
            return
        candidate = float(decimal)
        if isfinite(candidate) and len(decimal.normalize().as_tuple().digits) <= 15:
            cell.value = candidate
            cell.number_format = '#,##0.00########'
            return
    cell.value = str(value)
    cell.data_type = 's'


def export_exchange(path, groups):
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    workbook = Workbook()
    about = workbook.active
    about.title = ABOUT
    about.append([IDENTITY])
    about.append(['版本', VERSION])
    about.append(['录入顺序', '先填交易组，再用同一组编号填写成交流水。组内顺序决定核算次序。'])
    about.append(['方向', '买基差、卖基差、ETF买入、ETF卖出、期货买入、期货卖出。'])
    about.append(['状态与时间', '使用已入账或草稿。成交时间可留空，日期时间格式为 YYYY-MM-DD HH:MM。'])
    about.append(['ETF 输入', '方式填均价或金额，按所选字段重算另一项，填入有效份额。'])
    about.append(['估值', '同组同代码可各有手填、本地收盘和导入快照。可只填写导入快照。'])
    about.append(['版本更正', '保留导出记录的版本号。新增流水可将版本和保存时间留空。'])
    about.append(['确认入库', '文件可编辑，导入时先预览与确认。每个组编号会建成单独交易组。'])
    about.column_dimensions['A'].width = 37
    about.column_dimensions['B'].width = 89
    about['A1'].font = Font(bold=True, size=17, color='17364D')
    about.row_dimensions[1].height = 26
    records = _rows_for_export(groups)
    for sheet, layout in SHEETS.items():
        tab = workbook.create_sheet(sheet)
        tab.append([caption for _, caption in layout])
        for index, (key, caption) in enumerate(layout, 1):
            cell = tab.cell(1, index)
            cell.fill = PatternFill('solid', fgColor='17364D')
            cell.font = Font(color='FFFFFF', bold=True)
            cell.alignment = Alignment(vertical='center')
            base_width = (38 if key in {'updated', 'time', 'imported'} else
                          35 if key in {'etf_price', 'amount'} else
                          31 if key in {'origin', 'note', 'source', 'name', 'reason', 'pair'} else 18)
            heading_width = sum(2 if east_asian_width(ch) in {'W', 'F'} else 1 for ch in caption)
            tab.column_dimensions[get_column_letter(index)].width = max(base_width, heading_width + 6)
        tab.row_dimensions[1].height = 24
        for line, row in enumerate(records[sheet], 2):
            for col, (key, _) in enumerate(layout, 1):
                _write_cell(tab.cell(line, col), key, row.get(key))
        tab.freeze_panes = 'B2'
        tab.auto_filter.ref = tab.dimensions

    target = Path(path)
    with NamedTemporaryFile(prefix='.ledger-', suffix='.xlsx', dir=target.parent, delete=False) as handle:
        temporary = Path(handle.name)
    try:
        workbook.save(temporary)
        os.replace(temporary, target)
    finally:
        workbook.close()
        temporary.unlink(missing_ok=True)
