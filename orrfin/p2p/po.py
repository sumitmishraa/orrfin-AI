"""Purchase order lifecycle: creation with GST, issue, PDF, goods receipt and change orders."""
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from orrfin import approvals
from orrfin.api.deps import audit, encode
from orrfin.documents.pdf import render_purchase_order
from orrfin.documents.storage import store_document
from orrfin.gst import STATES, fiscal_year, money, quantity, split_tax
from orrfin.models import (
    ApprovalInstance,
    Branch,
    Document,
    GoodsReceipt,
    GrnLine,
    LegalEntity,
    Location,
    MemoryOutbox,
    PoLine,
    PoRevision,
    PurchaseOrder,
    Supplier,
)
from orrfin.numbering import next_number
from orrfin.policy import policy_for


@dataclass
class LineInput:
    description: str
    quantity: Decimal
    unit_price: Decimal
    hsn: str = ""
    unit: str = "NOS"
    gst_rate: Decimal = Decimal("18")
    item_id: UUID | None = None
    sku: str = ""


def _recalculate(po: PurchaseOrder, lines: list[PoLine]) -> None:
    for line in lines:
        line.taxable = money(line.quantity * line.unit_price)
        tax = split_tax(line.taxable, line.gst_rate, po.is_interstate)
        line.cgst, line.sgst, line.igst = tax["cgst"], tax["sgst"], tax["igst"]
    po.subtotal = money(sum((line.taxable for line in lines), Decimal(0)))
    po.cgst = money(sum((line.cgst for line in lines), Decimal(0)))
    po.sgst = money(sum((line.sgst for line in lines), Decimal(0)))
    po.igst = money(sum((line.igst for line in lines), Decimal(0)))
    po.total = money(po.subtotal + po.cgst + po.sgst + po.igst + po.freight)


def create_draft(
    db: Session,
    actor,
    *,
    branch_id: UUID,
    supplier_id: UUID,
    lines: list[LineInput],
    location_id: UUID | None = None,
    intake_id: UUID | None = None,
    event_id: UUID | None = None,
    approval_instance_id: UUID | None = None,
    approved_amount: Decimal = Decimal(0),
    needed_by: date | None = None,
    freight: Decimal = Decimal(0),
    notes: str = "",
    at: datetime | None = None,
) -> PurchaseOrder:
    if not lines:
        raise HTTPException(422, "A purchase order needs at least one line.")
    branch = db.get(Branch, branch_id)
    if branch is None:
        raise HTTPException(404, "Record not found.")
    supplier = db.get(Supplier, supplier_id)
    if supplier is None:
        raise HTTPException(404, "Record not found.")
    if supplier.status != "approved":
        raise HTTPException(409, "This supplier isn't approved yet. Complete onboarding first.")
    supplier_state = supplier.state_code or supplier.gstin[:2]
    if not supplier_state:
        raise HTTPException(422, "Add the supplier's GSTIN or state, so the right GST can be applied.")

    entity = db.get(LegalEntity, branch.legal_entity_id)
    policy = policy_for(db, actor.tenant_id)
    po = PurchaseOrder(
        tenant_id=actor.tenant_id,
        legal_entity_id=entity.id,
        branch_id=branch.id,
        location_id=location_id,
        supplier_id=supplier.id,
        intake_id=intake_id,
        event_id=event_id,
        approval_instance_id=approval_instance_id,
        approved_amount=money(approved_amount),
        status="draft",
        freight=money(freight),
        place_of_supply=f"{entity.state_name} ({entity.state_code})",
        is_interstate=supplier_state != entity.state_code,
        needed_by=needed_by,
        payment_terms_days=supplier.payment_terms_days,
        notes=notes,
    )
    if at:
        po.created_at = at
    db.add(po)
    db.flush()
    rows = []
    for number, line in enumerate(lines, start=1):
        qty = quantity(line.quantity)
        if qty <= 0:
            raise HTTPException(422, f"Line {number}: enter a quantity above zero.")
        cap = quantity(qty * (1 + policy.over_receipt_pct / 100))
        bill_cap = quantity(qty * (1 + policy.qty_tolerance_pct / 100))
        rows.append(
            PoLine(
                tenant_id=actor.tenant_id,
                po_id=po.id,
                line_no=number,
                item_id=line.item_id,
                sku=line.sku,
                description=line.description,
                hsn=line.hsn,
                unit=line.unit,
                quantity=qty,
                unit_price=money(line.unit_price),
                gst_rate=line.gst_rate,
                receipt_cap=cap,
                billing_cap=bill_cap,
                qty_received=Decimal(0),
                qty_billed=Decimal(0),
            )
        )
    _recalculate(po, rows)
    db.add_all(rows)
    audit(db, actor, "po_drafted", "purchase_order", po.id, total=po.total)
    db.flush()
    return po


