"""Invoice lifecycle: upload, extraction, human confirmation, matching, exceptions, approval, payment."""
import re
from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from orrfin.api.deps import audit, encode
from orrfin.documents.storage import read_document, sniff_upload_type, store_document
from orrfin.gst import fiscal_year, money, quantity
from orrfin.models import (
    Document,
    ExtractionRun,
    Invoice,
    InvoiceAllocation,
    InvoiceLine,
    LegalEntity,
    MatchException,
    MemoryOutbox,
    Payment,
    PoLine,
    PurchaseOrder,
    RiskHold,
    Supplier,
)
from orrfin.p2p import extraction, matching
from orrfin.policy import policy_for
from orrfin.worker import enqueue

MAX_UPLOAD = 25 * 1024 * 1024


def normalize_number(number: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", (number or "").upper())


def upload(db: Session, actor, raw: bytes, filename: str, po_id: UUID | None = None, uploaded_by: str | None = None) -> Invoice:
    if len(raw) > MAX_UPLOAD:
        raise HTTPException(413, "The file must be under 25 MB.")
    content_type = sniff_upload_type(raw)
    if content_type is None:
        raise HTTPException(422, "Upload the invoice as a PDF, PNG or JPEG.")
    import hashlib

    sha = hashlib.sha256(raw).hexdigest()
    earlier = db.scalar(select(Document).where(Document.kind == "invoice", Document.sha256 == sha))
    if earlier:
        previous = db.get(Invoice, earlier.subject_id)
        label = previous.number or "already uploaded" if previous else "already uploaded"
        raise HTTPException(409, f"This exact file was uploaded before (invoice {label}).")
    po = db.get(PurchaseOrder, po_id) if po_id else None
    if po_id and po is None:
        raise HTTPException(404, "Record not found.")
    invoice = Invoice(tenant_id=actor.tenant_id, po_id=po.id if po else None, supplier_id=po.supplier_id if po else None, status="uploaded", uploaded_by=uploaded_by or actor.user_name)
    db.add(invoice)
    db.flush()
    document = store_document(
        db,
        actor.tenant_id,
        kind="invoice",
        filename=filename or "invoice",
        content_type=content_type,
        data=raw,
        subject_type="invoice",
        subject_id=invoice.id,
        uploaded_by=invoice.uploaded_by,
    )
    invoice.document_id = document.id
    audit(db, actor, "invoice_uploaded", "invoice", invoice.id, filename=filename)
    enqueue(db, actor.tenant_id, "extract_invoice", invoice_id=invoice.id)
    db.flush()
    return invoice


def run_extraction(db: Session, tenant_id: UUID, invoice_id: UUID) -> ExtractionRun:
    """Worker job. Idempotent: rerunning replaces nothing a person has confirmed."""
    invoice = db.scalar(select(Invoice).where(Invoice.id == invoice_id).with_for_update())
    if invoice is None or invoice.status not in ("uploaded", "extraction_failed", "extracted"):
        return None
    document = db.get(Document, invoice.document_id)
    known = set(db.scalars(select(LegalEntity.gstin)).all())
    try:
        result = extraction.extract(read_document(document), document.content_type, known)
    except Exception as error:  # Unreadable files become a visible state, not a crashed job.
        run = ExtractionRun(tenant_id=tenant_id, invoice_id=invoice.id, document_id=document.id, engine="none", status="failed", error=str(error)[:1000])
        db.add(run)
        invoice.status = "extraction_failed"
        db.flush()
        return run

    fields = result["fields"]
    run = ExtractionRun(
        tenant_id=tenant_id,
        invoice_id=invoice.id,
        document_id=document.id,
        engine=result["engine"],
        status="done",
        fields={"header": fields, "lines": result["lines"]},
        overall_confidence=Decimal(str(result["overall_confidence"])),
        warnings=result["warnings"],
    )
    db.add(run)
    if invoice.po_id is None and "po_number" in fields:
        po = db.scalar(select(PurchaseOrder).where(PurchaseOrder.number == fields["po_number"]["value"]))
        if po:
            invoice.po_id, invoice.supplier_id = po.id, po.supplier_id
    if invoice.supplier_id is None and "supplier_gstin" in fields:
        supplier = db.scalar(select(Supplier).where(Supplier.gstin == fields["supplier_gstin"]["value"]))
        if supplier:
            invoice.supplier_id = supplier.id
    invoice.status = "extracted"
    audit(db, None, "invoice_extracted", "invoice", invoice.id, tenant_id=tenant_id, engine=result["engine"], confidence=result["overall_confidence"])
    db.flush()
    return run


def confirm(db: Session, actor, invoice_id: UUID, data: dict) -> Invoice:
    """A person accepts or corrects the fields. Only confirmed values ever reach matching."""
    invoice = db.scalar(select(Invoice).where(Invoice.id == invoice_id).with_for_update())
    if invoice is None:
        raise HTTPException(404, "Record not found.")
    if invoice.status in ("approved", "paid", "rejected"):
        raise HTTPException(409, "This invoice is already closed.")
    po = db.get(PurchaseOrder, data["po_id"])
    if po is None:
        raise HTTPException(404, "That purchase order wasn't found.")
    invoice.po_id, invoice.supplier_id = po.id, po.supplier_id
    invoice.number = data["number"].strip()
    invoice.normalized_number = normalize_number(invoice.number)
    invoice.invoice_date = data["invoice_date"]
    invoice.fiscal_year = fiscal_year(data["invoice_date"])
    invoice.supplier_gstin = data["supplier_gstin"].strip().upper()
    invoice.buyer_gstin = (data.get("buyer_gstin") or "").strip().upper()
    for key in ("subtotal", "cgst", "sgst", "igst", "freight", "round_off", "total"):
        setattr(invoice, key, money(data.get(key) or 0))
    db.execute(delete(InvoiceLine).where(InvoiceLine.invoice_id == invoice.id))
    for number, line in enumerate(data["lines"], start=1):
        db.add(
            InvoiceLine(
                tenant_id=actor.tenant_id,
                invoice_id=invoice.id,
                line_no=number,
                description=line["description"],
                hsn=line.get("hsn") or "",
                unit=line.get("unit") or "",
                quantity=quantity(line["quantity"]),
                unit_price=money(line["unit_price"]),
                taxable=money(line.get("taxable") if line.get("taxable") is not None else Decimal(str(line["quantity"])) * Decimal(str(line["unit_price"]))),
                gst_rate=line.get("gst_rate"),
            )
        )
    invoice.confirmed_by, invoice.confirmed_at = actor.user_id, datetime.now(timezone.utc)
    invoice.status = "confirmed"
    # The partial unique index rejects a second invoice with this supplier and number here.
    db.flush()
    audit(db, actor, "invoice_confirmed", "invoice", invoice.id, number=invoice.number, total=invoice.total)
    run_match(db, actor, invoice)
    return invoice


def run_match(db: Session, actor, invoice: Invoice) -> matching.MatchResult:
    po = db.get(PurchaseOrder, invoice.po_id)
    supplier = db.get(Supplier, po.supplier_id)
    entity = db.get(LegalEntity, po.legal_entity_id)
    policy = policy_for(db, invoice.tenant_id)
    po_lines = db.scalars(select(PoLine).where(PoLine.po_id == po.id).order_by(PoLine.line_no)).all()
    invoice_lines = db.scalars(select(InvoiceLine).where(InvoiceLine.invoice_id == invoice.id).order_by(InvoiceLine.line_no)).all()
    hold = db.scalar(select(RiskHold.id).where(RiskHold.supplier_id == supplier.id, RiskHold.active.is_(True), RiskHold.scope.in_(("payment", "all"))).limit(1))
    freight_billed = db.scalar(
        select(func.coalesce(func.sum(Invoice.freight), 0)).where(Invoice.po_id == po.id, Invoice.status.in_(("approved", "paid")), Invoice.id != invoice.id)
    )
    result = matching.match(
        matching.MatchInput(
            po_number=po.number or "",
            po_status=po.status,
            po_interstate=po.is_interstate,
            po_freight=po.freight - freight_billed,
            po_supplier_gstin=supplier.gstin,
            po_buyer_gstin=entity.gstin,
            po_lines=[
                matching.PoLineData(
                    id=str(line.id), line_no=line.line_no, description=line.description, quantity=line.quantity, unit_price=line.unit_price,
                    gst_rate=line.gst_rate, qty_received=line.qty_received, qty_billed=line.qty_billed, sku=line.sku, hsn=line.hsn,
                )
                for line in po_lines
            ],
            invoice_lines=[
                matching.InvoiceLineData(
                    line_no=line.line_no, description=line.description, quantity=line.quantity, unit_price=line.unit_price,
                    taxable=line.taxable, hsn=line.hsn, gst_rate=line.gst_rate,
                )
                for line in invoice_lines
            ],
            supplier_gstin=invoice.supplier_gstin,
            buyer_gstin=invoice.buyer_gstin,
            subtotal=invoice.subtotal,
            cgst=invoice.cgst,
            sgst=invoice.sgst,
            igst=invoice.igst,
            freight=invoice.freight,
            round_off=invoice.round_off,
            total=invoice.total,
            price_tolerance_pct=policy.price_tolerance_pct,
            qty_tolerance_pct=policy.qty_tolerance_pct,
            tax_tolerance_abs=policy.tax_tolerance_abs,
            total_tolerance_abs=policy.total_tolerance_abs,
            payment_hold=hold is not None,
        )
    )
    for line in invoice_lines:
        pair = next((row for row in result.lines if row["invoice_line_no"] == line.line_no), None)
        line.po_line_id = UUID(pair["po_line_id"]) if pair else None
    db.execute(delete(MatchException).where(MatchException.invoice_id == invoice.id, MatchException.status == "open"))
    for finding in result.exceptions:
        db.add(
            MatchException(
                tenant_id=invoice.tenant_id,
                invoice_id=invoice.id,
                code=finding.code,
                severity=finding.severity,
                message=finding.message[:600],
                line_no=finding.line_no,
                expected=finding.expected[:120],
                actual=finding.actual[:120],
                assignee_role=finding.assignee_role,
            )
        )
    invoice.match_result = encode({"status": result.status, "lines": result.lines, "checked_at": datetime.now(timezone.utc)})
    invoice.status = result.status
    audit(db, actor, "invoice_matched", "invoice", invoice.id, status=result.status, exceptions=[item.code for item in result.exceptions])
    db.flush()
    return result


def resolve_exception(db: Session, actor, exception_id: UUID, resolution: str) -> MatchException:
    item = db.scalar(select(MatchException).where(MatchException.id == exception_id).with_for_update())
    if item is None:
        raise HTTPException(404, "Record not found.")
    if item.status != "open":
        raise HTTPException(409, "This exception is already resolved.")
    if actor.role not in (item.assignee_role, "admin", "finance_ap"):
        raise HTTPException(403, "This exception is assigned to a different team.")
    item.status, item.resolution = "resolved", resolution
    item.resolved_by, item.resolved_at = actor.user_id, datetime.now(timezone.utc)
    audit(db, actor, "exception_resolved", "invoice", item.invoice_id, code=item.code, resolution=resolution)
    db.flush()
    return item


def approve(db: Session, actor, invoice_id: UUID) -> Invoice:
    invoice = db.scalar(select(Invoice).where(Invoice.id == invoice_id).with_for_update())
    if invoice is None:
        raise HTTPException(404, "Record not found.")
    if invoice.status not in ("matched", "exception"):
        raise HTTPException(409, "Confirm and match this invoice before approving it.")
    if invoice.confirmed_by == actor.user_id and actor.role != "admin":
        raise HTTPException(409, "A different person must approve an invoice you confirmed.")
    open_blocking = db.scalar(
        select(func.count()).where(MatchException.invoice_id == invoice.id, MatchException.status == "open", MatchException.severity == "blocking")
    )
    if open_blocking:
        raise HTTPException(409, f"Resolve the {open_blocking} open exception(s) before approving.")
    lines = db.scalars(select(InvoiceLine).where(InvoiceLine.invoice_id == invoice.id, InvoiceLine.po_line_id.is_not(None))).all()
    # Lock PO lines in id order so concurrent approvals queue instead of deadlocking.
    ids = sorted({line.po_line_id for line in lines})
    if ids:
        db.scalars(select(PoLine).where(PoLine.id.in_(ids)).order_by(PoLine.id).with_for_update()).all()
    for line in lines:
        db.add(InvoiceAllocation(tenant_id=invoice.tenant_id, invoice_line_id=line.id, po_line_id=line.po_line_id, quantity=line.quantity))
    # The allocation trigger raises qty_billed; the line's CHECK rejects any over-billing race.
    db.flush()
    invoice.status = "approved"
    invoice.approved_by, invoice.approved_at = actor.user_id, datetime.now(timezone.utc)
    # Invoice numbers repeat across suppliers, so the source record is the invoice's own id.
    db.add(MemoryOutbox(tenant_id=invoice.tenant_id, supplier_id=invoice.supplier_id, source_id=str(invoice.id), event_type="invoice_approved"))
    audit(db, actor, "invoice_approved", "invoice", invoice.id, total=invoice.total)
    from orrfin.erp.outbox import queue_document

    queue_document(db, invoice.tenant_id, "bill", invoice.id)
    db.flush()
    return invoice


def reject(db: Session, actor, invoice_id: UUID, reason: str) -> Invoice:
    invoice = db.scalar(select(Invoice).where(Invoice.id == invoice_id).with_for_update())
    if invoice is None:
        raise HTTPException(404, "Record not found.")
    if invoice.status in ("approved", "paid"):
        raise HTTPException(409, "An approved invoice can't be rejected.")
    invoice.status = "rejected"
    db.execute(delete(MatchException).where(MatchException.invoice_id == invoice.id, MatchException.status == "open"))
    audit(db, actor, "invoice_rejected", "invoice", invoice.id, reason=reason)
    db.flush()
    return invoice


def record_payment(db: Session, actor, invoice_id: UUID, amount: Decimal, paid_on: date | None, reference: str, status: str) -> Payment:
    invoice = db.scalar(select(Invoice).where(Invoice.id == invoice_id).with_for_update())
    if invoice is None:
        raise HTTPException(404, "Record not found.")
    already = db.scalar(select(func.coalesce(func.sum(Payment.amount), 0)).where(Payment.invoice_id == invoice.id))
    if already + amount > invoice.total:
        raise HTTPException(409, f"That would pay {already + amount}, more than the invoice total of {invoice.total}.")
    payment = Payment(tenant_id=invoice.tenant_id, invoice_id=invoice.id, supplier_id=invoice.supplier_id, amount=money(amount), status=status, reference=reference, paid_on=paid_on)
    db.add(payment)
    db.flush()  # The payment trigger blocks unapproved invoices and supplier payment holds.
    if status == "paid" and already + amount == invoice.total:
        invoice.status = "paid"
    audit(db, actor, "payment_recorded", "invoice", invoice.id, amount=amount, status=status)
    db.flush()
    return payment
