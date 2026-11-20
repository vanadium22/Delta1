"""Daily, catch-up and single-day company acceptance commands."""

import argparse
from collections import defaultdict
from datetime import date, datetime
import hashlib
import json
import os
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

from openpyxl import load_workbook

from dashboard.marketdata.trading_calendar import trading_days
from shared_data.io import atomic_json, file_lock
from shared_data.paths import DataPaths

from .baseline import ACCOUNTS, BASE_DAY, import_baseline
from .daily_cache import digest, funding_inputs, price_inputs, resume, save, unpack_day
from .ledger import POSITIONS, SUMMARY, ZERO, money, report, snapshot_checks
from .performance import PERIOD_COLUMNS, Performance, period_summary, sheet_rows
from .prices import resolve
from .seed import ARCHIVE_NAME, install_seed, make_seed
from .series import SERIES_FILENAME, write_series
from .sources import archive_missing, bct_credential_path, read_source, write_book


REPO = Path(__file__).resolve().parents[1]
STATE_VERSION = 1
DETAIL_STATUS = ("交易日", "账户", "检查说明")


def read_json(path, default=None):
    if default is not None and not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8-sig"))


def date_text(value):
    day = date.fromisoformat(value).isoformat()
    if day != value:
        raise ValueError(f"日期必须使用 YYYY-MM-DD：{value}")
    return day


def settlement_equities(path):
    if not path.is_file():
        return {}
    workbook = load_workbook(path, data_only=True, read_only=True)
    try:
        sheet = workbook.active
        sheet.reset_dimensions()
        rows = sheet.values
        header = next(rows, ())
        try:
            columns = tuple(header.index(name) for name in ("交易日", "账户", "总权益"))
        except ValueError as exc:
            raise ValueError(f"{path} 需要交易日、账户、总权益三列。") from exc
        values = {}
        for number, row in enumerate(rows, 2):
            if not any(value is not None for value in row):
                continue
            stamp, account, amount = (row[index] if index < len(row) else None for index in columns)
            day = date_text(str(stamp)[:10] if isinstance(stamp, (date, datetime)) else str(stamp))
            account = str(account).strip()
            key = day, account
            if day < BASE_DAY or account not in ACCOUNTS or key in values:
                raise ValueError(f"{path} 第 {number} 行的账户、日期或重复键有误。")
            values[key] = money(amount)
        return values
    finally:
        workbook.close()


def funding_config(config, settlement_file):
    opening = {}
    complete = {}
    movements = defaultdict(lambda: ZERO)
    weighted = defaultdict(lambda: ZERO)
    for account, values in config.get("accounts", {}).items():
        if account not in ACCOUNTS:
            raise ValueError(f"未知资金账户 {account}。")
        if values.get("opening_equity") is not None:
            opening[account] = money(values["opening_equity"])
        if values.get("cash_flows_confirmed_through") is not None:
            complete[account] = date_text(values["cash_flows_confirmed_through"])
    for entry in config.get("cash_movements", []):
        account = entry["account"]
        if account not in ACCOUNTS:
            raise ValueError(f"未知资金账户 {account}。")
        stamp = date_text(entry["date"])
        if stamp <= BASE_DAY:
            raise ValueError("入出金业务日必须在基准日之后。")
        amount = money(entry["net_deposit"])
        key = stamp, account
        movements[key] += amount
        weight = entry.get("weight")
        if weight is not None:
            weight = money(weight)
            if not ZERO <= weight <= 1:
                raise ValueError("资金流权重必须在 0 至 1 之间。")
        if amount and (weight is None or weighted[key] is None):
            weighted[key] = None
        elif weighted[key] is not None:
            weighted[key] += (weight or ZERO) * amount
    equity = settlement_equities(settlement_file)
    if any((BASE_DAY, account) in equity and equity[BASE_DAY, account] != amount for account, amount in opening.items()):
        raise ValueError("基准日结算单总权益与本机 opening_equity 不一致，请核对。")
    return {"opening": opening, "confirmed_through": complete, "movements": movements,
            "equity": equity, "weighted": weighted}


