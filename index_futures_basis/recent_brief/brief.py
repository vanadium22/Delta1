from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import uuid

import numpy as np
import pandas as pd

from ..analytics import sha256
from ..config import ROOT, timestamp
from . import card_charts as charts
from .charts import number
from .data import (ORDER, PAIRS, activity_totals, add_volumes, adjust, calendar_series,
                   change, load_market, session_quantiles, multi_session_quantiles, snapshot_table)
from .metrics import highlights, series_metrics, total_metrics, activity_commentary
from .narrative import compose


def refresh_market(as_of=None, factory=None, volume_refresher=None):
    """Reuse the original incremental updater; never fabricate a successful refresh."""
    if factory is None:
        from ..service import BasisService
        factory = BasisService
    print("先检查并增量补齐Wind行情。", flush=True)
    try:
        service = factory(mode="wind")
        outcome = service.sync(progress=print, end=as_of)
        info = {"requested": True, "started_with": "original BasisService.sync", **outcome}
        if info["state"] == "complete":
            if volume_refresher is None:
                from .refresh import refresh_volumes
                volume_refresher = refresh_volumes
            try:
                volume_info = volume_refresher(service, as_of)
            except Exception as exc:
                volume_info = {"state": "failed", "message": str(exc)}
            info["volume_refresh"] = volume_info
            if volume_info["state"] != "complete":
                info["state"] = "partial"
                info["message"] = "期现货/持仓更新完成，成交量未完整更新：" + volume_info.get("message", "缺成交量")
    except Exception as exc:
        info = {"requested": True, "state": "failed", "reason": str(exc)}
    if info["state"] != "complete":
        print("行情未完整更新，将使用本地实际可用数据生成；日期以报告为准。", flush=True)
    return info


def explanations(panel, spreads, single_q, end, cross_q=None):
    latest = snapshot_table(panel, end)
    available = latest[latest.change_5d.notna()]
    first = "绝对基差 = 期货收盘价 + 分红点数 − 现货；负值为贴水，保留正负号。"
    if len(available):
        move = available.loc[available.change_5d.abs().idxmax()]
        g = panel[panel.root.eq(move.root) & panel.slot.eq(move.slot) & panel.trade_date.le(end)].tail(6)
        roll = "（区间含换月）" if g.roll_day.any() else ""
        first += f"近5个交易日变动最大：{move.root}{int(move.slot)-1:02d} {number(move.change_5d, signed=True)}点{roll}。"
    moves = []
    for (root, pair), g in spreads.groupby(["root", "pair"]):
        value = change(g, end, lag=5)
        if np.isfinite(value):
            moves.append((abs(value), root, pair, value, bool(g[g.trade_date.le(end)].tail(6).roll_day.any())))
    if moves:
        _, root, pair, value, roll = max(moves)
        first += f"跨期变动最大：{root} {pair} {number(value, signed=True)}点" + ("（区间含换月）。" if roll else "。")
    def tail_note(q, key):
        if q is None:
            return ""
        complete = q[q.complete & q.percentile.notna()]
        extremes = complete[complete.percentile.le(5) | complete.percentile.ge(95)]
        if len(extremes):
            picks = extremes.assign(distance=(extremes.percentile-50).abs()).sort_values("distance", ascending=False).head(3)
            labels = []
            for r in picks.itertuples():
                identity = f"{int(r.slot)-1:02d}" if key == "slot" else " " + r.pair
                labels.append(f"{r.root}{identity} P{r.percentile:.1f}%（{r.current:.2f}%）")
            return "60交易日尾部：" + "；".join(labels) + "。"
        return "有效当前值未落入5%/95%尾部。" if len(complete) else "当前值或历史覆盖不足，分位留空。"
    second = ("每品种仅画01—03三条年化曲线，00不画年化走势。右侧表格按00、01、02、03排列，"
              "列出当前实际年化及前30、60、120交易日历史分位；均排除当日，并列值半权重。"
              "T≥1保留在表格，T=0留空；n为有效样本，覆盖不足标—，不缩短窗口。")
    second += tail_note(single_q, "slot")
    third = ("跨期仅展示01−02、02−03；年化为调整后价差÷现货×365÷两合约实际到期日间隔。"
             "右侧表格列当前年化及前30/60/120交易日分位，排除当日，不直接相减两腿年化。")
    third += tail_note(cross_q, "pair")
    fourth = "每品种00—03四合约加总：柱形为总成交（左轴），曲线为总持仓（右轴），均为万手。任一合约缺值则总量留空。"
    totals = activity_totals(panel)
    activity_rows, ratios = [], []
    days = sorted(panel.loc[panel.trade_date.lt(end), "trade_date"].unique())[-20:]
    latest_totals = totals[totals.trade_date.eq(end)]
    for row in latest_totals.itertuples():
        history = totals[totals.root.eq(row.root) & totals.trade_date.isin(days)].volume
        median = history.median() if history.notna().sum() >= 10 else np.nan
        ratio = row.volume/median if np.isfinite(median) and median > 0 else np.nan
        activity_rows.append({"root": row.root,
                              "volume": row.volume, "previous_20_sessions_median": median,
                              "valid_samples": int(history.notna().sum()), "volume_multiple": ratio})
        if np.isfinite(ratio):
            ratios.append((ratio, row.root))
    if ratios:
        ratio, root = max(ratios)
        fourth += f"相对前20交易日总成交中位数，最高为 {root} {ratio:.2f}倍"
        fourth += "（达到2倍观察阈值）。" if ratio >= 2 else "（未达2倍观察阈值）。"
    else:
        fourth += "总成交历史样本不足，未计算放量倍数。"
    oi = latest_totals[latest_totals.oi_change.notna()]
    if len(oi):
        row = oi.loc[oi.oi_change.abs().idxmax()]
        fourth += f"四合约总持仓当日变化最大：{row.root} {number(row.oi_change/10000, 2, True)}万手。"
    return [first, second, third, fourth], pd.DataFrame(activity_rows)


