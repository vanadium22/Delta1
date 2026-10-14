"""Deterministic notional sizing; amounts are CNY, quantities are shares."""
from decimal import Decimal, InvalidOperation, ROUND_FLOOR, localcontext

LOT = 100


def decimal_value(value):
    if isinstance(value, bool):
        return None
    try:
        result = Decimal(str(value).strip().replace(",", "").replace("，", ""))
        return result if result.is_finite() else None
    except (InvalidOperation, ValueError):
        return None


def size_order(target, price, available, inventory_complete=True):
    """Never silently cap an oversized order. Return its demand and capacity."""
    amount, last, quantity = map(decimal_value, (target, price, available))
    capacity = None
    if inventory_complete and quantity is not None and quantity >= 0:
        capacity = int((quantity / LOT).to_integral_value(rounding=ROUND_FLOOR)) * LOT
    result = {"status": "empty", "message": "输入目标名本后计算", "lot_size": LOT,
              "target_nominal": None, "requested_shares": None, "executable_shares": None,
              "actual_nominal": None, "unused_nominal": None, "maximum_shares": capacity,
              "maximum_nominal": None}
    if last is not None and last > 0 and capacity is not None:
        result["maximum_nominal"] = str(last * capacity)
    if target is None or str(target).strip() == "":
        return result
    if amount is None or amount <= 0 or amount > Decimal("1e14"):
        return {**result, "status": "invalid", "message": "目标名本须为大于 0 且不超过 100 万亿元的数值"}
    result["target_nominal"] = str(amount)
    if last is None or last <= 0:
        return {**result, "status": "no_price", "message": "本次未获取有效 Wind 最新价，无法换算股数"}
    with localcontext() as context:
        context.prec = 50
        shares = int((amount / (last * LOT)).to_integral_value(rounding=ROUND_FLOOR)) * LOT
        actual = last * shares
        result.update(requested_shares=shares, actual_nominal=str(actual), unused_nominal=str(amount - actual))
    if not shares:
        return {**result, "status": "below_lot", "message": f"目标名本不足 100 股，至少需要 {last * LOT:,.2f} 元"}
    if capacity is None:
        return {**result, "status": "unknown_inventory", "message": "库存数量缺失或不完整，无法确认最大可借股数"}
    if shares > capacity:
        return {**result, "status": "insufficient", "message": f"库存不足：需要 {shares:,} 股，目前最多可借 {capacity:,} 股"}
    return {**result, "status": "ok", "executable_shares": shares,
            "message": f"可借 {shares:,} 股；取整后名本 {actual:,.2f} 元"}
