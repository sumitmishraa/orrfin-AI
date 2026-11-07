"""Supplier risk: transparent, rule-based scoring with every point traceable to a factor.

Tiers drive approvals (high and critical add a risk step), the review schedule, and an automatic
PO hold at critical. Sanctions screening, bank verification and GSTN registration lookups need
paid data providers; they are listed as "not performed", never as passed.
"""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from orrfin.api.deps import audit
from orrfin.models import (
    Document,
    GoodsReceipt,
    Invoice,
    MatchException,
    OnboardingCase,
    PurchaseOrder,
    RiskAssessment,
    RiskHold,
    Supplier,
)

TIERS = ((25, "low"), (50, "medium"), (75, "high"), (101, "critical"))
REVIEW_DAYS = {"low": 365, "medium": 180, "high": 90, "critical": 30}
REQUIRED_DOCUMENTS = ("gst_certificate", "cancelled_cheque")
AUTO_HOLD_REASON = "Automatic: supplier risk is critical. Review before issuing new purchase orders."


def tier_for(score: int) -> str:
    return next(name for limit, name in TIERS if score < limit)


def performance(db: Session, supplier_id) -> dict:
    receipts = db.execute(
        select(GoodsReceipt.received_on, GoodsReceipt.quality_ok, PurchaseOrder.needed_by)
        .join(PurchaseOrder, PurchaseOrder.id == GoodsReceipt.po_id)
        .where(PurchaseOrder.supplier_id == supplier_id)
    ).all()
    late = sum(1 for row in receipts if row.needed_by and row.received_on > row.needed_by)
    quality_issues = sum(1 for row in receipts if not row.quality_ok)
    invoices = db.scalar(select(func.count()).select_from(Invoice).where(Invoice.supplier_id == supplier_id, Invoice.status != "rejected"))
    with_exceptions = db.scalar(
        select(func.count(func.distinct(MatchException.invoice_id)))
        .join(Invoice, Invoice.id == MatchException.invoice_id)
        .where(Invoice.supplier_id == supplier_id, MatchException.severity == "blocking")
    )
    spend = db.scalar(
        select(func.coalesce(func.sum(PurchaseOrder.total), 0)).where(
            PurchaseOrder.supplier_id == supplier_id, PurchaseOrder.status.in_(("issued", "partially_received", "received", "closed"))
        )
    )
    rate = lambda part, whole: round(100 * part / whole) if whole else None  # noqa: E731
    return {
        "receipts": len(receipts),
        "on_time_pct": rate(len(receipts) - late, len(receipts)),
        "quality_ok_pct": rate(len(receipts) - quality_issues, len(receipts)),
        "invoices": invoices,
        "invoice_exception_pct": rate(with_exceptions, invoices),
        "spend": str(spend),
    }


