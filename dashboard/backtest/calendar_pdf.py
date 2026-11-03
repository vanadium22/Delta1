"""Six-page research summary from saved CSV and PNG, independent of market readers."""
import argparse
import csv
import json
import math
from pathlib import Path
from statistics import mean
from xml.sax.saxutils import escape


def build_pdf(directory, *, output=None):
    from PIL import Image
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.pdfgen.canvas import Canvas
    from reportlab.platypus import Paragraph, Table, TableStyle
    from pypdf import PdfReader
    out=Path(directory).resolve()
    study=json.loads((out/"study.local.json").read_text(encoding="utf-8"))
    research_date=study.get("research_date","2026-11-03")
    window=study["factor"]["parameters"]["window_days"]
    target=Path(output) if output else out/"output/pdf"/f"Delta1_calendar_reversal_summary_{research_date.replace('-','')}.pdf"
    target.parent.mkdir(parents=True,exist_ok=True)
    charts=json.loads((out/"chart_validation.local.json").read_text(encoding="utf-8"))
    if study["scenario_count"]!=48 or study["standalone_verified"]!=48 or len(charts["schemes"])!=48:
        raise ValueError("Final report requires all 48 schemes and their independent verification")
    def read(name):
        with (out/"csv"/(name+".csv")).open(encoding="utf-8-sig",newline="") as f:
            return list(csv.DictReader(f))
    metrics=read("account_metrics")
    trips=read("round_trips")
    episodes=read("drawdown_top3")
    examples=read("pair_examples")
    by_id={m["scenario"]:m for m in metrics}
    def num(row,key):
        return float(row[key]) if row.get(key) else math.nan
    def pct(value,sign=False):
        return f"{value*100:+.2f}%" if sign else f"{value*100:.2f}%"
    def date(value):
        return value[:10] if value else "未恢复"
    def exit_name(row):
        return "到期" if row["exit_mode"]=="expiry" else "平 "+f"{num(row,'q_close'):.1f}"
    fonts=Path("C:/Windows/Fonts")
    pdfmetrics.registerFont(TTFont("CalendarCJK",str(fonts/"msyh.ttc"),subfontIndex=0))
    pdfmetrics.registerFont(TTFont("CalendarCJKB",str(fonts/"msyhbd.ttc"),subfontIndex=0))
    pdfmetrics.registerFontFamily("CalendarCJK",normal="CalendarCJK",bold="CalendarCJKB",italic="CalendarCJK",boldItalic="CalendarCJKB")
    navy=colors.HexColor("#18334c")
    gray=colors.HexColor("#526777")
    light=colors.HexColor("#edf3f8")
    width,height=landscape(A4)
    margin=36
    available=width-2*margin
    canvas=Canvas(str(target),pagesize=(width,height),pageCompression=1)
    canvas.setTitle("Delta1 跨期策略研究：48方案、原始分位、20%保证金")
    canvas.setAuthor("Delta1 Research")
    layouts=[]
    page=0
    def text(value,x,y,size=10,bold=False,color=navy):
        canvas.setFillColor(color)
        canvas.setFont("CalendarCJKB" if bold else "CalendarCJK",size)
        canvas.drawString(x,y,str(value))
    def para(value,x,top,w=available,size=10,leading=16,min_y=38):
        p=Paragraph(value,ParagraphStyle("body",fontName="CalendarCJK",fontSize=size,leading=leading,textColor=navy))
        _,h=p.wrap(w,1000)
        if top-h<min_y:
            raise ValueError(f"Page {page} paragraph exceeds layout: {value[:50]}")
        p.drawOn(canvas,x,top-h)
        layouts.append(dict(page=page,kind="paragraph",top=top,bottom=top-h))
        return top-h
    def start(title,subtitle):
        nonlocal page
        if page:
            canvas.showPage()
        page+=1
        canvas.setFillColor(navy)
        canvas.rect(0,height-8,width,8,fill=1,stroke=0)
        text(title,margin,height-41,21,True)
        text(subtitle,margin,height-62,9.3,color=gray)
        canvas.setStrokeColor(colors.HexColor("#c7d3df"))
        canvas.line(margin,30,width-margin,30)
        text(f"Delta1 | 本地审计快照 | 数据截至 {study['evaluation_end']} | 研究日期 {research_date}",margin,17,8,color=gray)
        text(f"{page} / 6",width-margin-30,17,8,color=gray)
    def figure(name,x,top,w):
        path=out/"figures"/(name+".png")
        with Image.open(path) as img:
            h=w*img.height/img.width
        canvas.drawImage(str(path),x,top-h,width=w,height=h,mask="auto")
        layouts.append(dict(page=page,kind="figure",name=name,top=top,bottom=top-h))
        return top-h
    def table(rows,x,top,widths,size=9,row_height=21):
        style=ParagraphStyle("cell",fontName="CalendarCJK",fontSize=size,leading=size+3,textColor=navy)
        converted=[[Paragraph(escape(str(cell)),style) for cell in row] for row in rows]
        t=Table(converted,colWidths=widths,rowHeights=[row_height]*len(rows))
        t.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,0),light),("FONTNAME",(0,0),(-1,-1),"CalendarCJK"),
            ("VALIGN",(0,0),(-1,-1),"MIDDLE"),("LEFTPADDING",(0,0),(-1,-1),6),("RIGHTPADDING",(0,0),(-1,-1),6),
            ("BOTTOMPADDING",(0,0),(-1,-1),2),("TOPPADDING",(0,0),(-1,-1),2),
            ("LINEBELOW",(0,0),(-1,0),.8,colors.HexColor("#a8bccc")),
            ("LINEBELOW",(0,1),(-1,-1),.3,colors.HexColor("#dce4eb")),("ROWBACKGROUNDS",(0,1),(-1,-1),[colors.white,colors.HexColor("#f8fafc")])]))
        _,h=t.wrap(sum(widths),1000)
        if top-h<36:
            raise ValueError(f"Table exceeds page {page}")
        t.drawOn(canvas,x,top-h)
        layouts.append(dict(page=page,kind="table",top=top,bottom=top-h))
        return top-h
    positives=sum(num(m,"net_pnl")>0 for m in metrics)
    gross_positive=sum(num(m,"net_pnl")+num(m,"fees")>0 for m in metrics)
    worst=min(episodes,key=lambda r:num(r,"drawdown"))
    closed=sum(t["status"]=="closed" for t in trips)
    opened=sum(t["status"]=="open" for t in trips)
    start("跨期反转研究："+("费用后多数方案亏损" if positives<24 else "48方案历史表现对比"), "01-03 / 02-03 × IF / IH / IC / IM × q_open 0.8 / 0.9 × 3 种退出 | 48 个独立账户")
    figure("summary_48",margin,520,available)
    text("主要发现",margin,182,13,True)
    lines=[
        f"<b>{positives}/48 个方案净收益为正。</b>累计净收益范围 {pct(min(num(m,'total_return') for m in metrics))} 至 {pct(max(num(m,'total_return') for m in metrics),True)}；账户 CAGR 范围 {pct(min(num(m,'annualized_return') for m in metrics))} 至 {pct(max(num(m,'annualized_return') for m in metrics),True)}。",
        f"<b>费用影响显著。</b>按实际成交加回手续费后的毛 PnL 为正有 {gross_positive} 个方案；每账户累计手续费约 {min(num(m,'fees') for m in metrics)/10000:.1f} 至 {max(num(m,'fees') for m in metrics)/10000:.1f} 万元。该比较不改变原有成交与手数。",
        f"<b>最深回撤 {pct(num(worst,'drawdown'))}。</b>{by_id[worst['scenario']]['root']} {by_id[worst['scenario']]['channel']}、q_open={num(by_id[worst['scenario']],'q_open'):.1f} / {exit_name(by_id[worst['scenario']])}：前高 {date(worst['peak_date'])}，谷底 {date(worst['trough_date'])}，{('恢复 '+date(worst['recovery_date'])) if worst['recovery_date'] else '截至样本末日未恢复'}。",
        f"评估 {study['evaluation_start']} 至 {study['evaluation_end']}，暖启动始于 {study['coverage']['price_start']}；共 {closed:,} 笔闭合交易及 {opened} 笔期末未平仓。每账户 {study['capital_per_account']/10000:,.0f} 万元，双腿各 20% 保证金、每腿每边费率万分之{study['commission_rate']*10000:g}；分红显式忽略。"
    ]
    y=168
    for line in lines:
        y=para(line,margin,y,size=9.4,leading=14)-5
    start("01-03：四品种、两阈值与三种退出方式", "全部 24 个方案；纵轴均为百分比。颜色区分退出方式，线型区分原始 q_open；各账户本金独立。")
    figure("overview_01-03",margin,525,available)
    subset=[m for m in metrics if m["channel"]=="01-03"]
    groups=[[m for m in subset if m["exit_mode"]=="expiry"],
        [m for m in subset if num(m,"q_close")==.6],[m for m in subset if num(m,"q_close")==.4]]
    para(f"01-03 共有 <b>{sum(num(m,'net_pnl')>0 for m in subset)}/24</b> 个方案累计净收益为正。到期 / 平0.6 / 平0.4 的独立账户收益均值分别为 "
        +" / ".join(pct(mean(num(m,"total_return") for m in g)) for g in groups)
        +"。这里是每组 8 个独立账户指标的描述均值，不是共享资金策略或交易合并胜率。",margin,68,size=9.5,leading=14)
    start("02-03：四品种、两阈值与三种退出方式", "全部 24 个方案；阈值退出改变持有期与费用，不能只凭较高胜率判断表现。")
    figure("overview_02-03",margin,525,available)
    subset=[m for m in metrics if m["channel"]=="02-03"]
    im=[by_id[f"IM_02-03_open{q:.1f}_close0.4"] for q in (.8,.9)]
    para(f"02-03 共有 <b>{sum(num(m,'net_pnl')>0 for m in subset)}/24</b> 个方案累计净收益为正。IM 的平0.4方案净收益为 "
        +" / ".join(pct(num(m,"total_return"),True) for m in im)+"（q_open=0.8 / 0.9），对应最大回撤 "
        +" / ".join(pct(num(m,"max_drawdown")) for m in im)+"。各品种的全部退出方式均展示在上图。",margin,68,size=9.5,leading=14)
    start("闭合交易胜率与关键回撤日期", "上表每格为“闭合笔数 / 净胜率”；盈利、亏损、持平分别计数。下表按每个品种和组合选最深回撤，未合并交易。")
    headers=["品种 / 组合"]+[f"{q:.1f} / {ex}" for q in (.8,.9) for ex in ("到期","平0.6","平0.4")]
    rows=[headers]
    for channel in ("01-03","02-03"):
        for root in ("IF","IH","IC","IM"):
            line=[root+" "+channel]
            for q in (.8,.9):
                for ex in ("expiry","close0.6","close0.4"):
                    m=by_id[f"{root}_{channel}_open{q:.1f}_{ex}"]
                    line.append(f"{int(num(m,'closed_trades'))} / {pct(num(m,'net_win_rate'))}")
            rows.append(line)
    table(rows,margin,519,[102]+[(available-102)/6]*6,size=9,row_height=21)
    text("每个品种 / 组合中最深的回撤区间",margin,309,12,True)
    selected=[]
    for channel in ("01-03","02-03"):
        for root in ("IF","IH","IC","IM"):
            selected.append(min((r for r in episodes if by_id[r["scenario"]]["root"]==root and by_id[r["scenario"]]["channel"]==channel),key=lambda r:num(r,"drawdown")))
    rows=[["方案（原始 q_open / 退出）","前高日期","谷底日期","恢复日期","回撤","持续天数"]]
    for r in selected:
        m=by_id[r["scenario"]]
        rows.append([f"{m['root']} {m['channel']}  {num(m,'q_open'):.1f} / {exit_name(m)}",date(r["peak_date"]),date(r["trough_date"]),date(r["recovery_date"]),pct(num(r,"drawdown")),int(num(r,"duration_calendar_days"))])
    table(rows,margin,294,[235,105,105,105,100,available-650],size=8.8,row_height=22)
    para(f"回撤采用高水位至恢复的完整区间；未恢复区间持续到 {study['evaluation_end']}。全部48方案的最大回撤及前3个不重叠区间、"
         "图中 P/T/R 标记值和日期见外部 CSV 与详细 PNG。期末未平仓不进入胜率；平均盈亏与盈亏比分方案列于 account_metrics.csv。",margin,82,size=9,leading=14)
    start("每笔收益分布与退出方式比较", "八账户统一 q_open=0.8 / q_close=0.6；纵轴=每笔保证金净收益率，横轴=次数；橙虚线=均值，绿点线=中位数，深线=零。")
    figure("distribution_comparison",margin,524,available)
    rows=[["组合 / 退出","账户净收益均值","净收益范围","闭合笔数范围","净胜率范围"]]
    for channel in ("01-03","02-03"):
        for ex,close in (("到期",None),("平0.6",.6),("平0.4",.4)):
            subset=[m for m in metrics if m["channel"]==channel and (m["exit_mode"]=="expiry" if close is None else num(m,"q_close")==close)]
            returns=[num(m,"total_return") for m in subset]
            counts=[int(num(m,"closed_trades")) for m in subset]
            wins=[num(m,"net_win_rate") for m in subset]
            rows.append([channel+" / "+ex,pct(mean(returns)),pct(min(returns))+" 至 "+pct(max(returns)),f"{min(counts)} - {max(counts)}",pct(min(wins))+" 至 "+pct(max(wins))])
    table(rows,margin,163,[125,140,220,130,available-615],size=8.7,row_height=17.5)
    start("实际两腿示例、口径与复现验证", "示例固定选各组合 IC、q_open=0.8、持有到期的首笔闭合交易；不按收益挑选。金额曲线均已扣实际手续费。")
    half=(available-18)/2
    figure("pair_IC_01-03",margin,523,half)
    figure("pair_IC_02-03",margin+half+18,523,half)
    for j,channel in enumerate(("01-03","02-03")):
        r=next(r for r in examples if r["root"]=="IC" and r["channel"]==channel)
        para(f"<b>{channel}</b> | 入场 p={num(r,'entry_p'):.3f}，退出 p={num(r,'exit_p'):.3f}；"
            f"入场保证金 {num(r,'entry_margin')/10000:.2f} 万元，净 PnL {num(r,'net_pnl')/10000:+.2f} 万元，"
            f"每笔净收益率 {pct(num(r,'net_return'),True)}。",margin+j*(half+18),335,w=half,size=9,leading=14)
    text("策略与统计口径",margin,276,12,True)
    text("验证结果与复现入口",margin+half+18,276,12,True)
    left=[
        f"年化价差 = 100 × (F近-F远) / F近 × 365 / (T远-T近)。T为真实到期剩余自然日；普通历史分位使用此前{window}交易日，排除当前日。",
        "q_open=0.8：p&gt;0.8空价差、p&lt;0.2多价差；0.9对应p&gt;0.9 / p&lt;0.1。等价中心化绝对阈值是0.6 / 0.8，报告统一使用原始p。",
        f"空价差在p≤q_close退出，多价差在p≥1-q_close退出。所持真实pair相对入场通道的滚动前{window}日连续分布取分位，因子阶段保存；CTA仅查表。",
        "阈值信号下一共同有效观测成交；本快照为下一日真实close。任一实际腿到期当日close双平。锁定实际合约、等整数手数，不重叠、不隐含换月。",
        "每笔 r=净PnL/冻结入场保证金；年化金额=净PnL×365/持有自然日；年化收益率=(1+r)^(365/天数)-1。天数为0或r≤-1时两项年化不适用。账户CAGR另以初始资金计算。"
    ]
    right=[
        "48/48方案完成并逐账户单独重跑一致；CTA参数变化未改变原始因子，重读保存因子得到相同权重；3个截点的因子前缀重放一致。",
        f"{closed:,}笔闭合交易、{opened}笔未平仓；每笔两腿毛PnL、手续费、保证金、数量和每日账户权益均对账。48幅直方图计数与各方案闭合样本数一致。",
        f"全部回撤图的权益、回撤与日期标记逐点核对；共{charts['total_figures']}幅PNG。完整数据、参数、图表及离线网页均在外部交付目录，不附入本PDF。",
        "运行：python -m dashboard.backtest.calendar_study --config YOUR_LOCAL_CONFIG --output NEW_OUTPUT。单阶段和调参命令详见 CALENDAR_REVERSAL.md 与交付包的运行说明。",
        "研究边界：仅作历史参数对比，无独立样本外检验；不考虑分红。算法无未来日期输入已验证，参考元数据未具备完整PIT发布时刻档案。DDB/VPN继续暂停，本轮未访问Z源。"
    ]
    for x,items in ((margin,left),(margin+half+18,right)):
        y=263
        for item in items:
            y=para(item,x,y,w=half,size=8.7,leading=12.2)-5
    canvas.save()
    reader=PdfReader(str(target))
    if len(reader.pages)!=6:
        raise ValueError("Summary PDF must have exactly six pages")
    extracted=[p.extract_text() for p in reader.pages]
    if "主要发现" not in extracted[0] or any(len(t)<100 for t in extracted):
        raise ValueError("PDF text integrity check failed")
    evidence=dict(pdf=str(target.resolve()),pages=6,all_48_schemes=True,home_summary_image="summary_48.png",
        closed_trades=closed,open_trades=opened,positive_schemes=positives,figures=charts["total_figures"],layouts=layouts,
        page_text_characters=list(map(len,extracted)))
    (out/"pdf_validation.local.json").write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding="utf-8")
    return evidence


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory",type=Path)
    parser.add_argument("--output",type=Path)
    args=parser.parse_args(argv)
    result=build_pdf(args.directory,output=args.output)
    print(json.dumps(dict(pdf=result["pdf"],pages=result["pages"]),ensure_ascii=False))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
