"""The approver's queue and decisions."""
from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from orrfin import approvals as service
from orrfin.api.deps import Ctx, out, require
from orrfin.models import ApprovalInstance, ApprovalTask, Delegation, Intake, Membership, PurchaseOrder

router = APIRouter(prefix="/api/approvals", tags=["approvals"])


class DecisionIn(BaseModel):
    comment: str = Field(default="", max_length=1000)


class DelegationIn(BaseModel):
    to_user_id: UUID
    starts_on: date
    ends_on: date


def _subject_label(db, instance: ApprovalInstance) -> str:
    if instance.subject_type == "intake":
        intake = db.get(Intake, instance.subject_id)
        return f"{intake.number}: {intake.title}" if intake else "Request"
    if instance.subject_type == "po_change":
        po = db.get(PurchaseOrder, instance.subject_id)
        return f"Change to {po.number}" if po else "Purchase order change"
    return instance.subject_type


@router.get("/queue")
def queue(ctx: Ctx = Depends(require("approvals.read"))):
    with ctx.tx() as db:
        roles = service.effective_roles(db, ctx)
        query = select(ApprovalTask).where(ApprovalTask.status == "pending").order_by(ApprovalTask.due_at)
        if ctx.role != "admin":
            query = query.where(ApprovalTask.approver_role.in_(roles))
        if ctx.branch_ids is not None:
            query = query.where(ApprovalTask.branch_id.in_(ctx.branch_ids))
        items = []
        for task in db.scalars(query.limit(200)):
            instance = db.get(ApprovalInstance, task.instance_id)
            items.append(
                out(
                    task,
                    subject_type=instance.subject_type,
                    subject_id=instance.subject_id,
                    subject=_subject_label(db, instance),
                    amount=instance.amount,
                    steps=len(instance.rules_snapshot),
                    own_request=task.requester_id == ctx.user_id,
                )
            )
        return items


@router.post("/tasks/{task_id}/approve")
def approve(task_id: UUID, data: DecisionIn, ctx: Ctx = Depends(require("approvals.decide"))):
    with ctx.tx() as db:
        return out(service.decide(db, ctx, task_id, True, data.comment))


@router.post("/tasks/{task_id}/reject")
def reject(task_id: UUID, data: DecisionIn, ctx: Ctx = Depends(require("approvals.decide"))):
    if not data.comment.strip():
        raise HTTPException(422, "Add a reason so the requester knows what to change.")
    with ctx.tx() as db:
        return out(service.decide(db, ctx, task_id, False, data.comment))


@router.post("/delegations", status_code=201)
def delegate(data: DelegationIn, ctx: Ctx = Depends(require("approvals.decide"))):
    if data.ends_on < data.starts_on:
        raise HTTPException(422, "The end date must not be before the start date.")
    if data.to_user_id == ctx.user_id:
        raise HTTPException(422, "You can't delegate to yourself.")
    with ctx.tx() as db:
        member = db.scalar(
            select(Membership.id).where(Membership.tenant_id == ctx.tenant_id, Membership.user_id == data.to_user_id)
        )
        if member is None:
            raise HTTPException(404, "That person isn't in this organization.")
        row = Delegation(tenant_id=ctx.tenant_id, from_user_id=ctx.user_id, **data.model_dump())
        db.add(row)
        db.flush()
        return out(row)
