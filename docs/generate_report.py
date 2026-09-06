"""Generates the Enterprise AI Operations Copilot technical report PDF.
Run:  python docs/generate_report.py  (from repo root)
"""
import os
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (BaseDocTemplate, PageTemplate, Frame, Paragraph,
                                Spacer, Table, TableStyle, PageBreak, KeepTogether,
                                Flowable, NextPageTemplate)
from reportlab.platypus.tableofcontents import TableOfContents
from reportlab.graphics.shapes import Drawing, Rect, String, Line, Polygon
from reportlab.lib.enums import TA_LEFT, TA_CENTER

BASE = os.path.dirname(os.path.abspath(__file__))

NAVY = colors.HexColor("#0F2A43")
BLUE = colors.HexColor("#1D6FB8")
LIGHT = colors.HexColor("#EAF2F9")
ACCENT = colors.HexColor("#0FA47F")
WARN = colors.HexColor("#B8860B")
GREY = colors.HexColor("#5A6B7B")

styles = getSampleStyleSheet()

def PS(name, **kw):
    return ParagraphStyle(name, parent=styles["Normal"], **kw)

S = {
    "CoverTitle": PS("CoverTitle", fontName="Helvetica-Bold", fontSize=26, leading=32,
                     textColor=colors.white, alignment=TA_CENTER),
    "CoverSub": PS("CoverSub", fontName="Helvetica", fontSize=13, leading=18,
                   textColor=colors.HexColor("#BFD7EA"), alignment=TA_CENTER),
    "CoverMeta": PS("CoverMeta", fontName="Helvetica", fontSize=11, leading=16,
                    textColor=colors.white, alignment=TA_CENTER),
    "H1": PS("H1", fontName="Helvetica-Bold", fontSize=17, leading=22, textColor=NAVY,
             spaceBefore=14, spaceAfter=8),
    "H2": PS("H2", fontName="Helvetica-Bold", fontSize=12.5, leading=17, textColor=BLUE,
             spaceBefore=10, spaceAfter=5),
    "H3": PS("H3", fontName="Helvetica-BoldOblique", fontSize=10.5, leading=14,
             textColor=NAVY, spaceBefore=8, spaceAfter=3),
    "P": PS("P", fontName="Helvetica", fontSize=9.5, leading=13.5, spaceAfter=5),
    "B": PS("B", fontName="Helvetica", fontSize=9.5, leading=13, leftIndent=14,
            bulletIndent=4, spaceAfter=2.5),
    "Cell": PS("Cell", fontName="Helvetica", fontSize=8.3, leading=10.8),
    "CellB": PS("CellB", fontName="Helvetica-Bold", fontSize=8.3, leading=10.8,
                textColor=colors.white),
    "Cap": PS("Cap", fontName="Helvetica-Oblique", fontSize=8, leading=10,
              textColor=GREY, alignment=TA_CENTER, spaceBefore=3, spaceAfter=8),
    "Code": PS("Code", fontName="Courier", fontSize=8, leading=10.5,
               backColor=colors.HexColor("#F4F6F8"), borderPadding=4, leftIndent=6,
               spaceAfter=6),
    "TOC1": PS("TOC1", fontName="Helvetica-Bold", fontSize=10, leading=15, textColor=NAVY),
    "TOC2": PS("TOC2", fontName="Helvetica", fontSize=9, leading=13, leftIndent=14),
}

def P(text, style="P"):
    return Paragraph(text, S[style])

def bullets(items):
    return [Paragraph(t, S["B"], bulletText="•") for t in items]

