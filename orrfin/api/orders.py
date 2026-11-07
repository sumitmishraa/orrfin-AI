"""Purchase orders and goods receipts."""
from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from orrfin.api.deps import Ctx, audit, out, owned, require
from orrfin.documents.storage import file_response, read_document
from orrfin.models import Document, GoodsReceipt, GrnLine, Invoice, PoLine, PoRevision, PurchaseOrder, Supplier
from orrfin.p2p import po as service

router = APIRouter(prefix="/api/purchase-orders", tags=["purchase orders"])


class ReceiptLineIn(BaseModel):
    po_line_id: UUID
    quantity: Decimal = Field(ge=0, max_digits=15, decimal_places=3)


class ReceiptIn(BaseModel):
    lines: list[ReceiptLineIn] = Field(min_length=1, max_length=200)
    received_on: date | None = None
    location_id: UUID | None = None
    quality_ok: bool = True
    note: str = Field(default="", max_length=1000)
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=100)


class ChangeLineIn(BaseModel):
    line_id: UUID
    quantity: Decimal | None = Field(default=None, gt=0, max_digits=15, decimal_places=3)
    unit_price: Decimal | None = Field(default=None, ge=0, max_digits=16, decimal_places=2)


class ChangeIn(BaseModel):
    reason: str = Field(min_length=3, max_length=1000)
    lines: list[ChangeLineIn] = Field(min_length=1, max_length=200)


def _visible(ctx: Ctx, po: PurchaseOrder) -> PurchaseOrder:
    ctx.require_branch(po.branch_id)
    return po


@router.get("")
def list_orders(
    status: str | None = None,
    branch_id: UUID | None = None,
    supplier_id: UUID | None = None,
    q: str = "",
    limit: int = 50,
    offset: int = 0,
    ctx: Ctx = Depends(require("po.read")),
):
    with ctx.tx() as db:
        query = select(PurchaseOrder, Supplier.name).join(Supplier, Supplier.id == PurchaseOrder.supplier_id)
        if status:
            query = query.where(PurchaseOrder.status == status)
        if branch_id:
            query = query.where(PurchaseOrder.branch_id == branch_id)
        if supplier_id:
            query = query.where(PurchaseOrder.supplier_id == supplier_id)
        if q:
            query = query.where(PurchaseOrder.number.ilike("%" + q.replace("%", r"\%").replace("_", r"\_") + "%"))
        if ctx.branch_ids is not None:
            query = query.where(PurchaseOrder.branch_id.in_(ctx.branch_ids))
        total = db.scalar(select(func.count()).select_from(query.subquery()))
        rows = db.execute(query.order_by(PurchaseOrder.created_at.desc()).limit(min(limit, 200)).offset(max(offset, 0))).all()
        return {"total": total, "items": [out(po, supplier=name) for po, name in rows]}


@router.get("/{po_id}")
def get_order(po_id: UUID, ctx: Ctx = Depends(require("po.read"))):
    with ctx.tx() as db:
        po = _visible(ctx, owned(db, PurchaseOrder, po_id))
        lines = db.scalars(select(PoLine).where(PoLine.po_id == po.id).order_by(PoLine.line_no)).all()
        receipts = db.scalars(select(GoodsReceipt).where(GoodsReceipt.po_id == po.id).order_by(GoodsReceipt.received_on)).all()
        invoices = db.scalars(select(Invoice).where(Invoice.po_id == po.id).order_by(Invoice.created_at)).all()
        revisions = db.scalars(select(PoRevision).where(PoRevision.po_id == po.id).order_by(PoRevision.revision)).all()
        supplier = db.get(Supplier, po.supplier_id)
        return out(
            po,
            supplier=out(supplier),
            lines=[out(line) for line in lines],
            receipts=[out(row) for row in receipts],
            invoices=[out(row, exclude=("match_result",)) for row in invoices],
            revisions=[out(row, exclude=("snapshot",)) for row in revisions],
        )


