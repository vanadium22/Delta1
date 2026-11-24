"""Compare same-day strategy report PnL with account 5526 after account publication."""

from datetime import date
from decimal import Decimal
import json

from script_making.storage import ReportError
from shared_data.io import atomic_json, sha256

from .baseline import BASE_DAY
from .ledger import rounded, total
from .series import SERIES_FILENAME, load_series
from .sources import write_book
from .strategy_pnl import (
    FUTURES, INDEX_ETF, OTHER_ETF, SNAPSHOT_VERSION, STOCK, WORKBOOK_ERRORS, source_reports, summarize,
)


BOOK_NAME = "策略台PnL对账.xlsx"
CHART_NAME = "策略台PnL对账.png"
METRICS = (
    ("stocks", "个股"),
    ("etf", "全部ETF"),
    ("index_etf", "　指数ETF（50/300/500/1000）"),
    ("other_etf", "　其他ETF"),
    ("excel_futures", "Excel股指期货"),
    ("actual_futures", "5526实盘净盈亏"),
    ("difference", "股指差额（5526 − Excel）"),
    ("excel_total", "Excel原口径合计"),
    ("replacement", "替换后合计"),
)
CURVES = {name: label for name, label in METRICS if name in {"excel_futures", "actual_futures"}}
RULES = (
    ("策略台日报", "交易对手为策略部交易台。按日报交易日对齐，起始日用于合约明细汇总。"),
    ("日报日期", "使用最近一个有可读日报且有同日 5526 日净盈亏的交易日。"),
    ("Excel 日 PnL", "相邻交易日报的累计余额差。余额为已实现及待实现的资产和利率收益之和。"),
    ("Excel 年内累计", "本日报余额减上年最后一份应有交易日报余额。前提是两期报表覆盖及累计口径一致。"),
    ("2025年覆盖", "与账户基准一致，自 2025-12-29 收盘起算，仅覆盖基准后的交易日。"),
    ("5526", "每日和年内累计分别沿用账户收益 JSON 的 net_pnl 和 ytd_net_pnl，金额为净盈亏。"),
    ("合计", "原口径为个股＋全部ETF＋Excel股指期货。替换后为个股＋全部ETF＋5526实盘净盈亏。"),
    ("缺数据", "空白表示缺数。日度需要相邻交易日，年内累计需要上年末基准与当前日报。"),
)


def load_snapshots(paths, days, cache_path, account_days):
    try:
        cache = json.loads(cache_path.read_text(encoding="utf-8"))
        cached = cache["days"] if cache["version"] == SNAPSHOT_VERSION and isinstance(cache["days"], dict) else {}
    except (OSError, ValueError, KeyError, TypeError):
        cached = {}
    snapshots, notes, latest = {}, [], None
    for day in reversed(days):
        if day not in paths:
            continue
        try:
            previous = cached.get(day, {})
            is_candidate = latest is None and day in account_days
            if not is_candidate and isinstance(previous, dict) and previous.get("source_sha256") == sha256(paths[day]):
                snapshots[day] = previous
                continue
            report = summarize(paths[day])
            snapshots[day] = {"source_sha256": report["source_sha256"], "totals": report["totals"],
                              "unclassified": len(report["unclassified"])}
            if is_candidate:
                latest = report
        except WORKBOOK_ERRORS as exc:
            notes.append((day, f"日报读取失败。{exc}"))
    atomic_json(cache_path, {"version": SNAPSHOT_VERSION, "days": cached | snapshots})
    return snapshots, latest, notes


def comparisons(current, anchor, account_value):
    def delta(group):
        if current is None or anchor is None:
            return None
        now, then = current["totals"][group], anchor["totals"][group]
        return sum((Decimal(now[key]) - Decimal(then[key]) for key in ("realized", "unrealized")), Decimal(0))

    stocks, index, other, futures = (delta(group) for group in (STOCK, INDEX_ETF, OTHER_ETF, FUTURES))
    etf = total([index, other])
    actual = Decimal(account_value) if account_value is not None else None
    difference = actual - futures if actual is not None and futures is not None else None
    return {"stocks": stocks, "etf": etf, "index_etf": index, "other_etf": other,
            "excel_futures": futures, "actual_futures": actual, "difference": difference,
            "excel_total": total([stocks, etf, futures]), "replacement": total([stocks, etf, actual])}


def reconcile(days, snapshots, accounts):
    results = []
    previous = year_anchor = BASE_DAY
    for day in days:
        if day[:4] != previous[:4]:
            year_anchor = previous
        current = snapshots.get(day)
        account = accounts.get(day, {})
        daily = comparisons(current, snapshots.get(previous), account.get("net_pnl"))
        annual = comparisons(current, snapshots.get(year_anchor), account.get("ytd_net_pnl"))
        notes = []
        if current is None:
            notes.append(f"缺有效日报 {day}")
        if previous not in snapshots:
            notes.append(f"缺日度基准 {previous}")
        if year_anchor != previous and year_anchor not in snapshots:
            notes.append(f"缺年内基准 {year_anchor}")
        if daily["actual_futures"] is None:
            notes.append("5526日净盈亏缺项")
        if annual["actual_futures"] is None:
            notes.append("5526年内净盈亏缺项")
        if day[:4] == BASE_DAY[:4]:
            notes.append(f"账户基准后累计（{BASE_DAY}收盘起）")
        if current and current["unclassified"]:
            notes.append(f"日报有 {current['unclassified']} 行不在已识别分类")
        results.append({"day": day, "daily": daily, "annual": annual, "notes": notes})
        previous = day
    return results