def issue(db: Session, actor, po_id: UUID, at: datetime | None = None) -> PurchaseOrder:
    """Numbering is last, so the sequence row lock is held only briefly and rollback frees the number."""
    now = at or datetime.now(timezone.utc)
    po = db.scalar(select(PurchaseOrder).where(PurchaseOrder.id == po_id).with_for_update())
    if po is None:
        raise HTTPException(404, "Record not found.")
    if po.status != "draft":
        raise HTTPException(409, "Only a draft purchase order can be issued.")
    branch = db.get(Branch, po.branch_id)
    po.fiscal_year = fiscal_year(now)
    po.issued_at = now
    po.issued_by = actor.user_id
    po.status = "issued"
    # Validate the database guards before consuming a number from the sequence.
    db.flush()
    po.number = next_number(db, actor.tenant_id, "PO", branch.code, po.fiscal_year)
    audit(db, actor, "po_issued", "purchase_order", po.id, number=po.number, total=po.total)
    from orrfin.erp.outbox import queue_document

    queue_document(db, actor.tenant_id, "purchase_order", po.id, 0)
    db.add(
        PoRevision(
            tenant_id=actor.tenant_id, po_id=po.id, revision=0, reason="Issued", snapshot=snapshot(db, po), created_by=actor.user_name
        )
    )
    db.flush()
    return po


def snapshot(db: Session, po: PurchaseOrder) -> dict:
    lines = db.scalars(select(PoLine).where(PoLine.po_id == po.id).order_by(PoLine.line_no)).all()
    return encode(
        {
            "total": po.total,
            "subtotal": po.subtotal,
            "lines": [
                {"line_no": line.line_no, "description": line.description, "quantity": line.quantity, "unit_price": line.unit_price}
                for line in lines
            ],
        }
    )


def pdf_payload(db: Session, po: PurchaseOrder) -> dict:
    entity = db.get(LegalEntity, po.legal_entity_id)
    branch = db.get(Branch, po.branch_id)
    supplier = db.get(Supplier, po.supplier_id)
    location = db.get(Location, po.location_id) if po.location_id else None
    lines = db.scalars(select(PoLine).where(PoLine.po_id == po.id).order_by(PoLine.line_no)).all()
    return {
        "number": po.number,
        "revision": po.revision,
        "date": po.issued_at.date().isoformat() if po.issued_at else "",
        "needed_by": po.needed_by.isoformat() if po.needed_by else "",
        "payment_terms_days": po.payment_terms_days,
        "is_interstate": po.is_interstate,
        "fictional": policy_for(db, po.tenant_id).fictional,
        "buyer": {
            "name": entity.name,
            "address": entity.address,
            "gstin": entity.gstin,
            "state": STATES.get(entity.state_code, entity.state_name),
            "state_code": entity.state_code,
        },
        "ship_to": {
            "name": location.name if location else branch.name,
            "address": location.address if location else branch.city,
            "branch": f"{branch.code} - {branch.name}",
        },
        "supplier": {"name": supplier.name, "address": supplier.address, "gstin": supplier.gstin},
        "lines": [
            {
                "line_no": line.line_no,
                "description": line.description,
                "hsn": line.hsn,
                "quantity": line.quantity,
                "unit": line.unit,
                "unit_price": line.unit_price,
                "taxable": line.taxable,
                "gst_rate": line.gst_rate,
                "cgst": line.cgst,
                "sgst": line.sgst,
                "igst": line.igst,
            }
            for line in lines
        ],
        "totals": {
            "subtotal": po.subtotal,
            "cgst": po.cgst,
            "sgst": po.sgst,
            "igst": po.igst,
            "freight": po.freight,
            "total": po.total,
        },
    }


