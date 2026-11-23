"""Run the offline brief in an isolated batch and record shareable input coverage."""
import argparse
from datetime import date, datetime, timedelta, timezone
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
import subprocess
import sys
import traceback
from uuid import uuid4

UNBOUND_LABELS = {
    "no_business_day_mapping": "缺表日映射",
    "invalid_contract_code": "实际合约代码异常",
    "invalid_effective_date": "生效时间早于表日",
}


def describe_inputs(write, panel, info, end, source):
    write(f"行情 {panel.trade_date.min():%Y-%m-%d} 至 {end:%Y-%m-%d}，"
          f"来源 {source['kind']} / {Path(source['path']).name}，共 {len(panel)} 条合约日记录")
    matched = (panel.loc[panel.dividend_points.notna(), "dividend_source_sha256"].value_counts()
               if "dividend_source_sha256" in panel else {})
    inventory = info.get("input_inventory", [])
    observable = panel.futures_close.notna() & panel.spot_close.notna()
    write(f"合计  有期现价 {observable.sum()}  缺分红 {(observable & panel.dividend_points.isna()).sum()}")
    estimates = panel.loc[observable & panel.get("dividend_is_estimated", False)]
    interpolated = (estimates.dividend_interpolation.notna().sum() if "dividend_interpolation" in estimates else 0)
    write(f"分红估算 {len(estimates)} 条  其中插值 {interpolated} 条  当日 {estimates.trade_date.eq(end).sum()} 条")
    if not estimates.empty:
        borrowed = estimates[estimates.instrument_id.ne(estimates.dividend_source_contract)]
        substitutions = borrowed.groupby(["instrument_id", "dividend_source_contract"]).size()
        if not substitutions.empty:
            write("  估算目标 ← 来源合约及条数  " + "  ".join(
                f"{target} ← {donor} {count}" for (target, donor), count in substitutions.items()))
    write(f"发现 {len(inventory)} 份 Excel；下列采用数按合约×行情日计数")
    for entry in inventory:
        name = Path(entry["path"]).name
        if "error" in entry:
            write(f"  {name}  读取失败  {entry['error']}")
        elif "duplicate_of" in entry:
            write(f"  {name}  与 {Path(entry['duplicate_of']).name} 内容相同，合并计算")
        else:
            write(f"  {name}  表日 {entry['snapshot_date']}  档位 {entry['slots']}  "
                  f"有效G {entry['valid_points']}  可绑定 {entry['bound_rows']}  "
                  f"采用 {matched.get(entry['sha256'], 0)}")
            issues = [f"{UNBOUND_LABELS[key]} {n}" for key, n in entry.get("rejected_rows", {}).items()]
            if entry["slots"] > entry["valid_points"]:
                issues.append(f"G列缺失或无有效缓存 {entry['slots'] - entry['valid_points']}")
            if entry.get("mapped_from_history"):
                issues.append(f"使用表日实际合约映射 {entry['mapped_from_history']}")
            if issues:
                write("    " + "  ".join(issues))
    for item in info.get("source_errors", []):
        if Path(item["path"]).suffix.lower() != ".xlsx":
            write(f"  {Path(item['path']).name}  读取失败  {item['error']}")
    write("逐月缺口（行情日×档位，有期现价格时才计缺分红）")
    for month, group in panel.groupby(panel.trade_date.dt.to_period("M")):
        observable = group.futures_close.notna() & group.spot_close.notna()
        missing = observable & group.dividend_points.isna()
        conflicts = (missing & group.dividend_match.eq("conflicting_same_effective_time")
                     if "dividend_match" in group else missing & False)
        write(f"  {month}  有期现价 {observable.sum()}/{len(group)}  "
              f"缺分红 {missing.sum()}（其中同刻冲突 {conflicts.sum()}）  "
              f"未知日历 {group.loc[~group.calendar_known.eq(True), 'trade_date'].nunique()} 日")
        if missing.any():
            gaps = group.loc[missing].groupby("instrument_id", as_index=False).agg(
                count=("trade_date", "size"), first=("trade_date", "min"), last=("trade_date", "max"))
            write("    缺分红合约、条数及首末日期  " + "  ".join(
                f"{row.instrument_id} {row.count}（{row.first:%m-%d} 至 {row.last:%m-%d}）"
                for row in gaps.itertuples(index=False)))