def publish_strategy(repo, root, outputs, days, *, source_dir=None, local_only=False):
    target = days[-1]
    series = load_series(outputs / SERIES_FILENAME, required_through=target)
    accounts = {row["trading_date"]: row for row in series["rows"] if row["account_id"] == "5526"}
    requested = [BASE_DAY, *days]
    try:
        paths, source_notes = source_reports(repo, requested, source_dir, local_only)
    except (OSError, ReportError) as exc:
        paths, source_notes = {}, [(target, f"日报来源读取失败。{exc}")]
    account_days = {day for day, row in accounts.items() if row["net_pnl"] is not None}
    snapshots, latest, snapshot_notes = load_snapshots(paths, requested, root / "strategy_contract_cache.json", account_days)
    if latest is None:
        print(f"截至 {target} 未找到同时有可读策略台日报及 5526 日净盈亏的交易日。", flush=True)
        for _, note in [*source_notes[-3:], *snapshot_notes[:3]]:
            print(f"策略台数据检查：{note}", flush=True)
        return None
    report_day = latest["report_date"]
    selection = f"账户截止 {target}，对账使用 {report_day} 日报及同日 5526。"
    print(selection, flush=True)
    if report_day < target:
        source_notes.append((target, f"使用最近可对账交易日。{selection}"))
        source_notes.extend((day, "日报可读，同日 5526 日净盈亏待补。")
                            for day in days if day > report_day and day in snapshots and day not in account_days)
    timeline = reconcile([day for day in days if day <= report_day], snapshots, accounts)
    current = timeline[-1]
    latest_by_year = {row["day"][:4]: row for row in timeline}
    summary = [(label, rounded(current["daily"][key]), rounded(current["annual"][key])) for key, label in METRICS]

    def table_row(row, period):
        return (date.fromisoformat(row["day"]), *(rounded(row[period][key]) for key, _ in METRICS),
                "；".join(row["notes"]))

    metrics_columns = tuple(label.strip() for _, label in METRICS)
    columns = ("交易日", *metrics_columns, "状态")
    summary_columns = (f"项目 · {report_day}", "当日（元）", "年内累计（元）")
    start_columns = ("起始日", "类别", "明细行数", "已实现余额（元）", "待实现余额（元）")
    source_checks = [(date.fromisoformat(day), note) for day, note in source_notes + snapshot_notes]
    checks = [(date.fromisoformat(row["day"]), note) for row in timeline for note in row["notes"]]
    start_rows = []
    for stamp, groups in latest["by_start_date"].items():
        for group, sums in groups.items():
            start_rows.append((date.fromisoformat(stamp), group, sums["rows"],
                               rounded(Decimal(sums["realized"])), rounded(Decimal(sums["unrealized"]))))
    tables = [
        ("收益汇总", summary_columns, summary),
        ("每日PnL", columns, (table_row(row, "daily") for row in timeline)),
        ("年内累计", columns, (table_row(row, "annual") for row in timeline)),
        ("年度汇总", ("年度", *columns), ((year, *table_row(row, "annual")) for year, row in latest_by_year.items())),
        ("合约起始日", start_columns, start_rows),
        ("数据检查", ("交易日", "检查说明"), [*source_checks, *checks]),
        ("计算口径", ("项目", "检查说明"), RULES),
    ]
    workbook = outputs / BOOK_NAME
    write_book(workbook, tables, column_widths={summary_columns[0]: 36, "类别": 32, "检查说明": 80},
               number_formats=dict.fromkeys((*summary_columns[1:], *metrics_columns, *start_columns[-2:]), "#,##0.00"))

    from .charts import write_strategy_chart

    chart = outputs / CHART_NAME
    chart_rows = [{"day": row["day"], "account": label, "pnl": row["daily"][key],
                  "ytd_pnl": row["annual"][key]} for row in timeline if row["day"][:4] == report_day[:4]
                  for key, label in CURVES.items()]
    write_strategy_chart(chart, chart_rows, summary)
    print(f"策略台对账：{workbook}", flush=True)
    print(f"策略台对账图：{chart}", flush=True)
    for _, note in [*source_notes[-3:], *snapshot_notes[:3]]:
        print(f"策略台数据检查：{note}", flush=True)
    if current["notes"]:
        print(f"策略台 {report_day}：{'；'.join(current['notes'])}", flush=True)
    return report_day
