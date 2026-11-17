#!/usr/bin/env python3
"""
Builds the three lab reports (Markdown + PDF with a cover page).

  python3 tools/build_reports.py

For every mini project it reads  tools/templates/<project>.md, fills in the tables
from the results/*.csv files, checks the word count of the "Required" section, writes
mini_project_X/report/<name>.md and renders the matching PDF with reportlab.

Template placeholders
  {{csv:results/file.csv|col one;col two}}   -> Markdown table with those columns
  {{csv:results/file.csv}}                    -> Markdown table with all columns
"""

import csv
import os
import re
import sys

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (Image, KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table,
                                TableStyle)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TPL = os.path.join(ROOT, "tools", "templates")

# ---------------------------------------------------------------- fonts
FONT, BOLD, ITAL, MONO = "Helvetica", "Helvetica-Bold", "Helvetica-Oblique", "Courier"
fd = "/usr/share/fonts/truetype/dejavu/"
if all(os.path.exists(fd + f) for f in ("DejaVuSans.ttf", "DejaVuSans-Bold.ttf", "DejaVuSans-Oblique.ttf",
                                        "DejaVuSansMono.ttf")):
    pdfmetrics.registerFont(TTFont("DV", fd + "DejaVuSans.ttf"))
    pdfmetrics.registerFont(TTFont("DV-B", fd + "DejaVuSans-Bold.ttf"))
    pdfmetrics.registerFont(TTFont("DV-I", fd + "DejaVuSans-Oblique.ttf"))
    pdfmetrics.registerFont(TTFont("DV-M", fd + "DejaVuSansMono.ttf"))
    pdfmetrics.registerFontFamily("DV", normal="DV", bold="DV-B", italic="DV-I", boldItalic="DV-B")
    FONT, BOLD, ITAL, MONO = "DV", "DV-B", "DV-I", "DV-M"

INK = colors.HexColor("#1F2933")
BLUE = colors.HexColor("#0072B2")
GREY = colors.HexColor("#5B6770")

ST = {
    "body": ParagraphStyle("body", fontName=FONT, fontSize=9.2, leading=13.2, textColor=INK, spaceAfter=5),
    "h1": ParagraphStyle("h1", fontName=BOLD, fontSize=15, leading=19, textColor=BLUE, spaceBefore=4, spaceAfter=8),
    "h2": ParagraphStyle("h2", fontName=BOLD, fontSize=11.5, leading=15, textColor=BLUE, spaceBefore=10, spaceAfter=4),
    "h3": ParagraphStyle("h3", fontName=BOLD, fontSize=9.6, leading=13, textColor=INK, spaceBefore=6, spaceAfter=3),
    "bullet": ParagraphStyle("bullet", fontName=FONT, fontSize=9.2, leading=13, textColor=INK, leftIndent=12,
                             bulletIndent=2, spaceAfter=2),
    "cap": ParagraphStyle("cap", fontName=ITAL, fontSize=7.8, leading=10, textColor=GREY, alignment=TA_CENTER,
                          spaceAfter=8),
    "note": ParagraphStyle("note", fontName=ITAL, fontSize=7.8, leading=10, textColor=GREY, spaceAfter=3),
    "code": ParagraphStyle("code", fontName=MONO, fontSize=7.8, leading=10, textColor=INK, leftIndent=8,
                           backColor=colors.HexColor("#F2F4F6"), spaceAfter=6),
}


# ---------------------------------------------------------------- helpers
def read_csv(path):
    with open(path, newline="") as fh:
        return list(csv.reader(fh))


def csv_to_md(rel, cols, base):
    rows = read_csv(os.path.join(base, rel))
    head = rows[0]
    idx = [head.index(c) for c in cols] if cols else list(range(len(head)))
    out = ["| " + " | ".join(head[i] for i in idx) + " |", "|" + "|".join("---" for _ in idx) + "|"]
    for r in rows[1:]:
        out.append("| " + " | ".join(r[i] for i in idx) + " |")
    return "\n".join(out)


def expand(md, base):
    def sub(m):
        spec = m.group(1)
        rel, _, cols = spec.partition("|")
        return csv_to_md(rel.strip(), [c.strip() for c in cols.split(";")] if cols else None, base)
    return re.sub(r"\{\{csv:([^}]+)\}\}", sub, md)


