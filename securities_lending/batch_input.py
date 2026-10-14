"""Parse user-pasted lists without guessing which of two numbers is a notional."""
import re
from decimal import Decimal

from .calculation import decimal_value


def parse_batch(text):
    if len(text) > 10000:
        raise ValueError("每次最多粘贴 100 个标的、10000 个字符")
    lines = [line.strip(" \r") for line in text.splitlines() if line.strip()]
    symbols, targets = [], {}
    for index, line in enumerate(lines, 1):
        # Excel two-column selections use tabs. Plain lists remain unambiguous.
        fields = line.split("\t")
        if len(fields) > 2:
            raise ValueError(f"第 {index} 行超过两列；只粘贴代码/名称和目标名本（万元）两列")
        if len(fields) == 2:
            token, amount = (field.strip() for field in fields)
            if index == 1 and token in {"代码", "证券代码", "股票代码", "名称", "证券名称", "代码/名称"}:
                if amount in {"目标名本（万元）", "目标名本(万元)", "目标名本 / 万元", "目标名本", "万元"}:
                    continue
            if not token or re.search(r"[\s,，;；、]", token):
                raise ValueError(f"第 {index} 行请只填写一个代码或名称")
            if amount:
                value = decimal_value(amount)
                if value is None or not Decimal(0) < value <= Decimal("1e10"):
                    raise ValueError(f"第 {index} 行目标名本须为有效正数，单位万元，上限 100 亿万元")
                yuan = str(value * 10000)
                if token in targets and decimal_value(targets[token]) != decimal_value(yuan):
                    raise ValueError(f"第 {index} 行「{token}」的目标名本与前一行冲突")
                targets[token] = yuan
            symbols.append(token)
        else:
            symbols.extend(token for token in re.split(r"[\s,，;；、]+", line) if token)
    symbols = list(dict.fromkeys(symbols))
    if not symbols:
        raise ValueError("请粘贴代码或名称；可带第二列目标名本（万元）")
    if len(symbols) > 100:
        raise ValueError("每次最多查询 100 个标的")
    return symbols, targets
