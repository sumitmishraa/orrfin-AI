"""Sourcing: RFQ events, supplier invitations, bid comparison with history, and award to PO."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from orrfin import portal, risk
from orrfin.api.deps import Ctx, audit, out, owned, require
from orrfin.api.intake import intake_po
from orrfin.gst import fiscal_year, money
from orrfin.models import (
    ApprovalInstance,
    Bid,
    BidLine,
    Branch,
    Intake,
    IntakeLine,
    LegalEntity,
    SourcingEvent,
    SourcingInvite,
    SourcingLine,
    Supplier,
)
from orrfin.numbering import next_number
from orrfin.policy import policy_for

router = APIRouter(prefix="/api/sourcing", tags=["sourcing"])


class EventIn(BaseModel):
    intake_id: UUID
    title: str | None = Field(default=None, max_length=200)
    due_in_days: int = Field(default=5, ge=1, le=60)
    supplier_ids: list[UUID] = Field(default=[], max_length=50)


class InviteIn(BaseModel):
    supplier_id: UUID


class AwardIn(BaseModel):
    bid_id: UUID
    reason: str = Field(default="", max_length=1000)


def invite_supplier(db: Session, actor, event: SourcingEvent, supplier: Supplier) -> tuple[SourcingInvite, bool]:
    if supplier.status != "approved":
        raise HTTPException(409, f"{supplier.name} isn't approved yet, so it can't be invited.")
    existing = db.scalar(select(SourcingInvite).where(SourcingInvite.event_id == event.id, SourcingInvite.supplier_id == supplier.id))
    if existing:
        return existing, False
    invite = SourcingInvite(tenant_id=actor.tenant_id, event_id=event.id, supplier_id=supplier.id)
    db.add(invite)
    db.flush()
    return invite, True


def create_event(db: Session, actor, intake: Intake, title: str | None, due_in_days: int, at: datetime | None = None) -> SourcingEvent:
    if intake.status != "approved":
        raise HTTPException(409, "Only an approved request can go to sourcing.")
    now = at or datetime.now(timezone.utc)
    branch = db.get(Branch, intake.branch_id)
    event = SourcingEvent(
        tenant_id=actor.tenant_id,
        number=next_number(db, actor.tenant_id, "RFQ", branch.code, fiscal_year(now)),
        intake_id=intake.id,
        branch_id=intake.branch_id,
        title=title or intake.title,
        status="open",
        due_at=now + timedelta(days=due_in_days),
        created_at=now,
    )
    db.add(event)
    db.flush()
    for line in db.scalars(select(IntakeLine).where(IntakeLine.intake_id == intake.id).order_by(IntakeLine.line_no)):
        db.add(
            SourcingLine(
                tenant_id=actor.tenant_id, event_id=event.id, line_no=line.line_no, item_id=line.item_id,
                description=line.description, hsn=line.hsn, quantity=line.quantity, unit=line.unit, gst_rate=line.gst_rate,
            )
        )
    intake.status = "sourcing"
    audit(db, actor, "sourcing_started", "intake", intake.id, event=event.number)
    db.flush()
    return event


def price_bid(db: Session, event: SourcingEvent, supplier: Supplier, prices: dict[UUID, Decimal], freight: Decimal) -> dict:
    lines = db.scalars(select(SourcingLine).where(SourcingLine.event_id == event.id).order_by(SourcingLine.line_no)).all()
    branch = db.get(Branch, event.branch_id)
    entity = db.get(LegalEntity, branch.legal_entity_id)
    interstate = (supplier.state_code or supplier.gstin[:2]) != entity.state_code
    subtotal = tax = Decimal(0)
    for line in lines:
        if line.id not in prices:
            raise HTTPException(422, f"Enter a price for line {line.line_no}: {line.description}.")
        taxable = money(line.quantity * prices[line.id])
        subtotal += taxable
        tax += money(taxable * line.gst_rate / 100)
    return {"subtotal": money(subtotal), "tax": money(tax), "total": money(subtotal + tax + freight), "interstate": interstate}


def comparison(db: Session, event: SourcingEvent) -> list[dict]:
    intake = db.get(Intake, event.intake_id)
    instance = db.scalar(
        select(ApprovalInstance).where(ApprovalInstance.subject_type == "intake", ApprovalInstance.subject_id == intake.id, ApprovalInstance.status == "approved")
    )
    ceiling = money(instance.amount * (1 + policy_for(db, event.tenant_id).approval_tolerance_pct / 100)) if instance else Decimal(0)
    rows = []
    for bid in db.scalars(select(Bid).where(Bid.event_id == event.id)):
        supplier = db.get(Supplier, bid.supplier_id)
        reasons = []
        if supplier.status != "approved":
            reasons.append("Supplier isn't approved.")
        if bid.total > ceiling:
            reasons.append(f"Total {bid.total} is above the approved ceiling {ceiling}.")
        arrival = (bid.created_at + timedelta(days=bid.lead_days)).date()
        if intake.needed_by and arrival > intake.needed_by:
            reasons.append(f"Lead time of {bid.lead_days} days misses the {intake.needed_by.isoformat()} deadline.")
        if supplier.risk_tier in ("high", "critical"):
            reasons.append(f"Supplier risk is {supplier.risk_tier}.")
        prices = {line.sourcing_line_id: line.unit_price for line in db.scalars(select(BidLine).where(BidLine.bid_id == bid.id))}
        rows.append(
            {
                "bid": out(bid),
                "supplier": {"id": str(supplier.id), "name": supplier.name, "risk_tier": supplier.risk_tier, "preferred": supplier.preferred},
                "prices": {str(key): str(value) for key, value in prices.items()},
                "performance": risk.performance(db, supplier.id),
                "eligible": not reasons,
                "reasons": reasons,
            }
        )
    rows.sort(key=lambda row: (not row["eligible"], Decimal(row["bid"]["total"])))
    return rows


@router.get("")
def list_events(status: str | None = None, ctx: Ctx = Depends(require("sourcing.read"))):
    with ctx.tx() as db:
        query = select(SourcingEvent).order_by(SourcingEvent.created_at.desc()).limit(200)
        if status:
            query = query.where(SourcingEvent.status == status)
        bid_counts = dict(db.execute(select(Bid.event_id, func.count()).group_by(Bid.event_id)).tuples().all())
        invite_counts = dict(db.execute(select(SourcingInvite.event_id, func.count()).group_by(SourcingInvite.event_id)).tuples().all())
        return [out(row, bids=bid_counts.get(row.id, 0), invites=invite_counts.get(row.id, 0)) for row in db.scalars(query)]


@router.post("", status_code=201)
def start_event(data: EventIn, ctx: Ctx = Depends(require("sourcing.write"))):
    links = []
    with ctx.tx() as db:
        intake = db.scalar(select(Intake).where(Intake.id == data.intake_id).with_for_update())
        if intake is None:
            raise HTTPException(404, "Record not found.")
        event = create_event(db, ctx, intake, data.title, data.due_in_days)
        invites = [invite_supplier(db, ctx, event, owned(db, Supplier, supplier_id))[0] for supplier_id in data.supplier_ids]
        event_id = event.id
        result = out(event)
    for invite in invites:
        links.append({"supplier_id": str(invite.supplier_id), "url": portal.link("rfq", portal.issue(ctx.tenant_id, "rfq", invite.id, days=data.due_in_days + 2))})
    return result | {"invite_links": links, "id": str(event_id)}


@router.get("/{event_id}")
def get_event(event_id: UUID, ctx: Ctx = Depends(require("sourcing.read"))):
    with ctx.tx() as db:
        event = owned(db, SourcingEvent, event_id)
        lines = db.scalars(select(SourcingLine).where(SourcingLine.event_id == event.id).order_by(SourcingLine.line_no)).all()
        invites = db.execute(select(SourcingInvite, Supplier.name).join(Supplier, Supplier.id == SourcingInvite.supplier_id).where(SourcingInvite.event_id == event.id)).all()
        return out(event, lines=[out(line) for line in lines], invites=[out(invite, supplier=name) for invite, name in invites], comparison=comparison(db, event))


@router.post("/{event_id}/invites", status_code=201)
def add_invite(event_id: UUID, data: InviteIn, ctx: Ctx = Depends(require("sourcing.write"))):
    with ctx.tx() as db:
        event = owned(db, SourcingEvent, event_id)
        if event.status != "open":
            raise HTTPException(409, "This event is closed.")
        invite, _ = invite_supplier(db, ctx, event, owned(db, Supplier, data.supplier_id))
        days = max(1, (event.due_at - datetime.now(timezone.utc)).days + 2)
        invite_id = invite.id
    return {"invite_id": str(invite_id), "url": portal.link("rfq", portal.issue(ctx.tenant_id, "rfq", invite_id, days=days))}


@router.post("/{event_id}/award", status_code=201)
def award(event_id: UUID, data: AwardIn, ctx: Ctx = Depends(require("sourcing.write"))):
    with ctx.tx() as db:
        event = db.scalar(select(SourcingEvent).where(SourcingEvent.id == event_id).with_for_update())
        if event is None:
            raise HTTPException(404, "Record not found.")
        if event.status not in ("open", "closed"):
            raise HTTPException(409, "This event has already been awarded.")
        bid = owned(db, Bid, data.bid_id)
        if bid.event_id != event.id:
            raise HTTPException(422, "That bid belongs to a different event.")
        intake = db.scalar(select(Intake).where(Intake.id == event.intake_id).with_for_update())
        intake.status = "approved"  # Temporarily, so the standard approved-intake path creates the PO.
        sourcing_lines = {line.id: line for line in db.scalars(select(SourcingLine).where(SourcingLine.event_id == event.id))}
        intake_lines = {line.line_no: line.id for line in db.scalars(select(IntakeLine).where(IntakeLine.intake_id == intake.id))}
        prices = {intake_lines[sourcing_lines[row.sourcing_line_id].line_no]: row.unit_price for row in db.scalars(select(BidLine).where(BidLine.bid_id == bid.id))}
        po = intake_po(db, ctx, intake, bid.supplier_id, bid.freight, prices)
        po.event_id = event.id
        event.status, event.awarded_bid_id = "awarded", bid.id
        audit(db, ctx, "sourcing_awarded", "intake", intake.id, event=event.number, bid_total=bid.total, reason=data.reason)
        db.flush()
        return out(po)


@router.post("/{event_id}/close")
def close(event_id: UUID, ctx: Ctx = Depends(require("sourcing.write"))):
    with ctx.tx() as db:
        event = owned(db, SourcingEvent, event_id)
        if event.status != "open":
            raise HTTPException(409, "Only an open event can be closed.")
        event.status = "closed"
        db.flush()
        return out(event)
