"""Three-way match: purchase order, goods receipts and a human-confirmed invoice.

A pure function over plain data, so it is deterministic and fully unit-testable. Invoice lines
are aligned to PO lines by SKU, HSN and description similarity, never by position.
"""
from dataclasses import dataclass, field
from decimal import Decimal

from rapidfuzz import fuzz

from orrfin.gst import is_valid_gstin

MIN_ALIGNMENT_SCORE = 60


@dataclass
class PoLineData:
    id: str
    line_no: int
    description: str
    quantity: Decimal
    unit_price: Decimal
    gst_rate: Decimal
    qty_received: Decimal
    qty_billed: Decimal
    sku: str = ""
    hsn: str = ""


@dataclass
class InvoiceLineData:
    line_no: int
    description: str
    quantity: Decimal
    unit_price: Decimal
    taxable: Decimal
    hsn: str = ""
    gst_rate: Decimal | None = None


@dataclass
class MatchInput:
    po_number: str
    po_status: str
    po_interstate: bool
    po_freight: Decimal
    po_supplier_gstin: str
    po_buyer_gstin: str
    po_lines: list[PoLineData]
    invoice_lines: list[InvoiceLineData]
    supplier_gstin: str
    buyer_gstin: str
    subtotal: Decimal
    cgst: Decimal
    sgst: Decimal
    igst: Decimal
    freight: Decimal
    round_off: Decimal
    total: Decimal
    price_tolerance_pct: Decimal = Decimal("2")
    qty_tolerance_pct: Decimal = Decimal("0")
    tax_tolerance_abs: Decimal = Decimal("5")
    total_tolerance_abs: Decimal = Decimal("10")
    payment_hold: bool = False
    duplicate_of: str = ""


@dataclass
class Finding:
    code: str
    message: str
    severity: str = "blocking"
    line_no: int | None = None
    expected: str = ""
    actual: str = ""
    assignee_role: str = "finance_ap"


@dataclass
class MatchResult:
    status: str
    exceptions: list[Finding] = field(default_factory=list)
    lines: list[dict] = field(default_factory=list)

    @property
    def blocking(self) -> list[Finding]:
        return [item for item in self.exceptions if item.severity == "blocking"]


def _score(invoice_line: InvoiceLineData, po_line: PoLineData) -> float:
    text = invoice_line.description.lower()
    score = fuzz.token_set_ratio(text, po_line.description.lower())
    if po_line.sku and po_line.sku.lower() in text:
        score = max(score, 100)
    if po_line.hsn and invoice_line.hsn and po_line.hsn[:4] == invoice_line.hsn[:4]:
        score += 15
    return score


def align(po_lines: list[PoLineData], invoice_lines: list[InvoiceLineData]) -> dict[int, tuple[PoLineData, float]]:
    """Greedy best-score assignment: each PO line is used once, best pairs first."""
    pairs = sorted(
        ((_score(inv, po), inv.line_no, po) for inv in invoice_lines for po in po_lines),
        key=lambda item: (-item[0], item[1], item[2].line_no),
    )
    used_po, assigned = set(), {}
    for score, invoice_no, po_line in pairs:
        if score < MIN_ALIGNMENT_SCORE or invoice_no in assigned or po_line.id in used_po:
            continue
        assigned[invoice_no] = (po_line, score)
        used_po.add(po_line.id)
    return assigned


