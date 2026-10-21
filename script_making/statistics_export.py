"""Render the same statistics documents to native views, full PNGs and mail drafts."""
from __future__ import annotations

import math
from datetime import datetime
from decimal import Decimal
from email.message import EmailMessage
from email.policy import SMTP
from email.utils import getaddresses
from html import escape
from pathlib import Path

from PySide6.QtCore import QRectF
from PySide6.QtGui import QFont, QImage, QPainter, QTextDocument

from .statistics import FIELDS, DEFAULT_TEMPLATE, LEGACY_DEFAULT_TEMPLATES, combined_risks
from .storage import ReportError, atomic_json

LABELS = {"swap": "收益互换日报", "strategy": "D1策略台日报", "pnl": "盈亏统计"}


def display(value):
    if value is None:
        return ""
    if isinstance(value, (int, float, Decimal)):
        return f"{value:,.2f}"
    return str(value)


def money(value):
    return "未取得" if value is None else f"{Decimal(value):,.2f}"


def table(headers, rows, highlight=None, *, summary=False, related=()):
    output = '<table width="100%" cellspacing="0" cellpadding="7" border="1"><tr>'
    output += "".join(f'<th bgcolor="#e8eef5">{escape(str(v))}</th>' for v in headers) + "</tr>"
    for index, row in enumerate(rows):
        color = ("#185b59" if index == highlight else "#fff0bf" if index in related
                 else "#ffffff" if index % 2 else "#f4f7fa")
        cells = []
        for position, value in enumerate(row):
            foreground = "#ffffff" if index == highlight else "#18324c"
            if summary and position >= 4:
                amount = Decimal(str(value).replace(",", ""))
                foreground = "#b84641" if amount > 0 else "#147b6d" if amount < 0 else "#536678"
            background = ("#e9f2fb" if index < 2 else "#e7f4ef" if index < 4 else "#ffe4a3") if summary else color
            content = escape(display(value))
            bold = summary or index == highlight or index in related
            size = ' size="4"' if index == highlight else ''
            cells.append(f'<td bgcolor="{background}"><font color="{foreground}"{size}>{"<b>" if bold else ""}{content}{"</b>" if bold else ""}</font></td>')
        output += "<tr>" + "".join(cells) + "</tr>"
    return output + "</table>"


def metric_cards(pnl):
    cards = []
    for title, key in (("本期累计净利润", "current"), ("上期累计净利润", "previous"), ("两期净利润变动", "change")):
        value = pnl[key]
        color = "#b84641" if value is not None and Decimal(value) > 0 else "#147b6d" if value is not None and Decimal(value) < 0 else "#18324c"
        cards.append(f'<td width="33%" bgcolor="#eaf1f8"><p>{title} · 元</p><p><font size="6" color="{color}"><b>{money(value)}</b></font></p></td>')
    return '<table width="100%" cellpadding="16" cellspacing="5"><tr>' + "".join(cards) + "</tr></table>"


def document(title, body, snapshot):
    return ("<html><head><style>body{color:#18324c;font-family:'Microsoft YaHei UI';font-size:10pt;}"
            "h1{font-size:23pt;color:#152d49;}h2{font-size:14pt;color:#185b59;}"
            "p{line-height:140%;}table{border-color:#d9e1ea;}th{text-align:left;}"
            ".note{color:#536678;}.error{color:#aa3b24;}</style></head><body>"
            f"<p>DELTA ONE · 日报统计</p><h1>{escape(title)}</h1>{body}"
            f'<p class="note">生成时间：{escape(snapshot["created_at"])} · 记录 {snapshot["id"][:10]}</p></body></html>')


def pnl_text(snapshot):
    pnl = snapshot["pnl"]
    if not pnl:
        return "pnl1 未生成：" + snapshot["errors"].get("pnl", "未取得报表")
    return (f"报表 {pnl['date']}｜累计净利润：{money(pnl['current'])} 元\n"
            f"较 {pnl['previous_date'] or '未取得上期'} 变动：{money(pnl['change'])} 元\n"
            "原表为 T-2 口径；两期变动可能跨日，跨年不相减。")


