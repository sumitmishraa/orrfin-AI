"""Synthetic supplier invoice PDFs in several real-world layouts, for the seed and the golden test corpus.

Each layout changes labels, date formats, number formats and table style, because real supplier
invoices differ in all of these. The scanned variant has no text layer, so it exercises OCR.
"""
import io
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.platypus import PageBreak, Paragraph, Spacer, Table, TableStyle

from orrfin.documents.pdf import BORDER, ICE, grid, inr, new_document, p, qty_text, styles

LAYOUTS = ("grid", "plain", "compact", "multipage")


@dataclass
class SpecLine:
    description: str
    quantity: Decimal
    rate: Decimal
    hsn: str = ""
    unit: str = "NOS"
    gst_rate: Decimal = Decimal("18")

    @property
    def taxable(self) -> Decimal:
        return (self.quantity * self.rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


@dataclass
class InvoiceSpec:
    number: str
    invoice_date: date
    po_number: str
    supplier_name: str
    supplier_gstin: str
    buyer_name: str
    buyer_gstin: str
    lines: list[SpecLine]
    interstate: bool
    supplier_address: str = ""
    buyer_address: str = ""
    place_of_supply: str = ""
    freight: Decimal = Decimal("0")
    total_override: Decimal | None = None
    hidden_text: str = ""
    fictional: bool = True
    extra: dict = field(default_factory=dict)

    def amounts(self) -> dict:
        subtotal = sum((line.taxable for line in self.lines), Decimal(0))
        cgst = sgst = igst = Decimal(0)
        for line in self.lines:
            if self.interstate:
                igst += (line.taxable * line.gst_rate / 100).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            else:
                half = (line.taxable * line.gst_rate / 200).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                cgst += half
                sgst += half
        exact = subtotal + cgst + sgst + igst + self.freight
        rounded = exact.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        total = self.total_override if self.total_override is not None else rounded
        return {
            "subtotal": subtotal,
            "cgst": cgst,
            "sgst": sgst,
            "igst": igst,
            "freight": self.freight,
            "round_off": (rounded - exact).quantize(Decimal("0.01")),
            "total": total,
        }


def _plain_amount(value: Decimal) -> str:
    """'Rs. 1,23,456.00' style used by many small suppliers."""
    return inr(value).replace("₹", "Rs. ")


def _header_block(spec: InvoiceSpec, st, title: str, labels: dict) -> list:
    story = []
    if spec.fictional:
        story.append(p("FICTIONAL SAMPLE DATA - NOT A REAL TAX INVOICE", st["stamp"]))
    story.append(p(title, st["title"]))
    story.append(Spacer(1, 3))
    left = [
        p(spec.supplier_name, st["label"]),
        p(spec.supplier_address, st["small"]),
        p(f"{labels['supplier_gstin']} {spec.supplier_gstin}", st["body"]),
    ]
    right = [
        p(f"{labels['number']} {spec.number}", st["body"]),
        p(f"{labels['date']} {labels['date_format'](spec.invoice_date)}", st["body"]),
        p(f"{labels['po']} {spec.po_number}", st["body"]),
        p(f"Place of Supply: {spec.place_of_supply}", st["small"]),
    ]
    table = Table([[left, right]], colWidths=[95 * mm, 83 * mm])
    table.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
    buyer = [
        p(labels["buyer"], st["label"]),
        p(spec.buyer_name, st["body"]),
        p(spec.buyer_address, st["small"]),
        p(f"{labels['buyer_gstin']} {spec.buyer_gstin}", st["body"]),
    ]
    story += [table, Spacer(1, 4)] + buyer + [Spacer(1, 6)]
    return story


def _totals_block(spec: InvoiceSpec, st, money_format, labels: dict) -> Table:
    amounts = spec.amounts()
    rows = [[labels["subtotal"], money_format(amounts["subtotal"])]]
    rates = sorted({line.gst_rate for line in spec.lines})
    rate_text = "/".join(qty_text(rate) for rate in rates)
    if spec.interstate:
        rows.append([f"IGST @ {rate_text}%", money_format(amounts["igst"])])
    else:
        half = "/".join(qty_text(rate / 2) for rate in rates)
        rows += [[f"CGST @ {half}%", money_format(amounts["cgst"])], [f"SGST @ {half}%", money_format(amounts["sgst"])]]
    if amounts["freight"]:
        rows.append(["Freight", money_format(amounts["freight"])])
    rows.append(["Round Off", money_format(amounts["round_off"])])
    rows.append([labels["total"], money_format(amounts["total"])])
    table = Table([[p(a, st["body"]), p(b, st["right"])] for a, b in rows], colWidths=[50 * mm, 40 * mm], hAlign="RIGHT")
    table.setStyle(TableStyle([("LINEABOVE", (0, -1), (-1, -1), 0.8, colors.black)]))
    return table


def _hidden(spec: InvoiceSpec, st) -> list:
    """Planted text a person can't see: white, tiny. Extraction must ignore it and flag it."""
    if not spec.hidden_text:
        return []
    style = st["small"].clone("hidden", textColor=colors.white, fontSize=1, leading=1.2)
    return [Paragraph(spec.hidden_text, style)]


def render_invoice(spec: InvoiceSpec, layout: str = "grid") -> bytes:
    st = styles()
    buffer = io.BytesIO()
    document = new_document(buffer, f"Invoice {spec.number}")
    if layout == "grid":
        labels = {
            "number": "Invoice No:", "date": "Invoice Date:", "date_format": lambda d: d.strftime("%d/%m/%Y"),
            "po": "PO Reference:", "supplier_gstin": "GSTIN:", "buyer": "Bill To", "buyer_gstin": "Buyer GSTIN:",
            "subtotal": "Taxable Value", "total": "Grand Total",
        }
        money_format = inr
    elif layout == "plain":
        labels = {
            "number": "Bill No.", "date": "Dated", "date_format": lambda d: d.strftime("%d-%b-%Y"),
            "po": "Your Order No.", "supplier_gstin": "GSTIN/UIN:", "buyer": "Buyer (Billed To)", "buyer_gstin": "GSTIN/UIN:",
            "subtotal": "Sub Total", "total": "Total Amount Payable",
        }
        money_format = _plain_amount
    elif layout in ("compact", "multipage"):
        labels = {
            "number": "Inv #", "date": "Date:", "date_format": lambda d: d.isoformat(),
            "po": "P.O. No:", "supplier_gstin": "Seller GSTIN:", "buyer": "Customer", "buyer_gstin": "Customer GSTIN:",
            "subtotal": "Total Taxable", "total": "Invoice Total",
        }
        money_format = lambda value: "INR " + inr(value).replace("₹", "")  # noqa: E731
    else:
        raise ValueError(f"Unknown layout {layout}")

    story = _header_block(spec, st, "TAX INVOICE" if layout != "plain" else "INVOICE", labels)
    story += _hidden(spec, st)

    header = ["S.No", "Description of Goods", "HSN/SAC", "Qty", "Unit", "Rate", "Amount"]
    body = [
        [str(n), line.description, line.hsn, qty_text(line.quantity), line.unit, money_format(line.rate), money_format(line.taxable)]
        for n, line in enumerate(spec.lines, start=1)
    ]
    widths = [10 * mm, 62 * mm, 18 * mm, 16 * mm, 12 * mm, 28 * mm, 32 * mm]
    cell = lambda text, right: p(text, st["right"] if right else st["body"])  # noqa: E731

    def item_table(rows: list[list[str]]) -> Table:
        data = [[p(text, st["label"]) for text in header]] + [
            [cell(value, index >= 3 and index != 4) for index, value in enumerate(row)] for row in rows
        ]
        if layout == "plain":
            table = Table(data, colWidths=widths, repeatRows=1)
            table.setStyle(TableStyle([("LINEBELOW", (0, 0), (-1, 0), 0.6, colors.black), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
            return table
        table = grid(data, widths)
        if layout == "compact":
            table.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), ICE), ("GRID", (0, 0), (-1, -1), 0.3, BORDER)]))
        return table

    if layout == "multipage" and len(body) > 22:
        for start in range(0, len(body), 22):
            story.append(item_table(body[start:start + 22]))
            if start + 22 < len(body):
                story.append(PageBreak())
    else:
        story.append(item_table(body))
    story += [Spacer(1, 6), _totals_block(spec, st, money_format, labels), Spacer(1, 8)]
    story.append(p("Declaration: We declare that this invoice shows the actual price of the goods described.", st["small"]))
    story.append(p(f"For {spec.supplier_name} - Authorised Signatory", st["small"]))
    document.build(story)
    return buffer.getvalue()


def render_scanned(spec: InvoiceSpec, layout: str = "grid", scale: float = 2.0) -> bytes:
    """Rasterises a layout into an image-only PDF, as a phone scan or photocopy would arrive."""
    import pypdfium2 as pdfium
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas

    source = pdfium.PdfDocument(render_invoice(spec, layout))
    buffer = io.BytesIO()
    page_size = A4
    output = canvas.Canvas(buffer, pagesize=page_size, invariant=1)
    try:
        for index in range(len(source)):
            page = source[index]
            bitmap = page.render(scale=scale, grayscale=True)
            image = bitmap.to_pil()
            image_buffer = io.BytesIO()
            image.save(image_buffer, format="PNG")
            image_buffer.seek(0)
            output.drawImage(ImageReader(image_buffer), 0, 0, width=page_size[0], height=page_size[1])
            output.showPage()
            bitmap.close()
            page.close()
    finally:
        source.close()
    output.save()
    return buffer.getvalue()
