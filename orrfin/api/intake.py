"""Intake-to-Procure: the front door for every purchase request."""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from orrfin import approvals
from orrfin.api.deps import Ctx, audit, out, owned, require
from orrfin.gst import fiscal_year, money, quantity
from orrfin.models import (
    ApprovalInstance,
    ApprovalTask,
    Branch,
    Budget,
    Category,
    Contract,
    Intake,
    IntakeLine,
    Item,
    Location,
    PurchaseOrder,
    Supplier,
)
from orrfin.numbering import next_number
from orrfin.p2p import po as po_service
from orrfin.policy import policy_for

router = APIRouter(prefix="/api/intakes", tags=["intake"])


class LineIn(BaseModel):
    item_id: UUID | None = None
    description: str = Field(default="", max_length=300)
    hsn: str = Field(default="", max_length=12)
    quantity: Decimal = Field(gt=0, max_digits=15, decimal_places=3)
    unit: str = Field(default="NOS", max_length=20)
    estimated_price: Decimal = Field(ge=0, max_digits=16, decimal_places=2)
    gst_rate: Decimal | None = Field(default=None, ge=0, le=40)


class IntakeIn(BaseModel):
    branch_id: UUID
    location_id: UUID | None = None
    category_id: UUID
    title: str = Field(min_length=3, max_length=200)
    justification: str = Field(default="", max_length=2000)
    needed_by: date
    route: str = Field(default="sourcing", pattern="^(sourcing|direct)$")
    preferred_supplier_id: UUID | None = None
    lines: list[LineIn] = Field(min_length=1, max_length=100)


class CreatePoIn(BaseModel):
    supplier_id: UUID | None = None
    freight: Decimal = Field(default=Decimal(0), ge=0)
    prices: dict[UUID, Decimal] = {}


def build_lines(db: Session, tenant_id: UUID, intake_id: UUID, lines: list[LineIn], category: Category) -> tuple[list[IntakeLine], Decimal]:
    rows, total = [], Decimal(0)
    for number, line in enumerate(lines, start=1):
        item = owned(db, Item, line.item_id) if line.item_id else None
        description = line.description.strip() or (item.name if item else "")
        if not description:
            raise HTTPException(422, f"Line {number}: choose an item or enter a description.")
        rate = line.gst_rate if line.gst_rate is not None else (item.gst_rate if item else category.default_gst_rate)
        rows.append(
            IntakeLine(
                tenant_id=tenant_id,
                intake_id=intake_id,
                line_no=number,
                item_id=line.item_id,
                description=description,
                hsn=line.hsn or (item.hsn if item else category.default_hsn),
                quantity=quantity(line.quantity),
                unit=line.unit if line.unit != "NOS" or not item else item.unit,
                estimated_price=money(line.estimated_price),
                gst_rate=rate,
            )
        )
        total += money(line.quantity * line.estimated_price * (1 + rate / 100))
    return rows, money(total)


def check_budget(db: Session, branch_id: UUID, category_id: UUID, amount: Decimal, when: date | None = None) -> dict:
    year = fiscal_year(when or datetime.now(timezone.utc))
    budget = db.scalar(
        select(Budget).where(Budget.branch_id == branch_id, Budget.category_id == category_id, Budget.fiscal_year == year)
    )
    if budget is None:
        return {"status": "no_budget", "fiscal_year": year, "message": f"No {year} budget is set for this branch and category."}
    remaining = budget.amount - budget.committed
    return {
        "status": "within" if amount <= remaining else "over",
        "fiscal_year": year,
        "budget": str(budget.amount),
        "committed": str(budget.committed),
        "remaining": str(remaining),
        "message": (
            f"Within budget. {remaining - amount:.2f} remains after this request."
            if amount <= remaining
            else f"Over budget by {amount - remaining:.2f}, so finance approval is added."
        ),
    }