def table(header, rows, widths=None, zebra=True, header_bg=NAVY):
    data = [[Paragraph(h, S["CellB"]) for h in header]]
    for r in rows:
        data.append([Paragraph(str(c), S["Cell"]) for c in r])
    t = Table(data, colWidths=widths, repeatRows=1)
    st = [
        ("BACKGROUND", (0, 0), (-1, 0), header_bg),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#B9C6D2")),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]
    if zebra:
        for i in range(1, len(data)):
            if i % 2 == 0:
                st.append(("BACKGROUND", (0, i), (-1, i), LIGHT))
    t.setStyle(TableStyle(st))
    return t

def caption(text):
    return Paragraph(text, S["Cap"])

class Diagram(Flowable):
    """Simple canvas-based diagram flowable."""
    def __init__(self, width, height, draw_fn):
        super().__init__()
        self.width = width
        self.height = height
        self._draw = draw_fn

    def draw(self):
        c = self.canv
        c.saveState()
        self._draw(c, self.width, self.height)
        c.restoreState()

def box(c, x, y, w, h, text, fill=LIGHT, stroke=BLUE, font_size=7.5,
        text_color=NAVY, bold=False, radius=3):
    c.setFillColor(fill); c.setStrokeColor(stroke); c.setLineWidth(0.8)
    c.roundRect(x, y, w, h, radius, stroke=1, fill=1)
    c.setFillColor(text_color)
    c.setFont("Helvetica-Bold" if bold else "Helvetica", font_size)
    lines = text.split("\n")
    total = len(lines) * (font_size + 2)
    ty = y + h / 2 + total / 2 - font_size
    for ln in lines:
        c.drawCentredString(x + w / 2, ty, ln)
        ty -= font_size + 2

# ---------------------------------------------------------------------------
# Document template with TOC support, header/footer, page numbers
# ---------------------------------------------------------------------------
class ReportDoc(BaseDocTemplate):
    def __init__(self, filename, **kw):
        super().__init__(filename, pagesize=A4, leftMargin=18 * mm,
                         rightMargin=18 * mm, topMargin=20 * mm,
                         bottomMargin=18 * mm, **kw)
        frame = Frame(self.leftMargin, self.bottomMargin, self.width, self.height)
        self.addPageTemplates([PageTemplate(id="main", frames=[frame],
                                            onPage=self._page_decor)])

    def _page_decor(self, canv, doc):
        if doc.page == 1:
            canv.saveState()
            canv.setFillColor(NAVY)
            canv.rect(0, 0, A4[0], A4[1], stroke=0, fill=1)
            canv.setFillColor(BLUE)
            canv.rect(0, A4[1] - 55 * mm, A4[0], 12 * mm, stroke=0, fill=1)
            canv.setFillColor(ACCENT)
            canv.rect(0, A4[1] - 57.5 * mm, A4[0], 2.5 * mm, stroke=0, fill=1)
            canv.restoreState()
            return
        canv.saveState()
        canv.setStrokeColor(colors.HexColor("#C9D4DE")); canv.setLineWidth(0.6)
        canv.line(18 * mm, A4[1] - 14 * mm, A4[0] - 18 * mm, A4[1] - 14 * mm)
        canv.setFont("Helvetica", 7.5); canv.setFillColor(GREY)
        canv.drawString(18 * mm, A4[1] - 12.5 * mm,
                        "Enterprise AI Operations Copilot — Technical Project Report")
        canv.drawRightString(A4[0] - 18 * mm, A4[1] - 12.5 * mm, "v1.1.0")
        canv.line(18 * mm, 13 * mm, A4[0] - 18 * mm, 13 * mm)
        canv.drawCentredString(A4[0] / 2, 9.5 * mm, f"Page {doc.page}")
        canv.restoreState()

    def afterFlowable(self, flowable):
        if isinstance(flowable, Paragraph):
            st = flowable.style.name
            if st == "H1":
                self.notify("TOCEntry", (0, flowable.getPlainText(), self.page))
                key = "h1-%s" % abs(hash(flowable.getPlainText()))
                self.canv.bookmarkPage(key)
                self.canv.addOutlineEntry(flowable.getPlainText(), key, 0, 0)
            elif st == "H2":
                self.notify("TOCEntry", (1, flowable.getPlainText(), self.page))


def build_cover():
    story = [Spacer(1, 55 * mm)]
    story.append(Paragraph("Enterprise AI Operations Copilot", S["CoverTitle"]))
    story.append(Spacer(1, 6))
    story.append(Paragraph(
        "RAG-Based Root Cause Analysis for Enterprise Operations —<br/>"
        "Multi-Agent AI · LangGraph · Qdrant Vector Search · Gemini · Langfuse",
        S["CoverSub"]))
    story.append(Spacer(1, 22 * mm))
    meta = [
        ["Document", "Technical Project Report"],
        ["Project", "Enterprise AI Operations Copilot"],
        ["Version", "1.1.0 (backend/frontend app version; git tag v1.0.0)"],
        ["Report Date", "September 4, 2026"],
        ["Backend Stack", "Python 3.12 · FastAPI · LangGraph · Qdrant · Gemini 2.5 Flash"],
        ["Frontend Stack", "React 19 · Vite 6 · Plain CSS · react-markdown"],
        ["Status", "Functional prototype — local deployment, 26/26 tests passing"],
    ]
    rows = [[Paragraph(a, S["CoverMeta"]), Paragraph(b, S["CoverMeta"])] for a, b in meta]
    t = Table(rows, colWidths=[40 * mm, 110 * mm])
    t.setStyle(TableStyle([
        ("LINEBELOW", (0, 0), (-1, -2), 0.4, colors.HexColor("#2C4A63")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    t.hAlign = "CENTER"
    story.append(t)
    story.append(PageBreak())
    return story


def build_toc():
    toc_title = ParagraphStyle("TOCTitle", parent=S["H1"])
    story = [Paragraph("Table of Contents", toc_title), Spacer(1, 4)]
    toc = TableOfContents()
    toc.levelStyles = [S["TOC1"], S["TOC2"]]
    toc.dotsMinLevel = 0
    story.append(toc)
    story.append(PageBreak())
    return story

# ---------------------------------------------------------------------------
# Diagrams
# ---------------------------------------------------------------------------
W = A4[0] - 36 * mm  # usable width

def d_arch(c, w, h):
    cx = w / 2
    box(c, cx - 40, h - 38, 80, 24, "User / Operations Engineer\n(browser)", fill=colors.HexColor("#DCEBDD"), stroke=ACCENT, bold=True)
    box(c, cx - 55, h - 92, 110, 26, "React Frontend (Vite, SPA)\nApp.jsx · components/ · services/api.js", fill=colors.HexColor("#E3EEF8"))
    box(c, cx - 55, h - 146, 110, 26, "FastAPI Backend (uvicorn)\napi/routes.py · Pydantic validation · rate limiter", fill=colors.HexColor("#E3EEF8"))
    box(c, cx - 70, h - 228, 140, 54, "LangGraph RCA Workflow\nquestion_analysis → incident_retrieval →\ndeployment_correlation → log_retrieval →\nrunbook_retrieval → evidence_aggregation →\nevidence_validation → rca_generation", fill=colors.HexColor("#FFF6E0"), stroke=WARN, font_size=6.5)
    box(c, 10, h - 292, 72, 34, "Qdrant Vector Store\n(embedded local,\n384-dim bge-small)", fill=colors.HexColor("#F1E8F7"), stroke=colors.HexColor("#7B4FA3"), font_size=6.5)
    box(c, 92, h - 292, 62, 34, "Static Data\nincidents.json ·\ndeployments.json ·\nlogs.txt · runbooks/", font_size=6)
    box(c, 164, h - 292, 62, 34, "Google Gemini\n2.5 Flash\n(external LLM)", fill=colors.HexColor("#FBEAEA"), stroke=colors.HexColor("#C0392B"), font_size=6.5)
    box(c, 236, h - 292, 62, 34, "Langfuse\nobservability\n(optional, fail-soft)", font_size=6.5)
    arrow(c, cx, h - 38, cx, h - 66)
    arrow(c, cx, h - 92, cx, h - 120)
    c.setFont("Helvetica", 6.5); c.setFillColor(GREY)
    c.drawString(cx + 4, h - 100, "POST /investigate[/stream] · SSE")
    arrow(c, cx, h - 146, cx, h - 174)
    dbl_arrow(c, cx - 60, h - 228, cx - 46, h - 258)
    dbl_arrow(c, cx - 5, h - 228, cx - 5, h - 258)
    arrow(c, cx + 45, h - 228, 195, h - 258)
    arrow(c, cx + 55, h - 228, 267, h - 258, dashed=True)
    c.drawString(cx + 50, h - 246, "grounded prompt")

def d_pipeline(c, w, h):
    stages = ["question\nanalysis", "incident\nretrieval", "deployment\ncorrelation",
              "log\nretrieval", "runbook\nretrieval", "evidence\naggregation",
              "evidence\nvalidation", "RCA\ngeneration"]
    bw, gap = 42, 7
    x = 6
    y = h / 2 - 8
    for i, s in enumerate(stages):
        fill = LIGHT if i < 6 else (colors.HexColor("#FFF6E0") if i == 6 else colors.HexColor("#FBEAEA"))
        box(c, x, y, bw, 32, s, fill=fill, font_size=6.5, bold=(i == 7))
        if i < len(stages) - 1:
            arrow(c, x + bw, y + 16, x + bw + gap, y + 16)
        x += bw + gap
    c.setFont("Helvetica", 6.5); c.setFillColor(GREY)
    c.drawString(6, y - 10, "START")
    c.drawString(x - 2, y - 10, "END")
    c.setFillColor(WARN)
    c.drawString(6, y - 22, "Nodes are defensive: any node failure is recorded and the workflow continues (partial evidence still yields an honest report).")
    c.setFillColor(BLUE)
    c.drawString(6, y - 33, "Evidence validation is authoritative: Gemini's reported confidence is clamped to the assessed evidence strength.")

def d_dataflow(c, w, h):
    box(c, 8, h - 40, 86, 26, "Input\nquestion (8–500 chars)\nvalidated Pydantic", font_size=6.5)
    box(c, 108, h - 40, 76, 26, "Keyword extraction\nregex tokenizer +\nstopword filter", font_size=6.5)
    box(c, 198, h - 40, 86, 26, "Retrieval agents\nvector search · correlation\nlog parse · runbook match", font_size=6.5)
    box(c, 8, h - 108, 86, 30, "EvidenceBundle\nPydantic models\n(models/evidence.py)", fill=colors.HexColor("#FFF6E0"), stroke=WARN, font_size=6.5)
    box(c, 108, h - 108, 76, 30, "EvidenceValidation\nstrength heuristic\nHIGH..INSUFFICIENT", fill=colors.HexColor("#FFF6E0"), stroke=WARN, font_size=6.5)
    box(c, 198, h - 108, 86, 30, "Gemini RCA\nstructured prompt\n→ markdown parse", fill=colors.HexColor("#FBEAEA"), stroke=colors.HexColor("#C0392B"), font_size=6.5)
    box(c, 8, h - 172, 120, 28, "API response\n{ status, investigation, report, message }", font_size=6.5)
    box(c, 150, h - 172, 134, 28, "React UI\nRCAReport · EvidencePanel ·\nTimeline · localStorage history", fill=colors.HexColor("#E3EEF8"), font_size=6.5)
    arrow(c, 94, h - 27, 108, h - 27)
    arrow(c, 184, h - 27, 198, h - 27)
    arrow(c, 241, h - 40, 51, h - 78)
    arrow(c, 94, h - 93, 108, h - 93)
    arrow(c, 184, h - 93, 198, h - 93)
    arrow(c, 241, h - 108, 68, h - 144)
    arrow(c, 128, h - 144, 217, h - 158)
    c.setFillColor(GREY); c.setFont("Helvetica", 6.5)
    c.drawString(8, h - 190, "Error paths: node failure → recorded in retrieval_errors · Gemini failure → retry ×3 → evidence-only fallback (no invented content)")

def d_rag(c, w, h):
    box(c, 8, h - 36, 74, 24, "incidents.json\n(20 incidents)", font_size=6.5)
    box(c, 92, h - 36, 86, 24, "Seed script (scripts/seed.py)\nvalidate → embed → upsert", font_size=6.5)
    box(c, 190, h - 36, 74, 24, "Qdrant collection\nenterprise_incidents\n384-dim · cosine", fill=colors.HexColor("#F1E8F7"), stroke=colors.HexColor("#7B4FA3"), font_size=6.5)
    box(c, 280, h - 36, 74, 24, "SentenceTransformer\nBAAI/bge-small-en-v1.5", font_size=6.5)
    box(c, 92, h - 96, 86, 26, "Query embedding\nsearch_service.search_incidents()", font_size=6.5)
    box(c, 190, h - 96, 74, 26, "Top-k cosine search\n+ payload indexes\n(service/severity/status)", fill=colors.HexColor("#F1E8F7"), stroke=colors.HexColor("#7B4FA3"), font_size=6.5)
    box(c, 280, h - 96, 74, 26, "Relevance filter\nscore ≥ 0.30\n(MIN_RELEVANCE_SCORE)", fill=colors.HexColor("#FFF6E0"), stroke=WARN, font_size=6.5)
    arrow(c, 82, h - 24, 92, h - 24); arrow(c, 178, h - 24, 190, h - 24); arrow(c, 264, h - 24, 280, h - 24)
    dbl_arrow(c, 227, h - 36, 227, h - 70)
    arrow(c, 264, h - 83, 280, h - 83)
    c.setFillColor(GREY); c.setFont("Helvetica", 6.5)
    c.drawString(8, h - 118, "Chunking: one vector per incident (service/title/root-cause text); runbooks and logs are retrieved by keyword heuristics, not embeddings.")

def d_deploy(c, w, h):
    box(c, 10, h - 44, 90, 30, "Developer machine\nnpm run dev (Vite :5173)\nuvicorn app:app (:8000)", font_size=6.5)
    box(c, 130, h - 44, 100, 30, "Local process deployment\nQdrant embedded (qdrant_data/)\nJSON/MD file data store", font_size=6.5)
    box(c, 260, h - 44, 84, 30, "External SaaS\nGemini API · Langfuse Cloud", fill=colors.HexColor("#FBEAEA"), stroke=colors.HexColor("#C0392B"), font_size=6.5)
    arrow(c, 100, h - 29, 130, h - 29)
    dbl_arrow(c, 230, h - 29, 260, h - 29)
    c.setFillColor(GREY); c.setFont("Helvetica", 6.5)
    c.drawString(10, h - 62, "Not identified in the current implementation: Dockerfile, CI/CD pipeline, cloud hosting, monitoring/alerting, production database.")

def arrow(c, x1, y1, x2, y2, color=GREY, dashed=False):
    c.setStrokeColor(color); c.setLineWidth(0.9)
    if dashed:
        c.setDash(3, 2)
    c.line(x1, y1, x2, y2)
    c.setDash()
    import math
    ang = math.atan2(y2 - y1, x2 - x1)
    for da in (0.4, -0.4):
        c.line(x2, y2, x2 - 6 * math.cos(ang - da), y2 - 6 * math.sin(ang - da))

def dbl_arrow(c, x1, y1, x2, y2, color=GREY):
    arrow(c, x1, y1, x2, y2, color)
    arrow(c, x2, y2, x1, y1, color)

def diag(fn, height, cap_text):
    return [Diagram(W, height, fn), caption(cap_text)]

# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------
def main():
    import rp1, rp2, rp3, rp4, rp5, rp6, rp7, rp8, rp9, rp10, rp11, rp12, rp13, rp14
    out = os.path.join(os.path.dirname(BASE), "Enterprise_AI_Operations_Copilot_Technical_Project_Report.pdf")
    doc = ReportDoc(out)
    story = []
    story += build_cover()
    story += build_toc()
    for mod in (rp1, rp2, rp3, rp4, rp5, rp6, rp7, rp8, rp9, rp10, rp11, rp12, rp13, rp14):
        mod.build(story)
    doc.multiBuild(story)
    print("PDF written:", out)


if __name__ == "__main__":
    main()