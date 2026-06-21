from pathlib import Path
import re

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    BaseDocTemplate, Frame, PageTemplate, Paragraph, Spacer, Table, TableStyle,
    PageBreak, KeepTogether, ListFlowable, ListItem, HRFlowable,
)

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "docs" / "manual-writing-guide.md"
OUTPUT = ROOT / "output" / "pdf" / "manual-writing-guide.pdf"

FONT = "/System/Library/Fonts/STHeiti Medium.ttc"
FONT_LIGHT = "/System/Library/Fonts/STHeiti Light.ttc"
pdfmetrics.registerFont(TTFont("CN", FONT, subfontIndex=0))
pdfmetrics.registerFont(TTFont("CNLight", FONT_LIGHT, subfontIndex=0))


def inline_markup(text):
    text = re.sub(r"\[([^]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"`([^`]+)`", r'<font name="CN">\1</font>', text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", text)
    return text.replace("&", "&amp;").replace("&amp;lt;", "&lt;") if False else text


class GuideDoc(BaseDocTemplate):
    def __init__(self, filename, **kwargs):
        super().__init__(filename, **kwargs)
        frame = Frame(self.leftMargin, self.bottomMargin, self.width, self.height,
                      leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
        self.addPageTemplates(PageTemplate(id="main", frames=[frame], onPage=self.decorate))

    def decorate(self, canvas, doc):
        canvas.saveState()
        canvas.setFont("CNLight", 8)
        canvas.setFillColor(colors.HexColor("#64748b"))
        canvas.drawString(self.leftMargin, 13 * mm, "AllDocs · 操作手册编写规范")
        canvas.drawRightString(A4[0] - self.rightMargin, 13 * mm, f"{doc.page}")
        canvas.setStrokeColor(colors.HexColor("#dbe3ec"))
        canvas.line(self.leftMargin, 17 * mm, A4[0] - self.rightMargin, 17 * mm)
        canvas.restoreState()

    def afterFlowable(self, flowable):
        if isinstance(flowable, Paragraph) and hasattr(flowable, "bookmark_level"):
            key = f"h-{self.seq.nextf('heading')}"
            self.canv.bookmarkPage(key, fit="FitH", top=self.canv._pagesize[1] - self.topMargin)
            self.canv.addOutlineEntry(flowable.getPlainText(), key, flowable.bookmark_level, closed=False)


base = getSampleStyleSheet()
styles = {
    "body": ParagraphStyle("body", fontName="CNLight", fontSize=9.4, leading=15,
                           textColor=colors.HexColor("#27364a"), spaceAfter=4),
    "h1": ParagraphStyle("h1", fontName="CN", fontSize=22, leading=29,
                         textColor=colors.HexColor("#102a43"), spaceAfter=12),
    "h2": ParagraphStyle("h2", fontName="CN", fontSize=15, leading=21,
                         textColor=colors.HexColor("#145da0"), spaceBefore=13, spaceAfter=7,
                         keepWithNext=True),
    "h3": ParagraphStyle("h3", fontName="CN", fontSize=11.5, leading=17,
                         textColor=colors.HexColor("#1e4f72"), spaceBefore=9, spaceAfter=5,
                         keepWithNext=True),
    "code": ParagraphStyle("code", fontName="CNLight", fontSize=8.1, leading=12,
                           leftIndent=8, rightIndent=8, borderColor=colors.HexColor("#d8e2ec"),
                           borderWidth=.5, borderPadding=7, backColor=colors.HexColor("#f6f8fa"),
                           spaceBefore=4, spaceAfter=7),
    "small": ParagraphStyle("small", fontName="CNLight", fontSize=7.9, leading=11.5,
                            textColor=colors.HexColor("#334e68")),
}


def para(text, style="body"):
    return Paragraph(inline_markup(text), styles[style])


def make_table(rows):
    cooked = [[Paragraph(inline_markup(c.strip()), styles["small"]) for c in row] for row in rows]
    n = len(cooked[0])
    widths = [170 * mm / n] * n
    t = Table(cooked, colWidths=widths, repeatRows=1, hAlign="LEFT")
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#dceaf5")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#123b5d")),
        ("FONTNAME", (0, 0), (-1, 0), "CN"),
        ("GRID", (0, 0), (-1, -1), .35, colors.HexColor("#b9cad8")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
    ]))
    return t


def parse_markdown(text):
    lines = text.splitlines()
    story = []
    i = 0
    while i < len(lines):
        line = lines[i].rstrip()
        if not line:
            i += 1
            continue
        if line.startswith("```"):
            block = []
            i += 1
            while i < len(lines) and not lines[i].startswith("```"):
                block.append(lines[i].replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
                i += 1
            story.append(Paragraph("<br/>".join(block), styles["code"]))
            i += 1
            continue
        if line.startswith("# "):
            p = para(line[2:], "h1"); p.bookmark_level = 0; story.append(p)
            i += 1; continue
        if line.startswith("## "):
            p = para(line[3:], "h2"); p.bookmark_level = 0; story.append(p)
            i += 1; continue
        if line.startswith("### "):
            p = para(line[4:], "h3"); p.bookmark_level = 1; story.append(p)
            i += 1; continue
        if re.match(r"^\|.*\|$", line) and i + 1 < len(lines) and re.match(r"^\|[ :|-]+\|$", lines[i + 1]):
            rows = [[c for c in line.strip("|").split("|")]]
            i += 2
            while i < len(lines) and re.match(r"^\|.*\|$", lines[i]):
                rows.append([c for c in lines[i].strip("|").split("|")])
                i += 1
            story.append(make_table(rows)); story.append(Spacer(1, 7)); continue
        if line.startswith("- "):
            items = []
            while i < len(lines) and lines[i].startswith("- "):
                items.append(ListItem(para(lines[i][2:]), leftIndent=10))
                i += 1
            story.append(ListFlowable(items, bulletType="bullet", leftIndent=16, bulletFontName="CN",
                                      bulletFontSize=7, spaceAfter=4)); continue
        if re.match(r"^\d+\. ", line):
            items = []
            while i < len(lines) and re.match(r"^\d+\. ", lines[i]):
                items.append(ListItem(para(re.sub(r"^\d+\. ", "", lines[i])), leftIndent=12))
                i += 1
            story.append(ListFlowable(items, bulletType="1", leftIndent=20, bulletFontName="CN",
                                      bulletFontSize=8.5, spaceAfter=4)); continue
        if line == "---":
            story.append(HRFlowable(width="100%", thickness=.6, color=colors.HexColor("#c7d5e0"),
                                    spaceBefore=4, spaceAfter=6)); i += 1; continue
        paragraph = [line]
        i += 1
        while i < len(lines) and lines[i].strip() and not re.match(r"^(#{1,3} |```|\|.*\||- |\d+\. |---$)", lines[i]):
            paragraph.append(lines[i].strip()); i += 1
        story.append(para(" ".join(paragraph)))
    return story


OUTPUT.parent.mkdir(parents=True, exist_ok=True)
doc = GuideDoc(str(OUTPUT), pagesize=A4, leftMargin=20 * mm, rightMargin=20 * mm,
               topMargin=19 * mm, bottomMargin=24 * mm,
               title="操作手册编写规范", author="AllDocs")
doc.build(parse_markdown(SOURCE.read_text(encoding="utf-8")))
print(OUTPUT)
