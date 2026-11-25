"""Plain-text lending inquiries for the current query results."""
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from .calculation import decimal_value
from .inventory import normalize_code
from .margin_sheet import SHEET_NAME as MARGIN_SHEET_NAME


def group_rows(rows, detailed):
    if detailed:
        return [[row] for row in rows]
    groups = {}
    for index, row in enumerate(rows):
        rate = row.get("rate")
        key = (rate, index if rate is None else None)
        groups.setdefault(key, []).append(row)
    return groups.values()


def rate_label(row):
    rate = row.get("rate")
    if rate is not None:
        whole, _, fraction = format(rate, "f").partition(".")
        return f"{whole}.{fraction.rstrip('0').ljust(2, '0')}%"
    return " ".join((row.get("rate_raw") or "").split()) or "未提供"


def remaining_label(row, query_day):
    if row.get("remaining_term"):
        return f"剩余 {row['remaining_term']}"
    if row.get("maturity_date"):
        days = (date.fromisoformat(row["maturity_date"]) - query_day).days
        return f"剩余 {days} 天" if days >= 0 else "剩余 0 天（已到期）"
    return "剩余期限未提供"


def total_quantity(rows):
    known = [row["quantity"] for row in rows if row.get("quantity") is not None]
    return (sum(known, Decimal(0)) if known else None), len(known) == len(rows)


def share_count(quantity):
    text = f"{quantity:,f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return f"{text} 股"


def inquiry_line(rows, price, query_day, detailed):
    quantity, complete = total_quantity(rows)
    if quantity is None:
        quantity_text = "数量未提供"
    else:
        quantity_text = share_count(quantity)
        if not complete:
            quantity_text += "（仅已知）"
    value_text = "市值未取得"
    if quantity is not None and complete and price is not None and price > 0:
        market_value = (quantity * price / 10000).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        value_text = f"市值 {market_value:,.2f} 万元"
    line = f"  {quantity_text}｜{value_text}｜费率 {rate_label(rows[0])}"
    if detailed:
        line += f"｜{remaining_label(rows[0], query_day)}"
    return line


def margin_note(sources, rows, has_code):
    if not sources:
        return "当日券单不可用"
    if all(source["state"] == "missing" for source in sources):
        return "缺少工作表"
    if not any(source["state"] == "ready" for source in sources):
        return "读取失败"
    if not has_code:
        return "标的代码未确认"
    if any(source["state"] != "ready" for source in sources):
        return "部分文件缺表或读取失败" if rows else "已读取的工作表中无记录（部分文件缺表或读取失败）"
    return "" if rows else "无记录"


def inquiry_text(items, status, *, detailed):
    query_day = date.fromisoformat(status["date"])
    intro = "券源信息如下：\n"
    lines = ["合成演示数据"] if status.get("mode") == "demo" else []
    inventory_sheet = status.get("sheet_name") or "库存券单"
    for index, item in enumerate(items):
        code = normalize_code(item["code"])
        name = " ".join(item["name"].split())
        price = decimal_value((item.get("quote") or {}).get("price"))
        inventory_records, margin_records = item["rows"], item.get("margin_rows", [])
        if status["state"] == "unavailable":
            inventory_note = "当日券单不可用"
        elif not code:
            inventory_note = "标的代码未确认"
        else:
            inventory_note = "" if inventory_records else "无记录"
        if index:
            lines.append("")
        lines.append(f"{code or '代码未确认'} - {name}")
        for sheet, records, note, is_margin in (
            (inventory_sheet, inventory_records, inventory_note, False),
            (MARGIN_SHEET_NAME, margin_records, margin_note(status.get("margin_sheets", []), margin_records, bool(code)), True),
        ):
            lines.append(sheet if records else f"{sheet}｜{note}")
            if is_margin and records and not detailed:
                quantity, complete = total_quantity(records)
                if quantity is None:
                    lines.append("  合计股数未提供")
                else:
                    label = "合计" if complete and not note else "已知合计"
                    lines.append(f"  {label} {share_count(quantity)}")
            for group in group_rows(records, detailed):
                lines.append(inquiry_line(group, price, query_day, detailed))
            if records and note:
                lines.append(f"  {note}")
    return intro + "\n".join(lines)
