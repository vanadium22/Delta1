"""Read maintained symbol lists without executing Python files."""
from __future__ import annotations

import ast
import json
from pathlib import Path
import re
from collections.abc import Iterable

_SYMBOL = re.compile(r"[A-Z0-9][A-Z0-9_-]*\.[A-Z][A-Z0-9]*\Z")


class SymbolFileError(ValueError):
    """A symbol file cannot be read as a nonempty list of market codes."""


def load_symbols(files: Iterable[Path]) -> list[str]:
    """Merge JSON lists, Python literal lists, or line-based TXT/LIST files."""
    merged: dict[str, None] = {}
    for filename in files:
        path = Path(filename)
        try:
            content = path.read_text(encoding="utf-8-sig").strip()
            if path.suffix.lower() == ".json":
                values = json.loads(content)
            elif path.suffix.lower() in {".txt", ".list"}:
                if content.startswith("["):
                    values = ast.literal_eval(content)
                else:
                    values = [line.split("#", 1)[0].strip() for line in content.splitlines()]
                    values = [value for value in values if value]
            else:
                raise ValueError("支持 .json、.txt、.list；不会执行 .py 文件")
            if not isinstance(values, list):
                raise ValueError("内容必须是标的字符串 list")
            for position, value in enumerate(values, 1):
                if not isinstance(value, str):
                    raise ValueError(f"第 {position} 项不是字符串；代码须加引号以保留前导零")
                symbol = value.strip().upper()
                if not _SYMBOL.fullmatch(symbol):
                    raise ValueError(f"第 {position} 项不是有效的 代码.交易所 格式")
                merged[symbol] = None
        except (OSError, UnicodeError, ValueError, SyntaxError) as exc:
            raise SymbolFileError(f"{path}: {exc}") from exc
    if not merged:
        raise SymbolFileError("合并后的标的列表为空")
    return list(merged)