def suggestions(db: Session, category_id: UUID, lines: list[IntakeLine]) -> dict:
    preferred = db.scalars(
        select(Supplier)
        .where(Supplier.category_id == category_id, Supplier.status == "approved")
        .order_by(Supplier.preferred.desc(), Supplier.risk_score.asc().nulls_last(), Supplier.name)
        .limit(5)
    ).all()
    today = datetime.now(timezone.utc).date()
    active = (
        db.scalars(
            select(Contract).where(
                Contract.supplier_id.in_([row.id for row in preferred]),
                Contract.status.in_(("approved", "signed")),
                Contract.end_on >= today,
            )
        ).all()
        if preferred
        else []
    )
    contract_by_supplier = {row.supplier_id: row for row in active}
    price_flags = []
    for line in lines:
        item = db.get(Item, line.item_id) if line.item_id else None
        if item and item.benchmark_price and line.estimated_price > item.benchmark_price * Decimal("1.10"):
            price_flags.append(
                {
                    "line_no": line.line_no,
                    "message": f"{line.description}: estimate {line.estimated_price} is over 10% above the benchmark {item.benchmark_price}.",
                }
            )
    return {
        "suppliers": [
            {
                "id": str(row.id),
                "name": row.name,
                "preferred": row.preferred,
                "risk_tier": row.risk_tier,
                "contract": contract_by_supplier[row.id].number if row.id in contract_by_supplier else None,
            }
            for row in preferred
        ],
        "price_flags": price_flags,
    }


def create_intake(db: Session, actor, data: IntakeIn, at: datetime | None = None) -> Intake:
    branch = owned(db, Branch, data.branch_id)
    category = owned(db, Category, data.category_id)
    if data.location_id:
        location = owned(db, Location, data.location_id)
        if location.branch_id != branch.id:
            raise HTTPException(422, "That location belongs to a different branch.")
    if data.preferred_supplier_id:
        owned(db, Supplier, data.preferred_supplier_id)
    now = at or datetime.now(timezone.utc)
    intake = Intake(
        tenant_id=actor.tenant_id,
        number=next_number(db, actor.tenant_id, "INT", branch.code, fiscal_year(now)),
        branch_id=branch.id,
        location_id=data.location_id,
        category_id=category.id,
        requester_id=actor.user_id,
        title=data.title.strip(),
        justification=data.justification,
        needed_by=data.needed_by,
        route=data.route,
        preferred_supplier_id=data.preferred_supplier_id,
        status="draft",
        created_at=now,
    )
    db.add(intake)
    db.flush()
    rows, total = build_lines(db, actor.tenant_id, intake.id, data.lines, category)
    db.add_all(rows)
    intake.estimated_total = total
    intake.budget_check = check_budget(db, branch.id, category.id, total, now)
    intake.suggestions = suggestions(db, category.id, rows)
    audit(db, actor, "intake_created", "intake", intake.id, number=intake.number, total=total)
    db.flush()
    return intake


def submit_intake(db: Session, actor, intake: Intake, at: datetime | None = None) -> ApprovalInstance:
    if intake.status != "draft":
        raise HTTPException(409, "This request has already been submitted.")
    supplier = db.get(Supplier, intake.preferred_supplier_id) if intake.preferred_supplier_id else None
    extra = ("finance_ap",) if intake.budget_check.get("status") == "over" else ()
    instance = approvals.submit(
        db,
        actor,
        subject_type="intake",
        subject_id=intake.id,
        branch_id=intake.branch_id,
        requester_id=intake.requester_id,
        amount=intake.estimated_total,
        category_id=intake.category_id,
        risk_tier=supplier.risk_tier if supplier else None,
        extra_roles=extra,
        at=at,
    )
    intake.status = "pending_approval"
    db.flush()
    return instance


@approvals.on_complete("intake")
def _intake_decided(db: Session, actor, instance: ApprovalInstance, approved: bool) -> None:
    intake = db.get(Intake, instance.subject_id)
    intake.status = "approved" if approved else "rejected"
    if approved:
        year = fiscal_year(instance.decided_at)
        budget = db.scalar(
            select(Budget)
            .where(Budget.branch_id == intake.branch_id, Budget.category_id == intake.category_id, Budget.fiscal_year == year)
            .with_for_update()
        )
        if budget:
            budget.committed += intake.estimated_total
    db.flush()


