"""Presentation-only research selectors shared by Excel and the local Apps.

Resolve an explicit family and X to a registered identity. These helpers never
calculate indicators or invent a fallback formula for an unavailable input.
"""
from copy import deepcopy

from dashboard.indicator_catalog import INPUTS, PAGES, catalog, find_variant
from dashboard.pair_catalog import INPUT_LABELS as PAIR_INPUT_LABELS

PRIMARY_INPUTS = ('future', 'basis', 'annual')
INPUT_LABELS = {
    'future': '期货收盘价 close',
    'basis': '分红调整基差（bp）',
    'annual': '分红调整基差年化',
    'raw_basis': '未调整普通基差（bp）',
    'log_basis': '未调整对数基差（bp）',
    'raw_annual': '未调整简单年化',
    'log_annual': '未调整对数年化',
    'fixed': '固定口径（不随 X 改变）',
}
FIXED_NOTE = '固定口径 · 不随输入 X 改变'
CROSS_PRICE_NOTE = '跨品种 close 构造为10000×ln(F_A/F_B)，单位对数bp；是相对价格序列，不是回归残差或实际组合盈亏。'


def input_label(input_id, timing='日终', page=None):
    if page in PAIR_INPUT_LABELS and input_id in PAIR_INPUT_LABELS[page]:
        label=PAIR_INPUT_LABELS[page][input_id]
        return label+'（盘中使用同步最新价）' if input_id=='future' and timing in ('盘中优先','intraday') else label
    if input_id == 'future' and timing in ('盘中优先', 'intraday'):
        return '期货最新价（盘中）/收盘价 close（日终）'
    return INPUT_LABELS.get(input_id, str(input_id or '未选择输入'))


def input_options(page, include_advanced=True):
    return [dict(input_id=key, label=input_label(key,page=page), legacy_labels=[input_label(key)], advanced=key not in PRIMARY_INPUTS)
            for key in INPUTS if (include_advanced or key in PRIMARY_INPUTS)
            ]


def family_title(group_or_family_id):
    entry = group_or_family_id
    if not isinstance(entry, dict):
        entry = find_variant(family_id=entry)
    if not entry:
        return str(group_or_family_id or '未选择指标')
    title = entry['title']
    return title.split(' · ', 1)[-1] if entry['input_id'] != 'fixed' else title


def families(page):
    result = {}
    for entry in catalog(page):
        key = entry['family_id']
        if key not in result:
            title = family_title(entry)
            result[key] = dict(family_id=key, title=title, label=title,
                               legacy_labels=[entry.get('legacy_title',title).split(' · ',1)[-1]],
                               input_ids=[], fixed=entry['input_id'] == 'fixed')
        result[key]['input_ids'].append(entry['input_id'])
    return list(result.values())


def _family_id(page, value):
    for entry in families(page):
        if value in (entry['family_id'], entry['title'], entry['label'], *entry.get('legacy_labels',[])):
            return entry['family_id']
    return value


def _input_id(value):
    for key, label in INPUT_LABELS.items():
        aliases=[input_label(key,timing,page) for page in PAGES for timing in ('日终','盘中优先')]
        if value in (key, label, input_label(key, '盘中优先'), *aliases):
            return key
    # The pre-simplification watchlist used these public names.
    return {'期货价': 'future', '基差bp': 'basis', '年化': 'annual'}.get(value, value)


def resolve_variant(page, family_id, input_id):
    """Return (registered entry or None, explanatory note), with no fallback."""
    if page not in PAGES:
        return None, '未识别的研究类别'
    family_id = _family_id(page, family_id)
    input_id = _input_id(input_id)
    choices = [entry for entry in catalog(page) if entry['family_id'] == family_id]
    if not choices:
        return None, '该指标不适用于当前研究类别，请选择其他指标。'
    if len(choices) == 1 and choices[0]['input_id'] == 'fixed':
        return choices[0], FIXED_NOTE
    match = next((entry for entry in choices if entry['input_id'] == input_id), None)
    if match is not None:
        return match, ''
    available = '、'.join(input_label(entry['input_id'],page=page) for entry in choices)
    return None, '当前指标不适用此输入；可选：' + available


def selection_from_controls(page, family, input_id, previous=None):
    """Map Chinese controls or legacy B3 identity, retaining saved contracts.

    An invalid combination explicitly removes the previous identity. Callers
    show selection_error and refrain from requesting/rendering its old values.
    """
    result = deepcopy(previous or {})
    legacy = find_variant(family, category=page) if family and '::' in family else None
    if legacy:
        family = legacy['family_id']
        if not input_id:
            input_id = legacy['input_id']
    if not family:
        family = result.get('family_id')
        old = find_variant(result.get('variant_id'), category=page) if result.get('variant_id') else None
        if old and not family:
            family = old['family_id']
        if not input_id:
            input_id = result.get('input') or (old or {}).get('input_id')
    family = _family_id(page, family or 'A03.percentile')
    requested_input = _input_id(input_id or 'basis')
    entry, note = resolve_variant(page, family, requested_input)
    result.update(family_id=family, input=requested_input,
                  variant_id=entry['variant_id'] if entry else None)
    if entry:
        result['input'] = entry['input_id']
        result.pop('selection_error', None)
    else:
        result['selection_error'] = note
    if previous and result.get('variant_id') != previous.get('variant_id'):
        result['offset'] = 0
    return result


def ui_controls(page):
    """Serializable selector metadata; the registry remains authoritative."""
    return dict(page=page, families=families(page), inputs=input_options(page),
                variants=[dict(family_id=e['family_id'], variant_id=e['variant_id'],
                               input_id=e['input_id'], family_label=family_title(e),
                               input_label=input_label(e['input_id'],page=page),
                               **{k:e.get(k,'') for k in ('title','pair_construction','formula_version','metric_roles','explanation','direction','limitations','daily_primary','intraday_primary','intraday_definition')}) for e in catalog(page)],
                cross_price_note=CROSS_PRICE_NOTE if page == 'cross' else '')
