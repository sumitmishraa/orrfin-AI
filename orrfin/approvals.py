"""Enforced multi-step approvals.

Rules are snapshotted at submission, so editing a rule never changes an in-flight approval.
Requesters can't approve their own request: this is checked here for a clear message and again
by a database constraint, so no code path can get around it.
"""
from collections.abc import Callable
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from orrfin.api.deps import audit, encode
from orrfin.models import ApprovalInstance, ApprovalRule, ApprovalTask, Delegation, Membership
from orrfin.security import BRANCH_SCOPED_ROLES

FALLBACK_ROLE = "procurement"
_completion_handlers: dict[str, Callable] = {}


def on_complete(subject_type: str):
    """Registers fn(db, actor, instance, approved) to run when an approval finishes."""

    def register(func):
        _completion_handlers[subject_type] = func
        return func

    return register


def _specificity(rule: ApprovalRule) -> tuple:
    return (rule.branch_id is not None, rule.category_id is not None, rule.risk_tier is not None, rule.min_amount)


def build_steps(
    db: Session,
    branch_id: UUID,
    category_id: UUID | None,
    amount: Decimal,
    risk_tier: str | None,
    extra_roles: tuple[str, ...] = (),
) -> list[dict]:
    rules = db.scalars(select(ApprovalRule).where(ApprovalRule.active.is_(True))).all()
    best_by_step: dict[int, ApprovalRule] = {}
    for rule in rules:
        if rule.branch_id not in (None, branch_id) or rule.category_id not in (None, category_id):
            continue
        if rule.risk_tier not in (None, risk_tier):
            continue
        if amount < rule.min_amount or (rule.max_amount is not None and amount > rule.max_amount):
            continue
        current = best_by_step.get(rule.step)
        if current is None or _specificity(rule) > _specificity(current):
            best_by_step[rule.step] = rule

    steps = [
        {"role": rule.approver_role, "sla_hours": rule.sla_hours, "rule": rule.name}
        for _, rule in sorted(best_by_step.items())
    ]
    if not steps:
        steps = [{"role": FALLBACK_ROLE, "sla_hours": 48, "rule": "Default: no rule matched"}]
    for role in extra_roles:
        if role not in {step["role"] for step in steps}:
            steps.append({"role": role, "sla_hours": 48, "rule": "Added by policy"})
    return steps


def submit(
    db: Session,
    actor,
    *,
    subject_type: str,
    subject_id: UUID,
    branch_id: UUID,
    requester_id: UUID,
    amount: Decimal,
    category_id: UUID | None = None,
    risk_tier: str | None = None,
    extra_roles: tuple[str, ...] = (),
    at: datetime | None = None,
) -> ApprovalInstance:
    now = at or datetime.now(timezone.utc)
    steps = build_steps(db, branch_id, category_id, amount, risk_tier, extra_roles)
    instance = ApprovalInstance(
        tenant_id=actor.tenant_id,
        subject_type=subject_type,
        subject_id=subject_id,
        branch_id=branch_id,
        requester_id=requester_id,
        amount=amount,
        status="pending",
        current_step=1,
        rules_snapshot=encode(steps),
        created_at=now,
    )
    db.add(instance)
    db.flush()
    for number, step in enumerate(steps, start=1):
        db.add(
            ApprovalTask(
                tenant_id=actor.tenant_id,
                instance_id=instance.id,
                step=number,
                approver_role=step["role"],
                branch_id=branch_id,
                requester_id=requester_id,
                status="pending" if number == 1 else "waiting",
                due_at=now + timedelta(hours=step["sla_hours"]) if number == 1 else None,
                created_at=now,
            )
        )
    audit(db, actor, "approval_submitted", subject_type, subject_id, steps=[step["role"] for step in steps])
    db.flush()
    return instance


def effective_roles(db: Session, actor, on: date | None = None) -> set[str]:
    """The actor's own role, plus the roles of anyone currently delegating to them."""
    today = on or datetime.now(timezone.utc).date()
    roles = {actor.role}
    delegators = db.scalars(
        select(Delegation.from_user_id).where(
            Delegation.to_user_id == actor.user_id, Delegation.starts_on <= today, Delegation.ends_on >= today
        )
    ).all()
    if delegators:
        roles |= set(
            db.scalars(
                select(Membership.role).where(Membership.tenant_id == actor.tenant_id, Membership.user_id.in_(delegators))
            ).all()
        )
    return roles


def _can_act(db: Session, actor, task: ApprovalTask) -> bool:
    if actor.role == "admin":
        return True
    if task.approver_role not in effective_roles(db, actor):
        return False
    if task.approver_role in BRANCH_SCOPED_ROLES and actor.branch_ids is not None:
        return task.branch_id in actor.branch_ids
    return True


def decide(
    db: Session, actor, task_id: UUID, approve: bool, comment: str = "", at: datetime | None = None
) -> ApprovalInstance:
    now = at or datetime.now(timezone.utc)
    task = db.get(ApprovalTask, task_id)
    if task is None:
        raise HTTPException(404, "Record not found.")
    # Lock the instance so two approvers on adjacent steps can't advance it at the same time.
    instance = db.scalar(select(ApprovalInstance).where(ApprovalInstance.id == task.instance_id).with_for_update())
    if instance.status != "pending":
        raise HTTPException(409, "This approval has already finished.")
    if task.step != instance.current_step or task.status != "pending":
        raise HTTPException(409, "This step isn't waiting for a decision.")
    if actor.user_id == task.requester_id:
        raise HTTPException(409, "You can't approve your own request.")
    if not _can_act(db, actor, task):
        raise HTTPException(403, "This step is assigned to a different role.")

    updated = db.execute(
        update(ApprovalTask)
        .where(ApprovalTask.id == task.id, ApprovalTask.status == "pending")
        .values(
            status="approved" if approve else "rejected",
            decided_by=actor.user_id,
            decided_at=now,
            comment=comment,
        )
    )
    if updated.rowcount != 1:
        raise HTTPException(409, "This step was just decided by someone else.")
    audit(db, actor, "approval_approved" if approve else "approval_rejected", instance.subject_type, instance.subject_id, step=task.step, comment=comment)

    finished = False
    if not approve:
        instance.status, instance.decided_at, finished = "rejected", now, True
        db.execute(
            update(ApprovalTask)
            .where(ApprovalTask.instance_id == instance.id, ApprovalTask.status == "waiting")
            .values(status="skipped")
        )
    else:
        following = db.scalar(
            select(ApprovalTask).where(ApprovalTask.instance_id == instance.id, ApprovalTask.step == task.step + 1)
        )
        if following is None:
            instance.status, instance.decided_at, finished = "approved", now, True
        else:
            hours = next(
                (step["sla_hours"] for number, step in enumerate(instance.rules_snapshot, 1) if number == following.step),
                48,
            )
            following.status = "pending"
            following.due_at = now + timedelta(hours=hours)
            instance.current_step = following.step
    db.flush()
    if finished and instance.subject_type in _completion_handlers:
        _completion_handlers[instance.subject_type](db, actor, instance, approve)
    return instance
