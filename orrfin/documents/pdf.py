"""PDF rendering. Uses Noto Sans because Helvetica can't encode the rupee sign."""
import io
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

FONT_DIR = Path("/usr/share/fonts/truetype/noto")
NAVY = colors.HexColor("#050f1b")
BLUE = colors.HexColor("#15376a")
ICE = colors.HexColor("#e8f5fe")
BORDER = colors.HexColor("#bee3fc")
MUTED = colors.HexColor("#536a84")
RED = colors.HexColor("#c94343")

_registered = False


def _fonts() -> None:
    global _registered
    if not _registered:
        pdfmetrics.registerFont(TTFont("Noto", str(FONT_DIR / "NotoSans-Regular.ttf")))
        pdfmetrics.registerFont(TTFont("Noto-Bold", str(FONT_DIR / "NotoSans-Bold.ttf")))
        pdfmetrics.registerFontFamily("Noto", normal="Noto", bold="Noto-Bold", italic="Noto", boldItalic="Noto-Bold")
        _registered = True


def styles() -> dict[str, ParagraphStyle]:
    _fonts()
    return {
        "body": ParagraphStyle("body", fontName="Noto", fontSize=8.5, leading=11.5, textColor=NAVY),
        "small": ParagraphStyle("small", fontName="Noto", fontSize=7.5, leading=10, textColor=MUTED),
        "label": ParagraphStyle("label", fontName="Noto-Bold", fontSize=7.5, leading=10, textColor=BLUE),
        "title": ParagraphStyle("title", fontName="Noto-Bold", fontSize=16, leading=20, textColor=BLUE),
        "right": ParagraphStyle("right", fontName="Noto", fontSize=8.5, leading=11.5, textColor=NAVY, alignment=TA_RIGHT),
        "stamp": ParagraphStyle("stamp", fontName="Noto-Bold", fontSize=8.5, leading=11, textColor=RED),
        "h2": ParagraphStyle("h2", fontName="Noto-Bold", fontSize=10, leading=14, textColor=BLUE, spaceBefore=8, spaceAfter=3),
    }


def inr(value) -> str:
    """Indian digit grouping with the rupee sign, e.g. ₹1,23,456.78."""
    amount = Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    sign = "-" if amount < 0 else ""
    whole, fraction = f"{abs(amount):.2f}".split(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        whole = ",".join(groups + [tail])
    return f"{sign}₹{whole}.{fraction}"


def qty_text(value) -> str:
    return f"{Decimal(str(value)).normalize():f}"


def p(text, style) -> Paragraph:
    return Paragraph(escape(str(text)).replace("\n", "<br/>"), style)


def new_document(buffer: io.BytesIO, title: str) -> SimpleDocTemplate:
    """invariant=1 makes output byte-identical for identical input, so re-renders deduplicate."""
    _fonts()
    return SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=16 * mm,
        rightMargin=16 * mm,
        topMargin=14 * mm,
        bottomMargin=14 * mm,
        title=title,
        author="Orrfin.ai",
        invariant=1,
    )


def grid(data, widths, header_rows: int = 1) -> Table:
    table = Table(data, colWidths=widths, repeatRows=header_rows)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, header_rows - 1), ICE),
                ("GRID", (0, 0), (-1, -1), 0.4, BORDER),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    return table


def _party(heading: str, name: str, lines: list[str], st) -> list:
    return [p(heading, st["label"]), p(name, st["body"])] + [p(line, st["small"]) for line in lines if line]


