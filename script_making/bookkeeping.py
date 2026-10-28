"""Local manual bookkeeping and explicitly confirmed back-to-back links.

The database records user input only. It neither changes source workbooks nor
submits trades. Identifiers are matched exactly, never inferred from economics.
"""
from __future__ import annotations

import json
import sqlite3
import unicodedata
import uuid
from contextlib import contextmanager
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

from shared_data.io import file_lock
from .storage import ReportError, timestamp


TEXT_FIELDS = ("contract_no", "confirmation_no", "local_id", "counterparty",
               "underlying_code", "underlying_name", "direction", "unit", "note")
NUMBER_FIELDS = ("quantity", "amount", "price")
ALIASES = ("contract_no", "confirmation_no", "local_id")
IDENTITY_FIELDS = (*ALIASES, "underlying_code")
SCHEMA_VERSION = 1
APPLICATION_ID = "delta1.script_making.manual_bookkeeping"

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS contracts (
    id TEXT PRIMARY KEY, metadata TEXT NOT NULL,
    back_flag TEXT NOT NULL CHECK(back_flag IN ('unknown','none')),
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS contract_aliases (
    kind TEXT NOT NULL, value TEXT NOT NULL, contract_id TEXT NOT NULL,
    PRIMARY KEY (kind,value), FOREIGN KEY(contract_id) REFERENCES contracts(id)
);
CREATE INDEX IF NOT EXISTS aliases_by_contract ON contract_aliases(contract_id);
CREATE TABLE IF NOT EXISTS records (
    id TEXT PRIMARY KEY, contract_id TEXT NOT NULL, payload TEXT NOT NULL,
    version INTEGER NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
    FOREIGN KEY(contract_id) REFERENCES contracts(id)
);
CREATE INDEX IF NOT EXISTS records_by_contract ON records(contract_id);
CREATE TABLE IF NOT EXISTS record_history (
    record_id TEXT NOT NULL, version INTEGER NOT NULL, payload TEXT NOT NULL,
    saved_at TEXT NOT NULL, PRIMARY KEY(record_id,version),
    FOREIGN KEY(record_id) REFERENCES records(id)
);
CREATE TABLE IF NOT EXISTS links (
    id TEXT PRIMARY KEY, left_id TEXT NOT NULL, right_id TEXT NOT NULL,
    note TEXT NOT NULL, created_at TEXT NOT NULL, left_snapshot TEXT NOT NULL, right_snapshot TEXT NOT NULL,
    CHECK(left_id < right_id), UNIQUE(left_id,right_id),
    FOREIGN KEY(left_id) REFERENCES contracts(id),
    FOREIGN KEY(right_id) REFERENCES contracts(id)
);
CREATE INDEX IF NOT EXISTS links_by_right ON links(right_id);
"""


def _normal(value):
    return unicodedata.normalize("NFKC", str(value or "")).strip().casefold()


def _identity(value):
    """Keep identifier spelling exact; search text normalization is separate."""
    return str(value or "").strip()


def _text(value, name):
    if value is None:
        return ""
    if not isinstance(value, (str, int)) or isinstance(value, bool):
        raise ReportError(f"{name} 应为文本。")
    result = str(value).strip()
    if len(result) > 20000 or "\x00" in result:
        raise ReportError(f"{name} 内容无效或过长。")
    return result


def _payload(data):
    if not isinstance(data, dict):
        raise ReportError("簿记记录格式无效。")
    action = data.get("action")
    if action not in ("open", "close"):
        raise ReportError("请选择新开或平仓。")
    day = _text(data.get("trade_date"), "日期")
    try:
        if len(day) != 10 or date.fromisoformat(day).isoformat() != day:
            raise ValueError
    except ValueError as exc:
        raise ReportError("请输入有效日期，格式为 YYYY-MM-DD。") from exc
    result = {"action": action, "trade_date": day}
    for field in TEXT_FIELDS:
        result[field] = _text(data.get(field), field)
    result["group_id"] = _text(data.get("group_id"), "操作组标识")
    result["group_name"] = _text(data.get("group_name"), "操作组名称")
    if bool(result["group_id"]) != bool(result["group_name"]):
        raise ReportError("操作组标识和名称须同时存在，或同时留空。")
    for field in NUMBER_FIELDS:
        value = _text(data.get(field), field)
        if value:
            try:
                parsed = Decimal(unicodedata.normalize("NFKC", value).replace(",", ""))
                if not parsed.is_finite():
                    raise InvalidOperation
            except InvalidOperation as exc:
                raise ReportError(f"{field} 请输入有效数字。") from exc
        result[field] = value
    source = data.get("source") or {}
    if not isinstance(source, dict):
        raise ReportError("来源快照格式无效。")
    try:
        encoded = json.dumps(source, ensure_ascii=False, allow_nan=False)
    except (ValueError, TypeError) as exc:
        raise ReportError("来源快照含有无法保存的值。") from exc
    if len(encoded) > 2_000_000:
        raise ReportError("来源快照过大。")
    result["source"] = json.loads(encoded)
    has_report_key = bool(result["underlying_code"] and (result["contract_no"] or result["confirmation_no"]))
    if action == "close" and not (result["local_id"] or has_report_key):
        raise ReportError("平仓请先选择已有合约，提供标的代码及合约编号/确认书编号，或本地记录标识。")
    if action == "open" and not (result["local_id"] or has_report_key):
        result["local_id"] = uuid.uuid4().hex
    return result


def _reference(ref):
    if not isinstance(ref, dict):
        raise ReportError("合约信息格式无效。")
    result = {name: _text(ref.get(name), name) for name in TEXT_FIELDS}
    source = ref.get("source") or {}
    if not isinstance(source, dict):
        raise ReportError("来源快照格式无效。")
    try:
        encoded = json.dumps(source, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ReportError("来源快照含有无法保存的值。") from exc
    if len(encoded) > 2_000_000:
        raise ReportError("来源快照过大。")
    result["source"] = json.loads(encoded)
    if not any(result[name] for name in ALIASES):
        raise ReportError("请提供合约编号、确认书编号或本地记录标识。")
    return result


class BookkeepingStore:
    """Transactional SQLite store, with exact identifier aliases and revisions."""

    def __init__(self, path: Path):
        self.path = Path(path).expanduser().resolve()

    @contextmanager
    def _connection(self, write=False):
        if write or self.path.exists():
            with file_lock(self.path.with_suffix(self.path.suffix + ".lock")):
                with self._open_connection(write=write) as connection:
                    yield connection
        else:
            with self._open_connection() as connection:
                yield connection

    @contextmanager
    def _open_connection(self, write=False):
        existed = self.path.is_file()
        if not write and not existed:
            yield None
            return
        if write:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(str(self.path), timeout=20)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA busy_timeout = 20000")
            if existed:
                try:
                    row = connection.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
                    application = connection.execute("SELECT value FROM meta WHERE key='application'").fetchone()
                except sqlite3.Error as exc:
                    raise ReportError("簿记记录库无法读取，原文件未修改。") from exc
                if row is None or row[0] != str(SCHEMA_VERSION) or application is None or application[0] != APPLICATION_ID:
                    raise ReportError("簿记记录版本不兼容，请勿覆盖原记录。")
            if write and not existed:
                # DELETE journal works on local and ordinary Windows shared paths;
                # do not switch the user's database to network-unsafe WAL mode.
                connection.executescript(SCHEMA)
                connection.execute("INSERT OR IGNORE INTO meta VALUES ('schema_version',?)", (str(SCHEMA_VERSION),))
                connection.execute("INSERT OR IGNORE INTO meta VALUES ('application',?)", (APPLICATION_ID,))
                connection.commit()
            if write:
                connection.execute("BEGIN IMMEDIATE")
            yield connection
            if write:
                connection.commit()
        except Exception:
            if write:
                connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def _alias_pairs(ref):
        pairs = []
        local = _identity(ref.get("local_id"))
        if local:
            pairs.append(("local_id", local))
        code = _identity(ref.get("underlying_code"))
        if code:
            for kind in ("contract_no", "confirmation_no"):
                value = _identity(ref.get(kind))
                if value:
                    pairs.append((kind, json.dumps([value, code], ensure_ascii=False, separators=(",", ":"))))
        return pairs

    @classmethod
    def _ids(cls, connection, ref):
        ids = set()
        for kind, value in cls._alias_pairs(ref):
            row = connection.execute("SELECT contract_id FROM contract_aliases WHERE kind=? AND value=?",
                                     (kind, value)).fetchone()
            if row:
                ids.add(row[0])
        if len(ids) > 1:
            raise ReportError("合约编号和确认书编号属于不同已登记合约，请核对后重试。")
        contract_id = next(iter(ids), None)
        if contract_id:
            row = connection.execute("SELECT metadata FROM contracts WHERE id=?", (contract_id,)).fetchone()
            metadata = json.loads(row[0])
            for key in ("contract_no", "confirmation_no", "underlying_code"):
                if ref.get(key) and metadata.get(key) and _identity(ref[key]) != _identity(metadata[key]):
                    raise ReportError("合约编号、确认书编号或标的代码与已登记信息冲突，请核对后重试。")
        return contract_id

    @classmethod
    def _ensure_contract(cls, connection, ref, forced_id=None):
        ref = _reference(ref)
        if not cls._alias_pairs(ref):
            raise ReportError("请提供标的代码及合约编号/确认书编号，或提供本地记录标识。")
        matched = cls._ids(connection, ref)
        if forced_id and matched and forced_id != matched:
            raise ReportError("该编号已属于另一合约，不能覆盖已有背对关系。")
        contract_id = forced_id or matched or uuid.uuid4().hex
        row = connection.execute("SELECT metadata FROM contracts WHERE id=?", (contract_id,)).fetchone()
        now = timestamp()
        if row is None:
            connection.execute("INSERT INTO contracts VALUES(?,?,?,?,?)",
                               (contract_id, json.dumps(ref, ensure_ascii=False), "unknown", now, now))
        else:
            metadata = json.loads(row[0])
            for name, value in ref.items():
                if value:
                    metadata[name] = value
            connection.execute("UPDATE contracts SET metadata=?,updated_at=? WHERE id=?",
                               (json.dumps(metadata, ensure_ascii=False), now, contract_id))
        for kind, value in cls._alias_pairs(ref):
            connection.execute("INSERT OR IGNORE INTO contract_aliases VALUES(?,?,?)",
                               (kind, value, contract_id))
        return contract_id

    @staticmethod
    def _back(connection, contract_id):
        contract = connection.execute("SELECT back_flag FROM contracts WHERE id=?", (contract_id,)).fetchone()
        if not contract:
            return {"status": "unknown", "counterparts": []}
        rows = connection.execute("""
            SELECT links.id, links.note, links.created_at, contracts.metadata,
                CASE WHEN links.left_id=? THEN links.right_snapshot ELSE links.left_snapshot END AS snapshot
            FROM links JOIN contracts ON contracts.id =
                CASE WHEN links.left_id=? THEN links.right_id ELSE links.left_id END
            WHERE links.left_id=? OR links.right_id=? ORDER BY links.created_at, links.id
        """, (contract_id, contract_id, contract_id, contract_id)).fetchall()
        counterparts = []
        for row in rows:
            current = json.loads(row["metadata"])
            snapshot = json.loads(row["snapshot"])
            if snapshot.get("source"):
                current["source"] = snapshot["source"]
            counterparts.append({"link_id": row["id"], "note": row["note"], "linked_at": row["created_at"],
                                 "ref": current, "link_snapshot": snapshot})
        return {"status": "linked" if counterparts else contract["back_flag"], "counterparts": counterparts}

    @classmethod
    def _record(cls, connection, row):
        value = json.loads(row["payload"])
        value.update(id=row["id"], version=row["version"], created_at=row["created_at"], updated_at=row["updated_at"])
        value["back_to_back"] = cls._back(connection, row["contract_id"])
        return value

    def save_record(self, data: dict, record_id: str | None = None, expected_version: int | None = None):
        value = _payload(data)
        with self._connection(write=True) as connection:
            existing = None
            if record_id:
                existing = connection.execute("SELECT * FROM records WHERE id=?", (record_id,)).fetchone()
                if existing is None:
                    raise ReportError("簿记记录不存在。")
                if expected_version != existing["version"]:
                    raise ReportError("记录已被修改，请刷新后再保存。")
                old = json.loads(existing["payload"])
                if old.get("source") and not data.get("source"):
                    value["source"] = old["source"]
                elif old.get("source") and old["source"] != value["source"]:
                    raise ReportError("已有来源快照不能覆盖，请新建记录以保留原始依据。")
                for key in IDENTITY_FIELDS:
                    if old.get(key) and _identity(old[key]) != _identity(value.get(key)):
                        raise ReportError("已登记的合约标识不能更改或清空；可补填原本为空的编号。")
            contract_id = self._ensure_contract(connection, value, existing["contract_id"] if existing else None)
            now = timestamp()
            encoded = json.dumps(value, ensure_ascii=False, allow_nan=False)
            if existing:
                version = existing["version"] + 1
                connection.execute("UPDATE records SET payload=?,version=?,updated_at=? WHERE id=?",
                                   (encoded, version, now, record_id))
            else:
                record_id, version = uuid.uuid4().hex, 1
                connection.execute("INSERT INTO records VALUES(?,?,?,?,?,?)", (record_id, contract_id, encoded, version, now, now))
            connection.execute("INSERT INTO record_history VALUES(?,?,?,?)", (record_id, version, encoded, now))
            row = connection.execute("SELECT * FROM records WHERE id=?", (record_id,)).fetchone()
            return self._record(connection, row)

    def get_record(self, record_id: str):
        with self._connection() as connection:
            if connection is None:
                return None
            row = connection.execute("SELECT * FROM records WHERE id=?", (record_id,)).fetchone()
            return self._record(connection, row) if row else None

    def list_records(self, search: str = ""):
        query = _normal(search)
        with self._connection() as connection:
            if connection is None:
                return []
            rows = connection.execute("SELECT * FROM records ORDER BY updated_at DESC, id DESC").fetchall()
            records = [self._record(connection, row) for row in rows]
            return [record for record in records if not query or query in _normal(json.dumps(record, ensure_ascii=False))]

    def record_history(self, record_id: str):
        with self._connection() as connection:
            if connection is None:
                return []
            rows = connection.execute("SELECT version,payload,saved_at FROM record_history WHERE record_id=? ORDER BY version", (record_id,)).fetchall()
            return [{"version": row["version"], "saved_at": row["saved_at"], "data": json.loads(row["payload"])} for row in rows]

    def get_back_to_back(self, ref: dict):
        reference = _reference(ref)
        with self._connection() as connection:
            if not self._alias_pairs(reference):
                candidates = []
                if connection is not None:
                    seen = set()
                    for kind in ("contract_no", "confirmation_no"):
                        value = _identity(reference.get(kind))
                        if not value:
                            continue
                        rows = connection.execute("SELECT value,contract_id FROM contract_aliases WHERE kind=?", (kind,)).fetchall()
                        for row in rows:
                            if json.loads(row["value"])[0] == value and row["contract_id"] not in seen:
                                seen.add(row["contract_id"])
                                metadata = connection.execute("SELECT metadata FROM contracts WHERE id=?", (row["contract_id"],)).fetchone()
                                candidates.append(json.loads(metadata[0]))
                return {"status": "unknown", "counterparts": [], "requires_underlying": True, "candidates": candidates}
            if connection is None:
                return {"status": "unknown", "counterparts": []}
            contract_id = self._ids(connection, reference)
            return self._back(connection, contract_id) if contract_id else {"status": "unknown", "counterparts": []}

    def set_back_status(self, ref: dict, status: str):
        if status not in ("unknown", "none"):
            raise ReportError("背对状态只能设为未确认或无背对；有关联时由关系自动显示。")
        with self._connection(write=True) as connection:
            contract_id = self._ensure_contract(connection, ref)
            if self._back(connection, contract_id)["counterparts"]:
                raise ReportError("该合约已有关联，请先解除背对关系。")
            connection.execute("UPDATE contracts SET back_flag=?,updated_at=? WHERE id=?", (status, timestamp(), contract_id))
            return self._back(connection, contract_id)

    def link_contracts(self, left_ref: dict, right_ref: dict, note: str = ""):
        note = _text(note, "备注")
        with self._connection(write=True) as connection:
            left_snapshot, right_snapshot = _reference(left_ref), _reference(right_ref)
            left = self._ensure_contract(connection, left_snapshot)
            right = self._ensure_contract(connection, right_snapshot)
            if left == right:
                raise ReportError("不能将同一合约关联为自己的背对。")
            if left > right:
                left, right = right, left
                left_snapshot, right_snapshot = right_snapshot, left_snapshot
            row = connection.execute("SELECT id FROM links WHERE left_id=? AND right_id=?", (left, right)).fetchone()
            if row:
                link_id = row[0]
                if note:
                    connection.execute("UPDATE links SET note=? WHERE id=?", (note, link_id))
            else:
                link_id = uuid.uuid4().hex
                connection.execute("INSERT INTO links VALUES(?,?,?,?,?,?,?)",
                                   (link_id, left, right, note, timestamp(),
                                    json.dumps(left_snapshot, ensure_ascii=False), json.dumps(right_snapshot, ensure_ascii=False)))
            connection.execute("UPDATE contracts SET back_flag='unknown',updated_at=? WHERE id IN (?,?)", (timestamp(), left, right))
            return {"id": link_id, "left": self._back(connection, left), "right": self._back(connection, right)}

    def unlink_contracts(self, left_ref: dict, right_ref: dict):
        left_ref, right_ref = _reference(left_ref), _reference(right_ref)
        with self._connection(write=True) as connection:
            left, right = self._ids(connection, left_ref), self._ids(connection, right_ref)
            if not left or not right or left == right:
                raise ReportError("未找到该背对关系。")
            left, right = sorted((left, right))
            cursor = connection.execute("DELETE FROM links WHERE left_id=? AND right_id=?", (left, right))
            if cursor.rowcount != 1:
                raise ReportError("未找到该背对关系。")
            connection.execute("UPDATE contracts SET back_flag='unknown',updated_at=? WHERE id IN (?,?)", (timestamp(), left, right))
            return True
