"""Saved-only independent slot comparisons, actual pair legs and offline charts."""
import argparse
import html
import json
from pathlib import Path

import pandas as pd

from .analytics import performance_metrics
from .io import write_json
from .structure_report import _finish, _payload, _plotting


METHODS={"history":"普通历史分位","regression":"期限结构分位回归"}
COLORS={"history":"#2563ab","regression":"#854bb2"}


def _wide(frame,keys,columns):
    parts=[]
    for method in METHODS:
        part=frame.loc[frame.method.eq(method)].set_index(keys)[columns]
        if part.index.duplicated().any():
            raise ValueError("Duplicate comparison identity")
        parts.append(part.add_prefix(method+"_"))
    return pd.concat(parts,axis=1).sort_index().reset_index()


def comparison_tables(out,metrics,pairs,curves,protocol):
    aggregate=[]
    capital=protocol["capital_per_account"]
    for threshold in protocol["thresholds"]:
        for method in METHODS:
            equity=curves[f"{method}_{str(threshold).replace('.','_')}"]
            for root in sorted(metrics.root.unique()):
                slots=[c for c in equity if c.startswith(root)]
                assert len(slots)==4
                result=performance_metrics(equity[slots].sum(axis=1),capital*4)
                aggregate.append(dict(root=root,threshold=threshold,method=method,**result))
    product=_wide(pd.DataFrame(aggregate),["root","threshold"],["annualized_return","max_drawdown","net_pnl","total_return"])
    groups=_wide(metrics.loc[metrics.method.ne("calendar")],["root","group_id","slot","threshold"],
                 ["annualized_return","max_drawdown","net_pnl","future_pnl","hedge_pnl","fees","orders"])
    index=pairs.loc[pairs.method.ne("calendar")]
    pair_compare=_wide(index,["root","group_id","slot","threshold","future","hedge"],
        ["future_pnl","hedge_pnl","net_pnl","future_fees","hedge_fees","future_gross_pnl","hedge_gross_pnl"])
    # An absent strategy/pair row means it made no trade, not a missing market quote.
    for method in METHODS:
        pair_compare[method+"_traded"]=pair_compare[method+"_net_pnl"].notna()
        fields=[c for c in pair_compare if c.startswith(method+"_") and c!=method+"_traded"]
        pair_compare[fields]=pair_compare[fields].fillna(0.)
    product.to_csv(out/"product_comparison.csv",index=False,encoding="utf-8-sig")
    groups.to_csv(out/"slot_comparison.csv",index=False,encoding="utf-8-sig")
    pair_compare.to_csv(out/"pair_comparison.csv",index=False,encoding="utf-8-sig")
    return product,groups,pair_compare