@router.post("/{po_id}/issue")
def issue(po_id: UUID, ctx: Ctx = Depends(require("po.write"))):
    with ctx.tx() as db:
        return out(service.issue(db, ctx, po_id))


@router.get("/{po_id}/pdf")
def download_pdf(po_id: UUID, ctx: Ctx = Depends(require("po.read"))):
    with ctx.tx() as db:
        po = _visible(ctx, owned(db, PurchaseOrder, po_id))
        document = service.ensure_pdf(db, po, ctx.user_name)
        audit(db, ctx, "po_pdf_downloaded", "purchase_order", po.id, revision=po.revision)
        filename, content_type, data = document.filename, document.content_type, read_document(document)
    return file_response(data, filename, content_type)


@router.post("/{po_id}/change-order")
def change_order(po_id: UUID, data: ChangeIn, ctx: Ctx = Depends(require("po.write"))):
    with ctx.tx() as db:
        changes = [line.model_dump() for line in data.lines]
        return out(service.request_change(db, ctx, po_id, changes, data.reason))


@router.post("/{po_id}/supplier-link", status_code=201)
def supplier_link(po_id: UUID, ctx: Ctx = Depends(require("po.write"))):
    from orrfin import portal

    with ctx.tx() as db:
        po = _visible(ctx, owned(db, PurchaseOrder, po_id))
        if not po.number:
            raise HTTPException(409, "Issue the purchase order before sharing it.")
        audit(db, ctx, "po_supplier_link_created", "purchase_order", po.id)
    return {"url": portal.link("po", portal.issue(ctx.tenant_id, "po", po_id, days=90)), "notice": "The supplier can view this PO, download its PDF and upload invoices. The link expires in 90 days."}


@router.post("/{po_id}/cancel")
def cancel(po_id: UUID, ctx: Ctx = Depends(require("po.write"))):
    with ctx.tx() as db:
        po = db.scalar(select(PurchaseOrder).where(PurchaseOrder.id == po_id).with_for_update())
        if po is None:
            raise HTTPException(404, "Record not found.")
        received = db.scalar(select(func.coalesce(func.sum(PoLine.qty_received), 0)).where(PoLine.po_id == po.id))
        if po.status not in ("draft", "issued") or received > 0:
            raise HTTPException(409, "A purchase order with receipts can't be cancelled. Use a change order.")
        po.status = "cancelled"
        audit(db, ctx, "po_cancelled", "purchase_order", po.id)
        db.flush()
        return out(po)


@router.get("/{po_id}/receipts")
def list_receipts(po_id: UUID, ctx: Ctx = Depends(require("po.read"))):
    with ctx.tx() as db:
        _visible(ctx, owned(db, PurchaseOrder, po_id))
        receipts = db.scalars(select(GoodsReceipt).where(GoodsReceipt.po_id == po_id).order_by(GoodsReceipt.received_on)).all()
        result = []
        for receipt in receipts:
            lines = db.scalars(select(GrnLine).where(GrnLine.grn_id == receipt.id)).all()
            result.append(out(receipt, lines=[out(line) for line in lines]))
        return result


@router.post("/{po_id}/receipts", status_code=201)
def create_receipt(po_id: UUID, data: ReceiptIn, ctx: Ctx = Depends(require("grn.write"))):
    with ctx.tx() as db:
        _visible(ctx, owned(db, PurchaseOrder, po_id))
        receipt = service.record_receipt(
            db,
            ctx,
            po_id,
            quantities={line.po_line_id: line.quantity for line in data.lines},
            idempotency_key=data.idempotency_key or uuid4().hex,
            received_on=data.received_on or datetime.now(timezone.utc).date(),
            location_id=data.location_id,
            quality_ok=data.quality_ok,
            note=data.note,
        )
        return out(receipt)


__all__ = ["router", "Document"]