def snapshot_plan(days, target, previous_download):
    month_ends = {}
    for day in days:
        if day[:7] < target[:7]:
            month_ends[day[:7]] = day
    keep = set(month_ends.values())
    keep.add(target)
    if previous_download:
        keep.update(day for day in days if previous_download < day <= target)
    return keep


def value_days(root, days, selected, targets, baseline, config, funding, no_wind, ledger, entries, log_detail):
    source_days = sorted({BASE_DAY, *days})
    market = price_inputs(root, source_days, config)
    funds = funding_inputs(days, funding)
    candidates = {}
    cached = {}
    exposure = set()

    def signature(day, previous):
        return digest((market[day], market[previous], funds[day]))

    for day in sorted(targets):
        entry = entries[day]
        current = entry.get("valuation")
        previous = entry["frame"]["previous_date"]
        changed = not current or current["inputs"] != signature(day, previous)
        retry_missing = not no_wind and current and current["pending"] and day in selected
        if not changed:
            cached[day] = current
        if changed or retry_missing:
            frame = unpack_day(entry["frame"])
            keys = (frame.valuation_keys() if day in selected else {(day, code) for _, code in frame.after})
            keys = {key for key in keys if key[0] != BASE_DAY}
            exposure.update(keys)
            candidates[day] = frame, keys, changed

    if not candidates:
        print(f"本次沿用 {len(cached)} 个交易日已有盈亏。", flush=True)
        print(f"Wind 缓存目录：{root / 'wind'}", flush=True)
        print("Wind 新下载并保存：0 项（直接沿用已有盈亏）。", flush=True)
        return cached
    prices, source_errors = resolve(exposure, root, config, no_wind=no_wind, session_days=days, log_detail=log_detail)
    for message in source_errors:
        print(message, flush=True)
    market.update(price_inputs(root, sorted({day for day, _ in exposure}), config))
    valued = 0
    for day, (frame, keys, changed) in candidates.items():
        old = cached.get(day)
        if not changed and not any(tuple(key) in prices for key in old["pending"]):
            continue
        overview, detail, checks = report(frame, ledger, baseline, prices, funding)
        if day in selected:
            snapshot = root / "snapshots" / f"{day}.xlsx"
            if snapshot.is_file():
                checks.extend(snapshot_checks(frame, read_source(snapshot, "snapshot", day)))
            if any(row["status"] for row in overview):
                checks.extend((day, "行情", error) for error in source_errors[:10])
        data = {"rows": overview, "detail": detail, "checks": checks, "pending": sorted(keys - prices.keys()),
                "inputs": signature(day, frame.previous_date)}
        cached[day] = data
        if day in selected:
            entries[day]["valuation"] = data
            valued += 1
    print(f"本次计算或更新 {valued} 个交易日的盈亏。", flush=True)
    return cached