def render_purchase_order(data: dict) -> bytes:
    """data: number, revision, date, needed_by, buyer, ship_to, supplier, lines, totals, terms, fictional."""
    st = styles()
    buffer = io.BytesIO()
    document = new_document(buffer, f"Purchase Order {data['number']}")
    story: list = []
    if data.get("fictional"):
        story.append(p("FICTIONAL SAMPLE DATA - NOT A REAL PURCHASE ORDER", st["stamp"]))

    heading = Table(
        [
            [
                p("PURCHASE ORDER", st["title"]),
                [
                    p(f"PO Number: {data['number']}", st["right"]),
                    p(f"Revision: {data['revision']}", st["right"]),
                    p(f"PO Date: {data['date']}", st["right"]),
                    p(f"Deliver by: {data.get('needed_by') or '-'}", st["right"]),
                ],
            ]
        ],
        colWidths=[90 * mm, 88 * mm],
    )
    story += [heading, Spacer(1, 5)]

    buyer, ship_to, supplier = data["buyer"], data["ship_to"], data["supplier"]
    parties = Table(
        [
            [
                _party("BILL TO", buyer["name"], [buyer["address"], f"GSTIN: {buyer['gstin']}", f"State: {buyer['state']} ({buyer['state_code']})"], st),
                _party("SHIP TO", ship_to["name"], [ship_to["address"], f"Branch: {ship_to['branch']}"], st),
                _party("SUPPLIER", supplier["name"], [supplier["address"], f"GSTIN: {supplier['gstin'] or 'Not provided'}", f"Payment terms: {data['payment_terms_days']} days"], st),
            ]
        ],
        colWidths=[60 * mm, 58 * mm, 60 * mm],
    )
    parties.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("BOX", (0, 0), (-1, -1), 0.4, BORDER), ("LINEBEFORE", (1, 0), (-1, -1), 0.4, BORDER)]))
    story += [parties, Spacer(1, 7)]

    interstate = data["is_interstate"]
    tax_heading = "IGST" if interstate else "CGST + SGST"
    rows = [[p(text, st["label"]) for text in ("#", "Description", "HSN/SAC", "Qty", "Unit", "Rate", "Taxable", "GST %", tax_heading)]]
    for line in data["lines"]:
        tax = Decimal(str(line["igst"])) if interstate else Decimal(str(line["cgst"])) + Decimal(str(line["sgst"]))
        rows.append(
            [
                p(line["line_no"], st["body"]),
                p(line["description"], st["body"]),
                p(line["hsn"] or "-", st["body"]),
                p(qty_text(line["quantity"]), st["right"]),
                p(line["unit"], st["body"]),
                p(inr(line["unit_price"]), st["right"]),
                p(inr(line["taxable"]), st["right"]),
                p(qty_text(line["gst_rate"]), st["right"]),
                p(inr(tax), st["right"]),
            ]
        )
    story += [grid(rows, [7 * mm, 53 * mm, 15 * mm, 13 * mm, 11 * mm, 20 * mm, 22 * mm, 11 * mm, 26 * mm]), Spacer(1, 6)]

    totals = data["totals"]
    summary = [["Subtotal", inr(totals["subtotal"])]]
    if interstate:
        summary.append(["IGST", inr(totals["igst"])])
    else:
        summary += [["CGST", inr(totals["cgst"])], ["SGST", inr(totals["sgst"])]]
    if Decimal(str(totals["freight"])) > 0:
        summary.append(["Freight", inr(totals["freight"])])
    summary.append(["Grand Total", inr(totals["total"])])
    table = Table(
        [[p(label, st["label"] if label == "Grand Total" else st["body"]), p(value, st["right"])] for label, value in summary],
        colWidths=[35 * mm, 35 * mm],
        hAlign="RIGHT",
    )
    table.setStyle(TableStyle([("LINEABOVE", (0, -1), (-1, -1), 0.8, BLUE), ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2)]))
    story += [table, Spacer(1, 8)]

    story.append(p("Terms", st["label"]))
    story.append(
        p(
            data.get("terms")
            or "Quote this PO number on every invoice and delivery note. Invoices must show the GSTIN, HSN and tax "
            "breakup. Goods are accepted subject to inspection at the delivery location.",
            st["small"],
        )
    )
    document.build(story)
    return buffer.getvalue()
