"""Offline, all-scheme charts; reports only read saved research outputs."""
import argparse
import html
import json
from pathlib import Path

import numpy as np
import pandas as pd

from .calendar_analytics import _check_equal
from .io import write_json


ROOTS=("IF","IH","IC","IM")
EXITS=("expiry","close0.6","close0.4")
COLORS={"expiry":"#2166a6","close0.6":"#d97826","close0.4":"#718b35"}
LABELS={"expiry":"持有到期","close0.6":"q_close=0.6","close0.4":"q_close=0.4"}


def _style():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    path=Path("C:/Windows/Fonts/msyh.ttc")
    if path.is_file():
        font_manager.fontManager.addfont(str(path))
        plt.rcParams["font.family"]=font_manager.FontProperties(fname=str(path)).get_name()
    plt.rcParams.update({"axes.unicode_minus":False,"font.size":10,"axes.titlesize":12,
        "axes.spines.top":False,"axes.spines.right":False,"axes.labelcolor":"#34465a",
        "text.color":"#18334c","axes.edgecolor":"#9aaaba","grid.color":"#dce4ec",
        "savefig.facecolor":"white","axes.facecolor":"#fbfcfe"})
    return plt


def _exit(row):
    return "expiry" if row.exit_mode=="expiry" else f"close{row.q_close:.1f}"


def _date(value):
    return "未恢复" if pd.isna(value) else str(pd.Timestamp(value).date())


def _matrix(metrics,field):
    return np.array([[metrics.loc[(metrics.root==root)&(metrics.channel==channel)&(metrics.q_open==q)&
        (metrics.exit_mode.eq("expiry") if ex=="expiry" else metrics.q_close.eq(float(ex[5:]))),field].iloc[0]
        for q in (.8,.9) for ex in EXITS] for channel in ("01-03","02-03") for root in ROOTS],dtype=float)


