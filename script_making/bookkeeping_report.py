"""Read explicit back-to-back references from a saved report, without inference."""
from __future__ import annotations

import math
import re
import unicodedata
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation, localcontext


REFERENCE_FIELDS = (
    ("关联背靠背合约", "合约编号"),
    ("关联背靠背确认书编号", "交易确认书编号"),
)
EXCEL_ERRORS = {
    "#N/A", "#VALUE!", "#REF!", "#NAME?", "#DIV/0!", "#NUM!", "#NULL!",
    "#SPILL!", "#CALC!", "#GETTING_DATA", "#FIELD!", "#BLOCKED!", "#UNKNOWN!",
}
PLACEHOLDERS = {"N/A", "NA", "NAN", "NONE", "NULL", "无", "暂无", "不适用", "-", "--", "—"}
ZERO_TEXT = re.compile(r"[+-]?0+(?:\.0+)?\Z")


def _identifier(value):
    """Return the exact stripped identifier and why an absent ID is unusable.

    Do not infer a match from counterpart, asset, direction or dates. Leading
    zeros and case are preserved for genuine text identifiers.
    """
    if value is None:
        return None, "empty"
    if isinstance(value, (bool, date, datetime, time)):
        return None, "invalid"
    if isinstance(value, Decimal) and not value.is_finite():
        return None, "invalid"
    if isinstance(value, float) and not math.isfinite(value):
        return None, "invalid"
    if isinstance(value, (int, float, Decimal)) and value == 0:
        return None, "zero"
    text = str(value).strip()
    if not text:
        return None, "empty"
    if text.upper() in EXCEL_ERRORS:
        return None, "excel_error"
    if ZERO_TEXT.fullmatch(text):
        return None, "zero"
    if text.upper() in PLACEHOLDERS:
        return None, "placeholder"
    return text, "value"


def _column_indexes(columns, name):
    return [index for index, column in enumerate(columns) if column.get("name") == name]


def report_backlinks(table: dict, row: dict) -> dict:
    """Find explicit references from one report row in that same report table.

    Each source field is evaluated independently. A unique source/target column
    is required, and only exact identifiers are compared. All matched rows are
    returned because a contract can contain many underlying positions. `no_value`
    means only that no usable reference is present; it does not mean the user
    has confirmed that a back-to-back contract does not exist.
    """
    columns = table.get("columns")
    rows = table.get("rows")
    source_rows = table.get("source_rows")
    values = row.get("values") if isinstance(row, dict) else None
    if (not isinstance(columns, list) or not isinstance(rows, list)
            or not isinstance(source_rows, list) or len(rows) != len(source_rows)
            or not isinstance(values, (list, tuple)) or len(values) != len(columns)):
        raise ValueError("报表字段或所选行不完整，无法查找关联。")

    results = []
    for source_name, target_name in REFERENCE_FIELDS:
        result = {"source_field": source_name, "target_field": target_name,
                  "state": "source_missing", "target_id": None, "matches": [],
                  "source_value_kind": None, "self_reference": False}
        source = _column_indexes(columns, source_name)
        if not source:
            results.append(result)
            continue
        if len(source) != 1:
            result["state"] = "source_ambiguous"
            results.append(result)
            continue
        identifier, kind = _identifier(values[source[0]])
        result["source_value_kind"] = kind
        if identifier is None:
            result["state"] = "no_value"
            results.append(result)
            continue
        result["target_id"] = identifier
        target = _column_indexes(columns, target_name)
        if not target:
            result["state"] = "target_missing"
            results.append(result)
            continue
        if len(target) != 1:
            result["state"] = "target_ambiguous"
            results.append(result)
            continue
        index = target[0]
        result["self_reference"] = _identifier(values[index])[0] == identifier
        for excel_row, candidate in zip(source_rows, rows):
            if len(candidate) != len(columns):
                raise ValueError("报表存在字段不完整的行，无法查找关联。")
            if _identifier(candidate[index])[0] == identifier:
                result["matches"].append({"excel_row": excel_row, "values": list(candidate)})
        result["state"] = "matched" if result["matches"] else "not_found"
        results.append(result)
    return {"fields": results, "columns": columns}