def match(data: MatchInput) -> MatchResult:
    findings: list[Finding] = []
    lines: list[dict] = []

    if data.po_status in ("cancelled", "closed", "draft"):
        findings.append(Finding("po_not_open", f"Purchase order {data.po_number} is {data.po_status}, so it can't be billed."))
    if data.duplicate_of:
        findings.append(Finding("duplicate_invoice", f"This looks like a duplicate of invoice {data.duplicate_of}."))

    if not is_valid_gstin(data.supplier_gstin):
        findings.append(Finding("gstin_invalid", "The supplier GSTIN on the invoice isn't valid.", actual=data.supplier_gstin))
    elif data.po_supplier_gstin and data.supplier_gstin != data.po_supplier_gstin:
        findings.append(
            Finding("gstin_mismatch", "The supplier GSTIN doesn't match the supplier on the purchase order.", expected=data.po_supplier_gstin, actual=data.supplier_gstin)
        )
    if data.buyer_gstin and data.buyer_gstin != data.po_buyer_gstin:
        findings.append(
            Finding("buyer_gstin_mismatch", "The invoice is billed to a different GSTIN than the ordering entity, so input tax credit is at risk.", expected=data.po_buyer_gstin, actual=data.buyer_gstin)
        )

    if data.po_interstate and (data.cgst > 0 or data.sgst > 0):
        findings.append(Finding("tax_regime_mismatch", "This is an inter-state supply, so it should carry IGST, not CGST and SGST.", expected="IGST", actual="CGST+SGST"))
    if not data.po_interstate and data.igst > 0:
        findings.append(Finding("tax_regime_mismatch", "This is an intra-state supply, so it should carry CGST and SGST, not IGST.", expected="CGST+SGST", actual="IGST"))

    assigned = align(data.po_lines, data.invoice_lines)
    expected_tax = Decimal(0)
    for invoice_line in data.invoice_lines:
        pair = assigned.get(invoice_line.line_no)
        if pair is None:
            findings.append(
                Finding("unmatched_line", f"'{invoice_line.description}' isn't on the purchase order.", line_no=invoice_line.line_no, assignee_role="procurement")
            )
            continue
        po_line, score = pair
        price_limit = po_line.unit_price * (1 + data.price_tolerance_pct / 100)
        if invoice_line.unit_price > price_limit:
            findings.append(
                Finding(
                    "price_variance",
                    f"Line {invoice_line.line_no}: billed at {invoice_line.unit_price}, but the PO price is {po_line.unit_price}.",
                    line_no=invoice_line.line_no,
                    expected=str(po_line.unit_price),
                    actual=str(invoice_line.unit_price),
                    assignee_role="procurement",
                )
            )
        if invoice_line.gst_rate is not None and invoice_line.gst_rate != po_line.gst_rate:
            findings.append(
                Finding("gst_rate_mismatch", f"Line {invoice_line.line_no}: GST rate {invoice_line.gst_rate}% differs from the PO's {po_line.gst_rate}%.", line_no=invoice_line.line_no, expected=str(po_line.gst_rate), actual=str(invoice_line.gst_rate))
            )
        if abs(invoice_line.quantity * invoice_line.unit_price - invoice_line.taxable) > Decimal("1.00"):
            findings.append(
                Finding("line_arithmetic", f"Line {invoice_line.line_no}: quantity times rate doesn't equal the amount.", line_no=invoice_line.line_no, expected=str(invoice_line.quantity * invoice_line.unit_price), actual=str(invoice_line.taxable))
            )
        total_billed = po_line.qty_billed + invoice_line.quantity
        ordered_limit = po_line.quantity * (1 + data.qty_tolerance_pct / 100)
        if po_line.qty_received <= 0:
            findings.append(Finding("no_receipt", f"Line {invoice_line.line_no}: no goods have been received yet.", line_no=invoice_line.line_no))
        elif total_billed > po_line.qty_received:
            findings.append(
                Finding(
                    "qty_over_received",
                    f"Line {invoice_line.line_no}: billing {total_billed} in total, but only {po_line.qty_received} received.",
                    line_no=invoice_line.line_no,
                    expected=str(po_line.qty_received),
                    actual=str(total_billed),
                )
            )
        if total_billed > ordered_limit:
            findings.append(
                Finding("qty_over_po", f"Line {invoice_line.line_no}: billing {total_billed} in total, above the {po_line.quantity} ordered.", line_no=invoice_line.line_no, expected=str(po_line.quantity), actual=str(total_billed))
            )
        expected_tax += invoice_line.taxable * po_line.gst_rate / 100
        lines.append(
            {
                "invoice_line_no": invoice_line.line_no,
                "po_line_id": po_line.id,
                "po_line_no": po_line.line_no,
                "alignment_score": round(score, 1),
                "description": invoice_line.description,
                "ordered": str(po_line.quantity),
                "received": str(po_line.qty_received),
                "previously_billed": str(po_line.qty_billed),
                "billed": str(invoice_line.quantity),
                "po_price": str(po_line.unit_price),
                "invoice_price": str(invoice_line.unit_price),
            }
        )

    invoice_tax = data.cgst + data.sgst + data.igst
    if abs(invoice_tax - expected_tax) > data.tax_tolerance_abs:
        findings.append(
            Finding("tax_amount_mismatch", f"Tax charged is {invoice_tax}; the PO's GST rates give {expected_tax.quantize(Decimal('0.01'))}.", expected=str(expected_tax.quantize(Decimal("0.01"))), actual=str(invoice_tax))
        )
    line_sum = sum((line.taxable for line in data.invoice_lines), Decimal(0))
    if abs(line_sum - data.subtotal) > Decimal("1.00"):
        findings.append(Finding("subtotal_mismatch", f"Line amounts add up to {line_sum}, but the subtotal is {data.subtotal}.", expected=str(line_sum), actual=str(data.subtotal)))
    computed_total = data.subtotal + invoice_tax + data.freight + data.round_off
    if abs(computed_total - data.total) > data.total_tolerance_abs:
        findings.append(Finding("arithmetic_error", f"Subtotal plus tax and freight is {computed_total}, but the invoice total is {data.total}.", expected=str(computed_total), actual=str(data.total)))
    if abs(data.round_off) > Decimal("1.00"):
        findings.append(Finding("round_off_large", f"Round-off of {data.round_off} is more than one rupee.", severity="warning"))
    if data.freight > data.po_freight:
        findings.append(Finding("freight_variance", f"Freight billed is {data.freight}; the PO allows {data.po_freight}.", expected=str(data.po_freight), actual=str(data.freight), assignee_role="procurement"))
    if data.payment_hold:
        findings.append(Finding("risk_hold", "This supplier has an active payment hold from risk review.", severity="warning", assignee_role="risk"))

    status = "exception" if any(item.severity == "blocking" for item in findings) else "matched"
    return MatchResult(status=status, exceptions=findings, lines=lines)