def intake_po(db: Session, actor, intake: Intake, supplier_id: UUID, freight: Decimal = Decimal(0), prices: dict | None = None, at: datetime | None = None) -> PurchaseOrder:
    """Creates a draft PO whose ceiling comes from the completed approval."""
    if intake.status != "approved":
        raise HTTPException(409, "This request must be approved before a purchase order is created.")
    instance = db.scalar(
        select(ApprovalInstance).where(
            ApprovalInstance.subject_type == "intake",
            ApprovalInstance.subject_id == intake.id,
            ApprovalInstance.status == "approved",
        )
    )
    lines = db.scalars(select(IntakeLine).where(IntakeLine.intake_id == intake.id).order_by(IntakeLine.line_no)).all()
    prices = prices or {}
    inputs = []
    for line in lines:
        item = db.get(Item, line.item_id) if line.item_id else None
        inputs.append(
            po_service.LineInput(
                description=line.description,
                quantity=line.quantity,
                unit_price=prices.get(line.id, line.estimated_price),
                hsn=line.hsn,
                unit=line.unit,
                gst_rate=line.gst_rate,
                item_id=line.item_id,
                sku=item.sku if item else "",
            )
        )
    tolerance = policy_for(db, actor.tenant_id).approval_tolerance_pct
    po = po_service.create_draft(
        db,
        actor,
        branch_id=intake.branch_id,
        supplier_id=supplier_id,
        lines=inputs,
        location_id=intake.location_id,
        intake_id=intake.id,
        approval_instance_id=instance.id,
        approved_amount=money(instance.amount * (1 + tolerance / 100)),
        needed_by=intake.needed_by,
        freight=freight,
        at=at,
    )
    intake.status = "ordered"
    db.flush()
    return po


@router.post("", status_code=201)
def create(data: IntakeIn, ctx: Ctx = Depends(require("intake.write"))):
    ctx.require_branch(data.branch_id)
    with ctx.tx() as db:
        intake = create_intake(db, ctx, data)
        return detail_json(db, intake)


@router.get("")
def list_intakes(status: str | None = None, branch_id: UUID | None = None, limit: int = 50, offset: int = 0, ctx: Ctx = Depends(require("intake.read"))):
    with ctx.tx() as db:
        query = select(Intake)
        if status:
            query = query.where(Intake.status == status)
        if branch_id:
            query = query.where(Intake.branch_id == branch_id)
        if ctx.branch_ids is not None:
            query = query.where(Intake.branch_id.in_(ctx.branch_ids))
        total = db.scalar(select(func.count()).select_from(query.subquery()))
        rows = db.scalars(query.order_by(Intake.created_at.desc()).limit(min(limit, 200)).offset(max(offset, 0))).all()
        return {"total": total, "items": [out(row) for row in rows]}


def detail_json(db: Session, intake: Intake) -> dict:
    lines = db.scalars(select(IntakeLine).where(IntakeLine.intake_id == intake.id).order_by(IntakeLine.line_no)).all()
    instance = db.scalar(
        select(ApprovalInstance)
        .where(ApprovalInstance.subject_type == "intake", ApprovalInstance.subject_id == intake.id)
        .order_by(ApprovalInstance.created_at.desc())
    )
    tasks = (
        db.scalars(select(ApprovalTask).where(ApprovalTask.instance_id == instance.id).order_by(ApprovalTask.step)).all()
        if instance
        else []
    )
    po = db.scalar(select(PurchaseOrder).where(PurchaseOrder.intake_id == intake.id))
    return out(
        intake,
        lines=[out(line) for line in lines],
        approval=out(instance) if instance else None,
        tasks=[out(task) for task in tasks],
        purchase_order=out(po) if po else None,
    )


@router.get("/{intake_id}")
def get_intake(intake_id: UUID, ctx: Ctx = Depends(require("intake.read"))):
    with ctx.tx() as db:
        intake = owned(db, Intake, intake_id)
        ctx.require_branch(intake.branch_id)
        return detail_json(db, intake)


@router.post("/{intake_id}/submit")
def submit(intake_id: UUID, ctx: Ctx = Depends(require("intake.write"))):
    with ctx.tx() as db:
        intake = db.scalar(select(Intake).where(Intake.id == intake_id).with_for_update())
        if intake is None:
            raise HTTPException(404, "Record not found.")
        ctx.require_branch(intake.branch_id)
        submit_intake(db, ctx, intake)
        return detail_json(db, intake)


@router.post("/{intake_id}/purchase-order", status_code=201)
def create_po(intake_id: UUID, data: CreatePoIn, ctx: Ctx = Depends(require("po.write"))):
    with ctx.tx() as db:
        intake = db.scalar(select(Intake).where(Intake.id == intake_id).with_for_update())
        if intake is None:
            raise HTTPException(404, "Record not found.")
        supplier_id = data.supplier_id or intake.preferred_supplier_id
        if supplier_id is None:
            raise HTTPException(422, "Choose a supplier for this purchase order.")
        po = intake_po(db, ctx, intake, supplier_id, data.freight, data.prices)
        return out(po)


__all__ = ["router", "timedelta"]
