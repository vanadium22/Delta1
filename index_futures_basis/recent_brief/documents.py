"""Word/PDF layout: a prominent opening observation page and clear chart pages."""
from __future__ import annotations

from pathlib import Path
import unicodedata

from PIL import Image

WORD_NAME = "股指基差简报.docx"
PDF_NAME = "股指基差简报.pdf"
TITLES = ("近期绝对基差与跨期", "单合约年化与历史分位表", "跨期年化与历史分位表", "四合约总成交与总持仓")
PAGE_WIDTH, PAGE_HEIGHT = 16.54, 11.69


def page_plan(output, files):
    """Split at product-row boundaries, retaining the original four full charts."""
    output = Path(output)
    parts = output / "document_figures"
    parts.mkdir(exist_ok=True)
    pages = []
    for index, filename in enumerate(files):
        with Image.open(output / filename) as image:
            bands = ((.95, .495), (.494, .048)) if index < 3 else ((.935, .500), (.497, .087))
            for half, (top, bottom) in enumerate(bands):
                target = parts / f"{index+1:02d}_{half+1}.png"
                image.crop((0, round((1-top)*image.height), image.width,
                            round((1-bottom)*image.height))).save(target)
                with Image.open(target) as part:
                    ratio = part.height / part.width
                width = min(PAGE_WIDTH-1.0, 10.0/ratio)
                pages.append({"title": TITLES[index], "part": half+1, "image": target,
                              "width": width, "height": width*ratio, "section": index})
    return pages


def _source(info):
    warning = "  "+info["dividend_warning"] if info.get("dividend_warning") else ""
    return f"行情截至 {info['as_of']}  日线收盘价  分红 {info['dividend_date']}"+warning


def _sections(info):
    return info.get("narrative_sections") or ([{"title": "", "text": info["narrative"]}] if info.get("narrative") else [])


def _wrap(text, units):
    lines, line, used = [], "", 0
    for char in text:
        width = 2 if unicodedata.east_asian_width(char) in ("W", "F") else 1
        if char == "\n" or used+width > units:
            lines.append(line)
            line, used = "", 0
            if char == "\n":
                continue
        line += char
        used += width
    if line:
        lines.append(line)
    return lines