def build(args):
    panel, end, source, config, paths = load_market(args.snapshot, args.database, args.as_of)
    volume_info = {"status": "未使用额外成交量来源"}
    dataset = args.volume_dataset
    if dataset is None and not args.no_volume_supplement:
        base = paths.root / "market/index_futures/dashboard/normalized"
        dataset = next((base/n for n in ("backfilled_cn_index_future", "cn_index_future")
                        if (base/n/"current.json").is_file()), None)
    if dataset and not args.no_volume_supplement:
        try:
            panel, volume_info = add_volumes(panel, dataset)
        except ImportError as exc:
            if args.volume_dataset:
                raise
            volume_info = {"status": "补充成交量不可用，保留原库字段及缺口", "reason": str(exc)}
    panel, dividend_info = adjust(panel, config, paths, args.dividends)
    spreads = calendar_series(panel)
    single_q, cross_q = session_quantiles(panel, end, "slot"), session_quantiles(spreads, end, "pair")
    single_tables = multi_session_quantiles(panel, end, "slot")
    cross_tables = multi_session_quantiles(spreads, end, "pair")
    single_metrics = series_metrics(panel, end, "slot", single_q)
    cross_metrics = series_metrics(spreads, end, "pair", cross_q)
    aggregate_metrics = total_metrics(panel, end)
    summary_cards = highlights(single_metrics, cross_metrics, aggregate_metrics)
    narrative = compose(panel, spreads, single_tables, cross_tables, aggregate_metrics, end)
    texts, activity_table = explanations(panel, spreads, single_q, end, cross_q)
    created = timestamp()
    run_id = re.sub(r"[^0-9]", "", created)[:14] + "_" + uuid.uuid4().hex[:6]
    out = (Path(args.output) if args.output else ROOT / "exports/recent_brief" / str(end.date()) / run_id).resolve()
    out.mkdir(parents=True, exist_ok=True)
    if (out / "run_manifest.json").exists():
        raise ValueError(f"输出目录已有批次，请换一个 --output 路径：{out}")
    dividend_date = dividend_info.get("snapshot_date", "逐日输入")
    last = {root: (str(g.loc[g.futures_close.notna(), "trade_date"].max().date())
                   if g.futures_close.notna().any() else "缺失") for root, g in panel.groupby("root")}
    note = (f"本地真实行情截至 {end:%Y-%m-%d}；分红快照 {dividend_date}，按连续档位固定应用于整个历史，并非历史逐日预测。\n"
            "00当月 / 01次月 / 02季月一 / 03季月二；曲线随逐日实际合约映射滚动。缺失留空，分位覆盖不足不绘制。")
    source_label = source.get("label") or source.get("source", {}).get("label", "本地持久化行情库")
    source_line = "\n行情来源：" + source_label + ("；成交量补充：共享修订后日线缓存。" if volume_info.get("version") else "。")
    chart1_note = note + " 阴影/加粗线为最近5日；变化按连续档位，换月在卡片标记。" + source_line
    chart2_note = note + " 年化走势只画01—03；00保留当前年化和30/60/120交易日分位表。T≥1均计入，排除当日。" + source_line
    chart3_note = note + " 年化=调整后价差÷现货×365÷实际到期日间隔；右侧为当前值及30/60/120交易日分位表。" + source_line
    chart4_note = note + " 图下按各自连续增减、转向和量仓同向/分化自动总结；双轴交点不作信号。总量任一腿缺值则留空。" + source_line
    charts.setup()
    files = ["01_近期基差与跨期.png", "02_单合约年化与历史分位表.png",
             "03_跨期年化与历史分位表.png", "04_四合约总成交与总持仓.png"]
    print("绘制 1/4：近期绝对基差与跨期", flush=True)
    charts.trends(panel, spreads, end, out/files[0], chart1_note, args.sessions, single_metrics, cross_metrics)
    print("绘制 2/4：01—03年化与30/60/120交易日分位表", flush=True)
    charts.annualized(panel, single_tables, end, out/files[1], chart2_note, args.sessions, metrics=single_metrics)
    print("绘制 3/4：跨期年化与30/60/120交易日分位表", flush=True)
    charts.annualized(spreads, cross_tables, end, out/files[2], chart3_note, args.sessions, key="pair", metrics=cross_metrics)
    print("绘制 4/4：四合约总成交与总持仓", flush=True)
    charts.activity(panel, end, out/files[3], chart4_note, args.sessions, aggregate_metrics)
    tables = {"daily_basis": panel, "daily_calendar": spreads, "basis_quantiles": single_q,
              "calendar_quantiles": cross_q, "latest_contracts": snapshot_table(panel, end),
              "basis_rank_tables": single_tables, "calendar_rank_tables": cross_tables,
              "activity_checks": activity_table, "activity_totals": activity_totals(panel),
              "basis_cards": single_metrics, "calendar_cards": cross_metrics, "activity_cards": aggregate_metrics}
    audit = panel[["trade_date", "root", "slot", "instrument_id", "futures_close", "spot_close",
                   "dividend_points", "raw_basis_points", "basis_points"]].copy()
    audit["adjustment_check"] = audit.basis_points-audit.raw_basis_points-audit.dividend_points
    tables["dividend_adjustment_audit"] = audit
    if dividend_info.get("path") and dividend_info.get("sha256"):
        dividend_bytes = Path(dividend_info["path"]).read_bytes()
        if hashlib.sha256(dividend_bytes).hexdigest() != dividend_info["sha256"]:
            raise ValueError("分红源文件在读取后已变化，请重新生成")
        (out/"dividend_input_snapshot.xlsx").write_bytes(dividend_bytes)
    (out/"narrative.json").write_text(json.dumps(narrative, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    for name, frame in tables.items():
        frame.to_csv(out/f"{name}.csv", index=False, encoding="utf-8-sig")
    source_note = f"生成时间 {created}；实际行情截至 {end:%Y-%m-%d}。分红快照 {dividend_date}。"
    source_note += " 各品种最新期货日：" + " / ".join(f"{r} {last.get(r, '缺失')}" for r in ORDER) + "。"
    if dividend_info.get("reason"):
        source_note += " 分红输入不可用，调整后基差留空：" + dividend_info["reason"]
    if volume_info.get("reason"):
        source_note += " 额外成交量不可用：" + volume_info["reason"]
    refresh_info = getattr(args, "refresh_result", {})
    if refresh_info.get("requested"):
        refresh_label = {"complete": "完整", "partial": "部分完成", "failed": "失败"}.get(refresh_info.get("state"), "未知")
        source_note += " 本次行情更新状态：" + refresh_label + "。"
        if refresh_info.get("state") != "complete":
            source_note += " 使用本地实际可用数据；" + str(refresh_info.get("reason") or refresh_info.get("message") or "部分字段未更新")
    from .documents import export_documents
    document_info = {"as_of": str(end.date()), "created_at": created, "dividend_date": dividend_date,
                     "summary_cards": summary_cards, "explanations": texts, "source_note": source_note,
                     "narrative": narrative["text"]}
    print("排版 Word 与 PDF 简报…", flush=True)
    document_outputs = export_documents(out, files, document_info)
    code_hash = hashlib.sha256(b"".join(p.read_bytes() for p in sorted(Path(__file__).parent.glob("*.py")))).hexdigest()
    cards_payload = {"summary": summary_cards,
        "single": json.loads(single_metrics.to_json(orient="records", date_format="iso")),
        "calendar": json.loads(cross_metrics.to_json(orient="records", date_format="iso")),
        "activity": json.loads(aggregate_metrics.to_json(orient="records", date_format="iso"))}
    (out/"cards.json").write_text(json.dumps(cards_payload, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    manifest = {"version": 7, "created_at": created, "as_of": str(end.date()), "latest_by_root": last,
                "market_source": source, "volume_source": volume_info, "dividends": dividend_info,
                "valuation": "adjusted", "basis_formula": "F+G-S", "calendar_formula": "left_adjusted_price-right_adjusted_price",
                "pairs": PAIRS, "windows": {"series_sessions": args.sessions, "annualized_quantile_sessions": [30, 60, 120], "summary_baseline_sessions": 60},
                "quantile_policy": "exact previous 30/60/120 local sessions, exclude current; half-weight ties; single-contract T>=1 included, T=0 excluded; missing inputs/unknown calendar invalidate",
                "minimum_days_to_expiry": 1,
                "percentile_metric": "dividend-adjusted annualized basis percent; calendar uses actual expiry gap and spot denominator",
                "calendar_annualized_formula": "(left_adjusted_price-right_adjusted_price)/spot_close*36500/(right_expiry-left_expiry).days",
                "activity_aggregation": "sum 4 contracts (00-03); any missing constituent makes total missing; total OI change is difference of daily sums",
                "card_policy": {"changes": "1/5 exact local trading sessions; continuous slots/pairs, rolls marked; unknown calendar invalidates",
                    "annual_change_unit": "percentage-point difference; bp retained only in audit CSV, not displayed",
                    "percentile_change": "current rank minus previous day's own trailing-60-session rank; percentage points",
                    "activity_relative_change": "(current/previous-1)*100; zero denominator unavailable"},
                "rendering": {"png_dpi": charts.DPI, "png_width_pixels": 3800, "vector_svg": True,
                    "rank_tables": "rows 00/01/02/03 or calendar pairs; columns current annualized value and P30/P60/P120, with sample counts",
                    "current_marker": "no candles; historical ranks shown as Pxx% in tables",
                    "single_contract_axes": "annualized time series 01-03 only, common axis; 00 current/ranks retained in table"},
                "summary_cards": summary_cards,
                "activity_commentary": activity_commentary(panel, end),
                "narrative": narrative,
                "summary_policy": "current level vs exact previous 60-session mean; select standardized deviations; today move compared with mean absolute daily move of 60 prior intervals; exclude 00 from annualized summary selection",
                "market_refresh": getattr(args, "refresh_result", {"requested": False}),
                "anomaly_policy": {"percentile_tails": [5,95], "volume_multiple": 2,
                    "volume_reference": "previous 20 sessions, four-contract total; >=10 finite samples; exclude current"},
                "code_sha256": code_hash, "explanations": texts,
                "document_info": document_info, "documents": document_outputs,
                "output_files": {p.name: {"sha256": sha256(p), "bytes": p.stat().st_size}
                                 for p in out.iterdir() if p.is_file()}}
    (out/"run_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2, default=str, allow_nan=False), encoding="utf-8")
    print(str(out/document_outputs["pdf"]), flush=True)
    print(str(out/document_outputs["word"]), flush=True)
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(description="生成基差Word/PDF简报及4张可独立修改的高清图；默认只读本地")
    parser.add_argument("--repack", type=Path, help="将已有批次的图片重新排成新Word/PDF批次，不下载、不重新计算行情")
    parser.add_argument("--snapshot", type=Path, help="原项目raw_market.json格式的四品种快照；不导入/覆盖行情库")
    parser.add_argument("--database", type=Path, help="指定只读行情SQLite，默认选择配置下最新可用真实库")
    parser.add_argument("--as-of", help="截止日YYYY-MM-DD；显式日期不回退")
    parser.add_argument("--dividends", type=Path, help="指定分红Excel；默认读取原项目配置的最新表内日期")
    parser.add_argument("--volume-dataset", type=Path, help="可选normalized股指期货数据集，只补同日同合约成交量")
    parser.add_argument("--no-volume-supplement", action="store_true", help="不读取额外成交量缓存")
    parser.add_argument("--sessions", type=int, default=60, help="走势图交易日数，默认60")
    parser.add_argument("--output", type=Path, help="输出到一个新的批次目录")
    parser.add_argument("--watch", action="store_true", help="持续检查本地输入，变化后自动生成新批次、卡片与图文；Ctrl+C退出")
    parser.add_argument("--refresh", action="store_true", help="单次先尝试原项目Wind增量补缺再生成；更新失败仍尽力导出，退出码2并记录原因")
    parser.add_argument("--poll-seconds", type=int, default=60, help="自动生成的本地输入检查间隔，默认60秒")
    args = parser.parse_args(argv)
    if args.repack:
        if args.refresh or args.watch or args.snapshot or args.database or args.as_of or args.dividends:
            parser.error("--repack仅与--output组合；使用已有批次图片和来源记录")
        from .workflow import repackage
        repackage(args.repack, args.output)
        return 0
    if args.snapshot and args.database:
        parser.error("--snapshot和--database只能指定一个")
    if args.refresh and (args.watch or args.snapshot or args.database):
        parser.error("--refresh只用于默认行情库的单次生成，不与--watch/--snapshot/--database组合")
    if not 10 <= args.sessions <= 80:
        parser.error("--sessions须为10至80；成交量补充读取最近80个交易日")
    if args.as_of:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", args.as_of):
            parser.error("--as-of须为YYYY-MM-DD")
        pd.Timestamp(args.as_of)
    if args.poll_seconds < 5:
        parser.error("--poll-seconds不得小于5秒")
    from .automation import publish_latest, watch
    if args.watch:
        return watch(args)
    from .workflow import generation_lock
    with generation_lock():
        if args.refresh:
            args.refresh_result = refresh_market(args.as_of)
        output = build(args)
        publish_latest(output, Path(args.output).resolve().parent if args.output else ROOT/"exports/recent_brief")
        return 2 if args.refresh and args.refresh_result["state"] != "complete" else 0
