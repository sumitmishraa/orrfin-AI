"""Supplier records and onboarding review."""
import csv
import io
import re
from datetime import date, datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field
from rapidfuzz import fuzz
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from orrfin import portal, risk
from orrfin.api.deps import Ctx, audit, out, owned, require
from orrfin.documents.storage import file_response, read_document
from orrfin.gst import STATES, is_valid_gstin
from orrfin.models import Category, Contract, Document, OnboardingCase, RiskAssessment, RiskHold, Supplier

router = APIRouter(prefix="/api/suppliers", tags=["suppliers"])
IFSC = re.compile(r"^[A-Z]{4}0[A-Z0-9]{6}$")
PAN = re.compile(r"^[A-Z]{5}\d{4}[A-Z]$")


class SupplierIn(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    email: str = Field(default="", max_length=255)
    phone: str = Field(default="", max_length=40)
    gstin: str = Field(default="", max_length=15)
    address: str = Field(default="", max_length=400)
    category_id: UUID | None = None


class SupplierPatch(BaseModel):
    preferred: bool | None = None
    payment_terms_days: int | None = Field(default=None, ge=0, le=365)
    email: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=40)
    status: str | None = Field(default=None, pattern="^(suspended|approved)$")


class DecisionIn(BaseModel):
    note: str = Field(default="", max_length=1000)


def run_checks(db: Session, supplier: Supplier, answers: dict) -> dict:
    gstin = (answers.get("gstin") or "").upper()
    pan = (answers.get("pan") or "").upper()
    checks: dict = {}
    if not gstin:
        checks["gstin"] = {"status": "fail", "detail": "No GSTIN given."}
    elif is_valid_gstin(gstin):
        checks["gstin"] = {"status": "pass", "detail": f"Format and checksum valid. State: {STATES[gstin[:2]]}."}
    else:
        checks["gstin"] = {"status": "fail", "detail": "Format or checksum is invalid."}
    if pan and gstin:
        checks["pan_matches_gstin"] = (
            {"status": "pass", "detail": "PAN matches characters 3 to 12 of the GSTIN."}
            if PAN.match(pan) and gstin[2:12] == pan
            else {"status": "fail", "detail": "PAN doesn't match the PAN inside the GSTIN."}
        )
    ifsc = (answers.get("ifsc") or "").upper()
    checks["ifsc_format"] = {"status": "pass" if IFSC.match(ifsc) else "fail", "detail": "IFSC format check only." if ifsc else "No IFSC given."}

    others = db.scalars(select(Supplier).where(Supplier.id != supplier.id)).all()
    duplicates = [
        row.name
        for row in others
        if (gstin and row.gstin == gstin)
        or (pan and row.pan == pan)
        or fuzz.token_set_ratio(row.name.lower(), (answers.get("legal_name") or supplier.name).lower()) >= 92
    ]
    checks["duplicates"] = (
        {"status": "warn", "detail": "Possible duplicate of: " + ", ".join(duplicates[:5])} if duplicates else {"status": "pass", "detail": "No similar supplier found."}
    )
    for name in ("sanctions_screening", "bank_verification", "gstn_registration"):
        checks[name] = {"status": "not_performed", "detail": "Needs a connected data provider."}
    return checks


def detail_json(db: Session, supplier: Supplier) -> dict:
    cases = db.scalars(select(OnboardingCase).where(OnboardingCase.supplier_id == supplier.id).order_by(OnboardingCase.created_at.desc())).all()
    assessment = db.scalar(select(RiskAssessment).where(RiskAssessment.supplier_id == supplier.id).order_by(RiskAssessment.created_at.desc()))
    holds = db.scalars(select(RiskHold).where(RiskHold.supplier_id == supplier.id).order_by(RiskHold.created_at.desc())).all()
    documents = (
        db.scalars(select(Document).where(Document.subject_type == "onboarding", Document.subject_id.in_([case.id for case in cases]))).all()
        if cases
        else []
    )
    contracts = db.scalars(select(Contract).where(Contract.supplier_id == supplier.id)).all()
    return out(
        supplier,
        performance=risk.performance(db, supplier.id),
        risk=out(assessment) if assessment else None,
        holds=[out(row) for row in holds],
        onboarding=[out(case) for case in cases],
        documents=[out(row, exclude=("storage_key",)) for row in documents],
        contracts=[out(row) for row in contracts],
    )


