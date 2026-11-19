"""Read the two baseline position exports without importing the attached scripts."""

from datetime import date
import io
from zipfile import ZipFile

from openpyxl import load_workbook

from shared_data.io import atomic_json

BASE_DAY = "2025-12-29"
ACCOUNTS = {"2602": "5102|510200|5102_000", "5526": "5526|552600|5526_000", "5524": "5524|552400|5524_000"}
ACCOUNT_IDS = {source: account for account, source in ACCOUNTS.items()}
MARKETS = {"上交所A": ".SH", "深交所A": ".SZ", "中金所": ".CFE"}


def baseline_xls(content, account):
    try:
        import xlrd
    except ImportError as exc:
        raise RuntimeError("首次从 ZIP 导入旧版 .xls 需要 xlrd。已打包的数据可直接运行。") from exc
    sheet = xlrd.open_workbook(file_contents=content, logfile=io.StringIO()).sheet_by_index(0)
    headers = sheet.row_values(0)
    rows = []
    navs = set()
    for index in range(1, sheet.nrows):
        row = dict(zip(headers, sheet.row_values(index)))
        if not row["证券代码"]:
            continue
        if str(row["日期"]) != BASE_DAY or row["组合编号"] != ACCOUNTS[account].split("|")[-1]:
            raise ValueError(f"{account} 基准持仓中的账户或日期不一致。")
        if row["交易币种"] != "人民币":
            raise ValueError(f"{account} 基准持仓包含未配置的币种。")
        code = row["证券代码"]
        if isinstance(code, float) and code.is_integer():
            code = f"{int(code):06d}"
        code = str(code).upper() + MARKETS[row["交易市场"]]
        side = {"多仓": "long", "空仓": "short"}[row["持仓多空标志"]]
        qty = abs(float(row["持仓"]))
        price = float(row["最新价"])
        navs.add(float(row["基金净值"]))
        rows.append({"account": account, "code": code, "side": side, "quantity": qty, "price": price})
    if not rows or len(navs) != 1:
        raise ValueError(f"{account} 基准持仓缺失，或基金净值不一致。")
    return rows, navs.pop()


def baseline_snapshot(content):
    workbook = load_workbook(io.BytesIO(content), data_only=True, read_only=True)
    try:
        sheet = workbook.active
        sheet.reset_dimensions()
        rows = sheet.values
        headers = next(rows)
        fields = ("交易日", "标的物代码", "标的物价格", "持仓数量(股数/手数)", "交易货币")
        columns = [headers.index(field) for field in fields]
        result = []
        for row in rows:
            stamp, code, price, qty, currency = [row[column] for column in columns]
            if str(stamp)[:10] != BASE_DAY or currency != "CNY":
                raise ValueError("基准快照的表内日期或币种不一致。")
            result.append([date.fromisoformat(BASE_DAY), code, price, qty, currency])
        return result
    finally:
        workbook.close()


def import_baseline(root, archive_path):
    dest = root / "inputs"
    dest.mkdir(parents=True, exist_ok=True)
    with ZipFile(archive_path) as archive:
        rows = []
        candidates = {}
        originals = {}
        for account in ("2602", "5526"):
            member, = [x for x in archive.infolist() if x.filename.endswith(f"{account}.xls")]
            content = archive.read(member)
            records, candidates[account] = baseline_xls(content, account)
            rows.extend(records)
            originals[dest / f"基准持仓_{account}_{BASE_DAY}.xls"] = content
        member, = [x for x in archive.infolist() if x.filename.endswith("2026-11-18).xlsx")]
        content = archive.read(member)
        prices = baseline_snapshot(content)
        originals[dest / f"BCT基准快照_{BASE_DAY}.xlsx"] = content
    for file, raw in originals.items():
        if file.exists() and file.read_bytes() != raw:
            raise ValueError(f"基准文件已存在且内容不同：{file}")
        if not file.exists():
            file.write_bytes(raw)
    atomic_json(dest / "baseline.json", {"day": BASE_DAY, "positions": rows, "equity_candidates": candidates,
                                         "snapshot": {code.upper(): {"price": price, "quantity": qty}
                                                      for _, code, price, qty, _ in prices}})