def score_supplier(db: Session, supplier: Supplier, today: date | None = None) -> tuple[int, str, list[dict]]:
    today = today or datetime.now(timezone.utc).date()
    factors: list[dict] = []

    def add(points: int, factor: str, detail: str) -> None:
        factors.append({"factor": factor, "points": points, "detail": detail})

    case = db.scalar(select(OnboardingCase).where(OnboardingCase.supplier_id == supplier.id).order_by(OnboardingCase.created_at.desc()))
    checks = case.checks if case else {}
    if supplier.status != "approved":
        add(15, "onboarding", "Onboarding isn't approved.")
    if not supplier.gstin:
        add(30, "gstin", "No GSTIN on file.")
    elif checks.get("gstin", {}).get("status") == "fail":
        add(30, "gstin", "GSTIN failed its checksum.")
    if checks.get("pan_matches_gstin", {}).get("status") == "fail":
        add(15, "pan", "PAN doesn't match the PAN inside the GSTIN.")
    if checks.get("duplicates", {}).get("status") == "warn":
        add(10, "duplicate", checks["duplicates"].get("detail", "Possible duplicate supplier."))
    for cert in (case.answers.get("certifications", []) if case else []):
        try:
            expiry = date.fromisoformat(cert.get("expiry", ""))
        except ValueError:
            continue
        if expiry < today:
            add(15, "certificate_expired", f"{cert.get('name', 'Certificate')} expired on {expiry.isoformat()}.")
        elif expiry <= today + timedelta(days=30):
            add(5, "certificate_expiring", f"{cert.get('name', 'Certificate')} expires on {expiry.isoformat()}.")
    if case:
        kinds = set(db.scalars(select(Document.kind).where(Document.subject_type == "onboarding", Document.subject_id == case.id)).all())
        for kind in REQUIRED_DOCUMENTS:
            if kind not in kinds:
                add(5, "document_missing", f"Missing {kind.replace('_', ' ')}.")

    stats = performance(db, supplier.id)
    if stats["receipts"] >= 3:
        late_pct = 100 - stats["on_time_pct"]
        if late_pct > 40:
            add(25, "late_deliveries", f"{late_pct}% of {stats['receipts']} deliveries were late.")
        elif late_pct > 20:
            add(15, "late_deliveries", f"{late_pct}% of {stats['receipts']} deliveries were late.")
        if 100 - stats["quality_ok_pct"] > 10:
            add(15, "quality", f"{100 - stats['quality_ok_pct']}% of deliveries had quality issues.")
    if stats["invoices"] >= 3 and (stats["invoice_exception_pct"] or 0) > 30:
        add(10, "invoice_accuracy", f"{stats['invoice_exception_pct']}% of invoices had blocking exceptions.")

    if supplier.category_id and Decimal(stats["spend"]) > 0:
        category_spend = db.scalar(
            select(func.coalesce(func.sum(PurchaseOrder.total), 0))
            .join(Supplier, Supplier.id == PurchaseOrder.supplier_id)
            .where(Supplier.category_id == supplier.category_id, PurchaseOrder.status.in_(("issued", "partially_received", "received", "closed")))
        )
        share = Decimal(stats["spend"]) / category_spend if category_spend else Decimal(0)
        if share > Decimal("0.5"):
            add(10, "concentration", f"This supplier holds {share:.0%} of spend in its category.")

    for name in ("sanctions_screening", "bank_verification", "gstn_registration"):
        factors.append({"factor": name, "points": 0, "detail": "Not performed: needs a connected data provider."})
    score = min(100, sum(item["points"] for item in factors))
    return score, tier_for(score), factors


def assess(db: Session, actor, supplier: Supplier, today: date | None = None) -> RiskAssessment:
    today = today or datetime.now(timezone.utc).date()
    score, tier, factors = score_supplier(db, supplier, today)
    assessment = RiskAssessment(
        tenant_id=supplier.tenant_id,
        supplier_id=supplier.id,
        score=score,
        tier=tier,
        factors=factors,
        source="rules",
        next_review_on=today + timedelta(days=REVIEW_DAYS[tier]),
        assessed_by=getattr(actor, "user_name", "system") if actor else "system",
    )
    db.add(assessment)
    supplier.risk_score, supplier.risk_tier = score, tier
    automatic = db.scalar(select(RiskHold).where(RiskHold.supplier_id == supplier.id, RiskHold.active.is_(True), RiskHold.reason == AUTO_HOLD_REASON))
    if tier == "critical" and automatic is None:
        db.add(RiskHold(tenant_id=supplier.tenant_id, supplier_id=supplier.id, scope="po", reason=AUTO_HOLD_REASON, placed_by="system"))
    elif tier != "critical" and automatic is not None:
        automatic.active, automatic.released_by, automatic.released_at = False, "system", datetime.now(timezone.utc)
    audit(db, actor, "risk_assessed", "supplier", supplier.id, tenant_id=supplier.tenant_id, score=score, tier=tier)
    db.flush()
    return assessment