@router.get("")
def list_suppliers(q: str = "", status: str | None = None, category_id: UUID | None = None, limit: int = 100, offset: int = 0, ctx: Ctx = Depends(require("suppliers.read"))):
    with ctx.tx() as db:
        query = select(Supplier)
        if q:
            pattern = "%" + q.replace("%", r"\%").replace("_", r"\_") + "%"
            query = query.where(Supplier.name.ilike(pattern) | Supplier.gstin.ilike(pattern))
        if status:
            query = query.where(Supplier.status == status)
        if category_id:
            query = query.where(Supplier.category_id == category_id)
        total = db.scalar(select(func.count()).select_from(query.subquery()))
        categories = {row.id: row.name for row in db.scalars(select(Category))}
        rows = db.scalars(query.order_by(Supplier.preferred.desc(), Supplier.name).limit(min(limit, 500)).offset(max(offset, 0))).all()
        return {"total": total, "items": [out(row, category=categories.get(row.category_id)) for row in rows]}


@router.post("", status_code=201)
def create_supplier(data: SupplierIn, ctx: Ctx = Depends(require("suppliers.write"))):
    gstin = data.gstin.strip().upper()
    if gstin and not is_valid_gstin(gstin):
        raise HTTPException(422, "That GSTIN isn't valid. Leave it blank and the supplier can enter it during onboarding.")
    with ctx.tx() as db:
        if data.category_id:
            owned(db, Category, data.category_id)
        row = Supplier(
            tenant_id=ctx.tenant_id, name=data.name.strip(), email=data.email, phone=data.phone, gstin=gstin,
            state_code=gstin[:2], pan=gstin[2:12] if gstin else "", address=data.address, category_id=data.category_id, status="draft",
        )
        db.add(row)
        db.flush()
        audit(db, ctx, "supplier_added", "supplier", row.id, name=row.name)
        return out(row)


@router.post("/import", status_code=201)
async def import_suppliers(file: UploadFile = File(...), ctx: Ctx = Depends(require("suppliers.write"))):
    raw = await file.read(1024 * 1024 + 1)
    if len(raw) > 1024 * 1024:
        raise HTTPException(413, "The CSV must be under 1 MB.")
    try:
        rows = list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))))
    except (UnicodeError, csv.Error) as error:
        raise HTTPException(422, "Upload a UTF-8 CSV file.") from error
    if not 1 <= len(rows) <= 2000:
        raise HTTPException(422, "The CSV must have between 1 and 2,000 rows.")
    with ctx.tx() as db:
        categories = {row.name.lower(): row.id for row in db.scalars(select(Category))}
        for number, row in enumerate(rows, start=2):
            name = (row.get("name") or "").strip()
            gstin = (row.get("gstin") or "").strip().upper()
            if not name:
                raise HTTPException(422, f"Row {number}: name is required.")
            if gstin and not is_valid_gstin(gstin):
                raise HTTPException(422, f"Row {number}: GSTIN {gstin} isn't valid.")
            db.add(
                Supplier(
                    tenant_id=ctx.tenant_id, name=name[:200], email=(row.get("email") or "")[:255], phone=(row.get("phone") or "")[:40],
                    gstin=gstin, state_code=gstin[:2], pan=gstin[2:12] if gstin else "",
                    category_id=categories.get((row.get("category") or "").strip().lower()), status="draft",
                )
            )
        db.flush()
        audit(db, ctx, "suppliers_imported", "tenant", ctx.tenant_id, count=len(rows))
    return {"imported": len(rows), "notice": "Imported suppliers stay in draft until onboarding is approved."}


@router.get("/{supplier_id}")
def get_supplier(supplier_id: UUID, ctx: Ctx = Depends(require("suppliers.read"))):
    with ctx.tx() as db:
        return detail_json(db, owned(db, Supplier, supplier_id))