def run(args, folder):
    folder.mkdir(parents=True, exist_ok=False)
    report = folder / "简报测试报告.txt"
    print(f"测试报告：{report}", flush=True)
    with report.open("w", encoding="utf-8-sig") as stream:
        def write(message):
            print(message, file=stream, flush=True)

        write("股指基差简报 · 本地历史输入及双版本生成测试")
        try:
            repo = Path(__file__).resolve().parents[2]
            try:
                head = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=repo,
                                      timeout=5, capture_output=True, text=True, check=True).stdout.strip()
            except (OSError, subprocess.SubprocessError):
                head = "未知"
            write(f"提交 {head}  Python {sys.version.split()[0]}")
            for package in ("pandas", "openpyxl", "matplotlib", "python-docx"):
                try:
                    write(f"{package} {version(package)}")
                except PackageNotFoundError:
                    write(f"{package} 未安装")
            from ..config import ROOT, load_config
            from shared_data import DataPaths
            from .dividend_sources import history_paths, local_directories

            config, paths = load_config(), DataPaths.for_module(ROOT)
            if args.backfill_share is not None:
                from .share_history import collect
                end = date.fromisoformat(args.as_of)
                start = date.fromisoformat(args.history_from) if args.history_from else end - timedelta(days=480)
                try:
                    collect(paths, config, start.isoformat(), end.isoformat(), args.backfill_share, folder, write)
                except OSError as exc:
                    write(f"公盘补收中断，继续使用本地数据  {type(exc).__name__}: {exc}")
            dirs = [args.dividends] if args.dividends else local_directories(ROOT, config, paths)
            write("检查位置")
            for directory in dirs:
                write(f"  {directory}（{'存在' if Path(directory).exists() else '不存在'}）")
            files, _ = history_paths(ROOT, config, paths, args.dividends)
            write(f"开始读取行情与分红，候选 Excel {len(files)} 份")
            from .brief import build
            from .documents import PDF_NAME, RAW_DIRECTORY, WORD_NAME

            args.output = folder / "batch"
            batch = build(args, inputs_ready=lambda *data: describe_inputs(write, *data))
            import pandas as pd
            for directory, label in ((batch, "去分红"), (batch/RAW_DIRECTORY, "不去分红")):
                for name in (WORD_NAME, PDF_NAME):
                    size = (directory/name).stat().st_size
                    if not size:
                        raise ValueError(f"{label} {name} 为空")
                    write(f"{label} {name}  {size} 字节")
                for name, label2 in (("basis_rank_tables", "单合约"), ("calendar_rank_tables", "跨期")):
                    ranks = pd.read_csv(directory/f"{name}.csv")
                    for days, group in ranks.groupby("window_sessions"):
                        write(f"  {label2} {days} 日  完整历史 {group.complete.sum()}/{len(group)}  "
                              f"可显示当前分位 {group.percentile.notna().sum()}/{len(group)}")
                        visible = group[group.percentile.notna()]
                        if not visible.empty:
                            labels = [f"{r.root}{r.slot - 1:02d}" if name == "basis_rank_tables"
                                      else f"{r.root} {r.pair}" for r in visible.itertuples()]
                            write("    " + "、".join(labels))
                            if "estimated_sample_n" in visible:
                                included = (visible.estimated_sample_n.gt(0) | visible.current_dividend_is_estimated).sum()
                                if included:
                                    write(f"    其中含估算分红的分位 {included} 项")
            write("结果：两套简报生成成功")
        except Exception:
            write("结果：生成失败")
            write(traceback.format_exc())
            return 1
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description="独立生成两版简报并输出测试报告，可按需从公司公盘补收历史 Excel")
    market = parser.add_mutually_exclusive_group()
    market.add_argument("--database", type=Path)
    market.add_argument("--snapshot", type=Path)
    parser.add_argument("--as-of")
    parser.add_argument("--dividends", type=Path)
    parser.add_argument("--backfill-share", nargs="?", const="", help="补收历史分红表，可选指定公盘目录")
    parser.add_argument("--history-from", help="公盘补收起始业务日，默认截止日往前480个自然日")
    parser.set_defaults(volume_dataset=None, no_volume_supplement=False, sessions=60)
    args = parser.parse_args(argv)
    if args.backfill_share is not None and (not args.as_of or args.dividends):
        parser.error("--backfill-share 需要 --as-of，并使用已有本地分红目录和公共归档")
    if args.history_from and args.backfill_share is None:
        parser.error("--history-from 需要 --backfill-share")
    try:
        if args.as_of and date.fromisoformat(args.as_of).isoformat() != args.as_of:
            raise ValueError
        if args.history_from and (date.fromisoformat(args.history_from).isoformat() != args.history_from
                                  or args.history_from > args.as_of):
            raise ValueError
    except ValueError:
        parser.error("日期须为 YYYY-MM-DD，补收起始日须早于或等于截止日")
    stamp = datetime.now(timezone(timedelta(hours=8))).strftime("%Y%m%d_%H%M%S")
    base = Path(__file__).resolve().parents[1] / "exports/recent_brief/diagnostics"
    return run(args, base / f"{stamp}_{uuid4().hex[:6]}")


if __name__ == "__main__":
    raise SystemExit(main())
