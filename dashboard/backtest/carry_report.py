"""Standalone PNGs and an offline HTML inspector for an expiry-carry study."""
import html
from pathlib import Path

import numpy as np
import pandas as pd

from .models import BacktestError, check_market_source


ROOTS = ("IF", "IH", "IC", "IM")
COLORS = {0.9: "#175b9a", 0.8: "#db812e"}


def render_carry_report(directory, summary, trades, curves, factors, decisions, metadata):
    if metadata.get("invalidated"):
        raise BacktestError("This study was invalidated and cannot be published")
    check_market_source(metadata.get("market", {}))
    settings = metadata["config"]
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    from plotly.subplots import make_subplots
    import plotly.graph_objects as go

    root = Path(directory)
    curves = curves.copy()
    curves["timestamp"] = pd.to_datetime(curves.timestamp)
    factors = factors.copy()
    factors["timestamp"] = pd.to_datetime(factors.timestamp)
    partial = metadata.get("coverage_status") == "available_data_only"
    period = f"{metadata['actual_start']} to {metadata['actual_end']}"
    note = "AVAILABLE DATA ONLY | " if partial else ""
    plt.rcParams.update({"font.size": 10, "axes.spines.top": False, "axes.spines.right": False,
                         "figure.facecolor": "white", "axes.facecolor": "white", "axes.grid": True,
                         "grid.alpha": .18, "savefig.facecolor": "white"})
    for field, filename, title, scale, ylabel in (("net_pnl", "pnl.png", "Paired net PnL after commissions", 1e-4, "10k CNY"),
                                                 ("drawdown", "drawdown.png", "Paired equity drawdown", 100, "%")):
        fig, axes = plt.subplots(2, 2, figsize=(14, 8), sharex=True, constrained_layout=True)
        for product, axis in zip(ROOTS, axes.ravel()):
            for threshold in metadata["config"]["thresholds"]:
                rows = curves.loc[curves.scope.eq("product_best") & curves.account.eq(product) & curves.threshold.eq(threshold)].sort_values("timestamp")
                if rows.empty:
                    continue
                label = f"|score| > {threshold:g}"
                if field == "drawdown":
                    label += f"; min {rows.drawdown.min():.2%}"
                axis.plot(rows.timestamp, rows[field] * scale, color=COLORS.get(threshold), label=label, linewidth=1.8)
                if field == "net_pnl" and not trades.empty:
                    lifecycle = trades.loc[trades.scope.eq("product_best") & trades.account.eq(product) & trades.threshold.eq(threshold)]
                    values = rows.set_index("timestamp")[field]
                    for column, marker, tag in (("entry_time", "^", "Pair open"), ("end_time", "x", "Pair close")):
                        events = lifecycle if column == "entry_time" else lifecycle.loc[lifecycle.status.eq("closed")]
                        dates = pd.to_datetime(events[column])
                        valid_dates = [date for date in dates if date in values.index]
                        axis.scatter(valid_dates, values.reindex(valid_dates)*scale, marker=marker, s=28,
                                     color=COLORS.get(threshold), zorder=4,
                                     label=tag if threshold == metadata["config"]["thresholds"][0] else None)
            axis.axhline(0, color="#56616d", linewidth=.7)
            axis.set_title(product, loc="left", fontweight="bold")
            axis.set_ylabel(ylabel)
            axis.xaxis.set_major_locator(mdates.AutoDateLocator(minticks=4, maxticks=7))
            axis.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
            axis.legend(loc="best", fontsize=8)
        fig.suptitle(f"{note}{title}\n{period} | each product account: {metadata['config']['initial_capital']:,.0f} CNY", fontsize=14)
        fig.savefig(root / filename, dpi=160)
        plt.close(fig)
    for threshold in metadata["config"]["thresholds"]:
        fig, axes = plt.subplots(2, 2, figsize=(14, 8), sharex=True, constrained_layout=True)
        for product, axis in zip(ROOTS, axes.ravel()):
            rows = curves.loc[curves.scope.eq("product_best") & curves.account.eq(product) & curves.threshold.eq(threshold)].sort_values("timestamp")
            for field, color, name in (("futures_pnl", "#175b9a", "Futures leg"), ("spot_pnl", "#db812e", "Index hedge leg"), ("net_pnl", "#172a3a", "Combined")):
                axis.plot(rows.timestamp, rows[field] / 1e4, color=color, label=name, linewidth=1.6)
            axis.set_title(product, loc="left", fontweight="bold")
            axis.set_ylabel("Net PnL (10k CNY)")
            axis.xaxis.set_major_locator(mdates.AutoDateLocator(minticks=4, maxticks=7))
            axis.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
            axis.legend(fontsize=8)
        fig.suptitle(f"{note}Actual-lot leg attribution | threshold {threshold:g}\n{period}", fontsize=14)
        fig.savefig(root / f"legs_{str(threshold).replace('.', '_')}.png", dpi=160)
        plt.close(fig)
    fig, axes = plt.subplots(4, 1, figsize=(18, 13), constrained_layout=True)
    for product, axis in zip(ROOTS, axes):
        subset = summary.loc[summary.scope.eq("contract_independent") & summary.root.eq(product)]
        names = sorted(subset.account.unique())
        for j, threshold in enumerate(metadata["config"]["thresholds"]):
            rows = subset.loc[subset.threshold.eq(threshold)].set_index("account").reindex(names)
            axis.bar(np.arange(len(names)) + (j-.5)*.36, rows.net_pnl / 1e4, width=.36,
                     color=COLORS.get(threshold), label=f"|score| > {threshold:g}")
        axis.set_xticks(np.arange(len(names)), names, rotation=45, ha="right", fontsize=8)
        axis.set_title(product, loc="left", fontweight="bold")
        axis.set_ylabel("Net PnL (10k CNY)")
        axis.legend(fontsize=8)
    fig.suptitle(f"{note}Independent paired contracts | each account has its own initial capital\n{period}", fontsize=14)
    fig.savefig(root / "independent_contracts.png", dpi=160)
    plt.close(fig)

    inspector = make_subplots(rows=4, cols=1, shared_xaxes=True, subplot_titles=ROOTS, vertical_spacing=.05)
    palette = ("#175b9a", "#448f97", "#db812e", "#9263a9")
    for i, product in enumerate(ROOTS, 1):
        for slot in range(4):
            rows = factors.loc[factors.root.eq(product) & factors.slot.eq(f"{product}0{slot}.CFE")]
            inspector.add_trace(go.Scatter(x=rows.timestamp, y=rows.score, name=f"slot 0{slot}", legendgroup=f"slot{slot}",
                showlegend=i==1, line=dict(color=palette[slot], width=1),
                customdata=rows[["contract", "annual_basis_pct", "percentile", "historical_samples"]].to_numpy(),
                hovertemplate="%{x}<br>%{customdata[0]}<br>annual %{customdata[1]:.5f}%<br>p %{customdata[2]:.5f}<br>score %{y:.5f}<br>n %{customdata[3]}<extra></extra>"), row=i, col=1)
        for threshold in metadata["config"]["thresholds"]:
            selected = decisions.loc[decisions.scope.eq("product_best") & decisions.account.eq(product)
                                     & decisions.threshold.eq(threshold) & decisions.action.eq("signal_open")]
            inspector.add_trace(go.Scatter(x=selected.timestamp, y=selected.score, mode="markers", name=f"entry signal {threshold:g}",
                legendgroup=f"threshold{threshold}", showlegend=i==1, text=selected.symbol,
                marker=dict(size=9, symbol="diamond" if threshold == .9 else "circle", color=COLORS.get(threshold)),
                hovertemplate="signal %{x}<br>%{text}<br>score %{y:.5f}<extra></extra>"), row=i, col=1)
        inspector.update_yaxes(range=[-1.05, 1.05], row=i, col=1)
    inspector.update_layout(height=1250, template="plotly_white", title=f"{note}{settings['window_days']}-session actual-contract factor and entry-signal inspector | {period}")
    inspector.write_html(root / "factor_inspector.html", include_plotlyjs=True)

    main = summary.loc[summary.scope.eq("product_best")].copy()
    independent = summary.loc[summary.scope.eq("contract_independent")].copy()
    columns = ["threshold", "account", "net_pnl", "total_return", "max_drawdown", "max_drawdown_cny", "futures_pnl", "spot_pnl", "fees", "entries", "closed_trades", "open_trades"]
    labels = dict(threshold="阈值", account="账户", net_pnl="合并净盈亏", total_return="资金收益率", max_drawdown="最大回撤",
                  max_drawdown_cny="最大回撤金额", futures_pnl="期货腿净盈亏", spot_pnl="指数腿净盈亏", fees="总手续费",
                  entries="开仓次数", closed_trades="已双平", open_trades="未到期持仓")
    def table(frame):
        frame = frame[columns].copy()
        for col in ("total_return", "max_drawdown"):
            frame[col] = frame[col].map(lambda x: f"{x:.3%}")
        for col in ("net_pnl", "max_drawdown_cny", "futures_pnl", "spot_pnl", "fees"):
            frame[col] = frame[col].map(lambda x: f"{x:,.2f}")
        return frame.rename(columns=labels).to_html(index=False, classes="filterable", border=0)
    lifecycle = trades.loc[trades.scope.eq("product_best")].copy() if len(trades) else pd.DataFrame()
    lifecycle_html = "<p>没有达到阈值且实际成交的开仓。</p>"
    if len(lifecycle):
        signal_factors = factors[["timestamp", "contract", "annual_basis_pct", "historical_samples"]].rename(columns={"timestamp":"signal_time"})
        lifecycle = lifecycle.merge(signal_factors, on=["signal_time", "contract"], how="left", validate="many_to_one")
        lifecycle = lifecycle.sort_values(["threshold", "entry_time", "root"], ascending=[False, True, True])
        lifecycle = lifecycle[["threshold", "contract", "slot_signal", "annual_basis_pct", "percentile_signal", "score_signal",
            "historical_samples", "signal_time", "entry_time", "end_time", "status", "futures_signed_lots", "spot_signed_units",
            "futures_net_pnl", "spot_net_pnl", "net_pnl"]]
        for col in ("signal_time", "entry_time", "end_time"):
            lifecycle[col] = pd.to_datetime(lifecycle[col]).dt.strftime("%Y-%m-%d %H:%M")
        for col in ("annual_basis_pct", "percentile_signal", "score_signal"):
            lifecycle[col] = lifecycle[col].map(lambda x:f"{x:.6f}")
        for col in ("futures_net_pnl", "spot_net_pnl", "net_pnl"):
            lifecycle[col] = lifecycle[col].map(lambda x:f"{x:,.2f}")
        lifecycle["status"] = lifecycle.status.replace({"closed":"已到期双平", "open_marked_to_latest_close":"未到期·末日估值"})
        lifecycle = lifecycle.rename(columns=dict(threshold="阈值",contract="实际合约",slot_signal="信号日档位",
            annual_basis_pct="信号年化(%)",percentile_signal="信号分位p",score_signal="中心化score",historical_samples="历史样本数",
            signal_time="信号收盘",entry_time="实际开仓",end_time="到期双平/估值",status="状态",futures_signed_lots="带向期货手数",
            spot_signed_units="反向指数单位",futures_net_pnl="期货腿净盈亏",spot_net_pnl="指数腿净盈亏",net_pnl="合并净盈亏"))
        lifecycle_html = lifecycle.to_html(index=False, border=0)
    banner = ("<div class='warning'>数据覆盖不足：这不是完整的2024年至今回测。仅展示已核验可用区间。</div>" if partial else "")
    tail = f"<p>尚无完整日线的尾部交易日：{html.escape(', '.join(metadata['tail_pending']))}</p>" if metadata["tail_pending"] else ""
    image_names = ["pnl.png", "drawdown.png"] + [f"legs_{str(t).replace('.', '_')}.png" for t in settings["thresholds"]] + ["independent_contracts.png"]
    imgs = "".join(f"<img src='{name}' alt='{name}'>" for name in image_names)
    threshold_text = " / ".join(f"&gt;{t:g}" for t in settings["thresholds"])
    text = f"""<!doctype html><html lang='zh-CN'><meta charset='utf-8'><title>60日分位反转与等点值指数对冲</title>
<style>body{{font:15px 'Segoe UI','Microsoft YaHei',sans-serif;color:#20364c;background:#f5f8fb;max-width:1500px;margin:28px auto;padding:0 20px}}h1,h2{{color:#144b77}}.warning{{background:#fff0d9;border-left:5px solid #d08024;padding:18px;font-weight:bold}}.card{{background:white;padding:22px;margin:18px 0;border-radius:8px}}img{{width:100%;background:white;margin:14px 0}}.wide{{overflow:auto}}table{{border-collapse:collapse;width:100%;white-space:nowrap}}td,th{{padding:9px 12px;border-bottom:1px solid #dce4ec;text-align:right}}th{{background:#e9f1f7}}input{{font:inherit;padding:10px;width:450px;max-width:90%}}a{{color:#175b9a}}</style>
<h1>60日连续档位分位反转 · 持有到期 · 等点值指数对冲</h1>{banner}<p>实际区间：{period}；请求区间：{settings['start']} 至 {settings['end']}。</p>{tail}
<div class='card'><p>每个品种／独立合约账户初始资金 {settings['initial_capital']:,.0f} 元，固定保证金 {settings['margin_rate']:.1%}（显式情景），最大占用 {settings['max_capital_usage']:.1%}，两腿每边名义本金手续费 {settings['commission_rate']*10000:g} 万分之。分红明确按 D=0。</p>
<p>先用前 {settings['window_days']} 个交易日的同档年化历史计算 p，排除当前日、等值半权、已知 T&lt;{settings['min_annual_days']} 排除。score=2p−1；四档中选 |score| 最大者，分别按 {threshold_text} 开仓，高分位空期货、低分位多期货。信号在收盘产生，下一有效日线 close 成交，持有实际手数至到期 close 双平。中途不择时平仓、不调手数。</p>
<p>IF/IH 每手期货配反向300个指数单位，IC/IM配200个；指数乘数为1，按两腿合计资金与手续费定手数。指数是全额资金占用的合成指数，不含融资、借券和现金派息。两腿归因使用实际成交手数，合计严格对账账户权益。</p>
<p>未到期仓位按最后实际 close 估值，不强行平仓。独立合约各自拥有一份初始资金，其结果不能直接当一个共用资金组合。</p>
<p><a href='factor_inspector.html'>交互查看四档具体因子与开仓信号</a> · <a href='factor_values.csv'>全部因子CSV</a> · <a href='trades.csv'>开仓／到期双平及两腿PnL</a> · <a href='summary.csv'>全部账户汇总</a> · <a href='decisions.csv'>逐日选约决策</a></p></div>
<div class='card'><h2>四品种四档择优主策略</h2><div class='wide'>{table(main)}</div></div>{imgs}
<div class='card'><h2>主策略每笔因子与开平仓效果</h2><p>信号时间严格早于成交；年化和分位均取信号当日，盈亏已扣两腿手续费，时间为上海时区。</p><div class='wide'>{lifecycle_html}</div></div>
<div class='card' id='independent'><h2>所有实际合约独立账户</h2><input placeholder='筛选合约，例如 IC2609 或阈值 0.9' oninput='filterRows(this.value)'><div class='wide'>{table(independent)}</div></div>
<p>交易日依据上交所公告及现有核验日历：<a href='https://www.sse.com.cn/disclosure/announcement/general/c/c_20221227_5714458.shtml'>2023</a>、<a href='https://www.sse.com.cn/disclosure/announcement/general/c/c_20231226_5733939.shtml'>2024</a>；价格及参考来源、覆盖、假设和输入快照见 study.json、requested_coverage.json。</p>
<script>function filterRows(v){{document.querySelectorAll('#independent .filterable tbody tr').forEach(r=>r.style.display=r.textContent.toLowerCase().includes(v.toLowerCase())?'':'none')}};</script></html>"""
    (root / "report.html").write_text(text, encoding="utf-8")