@router.patch("/{supplier_id}")
def update_supplier(supplier_id: UUID, data: SupplierPatch, ctx: Ctx = Depends(require("suppliers.write"))):
    with ctx.tx() as db:
        supplier = owned(db, Supplier, supplier_id)
        changes = data.model_dump(exclude_none=True)
        if changes.get("status") == "approved" and supplier.status != "suspended":
            raise HTTPException(409, "Approve a new supplier through onboarding review.")
        for key, value in changes.items():
            setattr(supplier, key, value)
        audit(db, ctx, "supplier_updated", "supplier", supplier.id, **changes)
        db.flush()
        return out(supplier)


@router.post("/{supplier_id}/onboarding", status_code=201)
def invite_to_onboarding(supplier_id: UUID, ctx: Ctx = Depends(require("suppliers.write"))):
    with ctx.tx() as db:
        supplier = owned(db, Supplier, supplier_id)
        if supplier.status == "approved":
            raise HTTPException(409, "This supplier is already approved.")
        case = OnboardingCase(tenant_id=ctx.tenant_id, supplier_id=supplier.id, status="invited")
        db.add(case)
        supplier.status = "onboarding"
        db.flush()
        audit(db, ctx, "onboarding_invited", "supplier", supplier.id)
        case_id = case.id
    token = portal.issue(ctx.tenant_id, "onboarding", case_id, days=14)
    return {"case_id": str(case_id), "url": portal.link("onboarding", token), "notice": "Share this link with the supplier. It expires in 14 days."}


def _decide(case_id: UUID, approve: bool, note: str, ctx: Ctx):
    with ctx.tx() as db:
        case = db.scalar(select(OnboardingCase).where(OnboardingCase.id == case_id).with_for_update())
        if case is None:
            raise HTTPException(404, "Record not found.")
        if case.status != "submitted":
            raise HTTPException(409, "Only a submitted questionnaire can be reviewed.")
        supplier = db.get(Supplier, case.supplier_id)
        if approve:
            failed = [name for name, check in case.checks.items() if check.get("status") == "fail"]
            if "gstin" in failed:
                raise HTTPException(409, "The GSTIN failed validation. Ask the supplier to correct it first.")
            answers = case.answers
            supplier.name = answers.get("legal_name") or supplier.name
            supplier.gstin = answers["gstin"].upper()
            supplier.state_code = supplier.gstin[:2]
            supplier.pan = (answers.get("pan") or supplier.gstin[2:12]).upper()
            supplier.address = answers.get("address") or supplier.address
            supplier.email = answers.get("contact_email") or supplier.email
            supplier.phone = answers.get("phone") or supplier.phone
            supplier.status = "approved"
        else:
            supplier.status = "draft"
        case.status = "approved" if approve else "rejected"
        case.decided_by, case.decided_at, case.decision_note = ctx.user_id, datetime.now(timezone.utc), note
        db.flush()
        if approve:
            risk.assess(db, ctx, supplier)
        audit(db, ctx, "onboarding_approved" if approve else "onboarding_rejected", "supplier", supplier.id, note=note)
        result = detail_json(db, supplier)
    portal.revoke(case_id, "onboarding")
    return result


@router.post("/onboarding/{case_id}/approve")
def approve_onboarding(case_id: UUID, data: DecisionIn, ctx: Ctx = Depends(require("suppliers.write"))):
    return _decide(case_id, True, data.note, ctx)


@router.post("/onboarding/{case_id}/reject")
def reject_onboarding(case_id: UUID, data: DecisionIn, ctx: Ctx = Depends(require("suppliers.write"))):
    if not data.note.strip():
        raise HTTPException(422, "Add a reason for the supplier.")
    return _decide(case_id, False, data.note, ctx)


@router.get("/documents/{document_id}")
def download_document(document_id: UUID, ctx: Ctx = Depends(require("suppliers.read"))):
    with ctx.tx() as db:
        document = owned(db, Document, document_id)
        if document.subject_type != "onboarding":
            raise HTTPException(404, "Record not found.")
        filename, content_type, data = document.filename, document.content_type, read_document(document)
    return file_response(data, filename, content_type)


__all__ = ["router", "run_checks", "date"]