def report_target_candidates(source_table: dict, source_row: dict, target_table: dict) -> dict:
    """Propose exact cross-report targets; callers must let the user choose one."""
    source_columns, target_columns = source_table.get("columns", []), target_table.get("columns", [])
    values = source_row.get("values", [])
    result = {"state": "no_identifier", "source_field": "", "target_field": "",
              "source_id": None, "underlying_hint": "", "underlying_matched": False, "rows": []}
    if len(values) != len(source_columns):
        raise ValueError("所选报表行与字段不匹配。")
    for source_name, target_name in (("合约编号", "合约编号"), ("交易确认书编号", "交易确认书编号"),
                                     ("协议编号", "交易确认书编号")):
        indexes = _column_indexes(source_columns, source_name)
        if len(indexes) > 1:
            result.update(state="source_ambiguous", source_field=source_name)
            return result
        if len(indexes) == 1:
            value, _ = _identifier(values[indexes[0]])
            if value:
                result.update(source_field=source_name, target_field=target_name, source_id=value)
                break
    if not result["source_id"]:
        return result
    target_indexes = _column_indexes(target_columns, result["target_field"])
    if len(target_indexes) != 1:
        result["state"] = "target_missing" if not target_indexes else "target_ambiguous"
        return result
    rows, excel_rows = target_table.get("rows", []), target_table.get("source_rows", [])
    if len(rows) != len(excel_rows):
        raise ValueError("存续合约表的行信息不完整。")
    matched = [{"excel_row": excel_row, "values": list(row)} for excel_row, row in zip(excel_rows, rows)
               if len(row) == len(target_columns) and _identifier(row[target_indexes[0]])[0] == result["source_id"]]
    for field in ("标的物代码", "标的代码", "标的", "标的物名称", "标的名称"):
        indexes = _column_indexes(source_columns, field)
        if len(indexes) == 1:
            hint, _ = _identifier(values[indexes[0]])
            if hint:
                result["underlying_hint"] = hint
                break
        elif len(indexes) > 1:
            break
    if result["underlying_hint"]:
        for field in ("标的物代码", "标的物名称"):
            indexes = _column_indexes(target_columns, field)
            if len(indexes) == 1:
                exact = [row for row in matched if _identifier(row["values"][indexes[0]])[0] == result["underlying_hint"]]
                if exact:
                    matched, result["underlying_matched"] = exact, True
                    break
    result["rows"] = matched
    result["state"] = "matched" if matched else "not_found"
    return result


def _quantity(value):
    """Parse quantities without binary-float arithmetic or treating blanks as 0."""
    if value is None or isinstance(value, (bool, date, datetime, time)):
        return None
    text = unicodedata.normalize("NFKC", str(value)).strip().replace(",", "")
    if not text or text.endswith("%"):
        return None
    try:
        parsed = Decimal(text)
        if (not parsed.is_finite() or len(parsed.as_tuple().digits) > 10000
                or abs(parsed.as_tuple().exponent) > 10000 or abs(parsed.adjusted()) > 10000):
            return None
        return parsed
    except (InvalidOperation, ValueError):
        return None


def _quantity_total(rows, index, field):
    parsed = [_quantity(row["values"][index]) if index is not None else None for row in rows]
    available = [value for value in parsed if value is not None]
    missing = len(parsed) - len(available)
    known = None
    if available:
        # Include enough significant digits for every integer and fraction and
        # carry from adding all rows, independent of the process Decimal context.
        integer_digits = max(1, max(value.adjusted() + 1 for value in available))
        decimal_places = max(0, max(-value.as_tuple().exponent for value in available))
        with localcontext() as context:
            context.prec = max(28, integer_digits + decimal_places + len(str(len(available))) + 2)
            known = format(sum(available, Decimal(0)), "f")
    return {"field": field, "value": known if available and not missing else None,
            "known_value": known, "complete": bool(available) and not missing,
            "missing_count": missing}


def _comparison_values(rows, index):
    if index is None:
        return None
    values = []
    for row in rows:
        value = row["values"][index]
        if isinstance(value, (date, datetime, time)):
            text = value.isoformat()
        else:
            text, _ = _identifier(value)
        if text is None:
            return None
        values.append(text)
    return set(values) if values else None


def _compare_values(left, right):
    if left is None or right is None:
        return "missing"
    return "same" if left == right else "different"


def sum_candidate_quantities(candidates, field="标的名义数量"):
    """Exact sum across candidate groups; any incomplete group stays missing."""
    rows = []
    for candidate in candidates:
        quantity = candidate.get("quantity") or {}
        value = quantity.get("value") if quantity.get("complete") else None
        rows.append({"values": [value]})
    return _quantity_total(rows, 0, field)


