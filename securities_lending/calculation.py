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


def size_order(target, price, available, inventory_complete=True, *, requested_shares=None):
    """Never silently cap an oversized order. Return its demand and capacity."""
    amount, last, quantity = map(decimal_value, (target, price, available))
    capacity = None
    if inventory_complete and quantity is not None and quantity >= 0:
        capacity = int((quantity / LOT).to_integral_value(rounding=ROUND_FLOOR)) * LOT
    result = {"status": "empty", "message": "输入目标名本后计算", "lot_size": LOT,
              "input_mode": "shares" if requested_shares is not None else "amount", "input_shares": requested_shares,
              "target_nominal": None, "requested_shares": None, "executable_shares": None,
              "actual_nominal": None, "unused_nominal": None, "maximum_shares": capacity,
              "maximum_nominal": None}
    if last is not None and last > 0 and capacity is not None:
        result["maximum_nominal"] = str(last * capacity)
    if requested_shares is not None:
        # Explicit share orders must not be silently rounded or capped.
        demand = decimal_value(requested_shares)
        if str(requested_shares).strip() == "":
            return {**result, "message": "输入要求股数后计算"}
        if demand is None or not 0 < demand <= Decimal("1e12") or demand % LOT:
            return {**result, "status": "invalid", "message": "要求股数须为 100 的正整数倍，且不超过 1 万亿股"}
        shares = int(demand)
        result["requested_shares"] = shares
        if last is not None and last > 0:
            result["actual_nominal"] = str(last * shares)
        if capacity is None:
            return {**result, "status": "unknown_inventory", "message": "库存数量缺失或不完整，无法确认最大可借股数"}
        if shares > capacity:
            return {**result, "status": "insufficient", "message": f"库存不足：需要 {shares:,} 股，目前最多可借 {capacity:,} 股"}
        return {**result, "status": "ok", "executable_shares": shares,
                "message": f"数量可融 {shares:,} 股" + (f"；约 {last * shares:,.2f} 元" if last is not None and last > 0 else "；价格不可用，无法估值")}
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


def source_coverage(rows, calculation, inventory_ready=True):
    """Quantity evidence only; never infer ownership for non-swap sources."""
    buckets = {"own": [], "other": []}
    for row in rows:
        buckets["own" if (row.get("source") or "").strip() == "互换" else "other"].append(row)
    result = {}
    for key, sources in buckets.items():
        values = [decimal_value(row.get("quantity")) for row in sources]
        complete = inventory_ready and all(value is not None and value >= 0 for value in values)
        known = sum((value for value in values if value is not None and value >= 0), Decimal(0))
        result[key + "_shares"] = int(known // LOT) * LOT if complete else None
        result[key + "_known_shares"] = known
    demand, capacity = calculation.get("requested_shares"), calculation.get("maximum_shares")
    result.update(status="empty", message="输入需求后判断自有覆盖", shortage_shares=None, other_needed_shares=None)
    if not inventory_ready or capacity is None:
        result.update(status="unknown", message="库存不可用或数量不完整，无法确认可融上限")
    elif capacity == 0:
        result.update(status="unavailable", message="库存没有可融整百股", shortage_shares=demand)
    elif calculation["status"] in {"invalid", "below_lot", "no_price"}:
        result.update(status=calculation["status"], message=calculation["message"])
    elif demand:
        own, other = result["own_shares"], result["other_shares"]
        needed = max(0, demand - own)
        result["other_needed_shares"] = needed
        if demand > capacity:
            result.update(status="insufficient", message="库存不足 · 合计仍不够", shortage_shares=demand - capacity)
        elif own >= demand:
            result.update(status="own", message="可融 · 自有券源足额覆盖")
        elif other >= demand:
            result.update(status="other", message="自有不足 · 其他来源单独足够（需询券）")
        else:
            result.update(status="combined", message="自有不足 · 其他来源可补足（需询券）")
    return result
