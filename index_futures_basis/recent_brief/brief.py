from __future__ import annotations

import argparse
import hashlib
from html import escape
import json
from pathlib import Path
import re

import numpy as np
import pandas as pd

from ..analytics import sha256
from ..config import ROOT, timestamp
from . import charts
from .charts import number
from .data import (ORDER, PAIRS, WINDOWS, add_volumes, adjust, calendar_series,
                   change, load_market, quantiles, snapshot_table)


def explanations(panel, spreads, single_q, end):
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
    second = "实体 P25–P75，中线 P50，须 P5–P95；红菱形及旁边数字为当日实际点数，横轴 P 为当日在该窗口的历史百分位。"
    complete = single_q[single_q.months.eq(3) & single_q.complete & single_q.percentile.notna()]
    extremes = complete[complete.percentile.le(5) | complete.percentile.ge(95)]
    if len(extremes):
        picks = extremes.assign(distance=(extremes.percentile-50).abs()).sort_values("distance", ascending=False).head(3)
        second += "3月尾部位置：" + "；".join(f"{r.root}{int(r.slot)-1:02d} P{r.percentile:.1f}%（{r.current:.1f}点）" for r in picks.itertuples()) + "。"
    elif len(complete):
        second += "已完整覆盖的单合约3月窗口中，当前未落入5%以下或95%以上尾部。"
    else:
        second += "历史覆盖不足，分位留空。"
    third = "四档持仓用曲线、成交量用并列柱，颜色一致；单位为万手。跨期两腿直接参照对应档位，不虚构跨期成交量。"
    activity_rows, ratios = [], []
    days = sorted(panel.loc[panel.trade_date.lt(end), "trade_date"].unique())[-20:]
    for row in latest.itertuples():
        history = panel[panel.instrument_id.eq(row.contract) & panel.trade_date.isin(days)].volume
        median = history.median() if history.notna().sum() >= 10 else np.nan
        ratio = row.volume/median if np.isfinite(median) and median > 0 else np.nan
        activity_rows.append({"root": row.root, "slot": row.slot, "contract": row.contract,
                              "volume": row.volume, "previous_20_sessions_median": median,
                              "valid_samples": int(history.notna().sum()), "volume_multiple": ratio})
        if np.isfinite(ratio):
            ratios.append((ratio, row.root, row.slot))
    if ratios:
        ratio, root, slot = max(ratios)
        third += f"相对前20交易日同一实际合约成交中位数，放量倍数最高为 {root}{int(slot)-1:02d} {ratio:.2f}倍"
        third += "（达到2倍观察阈值）。" if ratio >= 2 else "（未达2倍观察阈值）。"
    else:
        third += "同合约成交样本不足，未计算放量倍数。"
    oi = latest[latest.oi_change.notna()]
    if len(oi):
        row = oi.loc[oi.oi_change.abs().idxmax()]
        third += f"同合约当日持仓变动最大：{row.root}{int(row.slot)-1:02d} {number(row.oi_change/10000, 2, True)}万手。"
    return [first, second, third], pd.DataFrame(activity_rows)


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
    single_q, cross_q = quantiles(panel, end, "slot"), quantiles(spreads, end, "pair")
    texts, activity_table = explanations(panel, spreads, single_q, end)
    created = timestamp()
    run_id = re.sub(r"[^0-9]", "", created)[:14]
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
    chart1_note = note + " 底部彩色短线标记换月；浅灰区为最近10个本地交易日。" + source_line
    chart2_note = note + " 各格独立纵轴，不能按蜡烛高度跨格比较波动；当前日不进入历史样本。" + source_line
    chart3_note = note + " 持仓变化比较同一实际合约；成交量仅按同交易日、同实际合约匹配。" + source_line
    charts.setup()
    files = ["01_近期基差与跨期.png", "02_基差分位蜡烛.png", "03_持仓与成交量.png"]
    print("绘制 1/3：近期基差与跨期", flush=True)
    charts.trends(panel, spreads, end, out/files[0], chart1_note, args.sessions)
    print("绘制 2/3：基差分位蜡烛", flush=True)
    charts.distributions(panel, single_q, cross_q, end, out/files[1], chart2_note)
    print("绘制 3/3：持仓与成交量", flush=True)
    charts.activity(panel, end, out/files[2], chart3_note, args.sessions)
    tables = {"daily_basis": panel, "daily_calendar": spreads, "basis_quantiles": single_q,
              "calendar_quantiles": cross_q, "latest_contracts": snapshot_table(panel, end),
              "activity_checks": activity_table}
    for name, frame in tables.items():
        frame.to_csv(out/f"{name}.csv", index=False, encoding="utf-8-sig")
    source_note = f"生成时间 {created}；行情截至 {end:%Y-%m-%d}，未更新至生成日。分红快照 {dividend_date}。"
    source_note += " 各品种最新期货日：" + " / ".join(f"{r} {last.get(r, '缺失')}" for r in ORDER) + "。"
    if dividend_info.get("reason"):
        source_note += " 分红输入不可用，调整后基差留空：" + dividend_info["reason"]
    if volume_info.get("reason"):
        source_note += " 额外成交量不可用：" + volume_info["reason"]
    body = "".join(f'<figure><img src="{escape(f)}" alt="{escape(f)}"><figcaption>{escape(t)}</figcaption></figure>'
                   for f, t in zip(files, texts))
    html = ('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>股指基差简报</title>'
            '<style>body{max-width:1440px;margin:32px auto;padding:0 24px;background:#f3f6f8;color:#1c344a;'
            'font:15px/1.8 "Microsoft YaHei",sans-serif}h1{font-size:26px;margin-bottom:8px}'
            'header p{color:#68798a;font-size:13px}figure{margin:26px 0;background:white;border-radius:8px;'
            'padding:18px}img{width:100%;display:block}figcaption{padding:12px 20px 8px}footer{font-size:12px;color:#68798a}</style>'
            f'<header><h1>股指基差简报 · {end:%Y-%m-%d}</h1><p>{escape(source_note)}</p></header>'
            f'{body}<footer>跨期公式：01−02=(F01+G01)−(F02+G02)；02−03=(F02+G02)−(F03+G03)。'
            '正值表示前一档调整价更高。分位采用连续档位历史，不是今天实际合约的固定存续期历史。'
            'CSV与run_manifest.json保存计算明细及来源。</footer></html>')
    (out/"index.html").write_text(html, encoding="utf-8")
    code_hash = hashlib.sha256(b"".join(p.read_bytes() for p in sorted(Path(__file__).parent.glob("*.py")))).hexdigest()
    manifest = {"version": 1, "created_at": created, "as_of": str(end.date()), "latest_by_root": last,
                "market_source": source, "volume_source": volume_info, "dividends": dividend_info,
                "valuation": "adjusted", "basis_formula": "F+G-S", "calendar_formula": "left_adjusted_price-right_adjusted_price",
                "pairs": PAIRS, "windows": {"series_sessions": args.sessions, "quantile_months": WINDOWS},
                "quantile_policy": "[end-N calendar months,end), exclude current; half-weight ties; incomplete windows blank",
                "percentile_metric": "signed absolute dividend-adjusted basis points, not annualized",
                "anomaly_policy": {"percentile_tails": [5,95], "volume_multiple": 2,
                    "volume_reference": "previous 20 sessions, same actual contract; >=10 finite samples; exclude current"},
                "code_sha256": code_hash, "explanations": texts,
                "output_files": {p.name: {"sha256": sha256(p), "bytes": p.stat().st_size}
                                 for p in out.iterdir() if p.is_file()}}
    (out/"run_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2, default=str, allow_nan=False), encoding="utf-8")
    print(str(out/"index.html"), flush=True)
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(description="仅用本地真实行情生成3张基差/跨期总览和简短说明，不访问Wind")
    parser.add_argument("--snapshot", type=Path, help="原项目raw_market.json格式的四品种快照；不导入/覆盖行情库")
    parser.add_argument("--database", type=Path, help="指定只读行情SQLite，默认选择配置下最新可用真实库")
    parser.add_argument("--as-of", help="截止日YYYY-MM-DD；显式日期不回退")
    parser.add_argument("--dividends", type=Path, help="指定分红Excel；默认读取原项目配置的最新表内日期")
    parser.add_argument("--volume-dataset", type=Path, help="可选normalized股指期货数据集，只补同日同合约成交量")
    parser.add_argument("--no-volume-supplement", action="store_true", help="不读取额外成交量缓存")
    parser.add_argument("--sessions", type=int, default=60, help="走势图交易日数，默认60")
    parser.add_argument("--output", type=Path, help="输出到一个新的批次目录")
    args = parser.parse_args(argv)
    if args.snapshot and args.database:
        parser.error("--snapshot和--database只能指定一个")
    if not 10 <= args.sessions <= 80:
        parser.error("--sessions须为10至80；成交量补充读取最近80个交易日")
    if args.as_of:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", args.as_of):
            parser.error("--as-of须为YYYY-MM-DD")
        pd.Timestamp(args.as_of)
    build(args)
    return 0