def render_calendar_report(directory):
    plt=_style()
    import matplotlib.dates as mdates
    from matplotlib.colors import TwoSlopeNorm
    out=Path(directory).resolve()
    figures=out/"figures"
    figures.mkdir(exist_ok=True)
    study=json.loads((out/"study.local.json").read_text(encoding="utf-8"))
    metrics=pd.read_parquet(out/"account_metrics.parquet")
    trips=pd.read_parquet(out/"round_trips.parquet")
    curves=pd.read_parquet(out/"equity_drawdown.parquet")
    episodes=pd.read_parquet(out/"drawdown_top3.parquet")
    paths=pd.read_parquet(out/"trades_daily.parquet")
    markers,bins,chart_records=[],[],[]
    saved=[]
    def save(fig,name):
        file=figures/(name+".png")
        fig.savefig(file,dpi=180)
        plt.close(fig)
        saved.append(file.name)
    collabels=[f"q_open={q:.1f}\n"+("到期" if ex=="expiry" else "平 "+ex[5:]) for q in (.8,.9) for ex in EXITS]
    rowlabels=[f"{root}  {channel}" for channel in ("01-03","02-03") for root in ROOTS]
    fig,axes=plt.subplots(1,2,figsize=(13,5.4),layout="constrained")
    for ax,field,title in zip(axes,("total_return","max_drawdown"),("累计净收益率 %","最大回撤 %")):
        matrix=_matrix(metrics,field)*100
        limit=max(float(np.abs(matrix).max()),.01)
        if field=="total_return":
            ax.imshow(matrix,cmap="RdYlGn",norm=TwoSlopeNorm(vmin=-limit,vcenter=0,vmax=limit),aspect="auto")
        else:
            ax.imshow(-matrix,cmap="YlOrRd",vmin=0,vmax=limit,aspect="auto")
        for (i,j),value in np.ndenumerate(matrix):
            ax.text(j,i,f"{value:+.1f}" if field=="total_return" else f"{value:.1f}",ha="center",va="center",
                color="white" if (abs(value)>.7*limit) else "#17324d",fontsize=11,fontweight="bold")
        ax.set(xticks=np.arange(6),xticklabels=collabels,yticks=np.arange(8),yticklabels=rowlabels,title=title)
        ax.tick_params(length=0)
        ax.axhline(3.5,color="white",lw=3)
        ax.axvline(2.5,color="white",lw=3)
    fig.suptitle(f"48 个独立方案 | {study['evaluation_start']} 至 {study['evaluation_end']} | 每账户 {study['capital_per_account']/10000:,.0f} 万元",fontsize=14)
    save(fig,"summary_48")
    for channel in ("01-03","02-03"):
        fig,axes=plt.subplots(4,2,figsize=(13,7.6),sharex=True,layout="constrained")
        for i,root in enumerate(ROOTS):
            subset=metrics.loc[metrics.channel.eq(channel)&metrics.root.eq(root)]
            for row in subset.itertuples(index=False):
                data=curves.loc[curves.scenario.eq(row.scenario)]
                label=f"q_open={row.q_open:.1f} / {LABELS[_exit(row)]}"
                for ax,field in zip(axes[i],("cumulative_net_return","drawdown")):
                    ax.plot(data.timestamp,data[field]*100,color=COLORS[_exit(row)],ls="-" if row.q_open==.8 else "--",lw=1.2,label=label)
                    ax.grid(alpha=.5)
                    ax.axhline(0,color="#697886",lw=.6)
            axes[i,0].set_ylabel(root+" 净收益 %")
            axes[i,1].set_ylabel("回撤 %")
        for ax in axes[-1]:
            ax.xaxis.set_major_locator(mdates.YearLocator())
            ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
        handles,labels=axes[0,0].get_legend_handles_labels()
        fig.legend(handles,labels,loc="outside lower center",ncol=3,fontsize=9)
        fig.suptitle(f"{channel} | 四品种累计净收益与同轴回撤（实线 q_open=0.8，虚线 q_open=0.9）",fontsize=14)
        save(fig,"overview_"+channel)
    for row in metrics.itertuples(index=False):
        data=curves.loc[curves.scenario.eq(row.scenario)].set_index("timestamp")
        dd=episodes.loc[episodes.scenario.eq(row.scenario)].sort_values("rank")
        closed=trips.loc[trips.scenario.eq(row.scenario)&trips.status.eq("closed")]
        values=closed.net_return.to_numpy()*100
        if len(values)!=row.closed_trades:
            raise ValueError("Histogram sample differs from closed-trade statistics")
        title=f"{row.root} {row.channel} | q_open={row.q_open:.1f} | {LABELS[_exit(row)]}"
        fig,axes=plt.subplots(2,1,figsize=(13,7.5),sharex=True,gridspec_kw={"height_ratios":[2,1]})
        fig.subplots_adjust(left=.09,right=.97,top=.9,bottom=.24,hspace=.12)
        axes[0].plot(data.index,data.cumulative_net_return*100,color="#2166a6",lw=1.35)
        axes[1].fill_between(data.index,data.drawdown*100,0,color="#d97826",alpha=.25)
        axes[1].plot(data.index,data.drawdown*100,color="#c26c24",lw=1)
        axes[0].set_ylabel("累计净收益率 %（初始账户资金）")
        axes[1].set_ylabel("回撤 %")
        for ax in axes:
            ax.grid(alpha=.55)
            ax.axhline(0,color="#788797",lw=.7)
        axes[1].xaxis.set_major_locator(mdates.MonthLocator(interval=4))
        axes[1].xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
        annotations={}
        for event in dd.itertuples(index=False):
            color=("#9a3763","#5452a2","#208b88")[event.rank-1]
            points=[("P",event.peak_date),("T",event.trough_date)]
            if event.recovered:
                points.append(("R",event.recovery_date))
            for kind,stamp in points:
                if kind=="P" and event.peak_is_initial_anchor:
                    eq,draw=study["capital_per_account"],0.
                else:
                    eq,draw=data.at[stamp,"equity"],data.at[stamp,"drawdown"]
                if kind=="P":
                    _check_equal(eq,event.peak_equity,"plot peak equity versus drawdown table")
                    _check_equal(draw,0.,"plot peak drawdown")
                elif kind=="T":
                    _check_equal(eq,event.trough_equity,"plot trough equity versus drawdown table")
                    _check_equal(draw,event.drawdown,"plot trough drawdown versus table")
                elif eq<event.peak_equity or draw!=0:
                    raise ValueError("Plotted recovery has not regained its high watermark")
                value=(eq/study["capital_per_account"]-1)*100
                for ax,ordinate,metric in ((axes[0],value,"cumulative_net_return_percent"),(axes[1],draw*100,"drawdown_percent")):
                    marker,=ax.plot([stamp],[ordinate],"o",color=color,ms=4)
                    if pd.Timestamp(marker.get_xdata()[0])!=stamp:
                        raise ValueError("Rendered drawdown marker date differs from table")
                    _check_equal(marker.get_ydata()[0],ordinate,"rendered drawdown marker")
                    markers.append(dict(scenario=row.scenario,rank=event.rank,point=kind,timestamp=stamp,
                        equity=eq,drawdown=draw,axis=metric,plotted_y=float(marker.get_ydata()[0])))
                item=annotations.setdefault((stamp,float(eq)),dict(value=value,draw=draw*100,labels=[],color=color,kind=kind))
                item["labels"].append(str(event.rank)+kind)
            text=(f"{event.rank}  前高 {_date(event.peak_date)} → 谷底 {_date(event.trough_date)} → "
                  f"{'恢复 '+_date(event.recovery_date) if event.recovered else '未恢复（截至 '+_date(event.end_date)+'）'}"
                  f"    回撤 {event.drawdown*100:.2f}%    持续 {event.duration_calendar_days} 自然日")
            fig.text(.09,.15-(event.rank-1)*.038,text,fontsize=9,color=color)
        for (stamp,_),item in annotations.items():
            label="/".join(item["labels"])
            for ax,y in ((axes[0],item["value"]),(axes[1],item["draw"])):
                ax.annotate(label,(stamp,y),xytext=(0,-14 if item["kind"]=="T" else 9),textcoords="offset points",
                    ha="center",fontsize=8,color=item["color"],bbox=dict(facecolor="white",edgecolor="none",alpha=.85,pad=.5))
        fig.text(.5,.92,"P=前高 / T=谷底 / R=恢复；完整日期与幅度见同图底部编号说明",ha="center",fontsize=9,color="#526777")
        fig.suptitle(title,fontsize=14)
        save(fig,row.scenario+"_curve")
        fig,ax=plt.subplots(figsize=(8,6),layout="constrained")
        edges=np.histogram_bin_edges(values,bins=min(18,max(6,int(np.sqrt(len(values))*2)))) if len(values) else np.array([-.5,.5])
        counts,edges=np.histogram(values,bins=edges)
        if counts.sum()!=len(values):
            raise ValueError("Histogram dropped closed trades")
        ax.barh((edges[:-1]+edges[1:])/2,counts,height=np.diff(edges)*.9,color="#4b86b5",alpha=.85)
        ax.axhline(0,color="#253d52",lw=1.3,label="零收益")
        if len(values):
            ax.axhline(values.mean(),color="#d97826",ls="--",label=f"均值 {values.mean():.2f}%")
            ax.axhline(np.median(values),color="#718b35",ls=":",label=f"中位数 {np.median(values):.2f}%")
        ax.set(xlabel="闭合 round trip 次数",ylabel="每笔净收益率 %（冻结入场保证金）",title=title+f"\nn={len(values)}，未平仓不计入")
        from matplotlib.ticker import MaxNLocator
        ax.xaxis.set_major_locator(MaxNLocator(integer=True))
        ax.grid(axis="x",alpha=.5)
        ax.legend(fontsize=9)
        save(fig,row.scenario+"_distribution")
        for low,high,count in zip(edges[:-1],edges[1:],counts):
            bins.append(dict(scenario=row.scenario,lower_percent=low,upper_percent=high,count=int(count),sample=len(values),
                mean_percent=float(values.mean()) if len(values) else np.nan,median_percent=float(np.median(values)) if len(values) else np.nan))
        chart_records.append(dict(scenario=row.scenario,closed_sample=len(values),histogram_count=int(counts.sum()),
            mean_percent=float(values.mean()) if len(values) else None,median_percent=float(np.median(values)) if len(values) else None,
            drawdown_episodes=len(dd),markers_verified=True))
    fig,axes=plt.subplots(2,4,figsize=(13,6),layout="constrained")
    for i,channel in enumerate(("01-03","02-03")):
        for j,root in enumerate(ROOTS):
            scenario=f"{root}_{channel}_open0.8_close0.6"
            vals=trips.loc[trips.scenario.eq(scenario)&trips.status.eq("closed"),"net_return"].to_numpy()*100
            ax=axes[i,j]
            ax.hist(vals,bins=max(6,min(14,int(np.sqrt(len(vals))*2))),orientation="horizontal",color="#548ab3",alpha=.85)
            ax.axhline(0,color="#293e51",lw=1)
            if len(vals):
                ax.axhline(vals.mean(),color="#d97826",ls="--",lw=1)
                ax.axhline(np.median(vals),color="#718b35",ls=":",lw=1.3)
                ax.text(.98,.97,f"n={len(vals)}\n均值 {vals.mean():.2f}%\n中位 {np.median(vals):.2f}%",ha="right",va="top",
                    transform=ax.transAxes,fontsize=8,bbox=dict(facecolor="white",alpha=.8,edgecolor="none"))
            ax.set(title=root+" "+channel,xlabel="交易次数",ylabel="每笔净收益率 %")
            ax.xaxis.set_major_locator(MaxNLocator(integer=True))
            ax.grid(axis="x",alpha=.4)
    fig.suptitle("统一展示 q_open=0.8 / q_close=0.6 | 每个面板单独统计，未合并方案",fontsize=14)
    save(fig,"distribution_comparison")
    examples=[]
    for channel in ("01-03","02-03"):
        for root in ROOTS:
            candidates=trips.loc[trips.scenario.eq(f"{root}_{channel}_open0.8_expiry")&trips.status.eq("closed")].sort_values("entry_time")
            if candidates.empty:
                continue
            trade=candidates.iloc[0]
            example=paths.loc[paths.trade_id.eq(trade.trade_id)]
            fig,ax=plt.subplots(figsize=(8,3.7),layout="constrained")
            for col,label,color in (("near_net_pnl","近月 "+trade.near,"#2166a6"),("far_net_pnl","远月 "+trade.far,"#d97826"),("net_pnl","两腿合计（扣费）","#223c50")):
                ax.plot(example.timestamp,example[col]/10000,label=label,color=color,lw=1.4)
            ax.axhline(0,color="#8896a3",lw=.7)
            ax.grid(alpha=.4)
            ax.legend(fontsize=8,loc="best")
            ax.set(title=f"{root} {channel} 首笔闭合示例 | {trade.actual_lots} 手 | {_date(trade.entry_time)} 至 {_date(trade.exit_time)}",
                ylabel="累计净 PnL（万元）")
            ax.xaxis.set_major_locator(mdates.AutoDateLocator(minticks=3,maxticks=5))
            ax.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d"))
            save(fig,"pair_"+root+"_"+channel)
            examples.append(trade)
    pd.DataFrame(examples).to_csv(out/"csv/pair_examples.csv",index=False,encoding="utf-8-sig")
    pd.DataFrame(markers).to_csv(out/"csv/chart_drawdown_markers.csv",index=False,encoding="utf-8-sig")
    pd.DataFrame(bins).to_csv(out/"csv/distribution_bins.csv",index=False,encoding="utf-8-sig")
    write_json(out/"chart_validation.local.json",dict(schemes=chart_records,total_figures=len(saved),
        all_histogram_counts_match=True,all_drawdown_markers_match=True,figures=saved))
    options="".join(f'<option value="{html.escape(r.scenario)}">{html.escape(r.scenario)}</option>' for r in metrics.itertuples())
    csv_links=" · ".join(f'<a href="csv/{p.name}">{html.escape(p.stem)}</a>' for p in sorted((out/"csv").glob("*.csv")))
    table=metrics[["scenario","total_return","annualized_return","max_drawdown","closed_trades","net_win_rate","open_net_pnl"]].copy()
    for col in ("total_return","annualized_return","max_drawdown","net_win_rate"):
        table[col]=table[col].map(lambda v:f"{v*100:.2f}%" if np.isfinite(v) else "N/A")
    page='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Delta1 跨期 48 方案研究</title><style>body{font:16px/1.6 system-ui,sans-serif;max-width:1400px;margin:auto;padding:28px;color:#18334c;background:#f5f8fb}h1,h2{line-height:1.3}img{max-width:100%;background:white}select{font:inherit;padding:8px;width:100%}section{background:white;padding:24px;margin:20px 0;border-radius:10px}table{border-collapse:collapse;font-size:13px;width:100%}td,th{padding:6px;border-bottom:1px solid #ddd;text-align:right}td:first-child{text-align:left}.scroll{overflow:auto}a{color:#2166a6}</style>
