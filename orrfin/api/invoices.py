"""Invoices: upload, review extracted fields, match, resolve exceptions, approve, pay."""
from datetime import date
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from orrfin.api.deps import Ctx, out, owned, require
from orrfin.documents.storage import file_response, read_document
from orrfin.models import Document, ExtractionRun, Invoice, InvoiceLine, MatchException, Payment, PurchaseOrder, Supplier
from orrfin.p2p import invoices as service

router = APIRouter(prefix="/api/invoices", tags=["invoices"])


class ConfirmLineIn(BaseModel):
    description: str = Field(min_length=1, max_length=300)
    hsn: str = Field(default="", max_length=12)
    unit: str = Field(default="", max_length=20)
    quantity: Decimal = Field(ge=0, max_digits=15, decimal_places=3)
    unit_price: Decimal = Field(ge=0, max_digits=16, decimal_places=2)
    taxable: Decimal | None = Field(default=None, ge=0, max_digits=16, decimal_places=2)
    gst_rate: Decimal | None = Field(default=None, ge=0, le=40)


class ConfirmIn(BaseModel):
    po_id: UUID
    number: str = Field(min_length=1, max_length=80)
    invoice_date: date
    supplier_gstin: str = Field(min_length=15, max_length=15)
    buyer_gstin: str = Field(default="", max_length=15)
    subtotal: Decimal = Field(ge=0)
    cgst: Decimal = Field(default=Decimal(0), ge=0)
    sgst: Decimal = Field(default=Decimal(0), ge=0)
    igst: Decimal = Field(default=Decimal(0), ge=0)
    freight: Decimal = Field(default=Decimal(0), ge=0)
    round_off: Decimal = Field(default=Decimal(0), ge=-100, le=100)
    total: Decimal = Field(ge=0)
    lines: list[ConfirmLineIn] = Field(min_length=1, max_length=300)


class ReasonIn(BaseModel):
    reason: str = Field(min_length=3, max_length=1000)


class PaymentIn(BaseModel):
    amount: Decimal = Field(gt=0, max_digits=16, decimal_places=2)
    paid_on: date | None = None
    reference: str = Field(default="", max_length=120)
    status: str = Field(default="scheduled", pattern="^(scheduled|paid)$")


@router.post("", status_code=201)
async def upload(file: UploadFile = File(...), po_id: UUID | None = Form(default=None), ctx: Ctx = Depends(require("invoice.write"))):
    raw = await file.read(service.MAX_UPLOAD + 1)
    with ctx.tx() as db:
        return out(service.upload(db, ctx, raw, file.filename or "invoice", po_id))


@router.get("")
def list_invoices(status: str | None = None, po_id: UUID | None = None, limit: int = 50, offset: int = 0, ctx: Ctx = Depends(require("invoice.read"))):
    with ctx.tx() as db:
        query = select(Invoice, Supplier.name, PurchaseOrder.number).outerjoin(Supplier, Supplier.id == Invoice.supplier_id).outerjoin(PurchaseOrder, PurchaseOrder.id == Invoice.po_id)
        if status:
            query = query.where(Invoice.status == status)
        if po_id:
            query = query.where(Invoice.po_id == po_id)
        total = db.scalar(select(func.count()).select_from(query.subquery()))
        rows = db.execute(query.order_by(Invoice.created_at.desc()).limit(min(limit, 200)).offset(max(offset, 0))).all()
        return {"total": total, "items": [out(row, exclude=("match_result",), supplier=name, po_number=number) for row, name, number in rows]}


@router.get("/exceptions")
def exception_queue(status: str = "open", ctx: Ctx = Depends(require("invoice.read"))):
    with ctx.tx() as db:
        query = (
            select(MatchException, Invoice.number, Supplier.name)
            .join(Invoice, Invoice.id == MatchException.invoice_id)
            .outerjoin(Supplier, Supplier.id == Invoice.supplier_id)
            .where(MatchException.status == status)
            .order_by(MatchException.created_at)
            .limit(300)
        )
        if ctx.role not in ("admin", "finance_ap"):
            query = query.where(MatchException.assignee_role == ctx.role)
        return [out(item, invoice_number=number, supplier=name) for item, number, name in db.execute(query)]