def export_reports(root, outputs, days, selected, baseline, config, no_wind, *, only_day=False, log_detail=False):
    funding = funding_config(config, root / "inputs" / "账户总权益.xlsx")
    trading_dates = set(days) | {BASE_DAY}
    dated_inputs = funding["movements"].keys() | funding["equity"].keys()
    if any(stamp <= days[-1] and stamp not in trading_dates for stamp, _ in dated_inputs):
        raise ValueError("入出金和结算权益请填写其实际归属的交易日。")
    full_history = not only_day
    targets = set(selected)
    if not full_history:
        anchor = next((day for day in reversed(days) if day[:4] < days[-1][:4]), None)
        if anchor:
            targets.add(anchor)
    ledger, cache = resume(root, days, baseline)
    facts = value_days(root, days, selected, targets, baseline, config, funding, no_wind, ledger, cache["days"], log_detail)
    report_state_path = root / "reports.json"
    report_state = read_json(report_state_path, {})
    all_summaries = []
    performance = Performance(funding, compound=full_history)
    for day in sorted(targets):
        data = facts[day]
        overview = performance.apply([row.copy() for row in data["rows"]])
        if day not in selected:
            continue
        output_path = outputs / f"场内账户_{day}.xlsx"
        tables = [("账户统计", SUMMARY, list(sheet_rows(overview))),
                  ("持仓明细", POSITIONS, data["detail"]), ("数据检查", DETAIL_STATUS, data["checks"])]
        fingerprint = hashlib.sha256(json.dumps(tables, ensure_ascii=False, default=str).encode()).hexdigest()
        if report_state.get(day) != fingerprint or not output_path.is_file():
            write_book(output_path, tables)
            report_state[day] = fingerprint
        all_summaries.extend(overview)
    if full_history:
        from .charts import CHART_VERSION, write_charts

        history_path = outputs / "逐交易日统计.xlsx"
        series_path = outputs / SERIES_FILENAME
        periods, annual = period_summary(all_summaries)
        fingerprint = hashlib.sha256(json.dumps((CHART_VERSION, all_summaries),
                                                ensure_ascii=False, default=str).encode()).hexdigest()
        images = [outputs / name for name in ("历史至今_账户收益.png", f"{days[-1][:4]}年_账户收益.png")]
        if report_state.get("_performance") != fingerprint or not history_path.is_file() or not all(p.is_file() for p in images):
            write_book(history_path, [("收益概览", PERIOD_COLUMNS, periods),
                                      ("逐交易日统计", SUMMARY, sheet_rows(all_summaries)),
                                      ("今年逐日", SUMMARY, sheet_rows(annual))])
            write_charts(images, all_summaries, annual)
            write_series(series_path, all_summaries)
            report_state["_performance"] = fingerprint
        elif not series_path.is_file():
            write_series(series_path, all_summaries)
        print(f"历史统计：{history_path}", flush=True)
        print(f"账户收益数据：{series_path}", flush=True)
        for path in images:
            print(f"收益图：{path}", flush=True)
    save(root, cache)
    atomic_json(report_state_path, report_state)
    print(f"本次目标日：{outputs / ('场内账户_' + days[-1] + '.xlsx')}", flush=True)
    pnl_ready = sum(row["pnl"] is not None for row in overview[:-1])
    print(f"目标日有盈亏数值的账户：{pnl_ready}/{len(ACCOUNTS)}；"
          f"有已核实输入的总权益：{sum(row['equity'] is not None for row in overview[:-1])}/{len(ACCOUNTS)}", flush=True)
    return pnl_ready == len(ACCOUNTS)


def run(args, root, outputs, now):
    implicit_seed = Path(__file__).with_name(ARCHIVE_NAME)
    seed_path = args.seed
    company_run = getattr(args, "company_run", False)
    if seed_path is None and not (root / "download_state.json").is_file():
        if implicit_seed.is_file():
            seed_path = implicit_seed
        elif company_run and not (root / "inputs" / "baseline.json").is_file():
            from .setup_daily import input_directories

            seed_path = next((folder / ARCHIVE_NAME for folder in input_directories(root)
                              if (folder / ARCHIVE_NAME).is_file()), None)
    if seed_path:
        install_seed(root, seed_path)
    if args.import_archive:
        import_baseline(root, args.import_archive)
    baseline_path = root / "inputs" / "baseline.json"
    if not baseline_path.is_file():
        raise FileNotFoundError(f"缺少基准持仓。请把 {ARCHIVE_NAME} 放到启动文件旁，或用 --seed 指定历史包。")
    baseline = read_json(baseline_path)
    if baseline["day"] != BASE_DAY:
        raise ValueError("基准日与项目设置不一致。")
    calendar_root = root / "calendar"
    calendar_root.mkdir(parents=True, exist_ok=True)
    days, latest = trading_days("2025-12-30", now.date(), calendar_root)
    target = date_text(args.date) if args.date else latest
    if target not in days:
        raise ValueError(f"{target} 必须是基准日之后、运行日前已完成的交易日。")
    days = [day for day in days if day <= target]
    print(f"本次统计截止 {target}，自基准日共 {len(days)} 个交易日。", flush=True)

    config_file = args.config or root / "inputs" / "config.local.json"
    config = read_json(config_file, {})
    if getattr(args, "setup_daily", False):
        from .setup_daily import configure_daily

        configure_daily(REPO, root, outputs, config, args)
    state_path = root / "download_state.json"
    state = read_json(state_path, {"version": STATE_VERSION})
    if state.get("version") != STATE_VERSION:
        raise ValueError("下载状态版本无法识别。")
    previous = state.get("latest_live_snapshot")
    snapshots = snapshot_plan(days, target, previous)
    if not args.no_download:
        credentials = bct_credential_path(root, config, args.bct_script)
        if company_run or getattr(args, "scheduled", False):
            from functools import partial
            from .setup_daily import configure_credentials

            client = partial(configure_credentials, root, config, args.bct_script,
                             allow_picker=company_run)
            archive_missing(root, days, snapshots, credentials, client_factory=client)
        else:
            archive_missing(root, days, snapshots, credentials)
        if not previous or target > previous:
            atomic_json(state_path, {"version": STATE_VERSION, "latest_live_snapshot": target})
    if args.make_seed:
        make_seed(root, args.make_seed.resolve(), days, snapshots, target)
    if args.prepare:
        print(f"历史 Excel 和基准输入目录：{root}", flush=True)
        return
    complete = export_reports(root, outputs, days, {target} if args.only_day else set(days), baseline, config,
                              args.no_wind, only_day=args.only_day, log_detail=getattr(args, "wind_log_detail", False))
    strategy_complete = True
    if not args.only_day and not args.skip_strategy:
        from .strategy_reconciliation import publish_strategy

        strategy_complete = publish_strategy(REPO, root, outputs, days, source_dir=args.strategy_source_dir,
                                             local_only=args.no_download)
        if not strategy_complete:
            print("账户收益已生成，策略台对账等待可读日报。", flush=True)
    if not complete and (company_run or getattr(args, "scheduled", False) or getattr(args, "setup_daily", False)):
        print("日报已保存，但目标日盈亏缺项。请查看日报的数据检查，补齐后可重跑。", flush=True)
        return 2
    return 0 if strategy_complete else 2