def risk_text(snapshot):
    config = snapshot["config"]
    lines = [f"观察：|{config['metric']}| ≥ {money(config['threshold'])}"]
    for kind in ("swap", "strategy"):
        result = snapshot["risks"].get(kind)
        if result is None:
            lines.append(f"{LABELS[kind]}：未生成，{snapshot['errors'].get(kind, '无数据')}")
            continue
        lines.append(f"{LABELS[kind]}：{result['date']}")
    for group in combined_risks(snapshot["risks"]):
        lines.append(f"• {group['name']}：总盈亏 {money(group['total'])}；"
                     f"当日盈亏 {money(group['daily'])}；净敞口 {money(group['net'])} 元")
    lines.append("上述为两日报观察项直接累加，日期可不同，同标的不去重；非全台盈亏。")
    return "\n".join(lines)


def render_pages(snapshot):
    pnl = snapshot["pnl"]
    if pnl:
        body = f"<p>报表日期：<b>{pnl['date']}</b> · 上期报表：<b>{pnl['previous_date'] or '未取得'}</b> · 金额单位：元</p>"
        body += metric_cards(pnl)
        body += f'<p class="note">{escape(pnl["warning"])}</p>'
        if snapshot.get("history", {}).get("pnl"):
            from .statistics_charts import chart_html
            body += chart_html(snapshot)
        body += "<h2>pnl1 · 累积盈亏统计原表内容</h2>"
        grid = pnl["grid"]
        rows = [[str(line), *row] for line, row in zip(grid["source_rows"], grid["rows"])]
        body += table(["原行号", *[c["name"] for c in grid["columns"]]], rows,
                      grid["source_rows"].index(pnl["row"]),
                      related={i for i, line in enumerate(grid["source_rows"]) if pnl["row"] < line <= pnl["row"] + 4})
        body += '<p class="note">保留原表全部有值行和列；合并区域文字位于左上角。读取 Excel 缓存净利润，不重算公式。</p>'
    else:
        body = '<p class="error">' + escape(pnl_text(snapshot)) + "</p>"
    first = document("组内收益 · pnl1", body, snapshot)
    config = snapshot["config"]
    body = (f"<p>观察条件：<b>|{escape(config['metric'])}| ≥ {money(config['threshold'])}</b></p>"
            "<p>金额单位：元。汇总仅含达到绝对值阈值且未剔除的标的，敞口保留正负号。Delta 数量只在明细展示，不跨标的相加。</p>")
    summary = []
    for kind in ("swap", "strategy"):
        risk = snapshot["risks"].get(kind)
        if not risk:
            body += f'<p class="error">{LABELS[kind]}未生成：{escape(snapshot["errors"].get(kind, "无数据"))}</p>'
            continue
        for group in risk["groups"]:
            summary.append([LABELS[kind], risk["date"], group["name"], str(group["count"]),
                            *[money(group[key]) for key in ("total", "daily", "net")]])
    for group in combined_risks(snapshot["risks"]):
        summary.append(["两日报总汇总", " / ".join(group["dates"].values()), group["name"], str(group["count"]),
                        *[money(group[key]) for key in ("total", "daily", "net")]])
    body += table(["日报", "日期", "分组", "观察数", "总盈亏", "当日盈亏", "净敞口金额 Σx"], summary, summary=True)
    body += '<p class="note">总汇总按两份日报各自日期直接累加，同标的跨日报不去重，观察数为两来源条目数之和；不是同一日的全台合并口径。任一来源失败时不生成总汇总。净敞口按原始正负值累加，不展示绝对敞口合计。</p>'
    for kind in ("swap", "strategy"):
        risk = snapshot["risks"].get(kind)
        if not risk:
            continue
        body += f"<h2>{LABELS[kind]} · {risk['date']}</h2>"
        for group in risk["groups"]:
            body += f"<p><b>{group['name']} · {group['count']} 个观察标的</b></p>"
            body += (table(FIELDS, [[*row[:2], *[money(v) for v in row[2:]]] for row in group["rows"]])
                     if group["rows"] else "<p>无达到阈值的标的。</p>")
        body += '<p class="note">本表实际剔除：' + escape("、".join(risk["excluded"]) or "无") + "</p>"
    body += '<p class="note">永久剔除名单：' + escape("、".join(config["exclusions"]) or "空") + "</p>"
    return first, document("风险观察 · 分日报与总汇总", body, snapshot)


