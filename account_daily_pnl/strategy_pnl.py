"""Summarize the strategy desk's contract rows from one dated report."""

import argparse
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
import re
import sys
import unicodedata

from openpyxl import load_workbook

from dashboard.marketdata.trading_calendar import trading_days
from script_making.downloads import archive_path, discover, file_date, sync_download, validate_report
from script_making.storage import ReportError, Settings, today
from shared_data.io import atomic_json, sha256
from shared_data.paths import DataPaths

from .series import SERIES_FILENAME, load_series


REPO = Path(__file__).resolve().parents[1]
DESK = "策略部交易台"
SHEET = "合约信息"
FUTURES, ETF, STOCK, INDEX_ETF, OTHER_ETF = GROUPS = (
    "股指期货", "全部ETF", "个股", "50/300/500/1000指数ETF", "其他ETF",
)
SNAPSHOT_VERSION = 2
INDEXES = {"50": "上证50", "300": "沪深300", "500": "中证500", "1000": "中证1000"}
REALIZED = ("已实现资产收益_结算货币", "已实现利率收益_结算货币")
UNREALIZED = ("待实现资产收益_结算货币", "待实现利率收益_结算货币")
FIELDS = ("交易对手名称", "起始日", "标的物代码", "标的物名称", "交易货币", *REALIZED, *UNREALIZED)


@dataclass
class Totals:
    rows: int = 0
    realized: Decimal = Decimal(0)
    unrealized: Decimal = Decimal(0)

    def add(self, realized, unrealized):
        self.rows += 1
        self.realized += realized
        self.unrealized += unrealized

    def as_dict(self):
        return {"rows": self.rows, "realized": format(self.realized, "f"),
                "unrealized": format(self.unrealized, "f")}


def classify(code, name):
    if re.fullmatch(r"(?:IF|IH|IC|IM)\d{4}\.CFE", code):
        return FUTURES, None
    if re.fullmatch(r"(?:5\d{5}\.SH|1[56]\d{4}\.SZ|\d{4,5}\.HK)", code):
        normalized = re.sub(r"\s+", "", unicodedata.normalize("NFKC", name).upper())
        if "联接" not in normalized and ("ETF" in normalized or "交易型开放式指数" in normalized):
            shorthand = re.match(r"^(50|300|500|1000)(?:指数)?ETF", normalized)
            index = INDEXES[shorthand[1]] if shorthand else next(
                (label for label in INDEXES.values() if re.search(
                    rf"{label}(?:指数)?(?:增强)?(?:ETF|交易型开放式指数)", normalized)), None)
            return ETF, index
    if re.fullmatch(r"(?:(?:60|68|90)\d{4}\.SH|(?:00|20|30)\d{4}\.SZ|\d{6}\.BJ)", code):
        return STOCK, None
    return None, None


def amount(row, fields, row_number):
    result = Decimal(0)
    for field in fields:
        value = row[field]
        number = Decimal(str(value)) if type(value) in (int, float) else None
        if number is None or not number.is_finite():
            raise ReportError(f"{SHEET}第 {row_number} 行「{field}」缺少有效数值。")
        result += number
    return result


def summarize(path):
    day = file_date(path.name, "strategy")
    if day is None:
        raise ReportError("日报文件须使用原始文件名 D1策略台日报_YYYY-MM-DD.xlsx。")
    fingerprint = sha256(path)
    validate_report(path, "strategy", day)
    book = load_workbook(path, read_only=True, data_only=True, keep_links=False)
    totals = {group: Totals() for group in GROUPS}
    indexes = {index: Totals() for index in INDEXES.values()}
    daily = defaultdict(lambda: defaultdict(Totals))
    unclassified = []
    try:
        if SHEET not in book.sheetnames:
            raise ReportError(f"日报缺少「{SHEET}」工作表。")
        sheet = book[SHEET]
        sheet.reset_dimensions()
        rows = sheet.iter_rows(min_row=2, values_only=True)
        header = tuple(str(value or "").strip() for value in next(rows, ()))
        for field in FIELDS:
            if header.count(field) != 1:
                raise ReportError(f"{SHEET}第 2 行须有唯一的「{field}」列。")
        columns = {field: header.index(field) for field in FIELDS}
        for row_number, values in enumerate(rows, 3):
            row = {field: values[i] if i < len(values) else None for field, i in columns.items()}
            if str(row["交易对手名称"] or "").strip() != DESK:
                continue
            code = str(row["标的物代码"] or "").strip().upper()
            name = str(row["标的物名称"] or "").strip()
            group, index = classify(code, name)
            if group is None:
                unclassified.append({"row": row_number, "code": code, "name": name})
                continue
            start = row["起始日"]
            try:
                start = start.date() if isinstance(start, datetime) else date.fromisoformat(str(start).strip())
            except ValueError as exc:
                raise ReportError(f"{SHEET}第 {row_number} 行「起始日」无效。") from exc
            if str(row["交易货币"]).strip().upper() != "CNY":
                raise ReportError(f"{SHEET}第 {row_number} 行的交易货币需要核对结算币种后再汇总。")
            earnings = amount(row, REALIZED, row_number), amount(row, UNREALIZED, row_number)
            categories = (ETF, INDEX_ETF if index else OTHER_ETF) if group == ETF else (group,)
            for category in categories:
                totals[category].add(*earnings)
                daily[start][category].add(*earnings)
            if index:
                indexes[index].add(*earnings)
    finally:
        book.close()
    if sha256(path) != fingerprint:
        raise ReportError("统计期间日报已更新，请重新运行。")
    return {"schema_version": SNAPSHOT_VERSION, "report_date": day.isoformat(), "source_sha256": fingerprint,
            "currency": "CNY", "counterparty": DESK,
            "desk_rows": sum(totals[group].rows for group in (FUTURES, ETF, STOCK)) + len(unclassified),
            "totals": {group: totals[group].as_dict() for group in GROUPS},
            "index_etfs": {index: totals.as_dict() for index, totals in indexes.items()},
            "by_start_date": {start.isoformat(): {group: sums.as_dict() for group, sums in groups.items()}
                              for start, groups in sorted(daily.items())},
            "unclassified": unclassified}