def _plots(out,metrics,curves,protocol,details):
    plt=_plotting()
    capital=protocol["capital_per_account"]
    roots=[r for r in ("IF","IH","IC","IM") if r in set(metrics.root)]
    images=[]
    for threshold in protocol["thresholds"]:
        tag=str(threshold).replace(".","_")
        for kind in ("returns","pnl"):
            fig,axes=plt.subplots(len(roots),4,figsize=(17,3.1*len(roots)),squeeze=False,layout="constrained")
            for i,root in enumerate(roots):
                for slot in range(4):
                    ax=axes[i,slot]
                    group=f"{root}{slot:02d}"
                    for method in METHODS:
                        equity=curves[method+"_"+tag][group]
                        y=100*(equity/capital-1) if kind=="returns" else (equity-capital)/10000
                        ax.plot(equity.index,y,color=COLORS[method],label=METHODS[method],lw=1.2)
                    ax.set_title(group+" · 独立账户",loc="left",fontsize=11)
                    ax.axhline(0,color="#64748b",lw=.6)
                    ax.tick_params(axis="x",labelsize=7,rotation=20)
                    if slot==0:
                        ax.set_ylabel("累计净收益（%）" if kind=="returns" else "累计净 PnL（万元）")
            axes[0,0].legend(fontsize=8)
            fig.suptitle(f"16组固定档位期现策略 | 中心化阈值 {threshold:g}\n{protocol['evaluation_start']}—{protocol['evaluation_end']} | 每组独立 {capital/10000:g} 万元 | 100%保证金 | 各自收费，不跨组净额",fontsize=14)
            file=f"{kind}_{tag}.png"
            _finish(plt,fig,out/file)
            images.append(file)
        fig,axes=plt.subplots(len(roots),4,figsize=(17,3*len(roots)),squeeze=False,layout="constrained")
        for i,root in enumerate(roots):
            for slot in range(4):
                ax=axes[i,slot]
                rows=metrics.loc[metrics.root.eq(root)&metrics.slot.eq(slot)&metrics.threshold.eq(threshold)].set_index("method")
                labels,values,colors=[],[],[]
                for method in METHODS:
                    for leg,title in (("future_pnl","期货"),("hedge_pnl","指数"),("net_pnl","合计")):
                        labels.append(("历史" if method=="history" else "回归")+title)
                        values.append(rows.at[method,leg]/10000)
                        colors.append(COLORS[method] if leg!="net_pnl" else "#20834e")
                ax.bar(range(6),values,color=colors)
                ax.set_xticks(range(6),labels,rotation=55,fontsize=7)
                ax.set_title(f"{root}{slot:02d}",loc="left",fontsize=11)
                ax.axhline(0,color="#64748b",lw=.6)
                if slot==0:
                    ax.set_ylabel("各腿净 PnL（万元）")
        fig.suptitle(f"两腿累计贡献 | 阈值 {threshold:g} | 每条腿已扣自身手续费，合计不重复扣费",fontsize=14)
        file=f"legs_{tag}.png"
        _finish(plt,fig,out/file)
        images.append(file)
    fig,axes=plt.subplots(2,2,figsize=(13,8),layout="constrained")
    for ax,root in zip(axes.ravel(),roots):
        for threshold in protocol["thresholds"]:
            equity=curves["calendar_"+str(threshold).replace(".","_")][root+"_01_03"]
            ax.plot(equity.index,100*(equity/capital-1),label=f"阈值 {threshold:g}")
        ax.set_title(root+" 01−03",loc="left")
        ax.set_ylabel("累计净收益（%）")
        ax.legend()
        ax.axhline(0,color="#64748b",lw=.6)
    fig.suptitle("跨期：4品种各一组独立账户 | 年化使用 T03−T01 | 任一腿到期双平",fontsize=14)
    _finish(plt,fig,out/"calendar_returns.png")
    images.append("calendar_returns.png")
    threshold=protocol["thresholds"][0]
    detail=details["regression_"+str(threshold).replace(".","_")]
    stamp=detail.timestamp.max()
    fig,axes=plt.subplots(len(roots),4,figsize=(17,2.7*len(roots)),squeeze=False,layout="constrained")
    for i,root in enumerate(roots):
        for slot in range(4):
            ax=axes[i,slot]
            ax.axis("off")
            group=f"{root}{slot:02d}"
            ax.text(.03,.95,group,weight="bold",fontsize=13)
            active=detail.loc[detail.group_id.eq(group)&detail.timestamp.eq(stamp)&detail.future_lots.ne(0)]
            if active.empty:
                ax.text(.03,.5,"期末无持仓",color="#64748b")
                continue
            assert len(active)==1
            row=active.iloc[0]
            ax.text(.06,.68,f"{row.future}\n{row.future_lots:+.0f} 手 × {row.multiplier:g}",fontsize=12,bbox=dict(boxstyle="round,pad=.5",fc="#eef3f9",ec="#2563ab"))
            ax.text(.48,.41,"反向，等价数量和 = 0",fontsize=10,ha="center")
            ax.text(.06,.12,f"{row.hedge}\n{row.hedge_units:+.0f} 单位 × 1",fontsize=12,bbox=dict(boxstyle="round,pad=.5",fc="#f5effa",ec="#854bb2"))
    fig.suptitle(f"16组实际期现 pair | 分位回归 {threshold:g} | {stamp.date()} 日结后\n每格为独立账户；不同档位即使持同一合约，也分别核算",fontsize=14)
    _finish(plt,fig,out/"pairs_latest_16.png")
    images.append("pairs_latest_16.png")
    return images


def _comparison_table(frame,identity):
    result=pd.DataFrame({label:frame[field] for field,label in identity})
    for method,label in METHODS.items():
        for field,title in (("annualized_return","年化"),("max_drawdown","最大回撤")):
            result[label+title]=frame[method+"_"+field].map(lambda v:f"{100*v:+.3f}%")
    return result.to_html(index=False,border=0)


