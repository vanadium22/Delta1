"""BCT source downloads and per-trading-day Excel archives."""

import ast
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
import json
from pathlib import Path
import os
import ssl
from tempfile import NamedTemporaryFile
import time
from zipfile import ZipFile

from openpyxl import Workbook, load_workbook
from openpyxl.cell import WriteOnlyCell
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter
import requests


BCT_URL = "https://eqdbct.swhysc.com:8181/bct"
BOOK = "境内权益互换台"
PAGE_SIZE = 20000
FLOW_COLUMNS = (
    "tradingDate", "tradeAccount", "instrumentId", "direction", "openClose", "type", "dealAmount",
    "dealPrice", "dealBalance", "fee", "dealBalanceWithFee", "currencyCode", "id", "tradeId",
)
SNAPSHOT_COLUMNS = ("tradingDate", "instrumentId", "instrumentQuote", "currencyCode", "netPosition")


def login_values(path):
    if not path:
        username = os.environ.get("BCT_USERNAME")
        password = os.environ.get("BCT_PASSWORD")
        if not username or not password:
            raise ValueError("需要 BCT 登录设置。请设置 BCT_USERNAME 和 BCT_PASSWORD，或指定 --bct-script。")
        return username, password
    path = Path(path)
    if path.suffix.lower() == ".zip":
        with ZipFile(path) as archive:
            source = archive.read("download_trading_flow_add_holdexcel.py")
    else:
        source = path.read_bytes()
    for node in ast.parse(source).body:
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Tuple)
                and [elt.id for elt in node.targets[0].elts if isinstance(elt, ast.Name)]
                == ["bct_username", "bct_password"]):
            username, password = ast.literal_eval(node.value)
            if isinstance(username, str) and isinstance(password, str) and username and password:
                return username, password
    raise ValueError("指定的来源中找不到 BCT 登录设置。")


class SystemCertificates(requests.adapters.HTTPAdapter):
    def init_poolmanager(self, *args, **kwargs):
        return super().init_poolmanager(*args, ssl_context=ssl.create_default_context(), **kwargs)


