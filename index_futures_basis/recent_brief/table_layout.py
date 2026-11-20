"""One combined contract matrix and a separate calendar-spread table."""

from .overview import table_cells
from .theme import PRODUCT_COLORS, HEADER, BORDER, INK, RED


def source_line(info):
    warning = "  " + info["dividend_warning"] if info.get("dividend_warning") else ""
    return (
        f"行情截至 {info['as_of']}  {info.get('price_label', '日线收盘价')}  分红 {info['dividend_date']}"
        + warning
    )


SINGLE_HEADERS = [
    "品种 / 指数",
    "连续档位",
    "实际合约",
    "期货价格",
    "分红G",
    "去分红基差",
    "年化基差",
    "到期日",
    "剩余天数",
]


SINGLE_WIDTHS = [2.45, 1.0, 2.05, 1.75, 1.35, 1.65, 1.50, 2.05, 1.74]


CROSS_HEADERS = [
    "品种 / 指数",
    "跨期",
    "原始价差",
    "分红差",
    "去分红价差",
    "年化价差",
    "间隔天数",
]


CROSS_WIDTHS = [2.65, 1.75, 2.4, 2.15, 2.45, 2.2, 1.94]


def table_rows(info, kind):
    rows = []
    for product in info["current_tables"]:
        spot = product["spot_close"]
        label = (
            f"{product['root']}  {product['name']}\n指数 {spot:,.2f}"
            if spot is not None
            else f"{product['root']}  {product['name']}\n指数 —"
        )
        for row in product["rows"]:
            if row["kind"] != kind:
                continue
            values = table_cells(row)
            rows.append(
                [label]
                + (
                    [
                        values[0],
                        values[1],
                        values[2],
                        values[3],
                        values[4],
                        values[5],
                        values[6],
                        values[7],
                    ]
                    if kind == "single"
                    else [
                        values[0],
                        values[2],
                        values[3],
                        values[4],
                        values[5],
                        values[7],
                    ]
                )
            )
    return rows


def _paint_cell(cell, value, fill, color, size, bold=False):
    from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Pt, RGBColor

    cell.text = ""
    cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
    pr = cell._tc.get_or_add_tcPr()
    shade = OxmlElement("w:shd")
    shade.set(qn("w:fill"), fill)
    pr.append(shade)
    borders = OxmlElement("w:tcBorders")
    for side in ("top", "left", "bottom", "right"):
        edge = OxmlElement("w:" + side)
        for key, val in (("val", "single"), ("sz", "4"), ("color", BORDER)):
            edge.set(qn("w:" + key), val)
        borders.append(edge)
    pr.append(borders)
    margin = OxmlElement("w:tcMar")
    for side, value_twips in (
        ("top", 110),
        ("bottom", 110),
        ("left", 85),
        ("right", 85),
    ):
        element = OxmlElement("w:" + side)
        element.set(qn("w:w"), str(value_twips))
        element.set(qn("w:type"), "dxa")
        margin.append(element)
    pr.append(margin)
    p = cell.paragraphs[0]
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(0)
    p.paragraph_format.space_after = Pt(0)
    p.paragraph_format.line_spacing = Pt(22)
    snap = OxmlElement("w:snapToGrid")
    snap.set(qn("w:val"), "0")
    p._p.get_or_add_pPr().append(snap)
    run = p.add_run(value)
    run.bold = bold
    run.font.size = Pt(size)
    run.font.color.rgb = RGBColor.from_string(color)


