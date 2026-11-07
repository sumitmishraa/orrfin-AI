"""AI Contract Orchestration: generate from templates, upload, version, redline, review, approve, renew."""
import io
from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from orrfin import ai
from orrfin import contracts as library
from orrfin.api.deps import Ctx, audit, out, owned, require
from orrfin.documents.storage import file_response, sniff_upload_type, store_document
from orrfin.gst import fiscal_year
from orrfin.models import Clause, Contract, ContractTemplate, ContractVersion, LegalEntity, Obligation, Supplier, Tenant
from orrfin.numbering import next_number
from orrfin.policy import policy_for

router = APIRouter(prefix="/api/contracts", tags=["contracts"])

SUMMARY_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "key_risks": {"type": "array", "items": {"type": "string"}},
        "suggested_changes": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["summary", "key_risks", "suggested_changes"],
    "additionalProperties": False,
}


class ContractIn(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    supplier_id: UUID
    template_id: UUID
    start_on: date
    end_on: date
    value: Decimal = Field(default=Decimal(0), ge=0)
    auto_renew: bool = False
    notice_days: int = Field(default=30, ge=0, le=365)
    liability_cap: str = Field(default="the fees paid in the twelve months before the claim", max_length=200)
    governing_city: str = Field(default="Bengaluru", max_length=60)


class VersionIn(BaseModel):
    body: str = Field(min_length=20, max_length=200_000)


class StatusIn(BaseModel):
    status: str = Field(pattern="^(review|approved|signed|terminated)$")
    signature_status: str | None = Field(default=None, pattern="^(not_sent|sent|signed_by_supplier|fully_signed)$")


def _review(db: Session, text: str) -> dict:
    result = library.review(db, text)
    if ai.configured() and ai.consent(db):
        summary = ai.structured(
            db,
            "You review procurement contracts for an Indian buyer. Summarise the commercial and legal risks "
            "plainly for a procurement manager. Do not give legal advice and do not invent clauses.",
            text[:150_000],
            SUMMARY_SCHEMA,
        )
        if summary:
            result["ai_summary"] = summary
            result["source"] = "rules+llm"
    return result


def _add_version(db: Session, ctx, contract: Contract, body: str, source: str, document_id=None) -> ContractVersion:
    previous = db.scalar(select(ContractVersion).where(ContractVersion.contract_id == contract.id).order_by(ContractVersion.version.desc()))
    version = ContractVersion(
        tenant_id=contract.tenant_id,
        contract_id=contract.id,
        version=(previous.version + 1) if previous else 1,
        body=body,
        source=source,
        document_id=document_id,
        created_by=ctx.user_name,
        review=_review(db, body),
    )
    db.add(version)
    contract.current_version = version.version
    if contract.status in ("approved", "signed"):
        contract.status = "review"
    db.flush()
    return version


def create_contract(db: Session, ctx, data: ContractIn) -> Contract:
    if data.end_on <= data.start_on:
        raise HTTPException(422, "The end date must be after the start date.")
    library.ensure_library(db, ctx.tenant_id)
    supplier = owned(db, Supplier, data.supplier_id)
    template = owned(db, ContractTemplate, data.template_id)
    tenant = db.get(Tenant, ctx.tenant_id)
    entity = db.scalar(select(LegalEntity).order_by(LegalEntity.created_at))
    contract = Contract(
        tenant_id=ctx.tenant_id,
        number=next_number(db, ctx.tenant_id, "CTR", "HQ", fiscal_year(data.start_on)),
        title=data.title,
        supplier_id=supplier.id,
        template_id=template.id,
        status="draft",
        start_on=data.start_on,
        end_on=data.end_on,
        auto_renew=data.auto_renew,
        notice_days=data.notice_days,
        value=data.value,
        owner_id=ctx.user_id,
    )
    db.add(contract)
    db.flush()
    body = library.render_text(
        db,
        template,
        data.title,
        {
            "buyer_name": entity.name if entity else tenant.name,
            "supplier_name": supplier.name,
            "start_on": data.start_on.strftime("%d %B %Y"),
            "end_on": data.end_on.strftime("%d %B %Y"),
            "payment_terms_days": supplier.payment_terms_days,
            "notice_days": data.notice_days,
            "liability_cap": data.liability_cap,
            "governing_city": data.governing_city,
        },
    )
    _add_version(db, ctx, contract, body, "generated")
    for title, due, role in library.obligations(data.start_on, data.end_on, data.notice_days, data.auto_renew):
        db.add(Obligation(tenant_id=ctx.tenant_id, contract_id=contract.id, title=title, due_on=due, owner_role=role))
    audit(db, ctx, "contract_generated", "contract", contract.id, template=template.name)
    db.flush()
    return contract


@router.get("/library")
def clause_library(ctx: Ctx = Depends(require("contracts.read"))):
    with ctx.tx() as db:
        library.ensure_library(db, ctx.tenant_id)
        return {
            "clauses": [out(row) for row in db.scalars(select(Clause).order_by(Clause.key))],
            "templates": [out(row) for row in db.scalars(select(ContractTemplate).order_by(ContractTemplate.name))],
        }


@router.get("")
def list_contracts(status: str | None = None, ctx: Ctx = Depends(require("contracts.read"))):
    with ctx.tx() as db:
        query = select(Contract, Supplier.name).join(Supplier, Supplier.id == Contract.supplier_id).order_by(Contract.end_on)
        if status:
            query = query.where(Contract.status == status)
        today = datetime.now(timezone.utc).date()
        return [out(row, supplier=name, days_to_expiry=(row.end_on - today).days) for row, name in db.execute(query.limit(500))]


@router.post("", status_code=201)
def generate(data: ContractIn, ctx: Ctx = Depends(require("contracts.write"))):
    with ctx.tx() as db:
        return out(create_contract(db, ctx, data))


@router.get("/{contract_id}")
def get_contract(contract_id: UUID, ctx: Ctx = Depends(require("contracts.read"))):
    with ctx.tx() as db:
        contract = owned(db, Contract, contract_id)
        versions = db.scalars(select(ContractVersion).where(ContractVersion.contract_id == contract.id).order_by(ContractVersion.version.desc())).all()
        obligations = db.scalars(select(Obligation).where(Obligation.contract_id == contract.id).order_by(Obligation.due_on)).all()
        supplier = db.get(Supplier, contract.supplier_id)
        return out(contract, supplier=supplier.name, versions=[out(row) for row in versions], obligations=[out(row) for row in obligations], ai=ai.status(db))


@router.post("/{contract_id}/versions", status_code=201)
def edit(contract_id: UUID, data: VersionIn, ctx: Ctx = Depends(require("contracts.write"))):
    with ctx.tx() as db:
        contract = owned(db, Contract, contract_id)
        version = _add_version(db, ctx, contract, data.body, "edited")
        audit(db, ctx, "contract_version_added", "contract", contract.id, version=version.version)
        return out(version)


@router.post("/{contract_id}/upload", status_code=201)
async def upload(contract_id: UUID, file: UploadFile = File(...), ctx: Ctx = Depends(require("contracts.write"))):
    """Upload the counterparty's paper. Text is extracted and reviewed like any other version."""
    raw = await file.read(25 * 1024 * 1024 + 1)
    if len(raw) > 25 * 1024 * 1024:
        raise HTTPException(413, "The file must be under 25 MB.")
    if sniff_upload_type(raw) != "application/pdf":
        raise HTTPException(422, "Upload the contract as a PDF.")
    import pdfplumber

    from orrfin.p2p.extraction import _is_hidden

    try:
        with pdfplumber.open(io.BytesIO(raw)) as pdf:
            if len(pdf.pages) > 200:
                raise HTTPException(422, "Contracts over 200 pages aren't supported.")
            text = "\n".join((page.filter(lambda obj: not _is_hidden(obj)).extract_text() or "") for page in pdf.pages)
    except HTTPException:
        raise
    except Exception as error:
        raise HTTPException(422, "This PDF couldn't be read.") from error
    if len(text.strip()) < 50:
        raise HTTPException(422, "No text layer was found. Upload a text-based PDF.")
    with ctx.tx() as db:
        contract = owned(db, Contract, contract_id)
        document = store_document(
            db, ctx.tenant_id, kind="contract", filename=file.filename or "contract.pdf", content_type="application/pdf", data=raw,
            subject_type="contract", subject_id=contract.id, uploaded_by=ctx.user_name,
        )
        version = _add_version(db, ctx, contract, text, "uploaded", document.id)
        audit(db, ctx, "contract_uploaded", "contract", contract.id, version=version.version)
        return out(version)


@router.get("/{contract_id}/redline")
def compare(contract_id: UUID, from_version: int, to_version: int, ctx: Ctx = Depends(require("contracts.read"))):
    with ctx.tx() as db:
        owned(db, Contract, contract_id)
        rows = {
            row.version: row.body
            for row in db.scalars(select(ContractVersion).where(ContractVersion.contract_id == contract_id, ContractVersion.version.in_((from_version, to_version))))
        }
        if from_version not in rows or to_version not in rows:
            raise HTTPException(404, "Version not found.")
        return {"from": from_version, "to": to_version, "changes": library.redline(rows[from_version], rows[to_version])}


@router.get("/{contract_id}/versions/{version}/{fmt}")
def download(contract_id: UUID, version: int, fmt: str, ctx: Ctx = Depends(require("contracts.read"))):
    if fmt not in ("docx", "pdf"):
        raise HTTPException(404, "Record not found.")
    with ctx.tx() as db:
        contract = owned(db, Contract, contract_id)
        row = db.scalar(select(ContractVersion).where(ContractVersion.contract_id == contract.id, ContractVersion.version == version))
        if row is None:
            raise HTTPException(404, "Version not found.")
        fictional = policy_for(db, ctx.tenant_id).fictional
        title, body, number = contract.title, row.body, contract.number
    name = f"{number.replace('/', '-')}-v{version}.{fmt}"
    if fmt == "docx":
        return file_response(library.render_docx(title, body, fictional), name, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    return file_response(library.render_pdf(title, body, fictional), name, "application/pdf")


@router.post("/{contract_id}/status")
def set_status(contract_id: UUID, data: StatusIn, ctx: Ctx = Depends(require("contracts.write"))):
    with ctx.tx() as db:
        contract = owned(db, Contract, contract_id)
        if data.status in ("approved", "signed") and ctx.role not in ("legal", "admin"):
            raise HTTPException(403, "Only legal can approve or sign off a contract.")
        latest = db.scalar(select(ContractVersion).where(ContractVersion.contract_id == contract.id, ContractVersion.version == contract.current_version))
        if data.status == "approved" and latest and latest.review.get("summary", {}).get("high", 0) and not latest.review.get("acknowledged"):
            latest.review = {**latest.review, "acknowledged": ctx.user_name}
        contract.status = data.status
        if data.signature_status:
            contract.signature_status = data.signature_status
        audit(db, ctx, f"contract_{data.status}", "contract", contract.id, signature=data.signature_status)
        db.flush()
        return out(contract)