class BctClient:
    def __init__(self, credentials_path):
        self.credentials_path = credentials_path
        self.token = None

    @staticmethod
    def session():
        session = requests.Session()
        session.trust_env = False
        session.mount("https://", SystemCertificates())
        session.headers["User-Agent"] = "PostmanRuntime/7.26.8"
        return session

    def connect(self):
        if self.token:
            return
        username, password = login_values(self.credentials_path)
        with self.session() as session:
            response = session.post(f"{BCT_URL}/auth-service/users/login", timeout=(10, 30),
                                    json={"userName": username, "password": password})
            response.raise_for_status()
            self.token = response.json().get("token")
        if not self.token:
            raise ValueError("BCT 登录未返回令牌。")

    def pages(self, endpoint, arguments):
        rows = []
        total = None
        with self.session() as session:
            session.headers["Authorization"] = f"Bearer {self.token}"
            while total is None or len(rows) < total:
                response = self.query(session, endpoint, {**arguments, "bookNames": [BOOK],
                                                          "page": len(rows) // PAGE_SIZE, "pageSize": PAGE_SIZE})
                page = response["page"]
                page_total = int(response["totalCount"])
                if total is not None and page_total != total:
                    raise ValueError(f"BCT {endpoint} 分页总数发生变化。")
                total = page_total
                if (not isinstance(page, list) or len(page) > PAGE_SIZE or len(rows) + len(page) > total
                        or (len(rows) + len(page) < total and len(page) != PAGE_SIZE)):
                    raise ValueError(f"BCT {endpoint} 分页返回不完整，预期总数 {total}。")
                rows.extend(page)
        return rows

    @staticmethod
    def query(session, endpoint, body):
        for attempt in range(3):
            try:
                response = session.post(f"{BCT_URL}/exchange-service/{endpoint}", json=body, timeout=(10, 150))
                response.raise_for_status()
                return response.json()
            except (requests.Timeout, requests.ConnectionError, requests.HTTPError) as exc:
                if attempt == 2 or isinstance(exc, requests.HTTPError) and exc.response.status_code not in {429, 502, 503, 504}:
                    raise
                time.sleep(2 ** attempt)

    def flows(self, days):
        return self.pages("excTradeRecordSearch", {"startDate": days[0], "endDate": days[-1]})

    def snapshot(self, day):
        return self.pages("excPositionSnapshotSearch", {"searchDate": day, "instrumentIds": None})


def plain_cell(sheet, value, *, header=False):
    if isinstance(value, (list, dict)):
        value = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    if isinstance(value, str) or header:
        cell = WriteOnlyCell(sheet, value=value)
        if isinstance(value, str):
            cell.data_type = "s"
        if header:
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = PatternFill("solid", fgColor="254462")
        return cell
    return value


def write_book(path, tables):
    path.parent.mkdir(parents=True, exist_ok=True)
    workbook = Workbook(write_only=True)
    with NamedTemporaryFile(dir=path.parent, suffix=".xlsx", delete=False) as temporary:
        stage = Path(temporary.name)
    try:
        for title, columns, rows in tables:
            sheet = workbook.create_sheet(title)
            sheet.freeze_panes = "A2"
            for index, column in enumerate(columns, 1):
                width = 56 if column in {"状态", "检查说明", "trace"} else max(19, len(column) + 4)
                sheet.column_dimensions[get_column_letter(index)].width = width
            sheet.append([plain_cell(sheet, value, header=True) for value in columns])
            for row in rows:
                sheet.append([plain_cell(sheet, value) for value in row])
        workbook.save(stage)
        stage.replace(path)
    finally:
        workbook.close()
        stage.unlink(missing_ok=True)


def write_source(path, kind, day, records):
    columns = FLOW_COLUMNS if kind == "flow" else SNAPSHOT_COLUMNS
    columns = (*columns, *sorted({key for row in records for key in row} - set(columns)))
    metadata = ((kind, date.fromisoformat(day), len(records), "BCT"),)
    write_book(path, [("原始数据", columns, ([row.get(key) for key in columns] for row in records)),
                      ("下载信息", ("kind", "tradingDate", "rowCount", "source"), metadata)])


def read_source(path, kind, day):
    workbook = load_workbook(path, read_only=True, data_only=True)
    try:
        info = list(workbook["下载信息"].values)
        if len(info) != 2:
            raise ValueError(f"{path} 缺少下载元数据。")
        meta_kind, stamp, expected, origin = info[1]
        if (meta_kind, stamp.date().isoformat() if isinstance(stamp, datetime) else str(stamp), origin) != (kind, day, "BCT"):
            raise ValueError(f"{path} 的来源或交易日不一致。")
        rows = workbook["原始数据"].values
        columns = next(rows)
        required = FLOW_COLUMNS if kind == "flow" else SNAPSHOT_COLUMNS
        if not set(required).issubset(columns):
            raise ValueError(f"{path} 缺少必要字段。")
        result = [dict(zip(columns, row)) for row in rows]
        if len(result) != expected or any(row["tradingDate"] != day for row in result):
            raise ValueError(f"{path} 的记录数或业务日不一致。")
        return result
    finally:
        workbook.close()


def archive_batch(client, root, days):
    buckets = defaultdict(list)
    identifiers = set()
    for row in client.flows(days):
        day = row["tradingDate"]
        key = row.get("id")
        if day not in days or not key or key in identifiers:
            raise ValueError(f"BCT 流水 {days[0]} 至 {days[-1]} 出现异常日期或重复记录。")
        identifiers.add(key)
        buckets[day].append(row)
    for day in days:
        write_source(root / "flows" / f"{day}.xlsx", "flow", day, buckets[day])
    print(f"流水 {days[0]} 至 {days[-1]}：{len(identifiers):,} 条 / {len(days)} 份 Excel", flush=True)


def archive_snapshot(client, root, day):
    rows = client.snapshot(day)
    keys = {(row["instrumentId"].upper(), row["currencyCode"]) for row in rows}
    if not rows or len(keys) != len(rows) or any(row["tradingDate"] != day for row in rows):
        raise ValueError(f"BCT 快照 {day} 为空、日期不符或标的重复。")
    write_source(root / "snapshots" / f"{day}.xlsx", "snapshot", day, rows)
    print(f"BCT 快照 {day}：{len(rows):,} 条 / 1 份 Excel", flush=True)


def archive_missing(root, days, snapshots, credentials_path, *, batch_size=8):
    batches = []
    batch = []
    for day in days:
        if (root / "flows" / f"{day}.xlsx").is_file() or len(batch) == batch_size:
            if batch:
                batches.append(batch)
                batch = []
        if not (root / "flows" / f"{day}.xlsx").is_file():
            batch.append(day)
    if batch:
        batches.append(batch)
    missing_snapshots = [day for day in sorted(set(snapshots)) if not (root / "snapshots" / f"{day}.xlsx").is_file()]
    if not batches and not missing_snapshots:
        return
    client = BctClient(credentials_path)
    client.connect()
    tasks = [(archive_batch, days) for days in batches] + [(archive_snapshot, day) for day in missing_snapshots]
    with ThreadPoolExecutor(max_workers=3) as pool:
        pending = [pool.submit(job, client, root, arg) for job, arg in tasks]
        errors = []
        for (job, arg), future in zip(tasks, pending):
            try:
                future.result()
            except Exception as exc:
                errors.append(f"{job.__name__} {arg}: {exc}")
    if errors:
        raise RuntimeError("以下交易日未能下载，已成功文件可在重跑时复用：\n" + "\n".join(errors))