def _report_html(out,protocol,metrics,product,groups,comparisons,curves,details,images):
    capital=protocol["capital_per_account"]
    records=[]
    payload_curves,payload_details={},{}
    for key,equity in curves.items():
        method,threshold=key.rsplit("_",2)[0],float(".".join(key.rsplit("_",2)[1:]))
        alias=("history_pairs" if method=="history" else "quantile_pairs" if method=="regression" else "calendar")+"_"+str(threshold).replace(".","_")
        records.append(dict(case=alias,label=METHODS.get(method,"年化跨期01−03"),threshold=threshold,capital_per_product=capital))
        payload_curves[alias]=equity
        payload_details[alias]=details[key].rename(columns={"root":"product_root"}).assign(root=details[key].group_id)
    data=_payload(pd.DataFrame(records),payload_curves,payload_details,capital_label="每组")
    data["pair_comparison"]=comparisons.to_dict(orient="records")
    payload=json.dumps(data,ensure_ascii=False,allow_nan=False,separators=(",",":")).replace("</","<\\/")
    calendar=metrics.loc[metrics.method.eq("calendar"),["root","threshold","annualized_return","max_drawdown","net_pnl","future_pnl","hedge_pnl"]].copy()
    for field in ("annualized_return","max_drawdown"):
        calendar[field]=calendar[field].map(lambda v:f"{v*100:+.3f}%")
    calendar=calendar.rename(columns={"root":"品种","threshold":"阈值","annualized_return":"年化净收益","max_drawdown":"最大回撤","net_pnl":"净PnL（元）","future_pnl":"近腿净PnL（元）","hedge_pnl":"远腿净PnL（元）"})
    body=f"""<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>2024起：16组独立期现与4组跨期</title>
<style>body{{font:15px 'Microsoft YaHei',sans-serif;max-width:1400px;margin:28px auto;padding:0 20px;background:#f4f7fb;color:#203249}}section{{background:white;border-radius:12px;padding:22px;margin:20px 0}}p{{line-height:1.8}}h1,h2{{color:#183d65}}table{{border-collapse:collapse;font-size:13px;width:100%}}th,td{{padding:9px;text-align:right;border-bottom:1px solid #dde5ef}}th:first-child,td:first-child{{text-align:left}}img,svg{{width:100%;display:block}}svg{{background:#f8fafc;border-radius:8px}}select,input{{padding:7px;margin:4px}}.scroll{{overflow-x:auto}}a{{color:#2563ab}}</style>
<h1>16组独立期现账户与4组跨期账户</h1><p>{protocol['evaluation_start']}—{protocol['evaluation_end']}，请求从2024年初起；2023年数据完成60交易日暖启动。
每组独立初始资金 {capital/10000:g} 万元，保证金100%，两腿每边万三，分红显式 D=0。期末未强制平仓，已含浮盈亏。</p>
<section><h2>IF / IH / IC / IM 分别比较</h2><p>此表仅把同品种四个独立账户的权益相加，初始资金为4组之和；原始成交、费用与指数腿仍逐组独立，没有跨档位净额或资金互用。</p>
<div class="scroll">{_comparison_table(product,[("root","品种"),("threshold","阈值")])}</div>
<h2>固定档位的16组 PnL</h2><p>IF02只在空仓时从当天02档找入场实际合约。成交后锁定实际代码直到到期，即使它后来成为01或00也不换月；到期后再从当时02档寻找下一组。四个品种、四个档位各自一组资金和指数持仓。</p>
<div class="scroll">{_comparison_table(groups,[("group_id","独立组"),("threshold","阈值")])}</div></section>
<section><h2>实际 pair、两腿 PnL 与账户收益</h2><div>方法和阈值 <select id="case"></select> 独立账户 <select id="root"></select></div>
<div>日期 <input id="day" type="range" style="width:65%"><span id="date"></span></div><svg id="structure" viewBox="0 0 1000 230"></svg><p id="positionNote"></p>
<svg id="nav" viewBox="0 0 1000 250"></svg><div>具体实际 pair <select id="pair"></select></div><svg id="pnl" viewBox="0 0 1000 260"></svg><p id="pnlNote"></p>
<p>下面按同一独立组、同一实际合约对比两种方法。数字为万元，两条腿分别已扣自身费用；合计相加即可，不能再减一次手续费。“未交易”按零贡献列示，不代表原价缺失补零。</p><div class="scroll" id="pairTable"></div>
<p><a href="actual_pair_legs.csv">每条腿毛PnL、费用与净PnL完整明细</a> · <a href="pair_comparison.csv">按实际合约对齐两种方法</a></p></section>
<section><h2>跨期：4品种各一组01−03</h2><p>每组独立 {capital/10000:g} 万元，两腿反向等手数，年化分母是 T03−T01，任一到期双平。</p><div class="scroll">{calendar.to_html(index=False,border=0)}</div></section>"""
    for filename in images:
        body+=f'<section><img src="{html.escape(filename)}" alt="{html.escape(filename)}"></section>'
    body+=f"""<section><h2>数据和计算口径</h2><p>普通历史分位比较今天所处档位此前60交易日的年化基差；分位回归按同品种前60交易日各期限的年化基差对剩余自然日拟合条件分位，当前日不入训练。
回归使用其他期限的历史观察作因子估计，各组持仓及账户完全隔离。0.9/0.8作用于 |2p−1|，对应两侧5%/10%；高尾部空期货多指数，低尾部反向，下一交易日真实close成交。
IF/IH每手配反向300指数单位，IC/IM配200；每个独立账户自身两腿等价数量和为零。</p>
<p>年化收益为 (期末权益/初始资金)^(365/实际经过自然日)−1。单个实际合约的PnL贡献不冒充一份独立本金的CAGR；各pair两腿净PnL合计必须等于对应组的权益变动。
本地快照 {protocol['price_start']}—{protocol['price_end']}，用户明确授权只读导入Z来源；所有回测读取P盘冻结快照，原始Z文件没有写操作。
已有注册价格优先，同一单元补缺不做跨日填充；源SHA、逐单元来源、映射、真实到期、重叠冲突见data快照的import_manifest.local.json。
Z项目声明T日收盘数据在收盘后可用；已有注册源的历史发布时间仍未知，分别保留来源口径。</p>
<p>DDB获取暂停，VPN未操作。末日为当前已核验的共同有效覆盖，未宣称补齐到今天。
<a href="product_comparison.csv">品种比较</a> · <a href="slot_comparison.csv">16组比较</a> · <a href="account_metrics.csv">各独立账户完整指标</a> · <a href="study.local.json">运行配置和审计</a>。</p></section>
<script>const DATA={payload};const $=id=>document.getElementById(id),NS='http://www.w3.org/2000/svg';
const money=x=>x.toLocaleString('zh-CN',{{maximumFractionDigits:2}}),sign=x=>(x>0?'+':'')+x;
function node(s,t,a,v){{let n=document.createElementNS(NS,t);Object.entries(a).forEach(([k,v])=>n.setAttribute(k,v));if(v!==undefined)n.textContent=v;s.append(n);return n;}}
function text(s,x,y,v,a={{}}){{node(s,'text',{{x,y,fill:'#203249','font-size':15,...a}},v);}}
function options(el,items){{el.replaceChildren();items.forEach(([v,t])=>{{let o=document.createElement('option');o.value=v;o.textContent=t;el.append(o);}});}}
function state(){{let c=DATA.cases[$('case').value],r=$('root').value,b=c.roots[r],d=+$('day').value;return {{c,r,b,d}};}}
function chart(svg,values,label,unit){{svg.replaceChildren();let h=svg.viewBox.baseVal.height,p=60,min=Math.min(0,...values),max=Math.max(0,...values),span=max-min||1;min-=span*.08;max+=span*.08;span=max-min;const X=i=>p+(1000-2*p)*i/Math.max(1,values.length-1),Y=v=>h-p-(h-2*p)*(v-min)/span;
 for(let j=0;j<5;j++){{let v=min+span*j/4;node(svg,'line',{{x1:p,x2:940,y1:Y(v),y2:Y(v),stroke:'#dce3ee'}});text(svg,4,Y(v)+4,money(v),{{'font-size':12}});}}node(svg,'polyline',{{points:values.map((v,i)=>X(i)+','+Y(v)).join(' '),fill:'none',stroke:'#854bb2','stroke-width':2}});text(svg,p,25,label+'（'+unit+'）');let {{c,d}}=state();node(svg,'line',{{x1:X(d),x2:X(d),y1:40,y2:h-p,stroke:'#d27719','stroke-dasharray':'4 3'}});text(svg,p,h-15,c.dates[0],{{'font-size':12}});text(svg,850,h-15,c.dates[c.dates.length-1],{{'font-size':12}});}}
function updatePair(){{let {{b,d}}=state(),p=b.pairs[$('pair').value];if(!p){{$('pnl').replaceChildren();$('pnlNote').textContent='此组没有实际成交';return;}}chart($('pnl'),p.pnl.map(v=>v/10000),p.future+' ↔ '+p.hedge+' 净 PnL','万元');$('pnlNote').textContent='所选日该实际pair累计净PnL：'+money(p.pnl[d])+' 元';}}
function updateDay(){{let {{c,r,b,d}}=state(),svg=$('structure'),active=b.states[d];svg.replaceChildren();$('date').textContent=c.dates[d];if(!active.length)text(svg,400,100,'此组当日空仓');active.forEach(([id,lots,units,margin],i)=>{{let p=b.pairs[id],y=80+i*80;[[20,p.future,sign(lots)+' 手 × '+p.multiplier],[650,p.hedge,sign(units)+(p.kind==='future_index'?' 指数单位 × 1':' 手')]].forEach(([x,a,z])=>{{node(svg,'rect',{{x,y:y-30,width:330,height:65,rx:8,fill:'#eef3f9',stroke:'#2563ab'}});text(svg,x+15,y-5,a);text(svg,x+15,y+20,z);}});node(svg,'line',{{x1:360,x2:640,y1:y,y2:y,stroke:'#854bb2','stroke-width':2}});text(svg,405,y-12,'独立两腿，数量对冲');}});$('positionNote').textContent='独立账户 '+r+' | '+active.length+'组实际pair | 占用 '+money(active.reduce((s,a)=>s+a[3],0))+' 元';chart($('nav'),c.curves[r].map(v=>(v-1)*100),r+' 账户累计净收益','%');updatePair();}}
function pairTable(){{let {{c,r}}=state(),threshold=+$('case').value.split('_').slice(-2).join('.'),rows=DATA.pair_comparison.filter(p=>p.group_id===r&&Math.abs(p.threshold-threshold)<1e-9),table=document.createElement('table');let head=table.createTHead().insertRow();['实际合约/指数','历史：期货净PnL','历史：指数净PnL','历史：合计','回归：期货净PnL','回归：指数净PnL','回归：合计'].forEach(t=>{{let th=document.createElement('th');th.textContent=t;head.append(th);}});let body=table.createTBody();rows.forEach(p=>{{let tr=body.insertRow();tr.insertCell().textContent=p.future+' / '+p.hedge;['history','regression'].forEach(m=>['future_pnl','hedge_pnl','net_pnl'].forEach(f=>tr.insertCell().textContent=money(p[m+'_'+f]/10000)));}});$('pairTable').replaceChildren(table);}}
function rootChanged(){{let {{b,d}}=state();options($('pair'),Object.entries(b.pairs).map(([id,p])=>[id,p.future+' ↔ '+p.hedge]));if(b.states[d].length)$('pair').value=b.states[d][0][0];updateDay();pairTable();}}
function caseChanged(){{let c=DATA.cases[$('case').value],old=$('root').value;options($('root'),Object.keys(c.roots).map(r=>[r,r]));if(c.roots[old])$('root').value=old;$('day').min=0;$('day').max=c.dates.length-1;$('day').value=c.dates.length-1;rootChanged();}}
options($('case'),Object.entries(DATA.cases).map(([k,c])=>[k,c.label]));$('case').value='quantile_pairs_0_9';$('case').onchange=caseChanged;$('root').onchange=rootChanged;$('day').oninput=updateDay;$('pair').onchange=updatePair;caseChanged();</script></html>"""
    (out/"report.html").write_text(body,encoding="utf-8")


