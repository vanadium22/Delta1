"""Word/PDF packaging, kept separate from market calculations and chart rendering."""
from __future__ import annotations

from pathlib import Path

from PIL import Image

WORD_NAME = "股指基差简报.docx"
PDF_NAME = "股指基差简报.pdf"
TITLES = ("近期绝对基差与跨期", "单合约年化与历史分位表", "跨期年化与历史分位表", "四合约总成交与总持仓")
PAGE_WIDTH, PAGE_HEIGHT = 16.54, 11.69  # A3 landscape: preserve readable chart size.


def page_plan(output, files):
    """Split only at product-row boundaries; retain the four full original charts."""
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
                # Same image rectangle in Word and PDF; no full-page tiny thumbnails.
                width = min(PAGE_WIDTH-1.0, 9.0/ratio)
                pages.append({"title": TITLES[index], "part": half+1, "image": target,
                              "width": width, "height": width*ratio, "section": index})
    return pages


def _notes(info, page, number):
    source = f"行情截至 {info['as_of']}  分红 {info['dividend_date']}"
    if number < 2:
        summary = "\n".join(f"{c['title']}：{c['value']}（{c['detail']}）" for c in info["summary_cards"][number*2:(number+1)*2])
    else:
        summary = ""
    caption = info["explanations"][page["section"]]
    return source, summary, caption


def _source_note(info):
    text = info["source_note"].replace("\n", " ")
    return text if len(text) <= 240 else text[:220]+"（完整来源与更新记录随报告保留）"


def write_word(output, pages, info):
    from docx import Document
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Inches, Pt, RGBColor
    document = Document()
    # The bundled/default Word template can carry a blue Title paragraph border.
    # Remove paragraph borders from styles as well as their inherited defaults.
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
    document.styles["Title"].font.size = Pt(17)
    document.styles["Title"].paragraph_format.space_before = Pt(0)
    for number, page in enumerate(pages):
        if number:
            document.add_page_break()
        source, summary, caption = _notes(info, page, number)
        document.add_paragraph(f"股指基差简报  {page['title']}  {page['part']}/2", "Title")
        document.add_paragraph(source)
        if summary:
            table = document.add_table(rows=1, cols=2)
            table.autofit = False
            for cell, card in zip(table.rows[0].cells, info["summary_cards"][number*2:(number+1)*2]):
                cell.width = Inches((PAGE_WIDTH-1.0)/2)
                shade = OxmlElement("w:shd")
                shade.set(qn("w:fill"), "F2F6FB")
                cell._tc.get_or_add_tcPr().append(shade)
                p = cell.paragraphs[0]
                run = p.add_run(card["title"])
                run.font.size = Pt(10)
                p = cell.add_paragraph()
                run = p.add_run(card["value"])
                run.bold = True
                run.font.size = Pt(16)
                run.font.color.rgb = RGBColor.from_string("A4474F" if card["direction"] < 0 else "285D94")
                p = cell.add_paragraph()
                run = p.add_run(card["detail"])
                run.font.size = Pt(8)
        p = document.add_paragraph()
        p.paragraph_format.space_after = Pt(0)
        p.add_run().add_picture(str(page["image"]), width=Inches(page["width"]), height=Inches(page["height"]))
        if number == len(pages)-1 and info.get("narrative"):
            document.add_paragraph("综合观察", "Heading 1")
            paragraph = document.add_paragraph(info["narrative"])
            for run in paragraph.runs:
                run.font.size = Pt(11)
            paragraph.paragraph_format.line_spacing = 1.5
    document.core_properties.title = "股指基差简报"
    document.core_properties.author = ""
    document.save(output / WORD_NAME)


def write_pdf(output, pages, info):
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_pdf import PdfPages
    from matplotlib.patches import FancyBboxPatch
    with PdfPages(output / PDF_NAME, metadata={"Title": "股指基差简报", "Author": ""}) as pdf:
        for number, page in enumerate(pages):
            fig = plt.figure(figsize=(PAGE_WIDTH, PAGE_HEIGHT), facecolor="white")
            fig.text(.03, .972, f"股指基差简报  {page['title']}  {page['part']}/2", fontsize=17, va="top", color="black")
            source, summary, caption = _notes(info, page, number)
            fig.text(.03, .94, source, fontsize=9, va="top", color="#405265")
            if summary:
                for col, card in enumerate(info["summary_cards"][number*2:(number+1)*2]):
                    x = .03+col*.475
                    fig.add_artist(FancyBboxPatch((x, .856), .462, .058, transform=fig.transFigure,
                        boxstyle="round,pad=0.002,rounding_size=0.003", facecolor="#f2f6fb", edgecolor="#e0e7ef", lw=.7))
                    fig.text(x+.008, .906, card["title"], fontsize=9, va="top", color="black")
                    fig.text(x+.008, .890, card["value"], fontsize=16, weight="bold", va="top",
                             color="#a4474f" if card["direction"] < 0 else "#285d94")
                    fig.text(x+.008, .866, card["detail"], fontsize=8, va="top", color="#405265")
            top = .846 if summary else .88
            ax = fig.add_axes([.03, top-page["height"]/PAGE_HEIGHT,
                               page["width"]/PAGE_WIDTH, page["height"]/PAGE_HEIGHT])
            with Image.open(page["image"]) as picture:
                # Opaque RGB avoids image-mask artifacts in PDF readers.
                ax.imshow(picture.convert("RGB"))
            ax.axis("off")
            if number == len(pages)-1 and info.get("narrative"):
                import unicodedata
                lines, line, used = [], "", 0
                for char in info["narrative"]:
                    width = 2 if unicodedata.east_asian_width(char) in ("W", "F") else 1
                    if used+width > 190:
                        lines.append(line)
                        line, used = "", 0
                    line += char
                    used += width
                if line:
                    lines.append(line)
                y = min(.34, top-page["height"]/PAGE_HEIGHT-.04)
                fig.text(.04, y, "综合观察", fontsize=14, weight="bold", va="top", color="black")
                fig.text(.04, y-.032, "\n".join(lines), fontsize=11, va="top", color="black", linespacing=1.65)
            pdf.savefig(fig, dpi=260)
            plt.close(fig)


def export_documents(output, files, info):
    output = Path(output)
    pages = page_plan(output, files)
    write_word(output, pages, info)
    write_pdf(output, pages, info)
    return {"word": WORD_NAME, "pdf": PDF_NAME, "pages": len(pages), "layout": "A3 landscape, images and cards; final data commentary only", "narrative_included": bool(info.get("narrative"))}
