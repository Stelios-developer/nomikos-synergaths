from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    PageBreak, KeepTogether,
)

OUTPUT = "examples/test-documents/nexus-tax-compliance-test-case.pdf"
FONT = "C:/Windows/Fonts/arial.ttf"
FONT_BOLD = "C:/Windows/Fonts/arialbd.ttf"

pdfmetrics.registerFont(TTFont("Document", FONT))
pdfmetrics.registerFont(TTFont("DocumentBold", FONT_BOLD))

GREEN = colors.HexColor("#176B48")
DEEP = colors.HexColor("#183F32")
MINT = colors.HexColor("#E8F7ED")
LINE = colors.HexColor("#C7E4D1")
AMBER = colors.HexColor("#FFF4DD")
RED = colors.HexColor("#FFF0F1")
TEXT = colors.HexColor("#294C40")

styles = getSampleStyleSheet()
styles.add(ParagraphStyle(name="DocumentTitle", parent=styles["Title"], fontName="DocumentBold", fontSize=24, leading=29, textColor=DEEP, spaceAfter=7))
styles.add(ParagraphStyle(name="DocumentSubtitle", parent=styles["Normal"], fontName="Document", fontSize=10.5, leading=15, textColor=TEXT, spaceAfter=17))
styles.add(ParagraphStyle(name="DocumentH2", parent=styles["Heading2"], fontName="DocumentBold", fontSize=15, leading=19, textColor=DEEP, spaceBefore=10, spaceAfter=8))
styles.add(ParagraphStyle(name="DocumentH3", parent=styles["Heading3"], fontName="DocumentBold", fontSize=10.5, leading=14, textColor=GREEN, spaceBefore=8, spaceAfter=5))
styles.add(ParagraphStyle(name="DocumentBody", parent=styles["BodyText"], fontName="Document", fontSize=9.5, leading=14, textColor=TEXT, spaceAfter=7))
styles.add(ParagraphStyle(name="DocumentSmall", parent=styles["BodyText"], fontName="Document", fontSize=8.2, leading=11, textColor=TEXT))
styles.add(ParagraphStyle(name="DocumentKicker", parent=styles["BodyText"], fontName="DocumentBold", fontSize=8, leading=10, textColor=GREEN, tracking=1.2, spaceAfter=7))
styles.add(ParagraphStyle(name="DocumentCenter", parent=styles["BodyText"], fontName="Document", fontSize=8.5, leading=12, textColor=TEXT, alignment=TA_CENTER))


def P(text, style="DocumentBody"):
    return Paragraph(text, styles[style])


def section_label(text):
    return P(text.upper(), "DocumentKicker")