<h1>Delta1 跨期反转研究 · 全部 48 个独立方案</h1>'''
    page+=f'<p>{study["evaluation_start"]} 至 {study["evaluation_end"]}；暖启动数据从 {study["coverage"]["price_start"]} 开始；原始 p 阈值；双腿保证金各 20%；每腿每边费率万分之 {study["commission_rate"]*10000:g}。所有图表与数据均可离线查看。</p>'
    page+='<section><img src="figures/summary_48.png" alt="全部48方案总结"></section>'
    page+='<section><h2>详细曲线、回撤日期及每笔收益分布</h2><select id="scheme">'+options+'</select><img id="curve" alt="收益与回撤"><img id="hist" alt="横向收益分布"><p>P=前高，T=谷底，R=恢复；编号与 drawdown_top3.csv 一致。分布收益以冻结入场保证金为分母；胜率仅包含该方案的闭合交易。</p></section>'
    page+='<section><h2>全部方案指标</h2><div class="scroll">'+table.to_html(index=False,escape=True,border=0)+'</div></section>'
    page+='<section><h2>完整 CSV</h2><p>'+csv_links+'</p></section>'
    page+='<section><h2>实际 pair 与两腿贡献示例</h2>'
    for channel in ("01-03","02-03"):
        for root in ROOTS:
            page+=f'<img src="figures/pair_{root}_{channel}.png" alt="{root} {channel} 实际两腿贡献">'
    verification_text=("因子前缀重放与48方案单独重跑一致" if study["standalone_verified"]==48 and study["prefix_checks"]
        else "本次为探索运行，尚未完成全部单独重跑和前缀验证")
    page+=f'</section><section><h2>研究口径与验证</h2><p>实际 pair 每日年化值与其入场通道此前{study["factor"]["parameters"]["window_days"]}交易日连续年化分布比较，排除当前日。CTA只读已保存因子；不重算、不读行情。阈值下一有效观测成交；到期由原引擎当日close双平。{verification_text}；费用、保证金、两腿PnL逐日与权益对账。详细证据见 study.local.json、chart_validation.local.json 及 verification.csv。</p><p>本轮是历史参数对比，无独立样本外检验。分红显式忽略；元数据无完整历史发布时刻档案。DDB与VPN保持暂停，本轮未访问Z源。</p></section>'
    page+='''<script>const s=document.getElementById('scheme');function update(){document.getElementById('curve').src='figures/'+s.value+'_curve.png';document.getElementById('hist').src='figures/'+s.value+'_distribution.png'}s.addEventListener('change',update);update();</script></html>'''
    (out/"report.html").write_text(page,encoding="utf-8")
    return dict(figures=len(saved),scenarios=len(chart_records),html=str(out/"report.html"))


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory",type=Path)
    args=parser.parse_args(argv)
    print(render_calendar_report(args.directory))


if __name__=="__main__":
    raise SystemExit(main())