def _word_cards(document, cards):
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Inches, Pt, RGBColor
    if not cards:
        return
    table = document.add_table(rows=(len(cards)+1)//2, cols=2)
    table.autofit = False
    for index, card in enumerate(cards):
        cell = table.cell(index//2, index%2)
        cell.width = Inches((PAGE_WIDTH-1.0)/2)
        shade = OxmlElement("w:shd")
        shade.set(qn("w:fill"), "F2F6FB")
        cell._tc.get_or_add_tcPr().append(shade)
        for number, (text, size, bold) in enumerate(
                [(card["title"], 10, False), (card["value"], 16, True), (card["detail"], 9, False)]
                +[(line, 8.5, False) for line in card.get("audit_lines", [])]):
            paragraph = cell.paragraphs[0] if number == 0 else cell.add_paragraph()
            run = paragraph.add_run(text)
            run.font.size = Pt(size)
            run.bold = bold
            if number == 1:
                run.font.color.rgb = RGBColor.from_string("A4474F" if card["direction"] < 0 else "285D94")
        # Keep the whole row together when Word repaginates.
        no_split = OxmlElement("w:cantSplit")
        table.rows[index//2]._tr.get_or_add_trPr().append(no_split)


def write_word(output, pages, info):
    from docx import Document
    from docx.oxml.ns import qn
    from docx.shared import Inches, Pt, RGBColor
    document = Document()
    for border in list(document.styles.element.iter(qn("w:pBdr"))):
        border.getparent().remove(border)
    section = document.sections[0]
    section.page_width, section.page_height = Inches(PAGE_WIDTH), Inches(PAGE_HEIGHT)
    section.top_margin = section.bottom_margin = Inches(.32)
    section.left_margin = section.right_margin = Inches(.5)
    for name in ("Normal", "Title", "Heading 1"):
        style = document.styles[name]
        style.font.name = "Microsoft YaHei"
        style.font.color.rgb = RGBColor(0, 0, 0)
        style.element.get_or_add_rPr().rFonts.set(qn("w:eastAsia"), "Microsoft YaHei")
        style.paragraph_format.space_after = Pt(2)
        style.paragraph_format.line_spacing = 1.0
    document.styles["Normal"].font.size = Pt(9)
    document.styles["Title"].font.size = Pt(24)
    document.styles["Title"].paragraph_format.space_before = Pt(0)
    document.styles["Heading 1"].font.size = Pt(17)
    opening = _sections(info)
    if opening:
        document.add_paragraph("股指基差简报 综合观察", "Title")
        document.add_paragraph(_source(info))
        for item in opening:
            if item["title"]:
                heading = document.add_paragraph(item["title"], "Heading 1")
                heading.paragraph_format.space_before = Pt(8)
            paragraph = document.add_paragraph(item["text"])
            paragraph.paragraph_format.line_spacing = 1.35
            paragraph.paragraph_format.space_after = Pt(8)
            for run in paragraph.runs:
                run.font.size = Pt(15)
        _word_cards(document, info.get("summary_cards", []))
    for number, page in enumerate(pages):
        if number or opening:
            document.add_page_break()
        heading = document.add_paragraph(f"股指基差简报 {page['title']} {page['part']}/2", "Title")
        for run in heading.runs:
            run.font.size = Pt(17)
        document.add_paragraph(_source(info))
        paragraph = document.add_paragraph()
        paragraph.paragraph_format.space_after = Pt(0)
        paragraph.add_run().add_picture(str(page["image"]), width=Inches(page["width"]), height=Inches(page["height"]))
    document.core_properties.title = "股指基差简报"
    document.core_properties.author = ""
    document.save(output / WORD_NAME)


def _pdf_cards(fig, cards, top):
    from matplotlib.patches import FancyBboxPatch
    rows = (len(cards)+1)//2
    if top-rows*.141 < .03:
        raise ValueError("综合观察首页超出版面，请缩短自动分析文本")
    for index, card in enumerate(cards):
        x, y = .03+(index%2)*.475, top-(index//2)*.141
        fig.add_artist(FancyBboxPatch((x,y-.132), .462, .128, transform=fig.transFigure,
            boxstyle="round,pad=0.002,rounding_size=0.003", facecolor="#f2f6fb", edgecolor="#e0e7ef", lw=.7))
        fig.text(x+.008, y-.009, card["title"], fontsize=10, va="top", color="black")
        fig.text(x+.008, y-.029, card["value"], fontsize=16, weight="bold", va="top",
                 color="#a4474f" if card["direction"] < 0 else "#285d94")
        fig.text(x+.008, y-.054, "\n".join(_wrap(card["detail"], 112)), fontsize=8.5, va="top", color="#405265", linespacing=1.2)
        for i, line in enumerate(card.get("audit_lines", [])):
            fig.text(x+.008, y-.088-i*.013, line, fontsize=8.5, va="top", color="#405265")


def write_pdf(output, pages, info):
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_pdf import PdfPages
    with PdfPages(output / PDF_NAME, metadata={"Title": "股指基差简报", "Author": ""}) as pdf:
        opening = _sections(info)
        if opening:
            fig = plt.figure(figsize=(PAGE_WIDTH, PAGE_HEIGHT), facecolor="white")
            fig.text(.03, .967, "股指基差简报 综合观察", fontsize=24, va="top", color="black")
            fig.text(.03, .922, _source(info), fontsize=10, va="top", color="#405265")
            y = .888
            for item in opening:
                if item["title"]:
                    fig.text(.03, y, item["title"], fontsize=17, weight="bold", va="top", color="black")
                    y -= .033
                lines = _wrap(item["text"], 145)
                fig.text(.03, y, "\n".join(lines), fontsize=15, va="top", color="black", linespacing=1.35)
                y -= len(lines)*.0241+.023
            _pdf_cards(fig, info.get("summary_cards", []), y)
            pdf.savefig(fig, dpi=260)
            plt.close(fig)
        for page in pages:
            fig = plt.figure(figsize=(PAGE_WIDTH, PAGE_HEIGHT), facecolor="white")
            fig.text(.03, .972, f"股指基差简报 {page['title']} {page['part']}/2", fontsize=17, va="top", color="black")
            fig.text(.03, .94, _source(info), fontsize=9, va="top", color="#405265")
            top = .908
            ax = fig.add_axes([.03, top-page["height"]/PAGE_HEIGHT,
                               page["width"]/PAGE_WIDTH, page["height"]/PAGE_HEIGHT])
            with Image.open(page["image"]) as picture:
                ax.imshow(picture.convert("RGB"))
            ax.axis("off")
            pdf.savefig(fig, dpi=260)
            plt.close(fig)


def export_documents(output, files, info):
    output = Path(output)
    pages = page_plan(output, files)
    write_word(output, pages, info)
    write_pdf(output, pages, info)
    return {"word": WORD_NAME, "pdf": PDF_NAME, "pages": len(pages)+bool(_sections(info)),
            "layout": "A3 landscape; opening observations and cards, then chart pages",
            "narrative_included": bool(_sections(info))}