def ensure_pdf(db: Session, po: PurchaseOrder, by: str = "system") -> Document:
    """Renders and stores the PDF for this revision once. Each revision keeps its own file."""
    if not po.number:
        raise HTTPException(409, "Issue this purchase order before downloading its PDF.")
    existing = db.scalar(
        select(Document).where(
            Document.subject_type == "purchase_order",
            Document.subject_id == po.id,
            Document.kind == "po_pdf",
            Document.version == po.revision,
        )
    )
    if existing:
        return existing
    data = render_purchase_order(pdf_payload(db, po))
    return store_document(
        db,
        po.tenant_id,
        kind="po_pdf",
        filename=po.number.replace("/", "-") + f"-r{po.revision}.pdf",
        content_type="application/pdf",
        data=data,
        subject_type="purchase_order",
        subject_id=po.id,
        version=po.revision,
        uploaded_by=by,
    )


def record_receipt(
    db: Session,
    actor,
    po_id: UUID,
    *,
    quantities: dict[UUID, Decimal],
    idempotency_key: str,
    received_on: date,
    location_id: UUID | None = None,
    quality_ok: bool = True,
    note: str = "",
) -> GoodsReceipt:
    po = db.scalar(select(PurchaseOrder).where(PurchaseOrder.id == po_id).with_for_update())
    if po is None:
        raise HTTPException(404, "Record not found.")
    previous = db.scalar(
        select(GoodsReceipt).where(GoodsReceipt.po_id == po.id, GoodsReceipt.idempotency_key == idempotency_key)
    )
    if previous:
        return previous
    if po.status not in ("issued", "partially_received", "received"):
        raise HTTPException(409, "Goods can only be received against an issued purchase order.")
    lines = {line.id: line for line in db.scalars(select(PoLine).where(PoLine.po_id == po.id))}
    unknown = set(quantities) - set(lines)
    if unknown:
        raise HTTPException(422, "One of those lines isn't on this purchase order.")
    positive = {line_id: quantity(amount) for line_id, amount in quantities.items() if amount > 0}
    if not positive:
        raise HTTPException(422, "Enter at least one received quantity.")

    branch = db.get(Branch, po.branch_id)
    receipt = GoodsReceipt(
        tenant_id=actor.tenant_id,
        number=next_number(db, actor.tenant_id, "GRN", branch.code, fiscal_year(received_on)),
        po_id=po.id,
        location_id=location_id or po.location_id,
        received_on=received_on,
        received_by=actor.user_id,
        quality_ok=quality_ok,
        note=note,
        idempotency_key=idempotency_key,
    )
    db.add(receipt)
    db.flush()
    for line_id, amount in positive.items():
        db.add(GrnLine(tenant_id=actor.tenant_id, grn_id=receipt.id, po_line_id=line_id, quantity=amount))
    # The trigger raises qty_received here, and the line's CHECK rejects any over-receipt.
    db.flush()
    db.expire_all()
    refresh_status(db, po.id)
    event = ("on_time" if not po.needed_by or received_on <= po.needed_by else "late") + (
        "_quality_ok" if quality_ok else "_quality_issue"
    )
    db.add(MemoryOutbox(tenant_id=actor.tenant_id, supplier_id=po.supplier_id, source_id=receipt.number, event_type=event))
    audit(db, actor, "goods_received", "purchase_order", po.id, receipt=receipt.number, quality_ok=quality_ok)
    db.flush()
    return receipt


def refresh_status(db: Session, po_id: UUID) -> None:
    po = db.get(PurchaseOrder, po_id)
    if po.status in ("cancelled", "closed", "change_pending"):
        return
    lines = db.scalars(select(PoLine).where(PoLine.po_id == po_id)).all()
    if all(line.qty_received >= line.quantity for line in lines):
        po.status = "received"
    elif any(line.qty_received > 0 for line in lines):
        po.status = "partially_received"
    else:
        po.status = "issued"


