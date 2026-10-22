"""The user-defined five-to-three option-sector rollup, from saved Excel values."""
from decimal import Decimal, InvalidOperation
import re
import unicodedata

from .storage import ReportError

SECTORS = {'TMT': ('TMT',), '消费': ('消费', '周期-消费代管'), '周期': ('周期', '周期-其他')}
PARTS = {name for parts in SECTORS.values() for name in parts}


def normalized_name(value):
    text = unicodedata.normalize('NFKC', str(value or '')).upper()
    return re.sub(r'\s+', '', re.sub('[‐‑‒–—−]', '-', text))


def amount(value, context):
    try:
        if value is None or isinstance(value, bool):
            raise ValueError()
        result = Decimal(str(value).strip().replace(',', ''))
        if not result.is_finite():
            raise ValueError()
        return result
    except (ValueError, InvalidOperation):
        raise ReportError(f'{context}数值缓存缺失或无效，未按零处理。') from None


def option_sectors(ws, grid, name_col, value_col):
    """Only accept exact sector names within the unique option desk's own block."""
    lookup = dict(zip(grid['source_rows'], grid['rows']))
    merges = list(ws.merged_cells.ranges)
    def name_cell(row):
        cell = ws.cell(row, name_col)
        merged = next((m for m in merges if cell.coordinate in m), None)
        if merged:
            return ws.cell(merged.min_row, merged.min_col), merged
        return cell, None
    parents = [r for r in grid['source_rows']
               if r > (grid['header_row'] or 5) and normalized_name(name_cell(r)[0].value) == '境内个股期权台'
               and (name_cell(r)[1] is None or name_cell(r)[1].min_row == r)]
    if not parents:
        return None
    if len(parents) != 1:
        raise ReportError('境内个股期权台不是唯一一行，无法确定TMT/消费/周期范围。')
    parent = parents[0]
    parent_cell, parent_merge = name_cell(parent)
    level = (parent_cell.alignment.indent or 0, ws.row_dimensions[parent].outlineLevel)
    found = {}
    for row in range(parent + 1, max(grid['source_rows']) + 1):
        cells = [ws.cell(row, col) for col in range(1, len(grid['columns']) + 1)]
        matches = [c for c in cells if normalized_name(c.value) in PARTS]
        cell, merged = name_cell(row)
        label = normalized_name(cell.value)
        if not matches:
            if (label and not label.startswith(('注', '说明', '单位'))
                    and not (merged and merged.min_row < row)
                    and (cell.font.bold and (cell.alignment.indent or 0, ws.row_dimensions[row].outlineLevel) == level
                         or label == '场外业务合计')):
                break
            continue
        if parent_merge and parent_merge.max_row > parent and row > parent_merge.max_row:
            break
        if len(matches) != 1:
            raise ReportError(f'第{row}行存在多个行业标签，无法确定唯一来源。')
        key = normalized_name(matches[0].value)
        if key in found:
            raise ReportError(f'境内个股期权台内“{key}”重复，未重复汇总。')
        amount(ws.cell(row, value_col).value, f'第{row}行{key}净利润')
        found[key] = (row, matches[0].column)
    missing = PARTS - found.keys()
    if missing:
        raise ReportError('境内个股期权台缺少原始行业行：' + '、'.join(sorted(missing)))
    headers = lookup[grid['header_row'] or 5] if (grid['header_row'] or 5) in lookup else []
    entries, notes = [], []
    for name, parts in SECTORS.items():
        sources = [found[p][0] for p in parts]
        values = list(lookup[sources[0]])
        if len(sources) > 1:
            for col in range(len(values)):
                raw = [lookup[r][col] for r in sources]
                if col + 1 == name_col or any(col + 1 == found[p][1] for p in parts):
                    values[col] = None
                    continue
                if all(v in (None, '') for v in raw):
                    values[col] = None
                elif col < len(headers) and any(word in str(headers[col]) for word in ('比例', '收益率', '利润率')):
                    values[col] = '—'
                else:
                    try:
                        values[col] = str(sum((amount(v, f'第{sources}行') for v in raw), Decimal(0)))
                    except ReportError:
                        values[col] = raw[0] if all(v == raw[0] for v in raw) else None
                        if any(v in (None, '') for v in raw):
                            notes.append(f'{name}原行{sources}第{col + 1}列缓存不全，合并值留空。')
        for _, label_col in (found[p] for p in parts):
            values[label_col - 1] = None
        values[name_col - 1] = name
        entries.append({'name': name, 'row': sources[0], 'source_rows': sources, 'values': values,
                        'value': str(sum((amount(ws.cell(r, value_col).value, f'第{r}行净利润') for r in sources), Decimal(0)))})
    return {'parent': parent, 'child_rows': {r for r, _ in found.values()}, 'entries': entries, 'notes': notes}
