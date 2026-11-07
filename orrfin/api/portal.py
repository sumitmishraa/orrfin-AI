"""Supplier portal: onboarding questionnaire, RFQ bids, and PO acknowledgement with invoice upload.

Suppliers have no account. Each link is scoped to one record, expires and can be revoked.
"""
from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, File, Form, Header, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select

from orrfin import portal
from orrfin.api.deps import audit, out, public
from orrfin.api.sourcing import price_bid
from orrfin.api.suppliers import run_checks
from orrfin.db import tenant_tx
from orrfin.documents.storage import file_response, read_document, sniff_upload_type, store_document
from orrfin.models import Bid, BidLine, OnboardingCase, PoLine, PurchaseOrder, SourcingEvent, SourcingInvite, SourcingLine, Supplier
from orrfin.p2p import invoices as invoice_service
from orrfin.p2p import po as po_service

router = APIRouter(prefix="/api/portal", tags=["supplier portal"])
DOCUMENT_KINDS = ("gst_certificate", "pan_card", "cancelled_cheque", "msme_certificate", "iso_certificate", "other")


class Certification(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    expiry: date


class OnboardingAnswers(BaseModel):
    legal_name: str = Field(min_length=2, max_length=200)
    gstin: str = Field(min_length=15, max_length=15)
    pan: str = Field(min_length=10, max_length=10)
    address: str = Field(min_length=5, max_length=400)
    contact_name: str = Field(min_length=2, max_length=160)
    contact_email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$", max_length=255)
    phone: str = Field(default="", max_length=40)
    bank_account_number: str = Field(min_length=6, max_length=20, pattern=r"^\d+$")
    ifsc: str = Field(min_length=11, max_length=11)
    msme_number: str = Field(default="", max_length=40)
    service_cities: list[str] = Field(default=[], max_length=50)
    certifications: list[Certification] = Field(default=[], max_length=20)
    declares_no_conflict_of_interest: bool
    accepts_code_of_conduct: bool


class BidPrice(BaseModel):
    line_id: UUID
    unit_price: Decimal = Field(gt=0, max_digits=16, decimal_places=2)


class BidIn(BaseModel):
    lead_days: int = Field(ge=0, le=365)
    freight: Decimal = Field(default=Decimal(0), ge=0)
    notes: str = Field(default="", max_length=1000)
    prices: list[BidPrice] = Field(min_length=1, max_length=300)


# ---------------------------------------------------------------- onboarding


@router.get("/onboarding")
@public
def onboarding_view(x_portal_token: str | None = Header(default=None)):
    tenant_id, case_id = portal.resolve(x_portal_token, "onboarding")
    with tenant_tx(tenant_id) as db:
        case = db.get(OnboardingCase, case_id)
        supplier = db.get(Supplier, case.supplier_id)
        return {"supplier": supplier.name, "status": case.status, "document_kinds": DOCUMENT_KINDS, "required_documents": ["gst_certificate", "cancelled_cheque"]}


@router.post("/onboarding")
@public
def onboarding_submit(data: OnboardingAnswers, x_portal_token: str | None = Header(default=None)):
    tenant_id, case_id = portal.resolve(x_portal_token, "onboarding")
    if not (data.declares_no_conflict_of_interest and data.accepts_code_of_conduct):
        raise HTTPException(422, "Both declarations are required to continue.")
    with tenant_tx(tenant_id) as db:
        case = db.scalar(select(OnboardingCase).where(OnboardingCase.id == case_id).with_for_update())
        if case.status not in ("invited", "submitted"):
            raise HTTPException(409, "This questionnaire has already been reviewed.")
        supplier = db.get(Supplier, case.supplier_id)
        answers = data.model_dump(mode="json")
        # Only the last four digits of the account are kept. Full numbers need a verified provider.
        answers["bank_last4"] = answers.pop("bank_account_number")[-4:]
        answers["gstin"], answers["pan"], answers["ifsc"] = data.gstin.upper(), data.pan.upper(), data.ifsc.upper()
        case.answers = answers
        case.checks = run_checks(db, supplier, answers)
        case.status, case.submitted_at = "submitted", datetime.now(timezone.utc)
        audit(db, portal.PortalActor(tenant_id), "onboarding_submitted", "supplier", supplier.id)
        return {"status": "submitted", "checks": case.checks}


@router.post("/onboarding/documents", status_code=201)
@public
async def onboarding_document(kind: str = Form(...), file: UploadFile = File(...), x_portal_token: str | None = Header(default=None)):
    tenant_id, case_id = portal.resolve(x_portal_token, "onboarding")
    if kind not in DOCUMENT_KINDS:
        raise HTTPException(422, "Unknown document type.")
    raw = await file.read(10 * 1024 * 1024 + 1)
    if len(raw) > 10 * 1024 * 1024:
        raise HTTPException(413, "Each document must be under 10 MB.")
    content_type = sniff_upload_type(raw)
    if content_type is None:
        raise HTTPException(422, "Upload a PDF, PNG or JPEG.")
    with tenant_tx(tenant_id) as db:
        case = db.get(OnboardingCase, case_id)
        if case.status not in ("invited", "submitted"):
            raise HTTPException(409, "This questionnaire has already been reviewed.")
        document = store_document(
            db, tenant_id, kind=kind, filename=file.filename or kind, content_type=content_type, data=raw,
            subject_type="onboarding", subject_id=case.id, uploaded_by="Supplier (portal)",
        )
        return {"id": str(document.id), "kind": kind}


# ---------------------------------------------------------------- RFQ


def _invite(db, invite_id: UUID) -> tuple[SourcingInvite, SourcingEvent, Supplier]:
    invite = db.get(SourcingInvite, invite_id)
    event = db.get(SourcingEvent, invite.event_id)
    return invite, event, db.get(Supplier, invite.supplier_id)


@router.get("/rfq")
@public
def rfq_view(x_portal_token: str | None = Header(default=None)):
    tenant_id, invite_id = portal.resolve(x_portal_token, "rfq")
    with tenant_tx(tenant_id) as db:
        invite, event, supplier = _invite(db, invite_id)
        lines = db.scalars(select(SourcingLine).where(SourcingLine.event_id == event.id).order_by(SourcingLine.line_no)).all()
        bid = db.scalar(select(Bid).where(Bid.event_id == event.id, Bid.supplier_id == supplier.id))
        # The budget and other suppliers' bids are never shown to a supplier.
        return {
            "supplier": supplier.name,
            "event": {"number": event.number, "title": event.title, "status": event.status, "due_at": event.due_at.isoformat()},
            "lines": [{"id": str(line.id), "line_no": line.line_no, "description": line.description, "hsn": line.hsn, "quantity": str(line.quantity), "unit": line.unit, "gst_rate": str(line.gst_rate)} for line in lines],
            "bid": out(bid) if bid else None,
        }


@router.post("/rfq/bid", status_code=201)
@public
def rfq_bid(data: BidIn, x_portal_token: str | None = Header(default=None)):
    tenant_id, invite_id = portal.resolve(x_portal_token, "rfq")
    with tenant_tx(tenant_id) as db:
        invite, event, supplier = _invite(db, invite_id)
        if event.status != "open" or event.due_at <= datetime.now(timezone.utc):
            raise HTTPException(409, "This request for quotation is closed.")
        if db.scalar(select(Bid.id).where(Bid.event_id == event.id, Bid.supplier_id == supplier.id)):
            raise HTTPException(409, "You've already submitted a bid for this request.")
        prices = {row.line_id: row.unit_price for row in data.prices}
        totals = price_bid(db, event, supplier, prices, data.freight)
        bid = Bid(
            tenant_id=tenant_id, event_id=event.id, supplier_id=supplier.id, lead_days=data.lead_days, freight=data.freight,
            subtotal=totals["subtotal"], tax=totals["tax"], total=totals["total"], notes=data.notes,
        )
        db.add(bid)
        db.flush()
        for line_id, price in prices.items():
            db.add(BidLine(tenant_id=tenant_id, bid_id=bid.id, sourcing_line_id=line_id, unit_price=price))
        invite.status = "bid_submitted"
        audit(db, portal.PortalActor(tenant_id), "bid_submitted", "sourcing_event", event.id, supplier=supplier.name, total=bid.total)
        db.flush()
        return {"id": str(bid.id), "subtotal": str(bid.subtotal), "tax": str(bid.tax), "total": str(bid.total)}


# ---------------------------------------------------------------- purchase orders


@router.get("/po")
@public
def po_view(x_portal_token: str | None = Header(default=None)):
    tenant_id, po_id = portal.resolve(x_portal_token, "po")
    with tenant_tx(tenant_id) as db:
        po = db.get(PurchaseOrder, po_id)
        lines = db.scalars(select(PoLine).where(PoLine.po_id == po.id).order_by(PoLine.line_no)).all()
        return {
            "number": po.number, "status": po.status, "total": str(po.total), "needed_by": po.needed_by.isoformat() if po.needed_by else None,
            "lines": [{"line_no": line.line_no, "description": line.description, "quantity": str(line.quantity), "unit": line.unit, "unit_price": str(line.unit_price), "received": str(line.qty_received)} for line in lines],
        }


@router.get("/po/pdf")
@public
def po_pdf(x_portal_token: str | None = Header(default=None)):
    tenant_id, po_id = portal.resolve(x_portal_token, "po")
    with tenant_tx(tenant_id) as db:
        po = db.get(PurchaseOrder, po_id)
        document = po_service.ensure_pdf(db, po, "Supplier (portal)")
        filename, content_type, data = document.filename, document.content_type, read_document(document)
    return file_response(data, filename, content_type)


@router.post("/po/invoices", status_code=201)
@public
async def po_invoice(file: UploadFile = File(...), x_portal_token: str | None = Header(default=None)):
    tenant_id, po_id = portal.resolve(x_portal_token, "po")
    raw = await file.read(invoice_service.MAX_UPLOAD + 1)
    with tenant_tx(tenant_id) as db:
        invoice = invoice_service.upload(db, portal.PortalActor(tenant_id), raw, file.filename or "invoice", po_id)
        return {"id": str(invoice.id), "status": invoice.status, "notice": "Received. The buyer's team will review it against the purchase order."}