def request_change(db: Session, actor, po_id: UUID, changes: list[dict], reason: str) -> PurchaseOrder:
    """Applies a change directly if it stays within the approved amount, else routes it for approval."""
    po = db.scalar(select(PurchaseOrder).where(PurchaseOrder.id == po_id).with_for_update())
    if po is None:
        raise HTTPException(404, "Record not found.")
    if po.status not in ("issued", "partially_received", "received"):
        raise HTTPException(409, "Only an issued purchase order can be changed.")
    lines = {line.id: line for line in db.scalars(select(PoLine).where(PoLine.po_id == po.id))}
    for change in changes:
        line = lines.get(change["line_id"])
        if line is None:
            raise HTTPException(422, "One of those lines isn't on this purchase order.")
        new_qty = change.get("quantity")
        if new_qty is not None and quantity(new_qty) < max(line.qty_received, line.qty_billed):
            raise HTTPException(422, f"Line {line.line_no}: can't go below what is already received or billed.")

    projected = _projected_total(po, lines, changes)
    if projected <= po.approved_amount:
        _apply_change(db, actor, po, changes, reason, new_approved=None)
        return po

    instance = approvals.submit(
        db,
        actor,
        subject_type="po_change",
        subject_id=po.id,
        branch_id=po.branch_id,
        requester_id=actor.user_id,
        amount=projected,
    )
    db.add(
        PoRevision(
            tenant_id=actor.tenant_id,
            po_id=po.id,
            revision=po.revision + 1,
            reason=reason,
            snapshot=encode({"pending": True, "instance_id": instance.id, "changes": changes, "projected_total": projected, "status_before": po.status}),
            created_by=actor.user_name,
        )
    )
    po.status = "change_pending"
    audit(db, actor, "po_change_requested", "purchase_order", po.id, projected_total=projected, reason=reason)
    db.flush()
    return po


def _projected_total(po: PurchaseOrder, lines: dict[UUID, PoLine], changes: list[dict]) -> Decimal:
    by_line = {change["line_id"]: change for change in changes}
    total = po.freight
    for line in lines.values():
        change = by_line.get(line.id, {})
        qty = quantity(change.get("quantity") if change.get("quantity") is not None else line.quantity)
        price = money(change.get("unit_price") if change.get("unit_price") is not None else line.unit_price)
        taxable = money(qty * price)
        tax = split_tax(taxable, line.gst_rate, po.is_interstate)
        total += taxable + tax["cgst"] + tax["sgst"] + tax["igst"]
    return money(total)


def _apply_change(db: Session, actor, po: PurchaseOrder, changes: list[dict], reason: str, new_approved: Decimal | None, status_after: str | None = None) -> None:
    lines = {line.id: line for line in db.scalars(select(PoLine).where(PoLine.po_id == po.id))}
    policy = policy_for(db, po.tenant_id)
    for change in changes:
        line = lines[UUID(str(change["line_id"]))]
        if change.get("quantity") is not None:
            line.quantity = quantity(change["quantity"])
            line.receipt_cap = quantity(line.quantity * (1 + policy.over_receipt_pct / 100))
            line.billing_cap = quantity(line.quantity * (1 + policy.qty_tolerance_pct / 100))
        if change.get("unit_price") is not None:
            line.unit_price = money(change["unit_price"])
    _recalculate(po, list(lines.values()))
    if new_approved is not None:
        po.approved_amount = new_approved
    po.revision += 1
    if status_after:
        po.status = status_after
    existing = db.scalar(select(PoRevision).where(PoRevision.po_id == po.id, PoRevision.revision == po.revision))
    if existing:
        existing.snapshot = snapshot(db, po)
    else:
        db.add(
            PoRevision(
                tenant_id=po.tenant_id, po_id=po.id, revision=po.revision, reason=reason, snapshot=snapshot(db, po), created_by=actor.user_name
            )
        )
    audit(db, actor, "po_changed", "purchase_order", po.id, revision=po.revision, total=po.total, reason=reason)
    from orrfin.erp.outbox import queue_document

    queue_document(db, po.tenant_id, "purchase_order", po.id, po.revision)
    db.flush()
    db.expire(po)
    refresh_status(db, po.id)


@approvals.on_complete("po_change")
def _change_decided(db: Session, actor, instance: ApprovalInstance, approved: bool) -> None:
    po = db.scalar(select(PurchaseOrder).where(PurchaseOrder.id == instance.subject_id).with_for_update())
    pending = db.scalar(select(PoRevision).where(PoRevision.po_id == po.id, PoRevision.revision == po.revision + 1))
    data = pending.snapshot
    if approved:
        _apply_change(
            db, actor, po, data["changes"], pending.reason, new_approved=instance.amount, status_after=data["status_before"]
        )
    else:
        po.status = data["status_before"]
        db.delete(pending)
        audit(db, actor, "po_change_rejected", "purchase_order", po.id)
    db.flush()