def inline(text):
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"<i>\1</i>", text)
    text = re.sub(r"`(.+?)`", rf'<font face="{MONO}" size="8">\1</font>', text)
    return text


def section_words(md, heading):
    """Word count of the text under '## <heading>' (until the next '## ')."""
    m = re.search(rf"^## {re.escape(heading)}\s*$(.*?)(?=^## |\Z)", md, flags=re.S | re.M)
    if not m:
        return None
    body = m.group(1)
    body = re.sub(r"\(\w+ count:.*?\)", "", body)
    body = re.sub(r"[*_`#>|-]", " ", body)
    return len(body.split())


def table_flow(lines, avail):
    rows = []
    for ln in lines:
        cells = [c.strip() for c in ln.strip().strip("|").split("|")]
        if all(re.fullmatch(r":?-{2,}:?", c) for c in cells):
            continue
        rows.append(cells)
    ncol = len(rows[0])
    fs = 7.6 if ncol <= 6 else (6.9 if ncol <= 9 else 6.2)
    cs = ParagraphStyle("c", fontName=FONT, fontSize=fs, leading=fs + 2.2, textColor=INK)
    hs = ParagraphStyle("h", fontName=BOLD, fontSize=fs, leading=fs + 2.2, textColor=colors.white)
    data = [[Paragraph(inline(c), hs if i == 0 else cs) for c in r] for i, r in enumerate(rows)]
    weights = []
    for j in range(ncol):
        longest_word = max(max((len(w) for w in rows[i][j].split()), default=1) for i in range(len(rows)))
        avg = sum(len(rows[i][j]) for i in range(len(rows))) / len(rows)
        weights.append(max(longest_word * 1.0, min(avg, 26) * 0.55, 5))
    tot = sum(weights)
    widths = [avail * w / tot for w in weights]
    t = Table(data, colWidths=widths, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), BLUE),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F2F6FA")]),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#C8D1D9")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]))
    return t