def main(argv=None):
    paths = DataPaths.for_repo(REPO)
    parser = argparse.ArgumentParser(description="三账户场内持仓与收益日更")
    parser.add_argument("--date", help="显式指定一个已完成交易日，默认前一个交易日")
    parser.add_argument("--only-day", action="store_true", help="仅导出目标日，优先续用已有日终持仓")
    parser.add_argument("--prepare", action="store_true", help="仅准备输入 Excel")
    parser.add_argument("--no-download", action="store_true", help="仅使用现有 BCT 和策略台日报文件")
    parser.add_argument("--no-wind", action="store_true", help="仅使用已有行情，不调用 Wind")
    parser.add_argument("--wind-log-detail", action="store_true", help="列出 Wind 行情复用、新下载和仍待补的标的日")
    parser.add_argument("--strategy-source-dir", type=Path, help="读取手动保存的策略台日报目录")
    parser.add_argument("--skip-strategy", action="store_true", help="本次仅生成账户收益")
    parser.add_argument("--data", type=Path, default=paths.root / "account_daily_pnl")
    parser.add_argument("--output", type=Path, default=paths.export("account_daily_pnl"))
    parser.add_argument("--config", type=Path, help="本机行情或资金设置")
    parser.add_argument("--import-archive", type=Path, help="从用户指定 ZIP 读取基准持仓")
    parser.add_argument("--bct-script", type=Path, help="读取本机可信 BCT 脚本或 ZIP 的登录设置")
    parser.add_argument("--seed", type=Path, help="核验并导入本地历史数据包")
    parser.add_argument("--make-seed", type=Path, help="打包基准和目标日以前的历史 Excel")
    parser.add_argument("--setup-daily", action="store_true", help="首次配置 BCT 并登记工作台日更任务")
    parser.add_argument("--work-root", type=Path, help="显式指定工作自动化工作台目录")
    parser.add_argument("--task-time", default="09:25", help="登记时间，北京时间，默认 09:25")
    parser.add_argument("--wa-output", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--scheduled", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--company-run", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--no-pause", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.wa_output and (args.only_day or args.prepare or args.skip_strategy):
        parser.error("邮件任务需要完整账户及策略台对账。")
    print(f"Python：{sys.executable}", flush=True)
    try:
        with file_lock(args.data / ".writer.lock", timeout=3):
            result = run(args, args.data.resolve(), args.output.resolve(), datetime.now(ZoneInfo("Asia/Shanghai"))) or 0
            if result == 0 and args.wa_output:
                from .daily_mail import create_manifest

                atomic_json(args.wa_output, create_manifest(args.output))
            return result
    except Exception as exc:
        print(f"运行失败：{exc}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
