"""Home dashboard: spend, pipeline, controls and alerts, scoped to the user's branches."""
from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import func, select

from orrfin.api.deps import Ctx, out, owned, require
from orrfin.gst import IST, fiscal_year
from orrfin.models import (
    Alert,
    ApprovalTask,
    Branch,
    Category,
    Contract,
    ErpOutbox,
    Intake,
    Invoice,
    MatchException,
    PurchaseOrder,
    Supplier,
)

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])
LIVE = ("issued", "partially_received", "received", "closed", "change_pending")


@router.get("")
def dashboard(ctx: Ctx = Depends(require("org.read"))):
    with ctx.tx() as db:
        scope = (lambda query, column: query.where(column.in_(ctx.branch_ids))) if ctx.branch_ids is not None else (lambda query, column: query)
        year = fiscal_year()
        start = datetime(int(year[:4]), 4, 1, tzinfo=IST)

        spend_by_branch = db.execute(
            scope(
                select(Branch.code, Branch.name, func.coalesce(func.sum(PurchaseOrder.total), 0), func.count(PurchaseOrder.id))
                .join(PurchaseOrder, PurchaseOrder.branch_id == Branch.id)
                .where(PurchaseOrder.status.in_(LIVE), PurchaseOrder.issued_at >= start)
                .group_by(Branch.code, Branch.name)
                .order_by(func.sum(PurchaseOrder.total).desc()),
                PurchaseOrder.branch_id,
            )
        ).all()
        spend_by_category = db.execute(
            scope(
                select(func.coalesce(Category.name, "Uncategorised"), func.coalesce(func.sum(PurchaseOrder.total), 0))
                .join(Supplier, Supplier.id == PurchaseOrder.supplier_id)
                .outerjoin(Category, Category.id == Supplier.category_id)
                .where(PurchaseOrder.status.in_(LIVE), PurchaseOrder.issued_at >= start)
                .group_by(Category.name)
                .order_by(func.sum(PurchaseOrder.total).desc()),
                PurchaseOrder.branch_id,
            )
        ).all()
        month = func.date_trunc("month", func.timezone("Asia/Kolkata", PurchaseOrder.issued_at))
        trend = db.execute(
            scope(
                select(month, func.coalesce(func.sum(PurchaseOrder.total), 0), func.count())
                .where(PurchaseOrder.status.in_(LIVE), PurchaseOrder.issued_at >= datetime.now(timezone.utc) - timedelta(days=366))
                .group_by(month)
                .order_by(month),
                PurchaseOrder.branch_id,
            )
        ).all()
        top_suppliers = db.execute(
            scope(
                select(Supplier.id, Supplier.name, Supplier.risk_tier, func.sum(PurchaseOrder.total))
                .join(PurchaseOrder, PurchaseOrder.supplier_id == Supplier.id)
                .where(PurchaseOrder.status.in_(LIVE), PurchaseOrder.issued_at >= start)
                .group_by(Supplier.id, Supplier.name, Supplier.risk_tier)
                .order_by(func.sum(PurchaseOrder.total).desc())
                .limit(8),
                PurchaseOrder.branch_id,
            )
        ).all()
        count = lambda query: db.scalar(select(func.count()).select_from(query.subquery()))  # noqa: E731
        pending_tasks = select(ApprovalTask.id).where(ApprovalTask.status == "pending")
        if ctx.role != "admin":
            pending_tasks = pending_tasks.where(ApprovalTask.approver_role == ctx.role)
        today = datetime.now(timezone.utc).date()
        return {
            "fiscal_year": year,
            "spend_by_branch": [{"code": code, "name": name, "spend": str(total), "orders": orders} for code, name, total, orders in spend_by_branch],
            "spend_by_category": [{"category": name, "spend": str(total)} for name, total in spend_by_category],
            "monthly_spend": [{"month": row[0].date().isoformat()[:7], "spend": str(row[1]), "orders": row[2]} for row in trend],
            "top_suppliers": [{"id": str(sid), "name": name, "risk_tier": tier, "spend": str(total)} for sid, name, tier, total in top_suppliers],
            "counts": {
                "my_pending_approvals": count(scope(pending_tasks, ApprovalTask.branch_id)),
                "open_requests": count(scope(select(Intake.id).where(Intake.status.in_(("pending_approval", "approved", "sourcing"))), Intake.branch_id)),
                "open_orders": count(scope(select(PurchaseOrder.id).where(PurchaseOrder.status.in_(("issued", "partially_received"))), PurchaseOrder.branch_id)),
                "invoices_to_review": count(select(Invoice.id).where(Invoice.status.in_(("uploaded", "extracted")))),
                "open_exceptions": count(select(MatchException.id).where(MatchException.status == "open", MatchException.severity == "blocking")),
                "erp_attention": count(select(ErpOutbox.id).where(ErpOutbox.status.in_(("needs_mapping", "rejected", "dead_letter")))),
                "contracts_expiring_60d": count(select(Contract.id).where(Contract.end_on <= today + timedelta(days=60), Contract.end_on >= today, Contract.status.in_(("approved", "signed")))),
                "high_risk_suppliers": count(select(Supplier.id).where(Supplier.risk_tier.in_(("high", "critical")))),
            },
        }


@router.get("/alerts")
def alerts(status: str = "open", ctx: Ctx = Depends(require("org.read"))):
    with ctx.tx() as db:
        return [out(row) for row in db.scalars(select(Alert).where(Alert.status == status).order_by(Alert.due_on.asc().nulls_last()).limit(200))]


@router.post("/alerts/{alert_id}/dismiss")
def dismiss(alert_id: UUID, ctx: Ctx = Depends(require("org.read"))):
    with ctx.tx() as db:
        row = owned(db, Alert, alert_id)
        row.status = "dismissed"
        db.flush()
        return out(row)