def latest_report(paths, as_of, source_dir=None):
    _, expected = trading_days(as_of, as_of, paths.root / "account_daily_pnl" / "calendar")
    if source_dir is not None:
        candidates, errors = discover(source_dir, "strategy", as_of - timedelta(days=14), as_of)
        target = date.fromisoformat(expected)
        if candidates and max(candidates) == target and len(candidates[target]) == 1:
            return candidates[target][0], "local_directory"
        observed = max(candidates).isoformat() if candidates else "未找到"
        detail = "；".join(errors)
        raise ReportError(f"本地目录未找到唯一的最新日报。应为 {expected}，观察到 {observed}。{detail}")

    settings = Settings(paths.repo_root / "script_making")
    result = sync_download(settings, "strategy", as_of)
    observed = result["source_latest"] or "未找到"
    confirmed = result["saved"] + result["updated"] + result["reused"]
    if observed != expected or expected not in confirmed:
        detail = "；".join(result["errors"])
        raise ReportError(f"同步未确认最新日报。应为 {expected}，来源最新日期 {observed}。{detail}")
    return archive_path(settings, "strategy") / expected / f"D1策略台日报_{expected}.xlsx", "company_sync"


def account_coverage(path, report_date):
    if not path.is_file():
        return None
    series = load_series(path)
    return {"through": series["through"],
            "has_report_date": any(row["trading_date"] == report_date for row in series["rows"])}


def main(argv=None):
    parser = argparse.ArgumentParser(description="统计策略部交易台合约收益")
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--source-dir", type=Path, help="检查手动下载目录是否有最新交易日的日报")
    source.add_argument("--workbook", type=Path, help="复查指定历史日报，仅核对文件名与表内日期")
    parser.add_argument("--output", type=Path, help="指定统计 JSON 路径")
    args = parser.parse_args(argv)
    try:
        paths = DataPaths.for_repo(REPO)
        if args.workbook:
            workbook, freshness = args.workbook, "historical_replay"
        else:
            workbook, freshness = latest_report(paths, today(), args.source_dir)
        result = summarize(workbook)
        result["source_file"] = workbook.name
        result["freshness"] = freshness
        output_root = paths.export("account_daily_pnl")
        result["account_series"] = account_coverage(output_root / SERIES_FILENAME, result["report_date"])
        output = args.output
        if output is None and not args.workbook:
            output = output_root / f"strategy_contract_pnl_{result['report_date']}.json"
        if output is not None:
            if output.suffix.lower() != ".json" or output.resolve() == (output_root / SERIES_FILENAME).resolve():
                raise ReportError("策略台统计需使用独立的 JSON 输出路径。")
            atomic_json(output, result)
            print(f"统计已保存：{output.resolve()}")
        print(f"日报日期 {result['report_date']}，策略部交易台 {result['desk_rows']} 行，"
              f"未分类 {len(result['unclassified'])} 行。")
        for group, metric in result["totals"].items():
            print(f"{group} {metric['rows']} 行，已实现 {Decimal(metric['realized']):,.2f} 元，"
                  f"待实现 {Decimal(metric['unrealized']):,.2f} 元")
        return 0
    except (OSError, ValueError) as exc:
        print(f"统计失败：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
