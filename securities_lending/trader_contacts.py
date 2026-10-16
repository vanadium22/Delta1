"""Editable inquiry contacts; never used to infer inventory ownership/capacity."""
from __future__ import annotations

import json
from pathlib import Path

from .config import ROOT, atomic_json
from shared_data import DataPaths


def contacts_path(root: Path, demo: bool) -> Path:
    return (DataPaths.for_module(root).demo("securities_lending") if demo else root) / "trader_contacts.local.json"


def _text(value, field: str) -> str:
    if not isinstance(value, str) or any(c in value for c in "\r\n\t"):
        raise ValueError(f"{field} 必须是单行文本")
    return value.strip()


def validate_contacts(value: dict) -> dict:
    """Validate and return a detached, normalized mapping for UI or JSON callers."""
    if not isinstance(value, dict) or type(value.get("schema_version")) is not int or value["schema_version"] != 1:
        raise ValueError("联系表 schema_version 必须为 1")
    group, note = _text(value.get("group"), "微信群名"), _text(value.get("note", ""), "备注")
    desks, industries = {}, {}
    if not isinstance(value.get("desks"), dict) or not isinstance(value.get("industries"), dict):
        raise ValueError("desks 和 industries 必须是映射表")
    for key, names in value["desks"].items():
        desk = _text(key, "交易台")
        if not desk or desk in desks:
            raise ValueError("交易台名称不能为空或重复")
        if not isinstance(names, list):
            raise ValueError(f"{desk} 的联系人必须是姓名列表")
        cleaned = []
        for name in names:
            name = _text(name, "联系人").lstrip("@＠").strip()
            if not name:
                raise ValueError(f"{desk} 的联系人姓名不能为空")
            if name not in cleaned:
                cleaned.append(name)
        desks[desk] = cleaned
    for key, value in value["industries"].items():
        industry, desk = _text(key, "行业"), _text(value, "交易台")
        if not industry or industry in industries:
            raise ValueError("行业名称不能为空或重复")
        if desk and desk not in desks:
            raise ValueError(f"行业「{industry}」引用了不存在的交易台「{desk}」")
        industries[industry] = desk
    return {"schema_version": 1, "group": group, "note": note, "desks": desks, "industries": industries}


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"联系表存在重复字段：{key}")
        result[key] = value
    return result


def load_contacts(path: Path) -> tuple[dict, str]:
    """Missing local file uses the example; broken local data fails closed."""
    try:
        source = path if path.exists() else ROOT / "trader_contacts.example.json"
        value = json.loads(source.read_text(encoding="utf-8-sig"), object_pairs_hook=_unique_object)
        return validate_contacts(value), ""
    except (OSError, ValueError) as exc:
        return {"schema_version": 1, "group": "", "note": "", "desks": {}, "industries": {}}, f"联系表读取失败：{exc}"


def save_contacts(path: Path, value: dict) -> dict:
    cleaned = validate_contacts(value)
    atomic_json(path, cleaned)
    return cleaned


def contact_for(industry: str, book: dict) -> dict:
    """Exact industry labels only; ambiguous/mixed/unmapped values stay empty."""
    desk = book["industries"].get((industry or "").strip(), "")
    names = book["desks"].get(desk, [])
    return {"desk": desk if names else "", "traders": list(names), "group": book["group"], "note": book["note"]}


def contact_description(contact: dict) -> str:
    names = "、".join("@" + name for name in contact["traders"])
    return (f"询券交易台：{contact['desk'] or '未映射'}\n联系人：{names or '未映射，留空'}"
            f"\n微信群：{contact['group'] or '未设置'}\n备注：{contact['note'] or '无'}"
            "\n仅为行业询券联系提示，不代表该交易台有库存。")