@router.get("/{invoice_id}")
def get_invoice(invoice_id: UUID, ctx: Ctx = Depends(require("invoice.read"))):
    with ctx.tx() as db:
        invoice = owned(db, Invoice, invoice_id)
        run = db.scalar(select(ExtractionRun).where(ExtractionRun.invoice_id == invoice.id).order_by(ExtractionRun.created_at.desc()))
        lines = db.scalars(select(InvoiceLine).where(InvoiceLine.invoice_id == invoice.id).order_by(InvoiceLine.line_no)).all()
        exceptions = db.scalars(select(MatchException).where(MatchException.invoice_id == invoice.id).order_by(MatchException.created_at)).all()
        payments = db.scalars(select(Payment).where(Payment.invoice_id == invoice.id)).all()
        po = db.get(PurchaseOrder, invoice.po_id) if invoice.po_id else None
        document = db.get(Document, invoice.document_id) if invoice.document_id else None
        return out(
            invoice,
            lines=[out(line) for line in lines],
            extraction=out(run) if run else None,
            exceptions=[out(item) for item in exceptions],
            payments=[out(item) for item in payments],
            purchase_order={"id": str(po.id), "number": po.number, "total": str(po.total)} if po else None,
            document={"filename": document.filename, "content_type": document.content_type, "size_bytes": document.size_bytes} if document else None,
        )


@router.get("/{invoice_id}/file")
def download_file(invoice_id: UUID, inline: bool = False, ctx: Ctx = Depends(require("invoice.read"))):
    with ctx.tx() as db:
        invoice = owned(db, Invoice, invoice_id)
        document = owned(db, Document, invoice.document_id)
        filename, content_type, data = document.filename, document.content_type, read_document(document)
    return file_response(data, filename, content_type, inline=inline)


@router.post("/{invoice_id}/extract")
def reextract(invoice_id: UUID, ctx: Ctx = Depends(require("invoice.write"))):
    from orrfin.worker import enqueue

    with ctx.tx() as db:
        invoice = owned(db, Invoice, invoice_id)
        if invoice.status not in ("uploaded", "extracted", "extraction_failed"):
            raise HTTPException(409, "This invoice has already been confirmed.")
        enqueue(db, ctx.tenant_id, "extract_invoice", invoice_id=invoice.id)
        return {"queued": True}


@router.put("/{invoice_id}/confirm")
def confirm(invoice_id: UUID, data: ConfirmIn, ctx: Ctx = Depends(require("invoice.write"))):
    with ctx.tx() as db:
        service.confirm(db, ctx, invoice_id, data.model_dump())
    return get_invoice(invoice_id, ctx)


@router.post("/{invoice_id}/rematch")
def rematch(invoice_id: UUID, ctx: Ctx = Depends(require("invoice.write"))):
    with ctx.tx() as db:
        invoice = owned(db, Invoice, invoice_id)
        if invoice.status not in ("matched", "exception"):
            raise HTTPException(409, "Only a confirmed, open invoice can be re-matched.")
        service.run_match(db, ctx, invoice)
    return get_invoice(invoice_id, ctx)


@router.post("/exceptions/{exception_id}/resolve")
def resolve(exception_id: UUID, data: ReasonIn, ctx: Ctx = Depends(require("invoice.read"))):
    if ctx.role not in ("admin", "finance_ap", "procurement", "risk"):
        raise HTTPException(403, "Your role doesn't allow this action.")
    with ctx.tx() as db:
        return out(service.resolve_exception(db, ctx, exception_id, data.reason))


@router.post("/{invoice_id}/approve")
def approve(invoice_id: UUID, ctx: Ctx = Depends(require("invoice.approve"))):
    with ctx.tx() as db:
        service.approve(db, ctx, invoice_id)
    return get_invoice(invoice_id, ctx)


@router.post("/{invoice_id}/reject")
def reject(invoice_id: UUID, data: ReasonIn, ctx: Ctx = Depends(require("invoice.write"))):
    with ctx.tx() as db:
        return out(service.reject(db, ctx, invoice_id, data.reason), exclude=("match_result",))


@router.post("/{invoice_id}/payments", status_code=201)
def pay(invoice_id: UUID, data: PaymentIn, ctx: Ctx = Depends(require("payment.write"))):
    with ctx.tx() as db:
        return out(service.record_payment(db, ctx, invoice_id, data.amount, data.paid_on, data.reference, data.status))