def write_word_tables(document, info):
    from docx.enum.table import WD_ROW_HEIGHT_RULE
    from docx.oxml import OxmlElement
    from docx.shared import Inches, Pt

    if not info.get("current_tables"):
        return
    for kind, title, headers, widths, legs in (
        ("single", "股指基差简报 四品种合约总表", SINGLE_HEADERS, SINGLE_WIDTHS, 4),
        ("calendar", "股指基差简报 跨期结构表", CROSS_HEADERS, CROSS_WIDTHS, 2),
    ):
        heading = document.add_paragraph(title, "Title")
        heading.paragraph_format.page_break_before = True
        document.add_paragraph(source_line(info)).paragraph_format.space_after = Pt(12)
        table = document.add_table(rows=1, cols=len(headers))
        table.autofit = False
        for col, width in zip(table.columns, widths):
            col.width = Inches(width)
        for j, value in enumerate(headers):
            cell = table.rows[0].cells[j]
            cell.width = Inches(widths[j])
            _paint_cell(cell, value, HEADER, "FFFFFF", 12.5, True)
        table.rows[0]._tr.get_or_add_trPr().append(OxmlElement("w:tblHeader"))
        values = table_rows(info, kind)
        for index, values_row in enumerate(values):
            row = table.add_row()
            row._tr.get_or_add_trPr().append(OxmlElement("w:cantSplit"))
            if kind == "calendar":
                row.height = Pt(52)
                row.height_rule = WD_ROW_HEIGHT_RULE.AT_LEAST
            root_index, slot = index // legs, index % legs
            tone, shades = PRODUCT_COLORS[root_index]
            for j, value in enumerate(values_row):
                cell = row.cells[j]
                cell.width = Inches(widths[j])
                _paint_cell(
                    cell,
                    "" if j == 0 else value,
                    shades[slot if kind == "single" else slot * 2],
                    (
                        RED.lstrip("#")
                        if j in ((5, 6) if kind == "single" else (4, 5))
                        and value.startswith("-")
                        else tone if j == 1 else INK.lstrip("#")
                    ),
                    13.5,
                    j in ((1, 5, 6) if kind == "single" else (1, 4, 5)),
                )
        for root_index in range(len(info.get("current_tables", []))):
            first = 1 + root_index * legs
            merged = table.cell(first, 0).merge(table.cell(first + legs - 1, 0))
            _paint_cell(
                merged,
                values[root_index * legs][0],
                PRODUCT_COLORS[root_index][0],
                "FFFFFF",
                14,
                True,
            )


def write_pdf_tables(pdf, info):
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle

    if not info.get("current_tables"):
        return
    for kind, title, headers, widths, legs in (
        ("single", "股指基差简报 四品种合约总表", SINGLE_HEADERS, SINGLE_WIDTHS, 4),
        ("calendar", "股指基差简报 跨期结构表", CROSS_HEADERS, CROSS_WIDTHS, 2),
    ):
        fig = plt.figure(figsize=(16.54, 11.69), facecolor="white")
        fig.text(0.03, 0.967, title, fontsize=24, va="top", color="black")
        fig.text(0.03, 0.922, source_line(info), fontsize=10, va="top", color="#405265")
        ax = fig.add_axes(
            [0.03, 0.09, 0.94, 0.775] if kind == "single" else [0.03, 0.305, 0.94, 0.56]
        )
        ax.axis("off")
        rows = table_rows(info, kind)
        texts = [[""] + row[1:] for row in rows]
        table = ax.table(
            cellText=texts,
            colLabels=headers,
            colWidths=[w / sum(widths) for w in widths],
            cellLoc="center",
            bbox=[0, 0, 1, 1],
        )
        table.auto_set_font_size(False)
        for (i, j), cell in table.get_celld().items():
            cell.set_edgecolor("#" + BORDER)
            cell.set_linewidth(0.7)
            if i == 0:
                cell.set_facecolor("#" + HEADER)
                cell.get_text().set_color("white")
                cell.get_text().set_fontsize(12.5)
                cell.get_text().set_weight("bold")
            else:
                root_index, slot = (i - 1) // legs, (i - 1) % legs
                tone, shades = PRODUCT_COLORS[root_index]
                value = cell.get_text().get_text()
                cell.set_facecolor(
                    "#"
                    + (
                        tone
                        if j == 0
                        else shades[slot if kind == "single" else slot * 2]
                    )
                )
                cell.get_text().set_color(
                    RED
                    if j in ((5, 6) if kind == "single" else (4, 5))
                    and value.startswith("-")
                    else "#" + tone if j == 1 else INK
                )
                cell.get_text().set_fontsize(13.5)
                cell.get_text().set_weight(
                    "bold"
                    if j in ((1, 5, 6) if kind == "single" else (1, 4, 5))
                    else "normal"
                )
                if j == 0:
                    cell.visible_edges = (
                        "LR"
                        + ("T" if slot == 0 else "")
                        + ("B" if slot == legs - 1 else "")
                    )
        for root_index in range(len(info.get("current_tables", []))):
            y = 1 - (1 + root_index * legs + legs / 2) / (len(rows) + 1)
            height = legs / (len(rows) + 1)
            ax.add_patch(
                Rectangle(
                    (0, y - height / 2),
                    widths[0] / sum(widths),
                    height,
                    transform=ax.transAxes,
                    facecolor="#" + PRODUCT_COLORS[root_index][0],
                    edgecolor="#" + BORDER,
                    linewidth=0.7,
                    zorder=5,
                )
            )
            ax.text(
                widths[0] / sum(widths) / 2,
                y,
                rows[root_index * legs][0],
                transform=ax.transAxes,
                ha="center",
                va="center",
                fontsize=14,
                weight="bold",
                color="white",
                linespacing=1.8,
                zorder=6,
            )
        pdf.savefig(fig, dpi=260)
        plt.close(fig)
