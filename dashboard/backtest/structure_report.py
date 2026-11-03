"""Offline plots and interactive actual-contract pair views from saved study outputs."""
import argparse
import html
import json
from pathlib import Path

import numpy as np
import pandas as pd

from .io import load_result, write_json
from .strategy import load_factors
from .strategy.term_structure import quantile_key


COLORS = {"best":"#2563ab", "history_pairs":"#20834e", "quantile_pairs":"#854bb2", "calendar":"#d27719"}


def _plotting():
    import matplotlib
    matplotlib.use("Agg")
    from matplotlib import font_manager, pyplot as plt
    fonts={f.name for f in font_manager.fontManager.ttflist}
    plt.rcParams.update({"font.family":next((f for f in ("Microsoft YaHei","SimHei","Noto Sans CJK SC") if f in fonts),"DejaVu Sans"),
                         "axes.unicode_minus":False,"font.size":10,"figure.facecolor":"white","axes.spines.top":False,
                         "axes.spines.right":False,"axes.grid":True,"grid.alpha":.18,"savefig.dpi":160})
    return plt


def _finish(plt, fig, file):
    fig.savefig(file, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def _curves(plt, out, main, curves, protocol):
    fig,axes=plt.subplots(3,1,figsize=(13,12),sharex=True,layout="constrained")
    for row in main.itertuples(index=False):
        equity=curves[row.case].sum(axis=1)
        peaks=np.maximum.accumulate(np.r_[row.initial_capital,equity.to_numpy()])[1:]
        style=dict(color=COLORS[row.family],ls="-" if row.threshold==main.threshold.max() else "--",lw=1.6)
        label=f"{row.label} | {row.threshold:g}"
        axes[0].plot(equity.index,(equity-row.initial_capital)/10000,label=label,**style)
        axes[1].plot(equity.index,100*(equity/row.initial_capital-1),**style)
        axes[2].plot(equity.index,100*(equity/peaks-1),**style)
    for ax,ylabel in zip(axes,("累计净 PnL（万元）","累计收益（%）","回撤（%）")):
        ax.axhline(0,color="#475569",lw=.6)
        ax.set_ylabel(ylabel)
    axes[0].legend(ncol=2,loc="upper left",fontsize=9)
    fig.suptitle(f"年化基差 / 期限结构条件分位回归 / 年化跨期\n{protocol['evaluation_start']}—{protocol['evaluation_end']} | "
                 f"每品种 {protocol['capital_per_product']/10000:,.0f} 万元 | 保证金 100% | 已扣实际手续费",fontsize=14)
    _finish(plt,fig,out/"pnl_returns.png")
    roots=list(next(iter(curves.values())).columns)
    fig,axes=plt.subplots(len(roots),1,figsize=(13,3.1*len(roots)),sharex=True,squeeze=False,layout="constrained")
    selected=main.loc[main.threshold.eq(main.threshold.max())]
    for ax,root in zip(axes[:,0],roots):
        for row in selected.itertuples(index=False):
            ax.plot(curves[row.case].index,100*(curves[row.case][root]/row.capital_per_product-1),color=COLORS[row.family],label=row.label)
        ax.set_ylabel(root+" 收益（%）")
        ax.axhline(0,color="#475569",lw=.6)
    axes[0,0].legend(ncol=2,fontsize=9)
    fig.suptitle(f"分品种累计净收益 | 中心化阈值 {selected.threshold.iloc[0]:g}",fontsize=14)
    _finish(plt,fig,out/"per_product.png")


def _structure(plt, out, detail, stamp, title, file):
    from matplotlib.patches import FancyArrowPatch, FancyBboxPatch
    roots=sorted(detail.root.unique())
    fig,axes=plt.subplots(2,2,figsize=(14,9),layout="constrained")
    for ax,root in zip(axes.ravel(),roots):
        active=detail.loc[detail.timestamp.eq(stamp)&detail.root.eq(root)&detail.future_lots.ne(0)].sort_values("future")
        ax.set(xlim=(0,1),ylim=(0,1))
        ax.axis("off")
        ax.text(.02,.97,root+" | "+str(stamp.date()),fontsize=14,weight="bold",va="top")
        if active.empty:
            ax.text(.5,.5,"无持仓",ha="center",color="#64748b")
            continue
        for row,y in zip(active.itertuples(index=False),np.linspace(.79,.20,len(active))):
            color="#1c7d53" if row.future_lots>0 else "#bb4c3d"
            for x,label in ((.03,f"{row.future}\n{row.future_lots:+.0f} 手 × {row.multiplier:g}"),
                            (.64,f"{row.hedge}\n{row.hedge_units:+.0f} 指数单位 × 1")):
                ax.add_patch(FancyBboxPatch((x,y-.065),.32,.13,boxstyle="round,pad=.012",fc="#f2f6fb",ec=color,lw=1.1))
                ax.text(x+.16,y,label,ha="center",va="center",fontsize=10)
            ax.add_patch(FancyArrowPatch((.37,y),(.62,y),arrowstyle="<->",mutation_scale=12,color=color,lw=1.4))
            ax.text(.495,y+.018,"等价数量 = 0",ha="center",fontsize=8,color="#475569")
        physical=active.hedge_units.sum()
        margin=active.allocated_actual_margin.sum()/10000
        ax.text(.02,.04,f"实际指数净额 {physical:+,.0f} 单位 | 实际保证金 {margin:,.1f} 万元\n"
                "各虚拟指数腿汇总后成交；图中为日结后的真实持仓",fontsize=9,color="#475569")
    for ax in axes.ravel()[len(roots):]:
        ax.axis("off")
    fig.suptitle(title,fontsize=15)
    _finish(plt,fig,out/file)


def _pair_plots(plt, out, key, details, summaries):
    detail=details[key]
    if detail.empty:
        return []
    stamp=detail.timestamp.max()
    _structure(plt,out,detail,stamp,f"实际合约 + 指数 pair | {key} | 期末持仓","pairs_latest.png")
    count=detail.loc[detail.future_lots.ne(0)].groupby("timestamp").size()
    if len(count):
        busiest=count.idxmax()
        _structure(plt,out,detail,busiest,f"实际合约 + 指数 pair | {key} | 同时持有 pair 最多的首日","pairs_maximum.png")
    roots=sorted(detail.root.unique())
    fig,axes=plt.subplots(len(roots),1,figsize=(13,3.3*len(roots)),layout="constrained",squeeze=False)
    for ax,root in zip(axes[:,0],roots):
        wide=detail.loc[detail.root.eq(root)].pivot(index="timestamp",columns="future",values="future_lots")
        wide=wide.loc[:,wide.ne(0).any()]
        bound=max(1,float(wide.abs().max().max())) if len(wide.columns) else 1
        ax.imshow(wide.to_numpy().T,aspect="auto",interpolation="nearest",cmap="RdBu",vmin=-bound,vmax=bound)
        ax.set_yticks(range(len(wide.columns)),[s.replace(".CFE","") for s in wide.columns],fontsize=8)
        ticks=np.unique(np.linspace(0,len(wide)-1,6).astype(int))
        ax.set_xticks(ticks,wide.index[ticks].strftime("%Y-%m-%d"),fontsize=8)
        ax.set_title(root+" 实际合约整数手数（蓝=多，红=空，白=0；每品种色阶独立）",loc="left",fontsize=10)
        ax.grid(False)
    fig.suptitle(key+" | 持有到真实到期，档位变化不换月",fontsize=14)
    _finish(plt,fig,out/"pair_positions.png")
    fig,axes=plt.subplots(len(roots),1,figsize=(13,3.5*len(roots)),layout="constrained",squeeze=False)
    latest=summaries[key]
    for ax,root in zip(axes[:,0],roots):
        rows=latest.loc[latest.root.eq(root)].sort_values("future")
        ax.bar(rows.future.str.replace(".CFE","",regex=False),rows.net_pnl/10000,color=np.where(rows.net_pnl>=0,"#20834e","#bb4c3d"))
        ax.tick_params(axis="x",rotation=50,labelsize=8)
        ax.set_ylabel(root+" 净 PnL（万元）")
        ax.axhline(0,color="#475569",lw=.7)
    fig.suptitle(key+" | 所有实际合约 pair 的期末累计贡献（含已平仓及持仓浮盈亏）",fontsize=13)
    _finish(plt,fig,out/"pair_contribution.png")
    return ["pairs_latest.png","pairs_maximum.png","pair_positions.png","pair_contribution.png"]


def _quantile_plots(plt, out, factors, protocol):
    models=factors.diagnostics.get("quantile_models")
    if models is None or models.empty:
        return False
    fitted=models.loc[models.status.eq("fit")]
    annual=factors.continuous_factors["annual_basis"]
    roots=sorted(fitted.root.unique())
    fig,axes=plt.subplots(2,2,figsize=(13,9),layout="constrained")
    for ax,root in zip(axes.ravel(),roots):
        stamp=fitted.loc[fitted.root.eq(root),"timestamp"].max()
        rows=fitted.loc[fitted.root.eq(root)&fitted.timestamp.eq(stamp)].sort_values("quantile")
        slots=[c for c in annual if c.startswith(root)]
        t=factors.panel.days_to_expiry.loc[stamp,slots]
        y=annual.loc[stamp,slots]
        x=np.linspace(max(5,float(t.min())),float(t.max())*1.05,100)
        standardized=(x/365-rows.term_years_mean.iloc[0])/rows.term_years_scale.iloc[0]
        beta=rows[[c for c in rows if c.startswith("beta")]].to_numpy()
        predicted=np.sort(np.vander(standardized,N=beta.shape[1],increasing=True)@beta.T,axis=1)
        probs=rows["quantile"].to_numpy()
        for q in (probs[0],.5,probs[-1]):
            j=int(np.flatnonzero(probs==q)[0])
            ax.plot(x,predicted[:,j],color="#854bb2" if q!=.5 else "#2563ab",ls="--" if q!=.5 else "-",label=f"条件 q={q:g}")
        for alias in slots:
            if np.isfinite(y[alias]) and np.isfinite(t[alias]):
                ax.scatter(t[alias],y[alias],color="#d27719",s=30,zorder=3)
                ax.annotate(factors.panel.mapping.at[stamp,alias].replace(".CFE",""),(t[alias],y[alias]),xytext=(3,6),textcoords="offset points",fontsize=8)
        ax.set_title(root+" | "+str(stamp.date()),loc="left")
        ax.set_xlabel("剩余自然日 T")
        ax.set_ylabel("年化期现基差（百分点）")
        ax.legend(fontsize=8)
    for ax in axes.ravel()[len(roots):]:
        ax.axis("off")
    fig.suptitle("每品种前 60 交易日 × 有效实际合约的条件分位回归\n当日不参与拟合；点为当日实际合约；曲线已逐期限排序处理交叉",fontsize=13)
    _finish(plt,fig,out/"quantile_structure.png")
    coverage=[]
    for root in roots:
        columns=[c for c in annual if c.startswith(root)]
        observed=annual.loc[protocol["evaluation_start"]:protocol["evaluation_end"],columns]
        for q in sorted(fitted["quantile"].unique()):
            bound=factors.continuous_factors[quantile_key(q)].reindex(index=observed.index,columns=columns)
            valid=np.isfinite(observed)&np.isfinite(bound)
            n=int(valid.sum().sum())
            coverage.append(dict(root=root,quantile=q,observations=n,observed_below_fraction=float(((observed<=bound)&valid).sum().sum()/n) if n else None))
    pd.DataFrame(coverage).to_csv(out/"quantile_coverage.csv",index=False,encoding="utf-8-sig")
    return True


def _payload(summary,curves,details,*,capital_label="每品种"):
    data={"cases":{}}
    for row in summary.itertuples(index=False):
        equity=curves[row.case]
        dates=equity.index.strftime("%Y-%m-%d").tolist()
        mapping={str(d.date()):i for i,d in enumerate(equity.index)}
        case=dict(label=row.label+f" | {row.threshold:g} | {capital_label} {row.capital_per_product/10000:g} 万元",dates=dates,
                  capital=row.capital_per_product,curves={r:np.round(equity[r]/row.capital_per_product,8).tolist() for r in equity},roots={})
        frame=details[row.case]
        for root in equity:
            book=dict(states=[[] for _ in dates],pairs={})
            if not frame.empty:
                subset=frame.loc[frame.root.eq(root)]
                for pair,group in subset.groupby("pair_id",sort=True):
                    first=group.iloc[0]
                    book["pairs"][pair]=dict(future=first.future,hedge=first.hedge,multiplier=float(first.multiplier),kind=first.pair_type,
                        pnl=np.round(group.set_index("timestamp").reindex(equity.index).net_pnl.to_numpy(),2).tolist())
                for record in subset.loc[subset.future_lots.ne(0)].itertuples(index=False):
                    book["states"][mapping[str(record.timestamp.date())]].append([record.pair_id,float(record.future_lots),float(record.hedge_units),round(record.allocated_actual_margin,2)])
            case["roots"][root]=book
        data["cases"][row.case]=case
    return data


def _table(frame, *, products=False):
    selected=frame.copy()
    result=pd.DataFrame({"方案":selected["label"] if "label" in selected else selected["case"]})
    if products:
        result["品种"]=selected.root
    result["阈值"]=selected.threshold
    for source,label in (("annualized_return","年化收益 CAGR"),("total_return","区间收益"),("max_drawdown","最大回撤")):
        result[label]=selected[source].map(lambda x:"不适用" if pd.isna(x) else f"{x*100:+.4f}%")
    result["净 PnL（元）"]=selected.net_pnl.map(lambda x:f"{x:,.2f}")
    result["费用（元）"]=selected["fees" if products else "total_fees"].map(lambda x:f"{x:,.2f}")
    result["平均保证金/权益"]=selected.average_margin_usage.map(lambda x:f"{x*100:.2f}%")
    return result.to_html(index=False,border=0,escape=True)


def _html(out,summary,products,curves,details,protocol,images):
    payload=json.dumps(_payload(summary,curves,details),ensure_ascii=False,allow_nan=False,separators=(",",":")).replace("</","<\\/")
    main=summary.loc[~summary.sensitivity]
    body=f"""<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>年化结构与逐合约 pair 回测</title>
<style>body{{font:15px 'Microsoft YaHei',sans-serif;max-width:1320px;margin:30px auto;padding:0 20px;background:#f4f7fb;color:#203249}}h1,h2{{color:#183d65}}section{{background:white;padding:22px;margin:22px 0;border-radius:12px}}p{{line-height:1.8}}table{{border-collapse:collapse;width:100%;font-size:13px}}th,td{{border-bottom:1px solid #dce3ee;padding:9px;text-align:right}}th:first-child,td:first-child{{text-align:left}}img{{width:100%;height:auto}}select,input{{padding:7px;margin:4px;max-width:100%}}svg{{width:100%;display:block;background:#f8fafc;border-radius:8px}}.note{{color:#58687e}}a{{color:#2563ab}}.scroll{{overflow-x:auto}}</style>
<h1>年化期现 / 跨期与期限结构条件分位回归</h1>
<p>{html.escape(protocol['evaluation_start'])}—{html.escape(protocol['evaluation_end'])}；行情自 {html.escape(protocol['price_start'])}，前 {protocol['warmup_sessions']} 交易日暖启动。
每品种 {protocol['capital_per_product']/10000:,.0f} 万元，同品种多个实际合约共享资金；四品种合计 {main.initial_capital.iloc[0]/10000:,.0f} 万元。保证金两腿均 100%，每腿每边手续费万三，分红显式忽略 D=0。</p>
<section><h2>收益与成本</h2><p>区间收益包含现金闲置和全部实际费用；年化为 (期末权益/初始资金)^(365/实际经过自然日)−1。
阈值作用于 |2p−1|，0.9 / 0.8 对应 5% / 10% 两侧极端区域。主表同一资本；每个 pair 的贡献按品种资金归因，不重复分配本金。</p><div class="scroll">{_table(main)}</div>
<h2>小资金敏感性：每品种 1,000 万元</h2><p>四份 pair 预算同时受 100% 保证金和整数手约束，部分预算不足一手，资金利用率显著下降。</p><div class="scroll">{_table(summary.loc[summary.sensitivity])}</div></section>
<section><h2>实际持仓与逐 pair 盈亏</h2><p>选择方案、品种和日期查看具体两腿。指数的虚拟 pair 数量相加后作为实际净持仓成交；只分摊实际发生的净额手续费和保证金。</p>
<div>方案 <select id="case"></select> 品种 <select id="root"></select></div>
<div>日期 <input id="day" type="range" style="width:65%"><span id="date"></span></div><svg id="structure" viewBox="0 0 1000 400"></svg><p id="positionNote"></p>
<div>实际 pair <select id="pair"></select></div><svg id="pnl" viewBox="0 0 1000 280"></svg><p id="pnlNote"></p>
<svg id="nav" viewBox="0 0 1000 230"></svg><p class="note">各 pair 累计净 PnL 之和等于品种权益减初始资金；持仓中包含期末浮盈亏，未额外假设期末平仓。</p></section>
"""
    for filename in images:
        body+=f'<section><img src="{filename}" alt="{filename}"></section>'
    body+=f"""<section><h2>分品种验证</h2><div class="scroll">{_table(products.loc[~products.sensitivity],products=True)}</div></section>
<section><h2>方法与复现范围</h2><p>期现年化 = 100×(F−S+D)/S×365/T；跨期沿用 01−03 符号，年化 = 100×(F01−F03+D01−D03)/F01×365/(T03−T01)，T 为真实剩余自然日。
跨期只用 01 和 03，开仓后锁定实际代码，任一腿到期双平。各期现 pair 分别反向开仓并持有到该实际合约到期；其他 pair 变化不重估旧手数。</p>
<p>条件分位回归以同品种前 60 交易日各有效合约的年化基差为响应，以标准化剩余期限为解释变量，分别拟合 5/10/25/50/75/90/95% 分位，最少 120 个有效观察。
已知 T&lt;5 的观察排除，其他缺项使该窗口无效，当日不入训练。预测曲线逐期限排序后反插值得到 p；CTA 才做中心化与阈值判断。
它检验的是“相对历史期限结构偏离后反转”，响应变量是年化基差；未声称预测未来收益，也未做参数搜索。
求解使用 <a href="https://docs.scipy.org/doc/scipy/reference/optimize.linprog-highs-ds.html">SciPy HiGHS 双单纯形</a>的分位 check-loss 线性规划；
<a href="quantile_coverage.csv">逐品种样本外条件分位覆盖</a>仅为描述统计，相邻日期及合约相关，不视作独立显著性检验。</p>
<p>成交为信号下一交易日真实 close，日结、到期强平、整数手、指数 200/300 单位、费用均由原引擎执行。
数据为 {html.escape(protocol['source'])}，冻结版本与绝对路径见 <a href="study.local.json">运行协议</a>，分片可用时点未核验，不能当作严格 PIT 数据证明。
DDB 获取保持暂停，VPN 未操作，没有读取 Z 或已知 Z 混合数据；区间未覆盖完整 2024 至今。</p>
<p><a href="summary.csv">汇总 CSV</a> · <a href="by_product.csv">品种 CSV</a> · <a href="study.local.json">配置、版本及核验</a>。
因子已独立保存，所有方案复用同一份原始因子，CTA 修改后逐单元一致。</p></section>
<script>const DATA={payload};
const $=id=>document.getElementById(id), NS='http://www.w3.org/2000/svg';
const money=x=>x.toLocaleString('zh-CN',{{maximumFractionDigits:2}}), sign=x=>(x>0?'+':'')+x;
function node(svg,tag,attrs,text){{let n=document.createElementNS(NS,tag);Object.entries(attrs).forEach(([k,v])=>n.setAttribute(k,v));if(text!==undefined)n.textContent=text;svg.appendChild(n);return n;}}
function text(svg,x,y,t,extra={{}}){{return node(svg,'text',{{x,y,fill:'#203249','font-size':15,...extra}},t);}}
function options(el,items){{el.replaceChildren();items.forEach(([v,t])=>{{let n=document.createElement('option');n.value=v;n.textContent=t;el.append(n);}});}}
function state(){{let c=DATA.cases[$('case').value],r=$('root').value,b=c.roots[r],d=+$('day').value;return {{c,r,b,d}};}}
function chart(svg,values,label,unit){{svg.replaceChildren();let w=1000,h=+svg.viewBox.baseVal.height,p=60,min=Math.min(0,...values),max=Math.max(0,...values),span=max-min||1;max+=span*.08;min-=span*.08;span=max-min;
 const X=i=>p+(w-2*p)*i/Math.max(1,values.length-1),Y=v=>h-p-(h-2*p)*(v-min)/span;
 for(let j=0;j<=4;j++){{let v=min+(max-min)*j/4;node(svg,'line',{{x1:p,x2:w-p,y1:Y(v),y2:Y(v),stroke:'#dce3ee'}});text(svg,4,Y(v)+5,money(v),{{'font-size':12}});}}
 node(svg,'polyline',{{points:values.map((v,i)=>X(i)+','+Y(v)).join(' '),fill:'none',stroke:'#854bb2','stroke-width':2}});text(svg,p,25,label+'（'+unit+'）');
 let {{c,d}}=state();node(svg,'line',{{x1:X(d),x2:X(d),y1:40,y2:h-p,stroke:'#e38c2b','stroke-dasharray':'4 3'}});text(svg,p,h-15,c.dates[0],{{'font-size':12}});text(svg,w-140,h-15,c.dates[c.dates.length-1],{{'font-size':12}});}}
function updatePair(){{let {{b,d}}=state(),p=b.pairs[$('pair').value];if(!p){{$('pnl').replaceChildren();$('pnlNote').textContent='该品种此方案没有实际成交 pair';return;}}chart($('pnl'),p.pnl.map(v=>v/10000),p.future+' ↔ '+p.hedge+' 累计净 PnL','万元');$('pnlNote').textContent='所选日 pair 累计净 PnL：'+money(p.pnl[d])+' 元；含实际分配费用与浮盈亏。';}}
function updateDay(){{let {{c,r,b,d}}=state(),active=b.states[d],svg=$('structure');svg.replaceChildren();$('date').textContent=c.dates[d];
 if(!active.length)text(svg,400,170,'该日无持仓');active.forEach(([id,lots,units,margin],i)=>{{let p=b.pairs[id],y=55+i*80,color=lots>0?'#20834e':'#bb4c3d';
 [[20,p.future,sign(lots)+' 手 × '+p.multiplier],[650,p.hedge,sign(units)+(p.kind==='future_index'?' 指数单位 × 1':' 手')]].forEach(([x,a,z])=>{{node(svg,'rect',{{x,y:y-30,width:330,height:62,rx:9,fill:'#eef3f9',stroke:color}});text(svg,x+16,y-5,a);text(svg,x+16,y+20,z);}});node(svg,'line',{{x1:360,x2:640,y1:y,y2:y,stroke:color,'stroke-width':2}});text(svg,405,y-10,'反向两腿 / 数量对冲');}});
 let net=active.reduce((s,a)=>s+a[2],0),margin=active.reduce((s,a)=>s+a[3],0);$('positionNote').textContent=active.length+' 个实际 pair | '+(active.some(a=>b.pairs[a[0]].kind==='future_index')?'实际指数净额 '+sign(net)+' 单位 | ':'')+'实际占用 '+money(margin)+' 元';
 chart($('nav'),c.curves[r].map(v=>(v-1)*100),r+' 账户累计净收益','%');updatePair();}}
function rootChanged(){{let {{b,d}}=state();options($('pair'),Object.entries(b.pairs).map(([id,p])=>[id,p.future+' ↔ '+p.hedge]));if(b.states[d].length)$('pair').value=b.states[d][0][0];updateDay();}}
function caseChanged(){{let c=DATA.cases[$('case').value],prev=$('root').value;options($('root'),Object.keys(c.roots).map(r=>[r,r]));if(c.roots[prev])$('root').value=prev;$('day').min=0;$('day').max=c.dates.length-1;$('day').value=c.dates.length-1;rootChanged();}}
options($('case'),Object.entries(DATA.cases).map(([k,c])=>[k,c.label]));if(DATA.cases.quantile_pairs_0_9)$('case').value='quantile_pairs_0_9';
$('case').onchange=caseChanged;$('root').onchange=rootChanged;$('day').oninput=updateDay;$('pair').onchange=updatePair;caseChanged();</script></html>"""
    (out/"report.html").write_text(body,encoding="utf-8")


def render_structure_report(out,summary,by_product,curves,pair_details,pair_summaries,results,factors,protocol):
    out=Path(out)
    plt=_plotting()
    main=summary.loc[~summary.sensitivity]
    _curves(plt,out,main,curves,protocol)
    images=["pnl_returns.png","per_product.png"]
    preferred=main.loc[main.family.eq("quantile_pairs")].iloc[0]["case"]
    images+=_pair_plots(plt,out,preferred,pair_details,pair_summaries)
    if _quantile_plots(plt,out,factors,protocol):
        images.append("quantile_structure.png")
    _html(out,summary,by_product,curves,pair_details,protocol,images)
    manifest=dict(report=str((out/"report.html").resolve()),images=images,render_input="saved factors, account equity and pair attribution; no price reread")
    write_json(out/"report.local.json",manifest)
    return manifest


def render_saved_structure_report(directory):
    out=Path(directory).resolve()
    summary=pd.read_csv(out/"summary.csv")
    products=pd.read_csv(out/"by_product.csv")
    protocol=json.loads((out/"study.local.json").read_text(encoding="utf-8-sig"))
    curves,details,summaries,results={},{},{},{}
    for key in summary["case"]:
        folder=out/key
        result=load_result(folder/"backtest")
        curves[key]=pd.concat({k:a.equity.equity for k,a in result.accounts.items()},axis=1)
        details[key]=pd.read_parquet(folder/"pairs_daily.parquet") if (folder/"pairs_daily.parquet").exists() else pd.DataFrame()
        summaries[key]=pd.read_csv(folder/"pairs_summary.csv") if (folder/"pairs_summary.csv").exists() else pd.DataFrame()
        results[key]=result
    factor_dir=out/"factors" if (out/"factors").is_dir() else protocol["factor_artifact"]
    return render_structure_report(out,summary,products,curves,details,summaries,results,load_factors(factor_dir),protocol)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--study",type=Path,required=True)
    args=parser.parse_args(argv)
    print(render_saved_structure_report(args.study)["report"])
    return 0


if __name__=="__main__":
    raise SystemExit(main())