def table(rows, widths, header=True):
    converted = []
    for r, row in enumerate(rows):
        converted.append([P(cell, "DocumentSmall" if r else "DocumentKicker") for cell in row])
    tbl = Table(converted, colWidths=widths, repeatRows=1 if header else 0, hAlign="LEFT")
    commands = [
        ("FONTNAME", (0, 0), (-1, -1), "Document"),
        ("GRID", (0, 0), (-1, -1), 0.45, LINE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ("BACKGROUND", (0, 0), (-1, 0), MINT),
    ]
    tbl.setStyle(TableStyle(commands))
    return tbl


def footer(canvas, doc):
    canvas.saveState()
    canvas.setStrokeColor(LINE)
    canvas.line(1.7 * cm, 1.35 * cm, A4[0] - 1.7 * cm, 1.35 * cm)
    canvas.setFont("Document", 8)
    canvas.setFillColor(TEXT)
    canvas.drawString(1.7 * cm, 0.85 * cm, "NOMIKOS SYNERGATHS - Test document for evidence-first analysis")
    canvas.drawRightString(A4[0] - 1.7 * cm, 0.85 * cm, f"Page {doc.page}")
    canvas.restoreState()


story = []
story += [
    section_label("Internal policy - test case"),
    P("2026 Greek Tax Compliance and Filing Policy", "DocumentTitle"),
    P("A realistic test document containing deadlines, owners, risks, decisions and evidence-ready actions. Upload it to NOMIKOS SYNERGATHS to test Overview, Facts, Timeline, Risks, Action plan, Decision center, Evidence and Ask.", "DocumentSubtitle"),
    P("Purpose", "DocumentH2"),
    P("This policy applies to Meridian Consulting Group's Greek subsidiary for fiscal year 2026. It covers income tax filings, VAT reporting, R&D deductions and business travel expense recognition. The Finance Director is accountable for compliance; the Tax Manager owns filing quality and escalation.", "DocumentBody"),
    P("Non-negotiable requirements", "DocumentH2"),
    table([
        ["Requirement", "Deadline", "Owner", "Evidence required"],
        ["Submit the annual corporate income tax declaration", "31 July 2026", "Tax Manager - Eleni Papadaki", "Final tax return, management approval and supporting schedules"],
        ["Submit monthly VAT return and pay VAT due", "20th day of each following month", "Finance Controller - Nikos Vrettos", "VAT reconciliation, invoice register and payment receipt"],
        ["Validate eligible R&D expenditure before claiming deduction", "15 June 2026", "R&D Lead and Tax Manager", "Supplier invoices, project timesheets and technical approval"],
        ["Upload travel expense receipts for reimbursement", "Within 45 days of travel", "Each employee; reviewed by Expense Team", "Receipt, itinerary and manager approval"],
    ], [5.0*cm, 3.0*cm, 4.0*cm, 5.0*cm]),
    Spacer(1, 12),
    P("Control rule", "DocumentH3"),
    P("No tax filing may be submitted until the Tax Manager confirms that every key claim is traceable to source evidence. Missing evidence must be escalated to the Finance Director within two working days.", "DocumentBody"),
    P("Risk signal", "DocumentH3"),
    P("The overall risk level is HIGH because late filing can trigger interest, administrative penalties and a formal tax authority review. The deadline for the annual declaration is the highest priority item.", "DocumentBody"),
    PageBreak(),
]

story += [
    section_label("Operational timeline"),
    P("Compliance milestones and ownership", "DocumentTitle"),
    P("The following milestones must be tracked in the order shown. Any blocked item must be reported to the Finance Director immediately.", "DocumentSubtitle"),
    table([
        ["Date", "Milestone", "Responsible owner", "Status / expected outcome"],
        ["15 June 2026", "Complete R&D documentation review", "R&D Lead + Tax Manager", "Open - evidence pack must be complete"],
        ["30 June 2026", "Management review of draft annual tax position", "Finance Director", "Decision required - approve filing assumptions"],
        ["15 July 2026", "Final reconciliation and legal review", "Tax Manager", "Open - resolve outstanding evidence gaps"],
        ["31 July 2026", "Submit annual corporate income tax declaration", "Tax Manager", "Critical deadline - submission receipt required"],
        ["Monthly, day 20", "Submit VAT return and payment", "Finance Controller", "Recurring deadline - payment confirmation required"],
    ], [3.0*cm, 5.2*cm, 4.4*cm, 4.4*cm]),
    Spacer(1, 15),
    P("Known risks and mitigations", "DocumentH2"),
    table([
        ["Risk", "Level", "Mitigation", "Owner"],
        ["Annual filing is submitted after 31 July 2026", "High", "Weekly readiness review from 15 June; escalate evidence gaps within two working days", "Tax Manager"],
        ["R&D deduction is claimed without complete invoices or timesheets", "High", "Use a mandatory evidence checklist and Finance Director approval", "R&D Lead"],
        ["VAT reconciliation differs from invoice register", "Medium", "Perform monthly reconciliation before the 15th day of the month", "Finance Controller"],
        ["Travel receipts are missing or uploaded late", "Medium", "Automated reminder on day 30; block late reimbursement until review", "Expense Team"],
    ], [5.0*cm, 2.0*cm, 6.4*cm, 3.6*cm]),
    Spacer(1, 12),
    P("Escalation", "DocumentH3"),
    P("If a critical deadline is at risk, the owner must notify the Finance Director and Tax Manager on the same business day. A corrected action plan must name an owner, a date and the supporting evidence required to close the issue.", "DocumentBody"),
    PageBreak(),
]

story += [
    section_label("Decision center"),
    P("Decisions and proposed actions", "DocumentTitle"),
    P("These decisions are intentionally written as a test case for NOMIKOS SYNERGATHS. Each one should appear in the Decision center with its recommended action and supporting citations.", "DocumentSubtitle"),
    P("Decision 1 - Approve the annual filing assumptions", "DocumentH2"),
    P("Decision required by 30 June 2026: the Finance Director must approve the tax position, including the 22% corporate tax rate and the treatment of eligible R&D deductions. Recommended action: review the R&D evidence pack and approve only supported claims.", "DocumentBody"),
    P("Decision 2 - Assign final filing owner", "DocumentH2"),
    P("Decision required by 15 July 2026: confirm Eleni Papadaki, Tax Manager, as the accountable owner for the annual declaration. Recommended action: give her authority to request evidence from Finance, R&D and Legal and require a signed readiness checklist.", "DocumentBody"),
    P("Decision 3 - Resolve missing travel receipts", "DocumentH2"),
    P("Decision required before the next monthly close: approve the policy that reimbursement is paused when travel receipts are not provided within 45 days. Recommended action: notify employees and configure a day-30 reminder.", "DocumentBody"),
    P("Proposed action checklist", "DocumentH2"),
    table([
        ["Action", "Priority", "Due date", "Owner"],
        ["Create the R&D evidence checklist and collect missing invoices", "High", "15 June 2026", "R&D Lead"],
        ["Run management review of draft annual tax position", "High", "30 June 2026", "Finance Director"],
        ["Complete final reconciliation and retain supporting schedules", "High", "15 July 2026", "Tax Manager"],
        ["Confirm annual filing submission and archive receipt", "Critical", "31 July 2026", "Tax Manager"],
        ["Configure VAT and travel receipt reminders", "Medium", "10 June 2026", "Finance Controller"],
    ], [7.0*cm, 2.2*cm, 3.5*cm, 4.3*cm]),
    Spacer(1, 14),
    P("Evidence note", "DocumentH3"),
    P("All conclusions in this policy must be checked against the cited page before approval. A human review is required because this document contains tax compliance obligations and financial decisions.", "DocumentBody"),
]

doc = SimpleDocTemplate(OUTPUT, pagesize=A4, leftMargin=1.7*cm, rightMargin=1.7*cm, topMargin=1.65*cm, bottomMargin=2.0*cm)
doc.build(story, onFirstPage=footer, onLaterPages=footer)