def report_back_to_back_candidates(table: dict, contract_id, internal_desks,
                                   *, quantity_field="标的名义数量") -> dict:
    """Find possible counterpart contracts without deciding a relationship.

    The target contract and underlying codes are exact identifiers. Candidate
    counterparties must occur in the caller-supplied internal desk names; a desk
    is never inferred from naming patterns. Quantity/date/operator/direction are
    displayed and compared, but never used to exclude a candidate.
    """
    columns = table.get("columns")
    rows = table.get("rows")
    source_rows = table.get("source_rows")
    if (not isinstance(columns, list) or not isinstance(rows, list)
            or not isinstance(source_rows, list) or len(rows) != len(source_rows)
            or any(not isinstance(row, (list, tuple)) or len(row) != len(columns) for row in rows)):
        raise ValueError("报表字段或行不完整，无法查找候选合约。")
    target_id, _ = _identifier(contract_id)
    result = {"state": "ok", "issues": [], "target_contract_id": target_id,
              "columns": columns, "target_rows": [], "underlyings": [],
              "unusable_candidate_rows": [],
              "sort_basis": "数量、交易达成日、开仓操作人员相同优先，其余按来源行顺序"}
    if target_id is None:
        result["state"] = "invalid_contract"
        return result

    names = {"contract": "合约编号", "code": "标的物代码", "party": "交易对手名称",
             "quantity": quantity_field, "trade_date": "交易达成日", "start_date": "起始日",
             "operator": "开仓操作人员", "direction": "我方资产方向"}
    indexes = {}
    for key, name in names.items():
        matches = _column_indexes(columns, name)
        indexes[key] = matches[0] if len(matches) == 1 else None
        if len(matches) != 1:
            result["issues"].append({"field": name, "reason": "missing" if not matches else "ambiguous"})
    if indexes["contract"] is None:
        result["state"] = "missing_columns"
        return result

    indexed = [{"excel_row": row_number, "values": list(values)}
               for row_number, values in zip(source_rows, rows)]
    target_rows = [row for row in indexed
                   if _identifier(row["values"][indexes["contract"]])[0] == target_id]
    result["target_rows"] = target_rows
    if not target_rows:
        result["state"] = "target_not_found"
        return result
    if indexes["code"] is None:
        result["state"] = "missing_columns"
        return result

    groups = {}
    for row in target_rows:
        code, _ = _identifier(row["values"][indexes["code"]])
        groups.setdefault(code, []).append(row)
    result_groups = {}
    for code, group in groups.items():
        item = {"code": code, "target_rows": group,
            "target_quantity": _quantity_total(group, indexes["quantity"], quantity_field),
            "candidates": [], "unusable_candidate_rows": []}
        result_groups[code] = item
        result["underlyings"].append(item)
    if indexes["party"] is None:
        result["state"] = "missing_columns"
        return result
    if isinstance(internal_desks, (str, bytes)) or internal_desks is None:
        result["state"] = "missing_desks"
        return result
    try:
        desks = {_identifier(value)[0] for value in internal_desks}
    except TypeError:
        result["state"] = "missing_desks"
        return result
    desks.discard(None)
    if not desks:
        result["state"] = "missing_desks"
        return result

    candidate_groups = {}
    for position, row in enumerate(indexed):
        code, _ = _identifier(row["values"][indexes["code"]])
        if code is None or code not in groups:
            continue
        party, _ = _identifier(row["values"][indexes["party"]])
        if party not in desks:
            continue
        candidate_id, _ = _identifier(row["values"][indexes["contract"]])
        if candidate_id == target_id:
            continue
        if candidate_id is None:
            result["unusable_candidate_rows"].append(row)
            result_groups[code]["unusable_candidate_rows"].append(row)
            continue
        candidates_for_code = candidate_groups.setdefault(code, {})
        key = (candidate_id, party)
        if key not in candidates_for_code:
            candidates_for_code[key] = {"contract_id": candidate_id, "counterparty": party,
                                        "rows": [], "_position": position}
        candidates_for_code[key]["rows"].append(row)

    for group in result["underlyings"]:
        for candidate in candidate_groups.get(group["code"], {}).values():
            candidate["quantity"] = _quantity_total(candidate["rows"], indexes["quantity"], quantity_field)
            left_quantity, right_quantity = group["target_quantity"], candidate["quantity"]
            left = Decimal(left_quantity["value"]) if left_quantity["complete"] else None
            right = Decimal(right_quantity["value"]) if right_quantity["complete"] else None
            comparison = {"quantity": _compare_values(left, right)}
            for key in ("trade_date", "start_date", "operator", "direction"):
                comparison[key] = _compare_values(_comparison_values(group["target_rows"], indexes[key]),
                                                  _comparison_values(candidate["rows"], indexes[key]))
            candidate["comparisons"] = comparison
            group["candidates"].append(candidate)
        rank = {"same": 0, "different": 1, "missing": 2}
        group["candidates"].sort(key=lambda item: (rank[item["comparisons"]["quantity"]],
                                                    rank[item["comparisons"]["trade_date"]],
                                                    rank[item["comparisons"]["operator"]],
                                                    item["_position"]))
        for candidate in group["candidates"]:
            candidate.pop("_position")
    return result