def mail_content(snapshot, values):
    dates = " / ".join(dict.fromkeys(item["date"] for key, item in snapshot["sources"].items() if key in LABELS))
    replacements = {"{{pnl1}}": pnl_text(snapshot), "{{risk}}": risk_text(snapshot), "{{dates}}": dates}
    body = values.get("template") or DEFAULT_TEMPLATE
    if body in LEGACY_DEFAULT_TEMPLATES:
        body = DEFAULT_TEMPLATE
    for old in ("附件为 pnl1 和风险观察两张完整统计图片。",
                "附件为 pnl1、风险观察完整统计图片及两份日报今年的盈亏双轴图。",
                "附件为 pnl1 完整统计图片（含当年最近30份报表的收益图）及风险观察汇总图片。"):
        body = body.replace(old, "详情见附件 pnl1.png（含当年收益图）和 risk.png。")
    body = body.replace("顺颂商祺。", "顺颂\n  时祺")
    subject = values.get("subject") or "日报统计 {{dates}}"
    for key, value in replacements.items():
        body, subject = body.replace(key, value), subject.replace(key, value)
    return subject, body


def save_image(html, path, width=1600):
    doc = QTextDocument()
    doc.setDefaultFont(QFont("Microsoft YaHei UI", 10))
    doc.setDocumentMargin(28)
    doc.setHtml(html)
    doc.setTextWidth(width)
    height = math.ceil(doc.size().height()) + 5
    if height > 60000 or width * height > 60_000_000:
        raise ReportError("完整页面过长，无法安全导出单张图片。请提高观察阈值后重新生成；不会截断内容。")
    canvas = QImage(width, height, QImage.Format.Format_RGB32)
    if canvas.isNull():
        raise ReportError("无法分配整页图片内存，请提高阈值后重试。")
    canvas.fill("white")
    painter = QPainter(canvas)
    doc.drawContents(painter, QRectF(0, 0, width, height))
    painter.end()
    if not canvas.save(str(path), "PNG"):
        raise ReportError("图片保存失败，请检查目标目录。")
    return width, height


def export_bundle(base, snapshot, pages, values):
    for field in ("to", "cc", "subject"):
        if any(c in values.get(field, "") for c in "\r\n"):
            raise ReportError("邮件地址及主题不能包含换行。")
    addresses = {}
    for field in ("to", "cc"):
        raw = values.get(field, "").replace("；", ",").replace(";", ",")
        parsed = getaddresses([raw])
        if raw.strip() and (not parsed or any(not addr or "@" not in addr or " " in addr for _, addr in parsed)):
            raise ReportError("邮件地址格式无效，请使用逗号分隔完整地址。")
        addresses[field] = raw
    folder = Path(base) / (datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + snapshot["id"][:10])
    # Repeated exports never replace an edited mail draft.
    suffix = 1
    original = folder
    while folder.exists():
        folder = original.with_name(original.name + f"-{suffix}")
        suffix += 1
    folder.mkdir(parents=True)
    try:
        files = [folder / "pnl1.png", folder / "risk.png"]
        for html, path in zip(pages, files):
            save_image(html, path)
        subject, body = mail_content(snapshot, values)
        message = EmailMessage(policy=SMTP)
        message["Subject"] = subject
        for field in ("to", "cc"):
            if addresses[field].strip():
                message[field.title()] = addresses[field]
        message["X-Unsent"] = "1"
        message.set_content(body)
        for path in files:
            message.add_attachment(path.read_bytes(), maintype="image", subtype="png", filename=path.name)
        (folder / "邮件草稿.eml").write_bytes(message.as_bytes())
        (folder / "邮件正文.txt").write_text(subject + "\n\n" + body, encoding="utf-8")
        atomic_json(folder / "统计记录.json", snapshot)
        atomic_json(folder / "邮件设置.json", values)
    except Exception:
        (folder / "导出未完成.txt").write_text("本次导出未完成，请重新导出，不要使用此目录的部分附件。", encoding="utf-8")
        raise
    return folder