def render_slot_report(directory):
    out=Path(directory).resolve()
    protocol=json.loads((out/"study.local.json").read_text(encoding="utf-8-sig"))
    metrics=pd.read_csv(out/"account_metrics.csv")
    pairs=pd.read_csv(out/"actual_pair_legs.csv")
    curves={}
    details={}
    for method in (*METHODS,"calendar"):
        for threshold in protocol["thresholds"]:
            key=method+"_"+str(threshold).replace(".","_")
            curves[key]=pd.read_parquet(out/(key+"_equity.parquet"))
            if curves[key].isna().any().any():
                raise ValueError("Cannot aggregate stopped accounts or fill missing equity")
            folders=[c for c in protocol["cases"] if c.startswith(method+"_") and c.endswith("_"+str(threshold).replace(".","_"))]
            frames=[pd.read_parquet(out/c/"pairs_daily.parquet") for c in folders if (out/c/"pairs_daily.parquet").exists()]
            details[key]=pd.concat(frames,ignore_index=True)
    product,groups,comparison=comparison_tables(out,metrics,pairs,curves,protocol)
    images=_plots(out,metrics,curves,protocol,details)
    _report_html(out,protocol,metrics,product,groups,comparison,curves,details,images)
    write_json(out/"report.local.json",dict(status="complete",report=str(out/"report.html"),images=images,
        input="saved account, pair and equity artifacts only; no original market reads",pair_rows=len(comparison)))
    return dict(report=str(out/"report.html"),product=product,groups=groups,pairs=comparison)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--study",type=Path,required=True)
    args=parser.parse_args(argv)
    print(render_slot_report(args.study)["report"])
    return 0


if __name__=="__main__":
    raise SystemExit(main())
