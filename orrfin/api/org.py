"""Organization structure and master data: legal entities, branches, sites, categories, items, budgets."""
import csv
import io
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from orrfin.api.deps import Ctx, audit, out, owned, require
from orrfin.gst import STATES, fiscal_year, is_valid_gstin
from orrfin.models import ApprovalRule, AuditLog, Branch, Budget, Category, Item, LegalEntity, Location
from orrfin.security import ROLES

router = APIRouter(prefix="/api/org", tags=["organization"])


class LegalEntityIn(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    gstin: str = Field(min_length=15, max_length=15)
    pan: str = Field(default="", max_length=10)
    address: str = Field(default="", max_length=400)


class BranchIn(BaseModel):
    code: str = Field(min_length=2, max_length=20, pattern=r"^[A-Za-z0-9-]+$")
    name: str = Field(min_length=2, max_length=120)
    city: str = Field(min_length=2, max_length=80)
    legal_entity_id: UUID
    erp_location_id: str = Field(default="", max_length=80)


class LocationIn(BaseModel):
    branch_id: UUID
    code: str = Field(min_length=2, max_length=30, pattern=r"^[A-Za-z0-9-]+$")
    name: str = Field(min_length=2, max_length=160)
    kind: str = Field(default="dark_store", pattern="^(dark_store|warehouse|office|kitchen)$")
    address: str = Field(default="", max_length=400)


class CategoryIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    default_hsn: str = Field(default="", max_length=12)
    default_gst_rate: Decimal = Field(default=Decimal("18"), ge=0, le=40)


class ItemIn(BaseModel):
    sku: str = Field(min_length=1, max_length=60)
    name: str = Field(min_length=2, max_length=200)
    category_id: UUID
    hsn: str = Field(default="", max_length=12)
    unit: str = Field(default="NOS", max_length=20)
    gst_rate: Decimal = Field(default=Decimal("18"), ge=0, le=40)
    benchmark_price: Decimal | None = Field(default=None, ge=0)


class BudgetIn(BaseModel):
    branch_id: UUID
    category_id: UUID
    fiscal_year: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}$")
    amount: Decimal = Field(ge=0, max_digits=16, decimal_places=2)