def md_to_flow(md, base, avail):
    flow, lines, i = [], md.split("\n"), 0
    para = []

    def flush():
        if para:
            flow.append(Paragraph(inline(" ".join(para)), ST["body"]))
            para.clear()

    while i < len(lines):
        ln = lines[i]
        s = ln.strip()
        if not s:
            flush()
        elif s.startswith("```"):
            flush()
            i += 1
            buf = []
            while i < len(lines) and not lines[i].strip().startswith("```"):
                buf.append(lines[i].replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
                i += 1
            flow.append(Paragraph("<br/>".join(b.replace(" ", "&nbsp;") for b in buf), ST["code"]))
        elif s.startswith("### "):
            flush()
            flow.append(Paragraph(inline(s[4:]), ST["h3"]))
        elif s.startswith("## "):
            flush()
            flow.append(Paragraph(inline(s[3:]), ST["h2"]))
        elif s.startswith("# "):
            flush()
            flow.append(Paragraph(inline(s[2:]), ST["h1"]))
        elif s.startswith("|"):
            flush()
            blk = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                blk.append(lines[i])
                i += 1
            flow.append(table_flow(blk, avail))
            flow.append(Spacer(1, 5))
            continue
        elif s.startswith("!["):
            flush()
            m = re.match(r"!\[(.*?)\]\((.*?)\)", s)
            cap, rel = m.group(1), m.group(2)
            path = os.path.normpath(os.path.join(base, rel))
            w, h = ImageReader(path).getSize()
            width = min(avail, 168 * mm)
            height = width * h / w
            if height > 118 * mm:
                height = 118 * mm
                width = height * w / h
            flow.append(KeepTogether([Image(path, width=width, height=height), Paragraph(inline(cap), ST["cap"])]))
        elif s.startswith("- "):
            flush()
            flow.append(Paragraph(inline(s[2:]), ST["bullet"], bulletText="•"))
        elif re.match(r"^\d+\. ", s):
            flush()
            n, rest = s.split(". ", 1)
            flow.append(Paragraph(inline(rest), ST["bullet"], bulletText=f"{n}."))
        elif s.startswith("_") and s.endswith("_") and len(s) > 2:
            flush()
            flow.append(Paragraph(inline(s.strip("_")), ST["note"]))
        else:
            para.append(s)
        i += 1
    flush()
    return flow


def cover(title, subtitle, project):
    big = ParagraphStyle("big", fontName=BOLD, fontSize=22, leading=28, textColor=BLUE, alignment=TA_CENTER)
    mid = ParagraphStyle("mid", fontName=BOLD, fontSize=13, leading=18, textColor=INK, alignment=TA_CENTER)
    sm = ParagraphStyle("sm", fontName=FONT, fontSize=10.5, leading=16, textColor=INK, alignment=TA_CENTER)
    gr = ParagraphStyle("gr", fontName=FONT, fontSize=9, leading=13, textColor=GREY, alignment=TA_CENTER)
    f = [Spacer(1, 38 * mm),
         Paragraph("UNIVERSITY OF RWANDA", mid),
         Paragraph("College of Science and Technology", sm),
         Spacer(1, 22 * mm),
         Paragraph("Real-Time Systems", mid),
         Paragraph("Unit 4 Lab: Mini Projects", sm),
         Spacer(1, 14 * mm),
         Paragraph(inline(title), big),
         Spacer(1, 6 * mm),
         Paragraph(inline(subtitle), sm),
         Spacer(1, 38 * mm)]
    t = Table([[Paragraph("Student name:", sm), Paragraph("_" * 34, sm)],
               [Paragraph("Registration number:", sm), Paragraph("_" * 34, sm)],
               [Paragraph("Date:", sm), Paragraph("November 2026", sm)]], colWidths=[55 * mm, 80 * mm])
    t.setStyle(TableStyle([("ALIGN", (0, 0), (-1, -1), "LEFT"), ("TOPPADDING", (0, 0), (-1, -1), 5)]))
    f += [t, Spacer(1, 18 * mm), Paragraph(f"Code: {project}", gr), PageBreak()]
    return f


def build(project_dir, name, title, subtitle, tpl_file, req_heading, wc_range):
    base = os.path.join(ROOT, project_dir)
    with open(os.path.join(TPL, tpl_file)) as fh:
        md = expand(fh.read(), base)
    wc = section_words(md, req_heading)
    lo, hi = wc_range
    status = "OK" if wc is not None and lo <= wc <= hi else "OUT OF RANGE"
    print(f"{name}: '{req_heading}' = {wc} words (required {lo}-{hi}) -> {status}")
    if status != "OK":
        sys.exit(1)
    md = md.replace("{{WORDS}}", str(wc))
    out_md = os.path.join(base, "report", name + ".md")
    with open(out_md, "w") as fh:
        fh.write(md)
    avail = A4[0] - 2 * 18 * mm

    def deco(canvas, doc):
        canvas.saveState()
        canvas.setFont(FONT, 7.5)
        canvas.setFillColor(GREY)
        canvas.drawString(18 * mm, 10 * mm, f"Real-Time Systems - Unit 4 Lab - {title}")
        canvas.drawRightString(A4[0] - 18 * mm, 10 * mm, f"Page {doc.page}")
        canvas.restoreState()

    doc = SimpleDocTemplate(os.path.join(base, "report", name + ".pdf"), pagesize=A4, leftMargin=18 * mm,
                            rightMargin=18 * mm, topMargin=16 * mm, bottomMargin=18 * mm, title=title,
                            author="Real-Time Systems Unit 4 Lab")
    flow = cover(title, subtitle, project_dir)
    flow += md_to_flow(md, os.path.join(base, "report"), avail)
    doc.build(flow, onFirstPage=lambda c, d: None, onLaterPages=deco)
    return wc


if __name__ == "__main__":
    build("mini_project_4_1", "Mini_Project_4_1_Report",
          "Mini Project 4.1", "Simulating Sampling Jitter and Processing Overruns in an Embedded "
          "Sensing-and-Control Loop", "mp41.md", "Required summary", (200, 400))
    build("mini_project_4_2", "Mini_Project_4_2_Report",
          "Mini Project 4.2", "Multi-Rate Environmental Monitoring Pipeline with Timing-Compliance Reporting",
          "mp42.md", "Required report", (300, 500))
    build("mini_project_4_3", "Mini_Project_4_3_Report",
          "Mini Project 4.3", "Edge-versus-Cloud Latency Simulator for a Real-Time IoT Decision Task",
          "mp43.md", "Required report", (300, 500))
