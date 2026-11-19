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

from dashboard.marketdata.trading_calendar import trading_days
from shared_data.io import atomic_json, file_lock
from shared_data.paths import DataPaths

from .baseline import ACCOUNTS, BASE_DAY, import_baseline
from .ledger import Ledger, POSITIONS, SUMMARY, ZERO, money, report, snapshot_checks
from .prices import resolve
from .seed import ARCHIVE_NAME, install_seed, make_seed
from .sources import archive_missing, read_source, write_book


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


def funding_config(config):
    opening = {}
    complete = {}
    movements = defaultdict(lambda: ZERO)
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
        movements[stamp, account] += money(entry["net_deposit"])
    return {"opening": opening, "confirmed_through": complete, "movements": movements}


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


def replay(root, days, baseline, targets):
    ledger = Ledger(baseline)
    frames = []
    previous_day = baseline["day"]
    for index, day in enumerate(days, 1):
        archive = root / "flows" / f"{day}.xlsx"
        if not archive.is_file():
            raise FileNotFoundError(f"缺少交易日 {day} 的流水 Excel：{archive}")
        rows = read_source(archive, "flow", day)
        rows.sort(key=lambda row: (str(row.get("dealDate")), str(row.get("dealTime")), str(row["id"])))
        frame = ledger.advance(day, previous_day, rows)
        if day in targets:
            frames.append(frame)
        previous_day = day
        if index % 30 == 0 or index == len(days):
            print(f"持仓回放 {index}/{len(days)} 个交易日，已到 {day}", flush=True)
    return ledger, frames


def export_reports(root, outputs, days, selected, baseline, config, no_wind):
    funding = funding_config(config)
    ledger, frames = replay(root, days, baseline, selected)
    exposure = set().union(*(frame.valuation_keys() for frame in frames))
    exposure = {key for key in exposure if key[0] != baseline["day"]}
    prices, source_errors = resolve(exposure, root, config, no_wind=no_wind)
    for message in source_errors:
        print(message, flush=True)
    report_state_path = root / "reports.json"
    report_state = read_json(report_state_path, {})
    changed = False
    all_summaries = []
    for frame in frames:
        overview, detail, checks = report(frame, ledger, baseline, prices, funding)
        day = frame.date
        snapshot = root / "snapshots" / f"{day}.xlsx"
        if snapshot.is_file():
            checks.extend(snapshot_checks(frame, read_source(snapshot, "snapshot", day)))
        if any(row[-1] for row in overview):
            checks.extend((day, "行情", error) for error in source_errors[:10])
        output_path = outputs / f"场内账户_{day}.xlsx"
        tables = [("账户统计", SUMMARY, overview), ("持仓明细", POSITIONS, detail), ("数据检查", DETAIL_STATUS, checks)]
        fingerprint = hashlib.sha256(json.dumps(tables, ensure_ascii=False, default=str).encode()).hexdigest()
        if report_state.get(day) != fingerprint or not output_path.is_file():
            write_book(output_path, tables)
            report_state[day] = fingerprint
            changed = True
        all_summaries.extend(overview)
    if selected == set(days):
        history_path = outputs / "逐交易日统计.xlsx"
        if changed or not history_path.is_file() or report_state.get("_history_through") != frames[-1].date:
            write_book(history_path, [("逐交易日统计", SUMMARY, all_summaries)])
            report_state["_history_through"] = frames[-1].date
        print(f"历史统计：{history_path}", flush=True)
    elif changed:
        report_state.pop("_history_through", None)
    atomic_json(report_state_path, report_state)
    print(f"本次目标日：{outputs / ('场内账户_' + frames[-1].date + '.xlsx')}", flush=True)
    print(f"目标日有盈亏数值的账户：{sum(row[4] is not None for row in overview[:-1])}/{len(ACCOUNTS)}；"
          f"有已核实输入的总权益：{sum(row[6] is not None for row in overview[:-1])}/{len(ACCOUNTS)}", flush=True)


def run(args, root, outputs, now):
    implicit_seed = Path(__file__).with_name(ARCHIVE_NAME)
    if args.seed or not (root / "download_state.json").is_file() and implicit_seed.is_file():
        install_seed(root, args.seed or implicit_seed)
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
    state_path = root / "download_state.json"
    state = read_json(state_path, {"version": STATE_VERSION})
    if state.get("version") != STATE_VERSION:
        raise ValueError("下载状态版本无法识别。")
    previous = state.get("latest_live_snapshot")
    snapshots = snapshot_plan(days, target, previous)
    if not args.no_download:
        credentials = args.bct_script or config.get("bct_script") or os.environ.get("BCT_CREDENTIALS_SCRIPT")
        archive_missing(root, days, snapshots, credentials)
        if not previous or target > previous:
            atomic_json(state_path, {"version": STATE_VERSION, "latest_live_snapshot": target})
    if args.make_seed:
        make_seed(root, args.make_seed.resolve(), days, snapshots, target)
    if args.prepare:
        print(f"历史 Excel 和基准输入目录：{root}", flush=True)
        return
    export_reports(root, outputs, days, {target} if args.only_day else set(days), baseline, config, args.no_wind)


def main(argv=None):
    paths = DataPaths.for_repo(REPO)
    parser = argparse.ArgumentParser(description="三账户场内持仓与收益日更")
    parser.add_argument("--date", help="显式指定一个已完成交易日，默认前一个交易日")
    parser.add_argument("--only-day", action="store_true", help="仅导出目标日，仍回放历史持仓")
    parser.add_argument("--prepare", action="store_true", help="仅准备输入 Excel")
    parser.add_argument("--no-download", action="store_true", help="仅使用现有 BCT 文件")
    parser.add_argument("--no-wind", action="store_true", help="仅使用已有行情，不调用 Wind")
    parser.add_argument("--data", type=Path, default=paths.root / "account_daily_pnl")
    parser.add_argument("--output", type=Path, default=paths.export("account_daily_pnl"))
    parser.add_argument("--config", type=Path, help="本机行情或资金设置")
    parser.add_argument("--import-archive", type=Path, help="从用户指定 ZIP 读取基准持仓")
    parser.add_argument("--bct-script", type=Path, help="读取本机可信 BCT 脚本或 ZIP 的登录设置")
    parser.add_argument("--seed", type=Path, help="核验并导入本地历史数据包")
    parser.add_argument("--make-seed", type=Path, help="打包基准和目标日以前的历史 Excel")
    parser.add_argument("--no-pause", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    try:
        with file_lock(args.data / ".writer.lock", timeout=3):
            run(args, args.data.resolve(), args.output.resolve(), datetime.now(ZoneInfo("Asia/Shanghai")))
    except Exception as exc:
        print(f"运行失败：{exc}", file=sys.stderr, flush=True)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
