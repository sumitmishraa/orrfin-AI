"""Background job handlers, registered with the worker's @handler decorator."""
from uuid import UUID

from orrfin.db import tenant_tx
from orrfin.worker import handler


@handler("extract_invoice")
def extract_invoice(tenant_id: UUID, payload: dict) -> None:
    from orrfin.p2p.invoices import run_extraction

    with tenant_tx(tenant_id) as db:
        run_extraction(db, tenant_id, UUID(payload["invoice_id"]))


@handler("erp_deliver")
def erp_deliver(tenant_id: UUID, payload: dict) -> None:
    from orrfin.erp.delivery import deliver

    with tenant_tx(tenant_id) as db:
        deliver(db, UUID(payload["outbox_id"]))


@handler("scan")
def scan(tenant_id: UUID, payload: dict) -> None:
    """Periodic per-tenant checks: renewals, review dates, expiring certificates, overdue approvals, memory."""
    from datetime import date, datetime, timedelta, timezone

    from sqlalchemy import select

    from orrfin import memory
    from orrfin.models import Alert, ApprovalTask, Contract, OnboardingCase, RiskAssessment, Supplier

    today = datetime.now(timezone.utc).date()

    def alert(db, key, kind, severity, message, subject_type, subject_id, due_on):
        if db.scalar(select(Alert.id).where(Alert.dedupe_key == key)) is None:
            db.add(Alert(tenant_id=tenant_id, kind=kind, severity=severity, message=message, subject_type=subject_type, subject_id=subject_id, due_on=due_on, dedupe_key=key))

    with tenant_tx(tenant_id) as db:
        for contract in db.scalars(select(Contract).where(Contract.status.in_(("approved", "signed")), Contract.end_on <= today + timedelta(days=60))):
            notice = contract.end_on - timedelta(days=contract.notice_days)
            alert(db, f"renewal:{contract.id}:{contract.end_on}", "contract_renewal", "high" if notice <= today else "medium",
                  f"{contract.number} ({contract.title}) ends on {contract.end_on}. Notice window {'has opened' if notice <= today else 'opens on ' + notice.isoformat()}.",
                  "contract", contract.id, notice)
        latest = {}
        for row in db.scalars(select(RiskAssessment).order_by(RiskAssessment.created_at)):
            latest[row.supplier_id] = row
        for supplier_id, row in latest.items():
            if row.next_review_on and row.next_review_on <= today + timedelta(days=14):
                supplier = db.get(Supplier, supplier_id)
                alert(db, f"review:{supplier_id}:{row.next_review_on}", "risk_review_due", "medium", f"Risk review for {supplier.name} is due on {row.next_review_on}.", "supplier", supplier_id, row.next_review_on)
        for case in db.scalars(select(OnboardingCase).where(OnboardingCase.status == "approved")):
            for cert in case.answers.get("certifications", []):
                try:
                    expiry = date.fromisoformat(cert.get("expiry", ""))
                except ValueError:
                    continue
                if expiry <= today + timedelta(days=30):
                    supplier = db.get(Supplier, case.supplier_id)
                    alert(db, f"cert:{case.id}:{cert.get('name')}:{expiry}", "certificate_expiry", "high" if expiry < today else "medium",
                          f"{supplier.name}: {cert.get('name')} {'expired' if expiry < today else 'expires'} on {expiry}.", "supplier", supplier.id, expiry)
        now = datetime.now(timezone.utc)
        for task in db.scalars(select(ApprovalTask).where(ApprovalTask.status == "pending", ApprovalTask.due_at < now).limit(200)):
            alert(db, f"sla:{task.id}", "approval_overdue", "medium", f"An approval step for the {task.approver_role.replace('_', ' ')} team is past its SLA.", "approval_task", task.id, task.due_at.date())
        memory.deliver_pending(db, tenant_id)