class RuleIn(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    branch_id: UUID | None = None
    category_id: UUID | None = None
    risk_tier: str | None = Field(default=None, pattern="^(low|medium|high|critical)$")
    min_amount: Decimal = Field(default=Decimal(0), ge=0)
    max_amount: Decimal | None = Field(default=None, ge=0)
    step: int = Field(default=1, ge=1, le=10)
    approver_role: str
    sla_hours: int = Field(default=48, ge=1, le=720)


@router.get("/overview")
def overview(ctx: Ctx = Depends(require("org.read"))):
    with ctx.tx() as db:
        counts = dict(
            db.execute(select(Location.branch_id, func.count()).group_by(Location.branch_id)).tuples().all()
        )
        entities = {row.id: row for row in db.scalars(select(LegalEntity))}
        branches = db.scalars(select(Branch).order_by(Branch.code)).all()
        return {
            "legal_entities": [out(row) for row in entities.values()],
            "branches": [
                out(
                    row,
                    locations=counts.get(row.id, 0),
                    legal_entity=entities[row.legal_entity_id].name,
                    gstin=entities[row.legal_entity_id].gstin,
                    state=entities[row.legal_entity_id].state_name,
                )
                for row in branches
                if ctx.can_access_branch(row.id)
            ],
        }


@router.post("/legal-entities", status_code=201)
def create_legal_entity(data: LegalEntityIn, ctx: Ctx = Depends(require("org.write"))):
    gstin = data.gstin.strip().upper()
    if not is_valid_gstin(gstin):
        raise HTTPException(422, "That GSTIN isn't valid. Check its format and last character.")
    with ctx.tx() as db:
        row = LegalEntity(
            tenant_id=ctx.tenant_id,
            name=data.name.strip(),
            gstin=gstin,
            pan=(data.pan or gstin[2:12]).upper(),
            state_code=gstin[:2],
            state_name=STATES[gstin[:2]],
            address=data.address,
        )
        db.add(row)
        db.flush()
        audit(db, ctx, "legal_entity_added", "legal_entity", row.id, gstin=gstin)
        return out(row)


@router.post("/branches", status_code=201)
def create_branch(data: BranchIn, ctx: Ctx = Depends(require("org.write"))):
    with ctx.tx() as db:
        owned(db, LegalEntity, data.legal_entity_id)
        row = Branch(tenant_id=ctx.tenant_id, **data.model_dump() | {"code": data.code.upper()})
        db.add(row)
        db.flush()
        audit(db, ctx, "branch_added", "branch", row.id, code=row.code)
        return out(row)


@router.post("/branches/import", status_code=201)
async def import_branches(file: UploadFile = File(...), ctx: Ctx = Depends(require("org.write"))):
    """All-or-nothing CSV import with columns code, name, city, gstin."""
    raw = await file.read(512 * 1024 + 1)
    if len(raw) > 512 * 1024:
        raise HTTPException(413, "The CSV must be under 512 KB.")
    try:
        reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
        rows = list(reader)
    except (UnicodeError, csv.Error) as error:
        raise HTTPException(422, "Upload a UTF-8 CSV file.") from error
    if not reader.fieldnames or not {"code", "name", "city", "gstin"} <= set(reader.fieldnames):
        raise HTTPException(422, "The CSV needs the columns code, name, city and gstin.")
    if not 1 <= len(rows) <= 1000:
        raise HTTPException(422, "The CSV must have between 1 and 1,000 rows.")
    with ctx.tx() as db:
        entities = {row.gstin: row.id for row in db.scalars(select(LegalEntity))}
        for number, row in enumerate(rows, start=2):
            entity_id = entities.get((row.get("gstin") or "").strip().upper())
            code = (row.get("code") or "").strip().upper()
            if not entity_id:
                raise HTTPException(422, f"Row {number}: add a legal entity with that GSTIN first.")
            if not code or not row.get("name") or not row.get("city"):
                raise HTTPException(422, f"Row {number}: code, name and city are required.")
            db.add(Branch(tenant_id=ctx.tenant_id, code=code, name=row["name"].strip(), city=row["city"].strip(), legal_entity_id=entity_id))
        db.flush()
        audit(db, ctx, "branches_imported", "tenant", ctx.tenant_id, count=len(rows))
    return {"imported": len(rows)}


@router.get("/locations")
def list_locations(branch_id: UUID | None = None, ctx: Ctx = Depends(require("org.read"))):
    with ctx.tx() as db:
        query = select(Location).order_by(Location.code)
        if branch_id:
            query = query.where(Location.branch_id == branch_id)
        return [out(row) for row in db.scalars(query) if ctx.can_access_branch(row.branch_id)]


@router.post("/locations", status_code=201)
def create_location(data: LocationIn, ctx: Ctx = Depends(require("org.write"))):
    with ctx.tx() as db:
        owned(db, Branch, data.branch_id)
        row = Location(tenant_id=ctx.tenant_id, **data.model_dump() | {"code": data.code.upper()})
        db.add(row)
        db.flush()
        return out(row)


@router.get("/categories")
def list_categories(ctx: Ctx = Depends(require("org.read"))):
    with ctx.tx() as db:
        return [out(row) for row in db.scalars(select(Category).order_by(Category.name))]


@router.post("/categories", status_code=201)
def create_category(data: CategoryIn, ctx: Ctx = Depends(require("org.write"))):
    with ctx.tx() as db:
        row = Category(tenant_id=ctx.tenant_id, **data.model_dump())
        db.add(row)
        db.flush()
        return out(row)


@router.get("/items")
def list_items(q: str = "", category_id: UUID | None = None, limit: int = 50, ctx: Ctx = Depends(require("org.read"))):
    with ctx.tx() as db:
        query = select(Item).order_by(Item.name).limit(min(limit, 200))
        if q:
            pattern = "%" + q.replace("%", r"\%").replace("_", r"\_") + "%"
            query = query.where(Item.name.ilike(pattern) | Item.sku.ilike(pattern))
        if category_id:
            query = query.where(Item.category_id == category_id)
        return [out(row) for row in db.scalars(query)]


@router.post("/items", status_code=201)
def create_item(data: ItemIn, ctx: Ctx = Depends(require("org.write"))):
    with ctx.tx() as db:
        owned(db, Category, data.category_id)
        row = Item(tenant_id=ctx.tenant_id, **data.model_dump())
        db.add(row)
        db.flush()
        return out(row)


@router.get("/budgets")
def list_budgets(fy: str | None = None, ctx: Ctx = Depends(require("org.read"))):
    with ctx.tx() as db:
        query = select(Budget).where(Budget.fiscal_year == (fy or fiscal_year()))
        return [out(row) for row in db.scalars(query) if ctx.can_access_branch(row.branch_id)]


@router.post("/budgets", status_code=201)
def set_budget(data: BudgetIn, ctx: Ctx = Depends(require("org.write"))):
    year = data.fiscal_year or fiscal_year()
    with ctx.tx() as db:
        owned(db, Branch, data.branch_id)
        owned(db, Category, data.category_id)
        row = db.scalar(
            select(Budget).where(
                Budget.branch_id == data.branch_id, Budget.category_id == data.category_id, Budget.fiscal_year == year
            )
        )
        if row:
            row.amount = data.amount
        else:
            row = Budget(tenant_id=ctx.tenant_id, branch_id=data.branch_id, category_id=data.category_id, fiscal_year=year, amount=data.amount)
            db.add(row)
        db.flush()
        audit(db, ctx, "budget_set", "budget", row.id, amount=data.amount, fiscal_year=year)
        return out(row)


@router.get("/approval-rules")
def list_rules(ctx: Ctx = Depends(require("org.read"))):
    with ctx.tx() as db:
        return [out(row) for row in db.scalars(select(ApprovalRule).order_by(ApprovalRule.step, ApprovalRule.min_amount))]


@router.post("/approval-rules", status_code=201)
def create_rule(data: RuleIn, ctx: Ctx = Depends(require("org.write"))):
    if data.approver_role not in ROLES:
        raise HTTPException(422, "Unknown approver role.")
    if data.max_amount is not None and data.max_amount < data.min_amount:
        raise HTTPException(422, "The maximum must not be below the minimum.")
    with ctx.tx() as db:
        row = ApprovalRule(tenant_id=ctx.tenant_id, **data.model_dump())
        db.add(row)
        db.flush()
        audit(db, ctx, "approval_rule_added", "approval_rule", row.id, name=row.name)
        return out(row)


@router.get("/audit")
def audit_trail(subject_id: UUID | None = None, limit: int = 100, ctx: Ctx = Depends(require("audit.read"))):
    with ctx.tx() as db:
        query = select(AuditLog).order_by(AuditLog.created_at.desc()).limit(min(limit, 500))
        if subject_id:
            query = query.where(AuditLog.subject_id == subject_id)
        return [out(row) for row in db.scalars(query)]
