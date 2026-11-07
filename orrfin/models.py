"""Relational model. Money is numeric(18,2), quantities numeric(18,3), ids UUID.

Every tenant table carries tenant_id and composite foreign keys, because foreign-key checks
bypass RLS: a composite key stops a row in one tenant pointing at a row in another.
"""
from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID as PyUUID
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    MetaData,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr, mapped_column

Money = Numeric(18, 2)
Qty = Numeric(18, 3)
Rate = Numeric(6, 3)
Json = JSON().with_variant(JSONB(), "postgresql")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    metadata = MetaData(
        naming_convention={
            "ix": "ix_%(table_name)s_%(column_0_N_name)s",
            "uq": "uq_%(table_name)s_%(column_0_N_name)s",
            "ck": "ck_%(table_name)s_%(constraint_name)s",
            "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
            "pk": "pk_%(table_name)s",
        }
    )


def tfk(column: str, target: str, ondelete: str | None = None) -> ForeignKeyConstraint:
    """Composite tenant-safe foreign key to target.id."""
    return ForeignKeyConstraint(
        ["tenant_id", column], [f"{target}.tenant_id", f"{target}.id"], ondelete=ondelete
    )


class Row:
    """Shared id and creation time."""

    id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class TenantRow(Row):
    """A row owned by one tenant and protected by RLS."""

    @declared_attr
    def tenant_id(cls) -> Mapped[PyUUID]:
        return mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"), index=True, nullable=False)


# ---------------------------------------------------------------- platform (no RLS)


class Tenant(Base, Row):
    __tablename__ = "tenants"
    name: Mapped[str] = mapped_column(String(200))
    slug: Mapped[str] = mapped_column(String(80), unique=True)
    settings: Mapped[dict] = mapped_column(Json, default=dict)


class User(Base, Row):
    __tablename__ = "users"
    email: Mapped[str] = mapped_column(String(255), unique=True)
    name: Mapped[str] = mapped_column(String(160))
    password_hash: Mapped[str] = mapped_column(String(255))
    failed_logins: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Membership(Base, Row):
    __tablename__ = "memberships"
    __table_args__ = (
        UniqueConstraint("tenant_id", "user_id"),
        UniqueConstraint("tenant_id", "id"),
    )
    tenant_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"), index=True)
    user_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), index=True)
    role: Mapped[str] = mapped_column(String(40))


class UserSession(Base, Row):
    __tablename__ = "sessions"
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    user_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), index=True)
    tenant_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"))
    csrf_token: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class PortalToken(Base, Row):
    """Supplier-facing link. Only the hash is stored; the token lives in a URL fragment."""

    __tablename__ = "portal_tokens"
    tenant_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"), index=True)
    kind: Mapped[str] = mapped_column(String(30))
    subject_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)


class Job(Base, Row):
    """Queue entry. Holds ids only, so it can stay outside RLS without exposing tenant data."""

    __tablename__ = "job_queue"
    __table_args__ = (
        Index("ix_job_queue_claim", "status", "run_after"),
    )
    tenant_id: Mapped[PyUUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"))
    kind: Mapped[str] = mapped_column(String(40))
    payload: Mapped[dict] = mapped_column(Json, default=dict)
    status: Mapped[str] = mapped_column(String(20), default="queued")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    run_after: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


# ---------------------------------------------------------------- organization


class LegalEntity(Base, TenantRow):
    __tablename__ = "legal_entities"
    __table_args__ = (UniqueConstraint("tenant_id", "gstin"),)
    name: Mapped[str] = mapped_column(String(200))
    gstin: Mapped[str] = mapped_column(String(15))
    pan: Mapped[str] = mapped_column(String(10), default="")
    state_code: Mapped[str] = mapped_column(String(2))
    state_name: Mapped[str] = mapped_column(String(60))
    address: Mapped[str] = mapped_column(String(400), default="")


class Branch(Base, TenantRow):
    __tablename__ = "branches"
    __table_args__ = (UniqueConstraint("tenant_id", "code"), tfk("legal_entity_id", "legal_entities"))
    code: Mapped[str] = mapped_column(String(20))
    name: Mapped[str] = mapped_column(String(120))
    city: Mapped[str] = mapped_column(String(80))
    legal_entity_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True))
    erp_location_id: Mapped[str] = mapped_column(String(80), default="")


class Location(Base, TenantRow):
    __tablename__ = "locations"
    __table_args__ = (UniqueConstraint("tenant_id", "code"), tfk("branch_id", "branches"))
    branch_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), index=True)
    code: Mapped[str] = mapped_column(String(30))
    name: Mapped[str] = mapped_column(String(160))
    kind: Mapped[str] = mapped_column(String(30), default="dark_store")
    address: Mapped[str] = mapped_column(String(400), default="")


class MembershipBranch(Base, TenantRow):
    """Branch scope for branch-limited roles."""

    __tablename__ = "membership_branches"
    __table_args__ = (
        UniqueConstraint("tenant_id", "membership_id", "branch_id"),
        tfk("branch_id", "branches"),
        tfk("membership_id", "memberships"),
    )
    membership_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), index=True)
    branch_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True))


class Category(Base, TenantRow):
    __tablename__ = "categories"
    __table_args__ = (UniqueConstraint("tenant_id", "name"),)
    name: Mapped[str] = mapped_column(String(120))
    default_hsn: Mapped[str] = mapped_column(String(12), default="")
    default_gst_rate: Mapped[Decimal] = mapped_column(Rate, default=Decimal("18"))


class Budget(Base, TenantRow):
    __tablename__ = "budgets"
    __table_args__ = (
        UniqueConstraint("tenant_id", "branch_id", "category_id", "fiscal_year"),
        tfk("branch_id", "branches"),
        tfk("category_id", "categories"),
        CheckConstraint("amount >= 0", name="amount_non_negative"),
    )
    branch_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True))
    category_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True))
    fiscal_year: Mapped[str] = mapped_column(String(7))
    amount: Mapped[Decimal] = mapped_column(Money)
    committed: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))


class NumberSequence(Base, TenantRow):
    __tablename__ = "number_sequences"
    __table_args__ = (UniqueConstraint("tenant_id", "scope", "fiscal_year"),)
    scope: Mapped[str] = mapped_column(String(60))
    fiscal_year: Mapped[str] = mapped_column(String(7))
    next_value: Mapped[int] = mapped_column(Integer, default=1)


class Document(Base, TenantRow):
    """Immutable stored file. A new version is a new row; UPDATE and DELETE are revoked."""

    __tablename__ = "documents"
    __table_args__ = (
        UniqueConstraint("tenant_id", "sha256", "subject_type", "subject_id"),
        Index("ix_documents_subject", "tenant_id", "subject_type", "subject_id"),
    )
    kind: Mapped[str] = mapped_column(String(40))
    filename: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(100))
    size_bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    storage_key: Mapped[str] = mapped_column(String(400))
    subject_type: Mapped[str] = mapped_column(String(40))
    subject_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True))
    version: Mapped[int] = mapped_column(Integer, default=1)
    uploaded_by: Mapped[str] = mapped_column(String(160), default="")


class AuditLog(Base, TenantRow):
    """Append-only trail. UPDATE and DELETE are revoked from the application role."""

    __tablename__ = "audit_log"
    __table_args__ = (Index("ix_audit_log_subject", "tenant_id", "subject_type", "subject_id"),)
    actor_id: Mapped[PyUUID | None] = mapped_column(UUID(as_uuid=True))
    actor_label: Mapped[str] = mapped_column(String(160), default="")
    action: Mapped[str] = mapped_column(String(80))
    subject_type: Mapped[str] = mapped_column(String(40))
    subject_id: Mapped[PyUUID | None] = mapped_column(UUID(as_uuid=True))
    detail: Mapped[dict] = mapped_column(Json, default=dict)


class Alert(Base, TenantRow):
    __tablename__ = "alerts"
    __table_args__ = (UniqueConstraint("tenant_id", "dedupe_key"),)
    kind: Mapped[str] = mapped_column(String(40))
    severity: Mapped[str] = mapped_column(String(20), default="info")
    message: Mapped[str] = mapped_column(String(500))
    subject_type: Mapped[str] = mapped_column(String(40), default="")
    subject_id: Mapped[PyUUID | None] = mapped_column(UUID(as_uuid=True))
    due_on: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), default="open")
    dedupe_key: Mapped[str] = mapped_column(String(200))


# ---------------------------------------------------------------- supply base


class Item(Base, TenantRow):
    __tablename__ = "items"
    __table_args__ = (UniqueConstraint("tenant_id", "sku"), tfk("category_id", "categories"))
    sku: Mapped[str] = mapped_column(String(60))
    name: Mapped[str] = mapped_column(String(200))
    category_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), index=True)
    hsn: Mapped[str] = mapped_column(String(12), default="")
    unit: Mapped[str] = mapped_column(String(20), default="NOS")
    gst_rate: Mapped[Decimal] = mapped_column(Rate, default=Decimal("18"))
    benchmark_price: Mapped[Decimal | None] = mapped_column(Money)


class Supplier(Base, TenantRow):
    __tablename__ = "suppliers"
    __table_args__ = (
        Index("uq_suppliers_tenant_gstin", "tenant_id", "gstin", unique=True, postgresql_where=text("gstin <> ''")),
        tfk("category_id", "categories"),
    )
    name: Mapped[str] = mapped_column(String(200), index=True)
    gstin: Mapped[str] = mapped_column(String(15), default="")
    pan: Mapped[str] = mapped_column(String(10), default="")
    state_code: Mapped[str] = mapped_column(String(2), default="")
    email: Mapped[str] = mapped_column(String(255), default="")
    phone: Mapped[str] = mapped_column(String(40), default="")
    address: Mapped[str] = mapped_column(String(400), default="")
    category_id: Mapped[PyUUID | None] = mapped_column(UUID(as_uuid=True))
    status: Mapped[str] = mapped_column(String(20), default="draft")
    preferred: Mapped[bool] = mapped_column(Boolean, default=False)
    risk_tier: Mapped[str] = mapped_column(String(20), default="unassessed")
    risk_score: Mapped[int | None] = mapped_column(Integer)
    payment_terms_days: Mapped[int] = mapped_column(Integer, default=30)


class OnboardingCase(Base, TenantRow):
    __tablename__ = "onboarding_cases"
    __table_args__ = (tfk("supplier_id", "suppliers"),)
    supplier_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), index=True)
    status: Mapped[str] = mapped_column(String(20), default="invited")
    answers: Mapped[dict] = mapped_column(Json, default=dict)
    checks: Mapped[dict] = mapped_column(Json, default=dict)
    decided_by: Mapped[PyUUID | None] = mapped_column(UUID(as_uuid=True))
    decision_note: Mapped[str] = mapped_column(String(1000), default="")
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RiskAssessment(Base, TenantRow):
    __tablename__ = "risk_assessments"
    __table_args__ = (tfk("supplier_id", "suppliers"),)
    supplier_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), index=True)
    score: Mapped[int] = mapped_column(Integer)
    tier: Mapped[str] = mapped_column(String(20))
    factors: Mapped[list] = mapped_column(Json, default=list)
    source: Mapped[str] = mapped_column(String(20), default="rules")
    next_review_on: Mapped[date | None] = mapped_column(Date)
    assessed_by: Mapped[str] = mapped_column(String(160), default="system")


class RiskHold(Base, TenantRow):
    """An active hold is enforced by database triggers on POs and payments."""

    __tablename__ = "risk_holds"
    __table_args__ = (
        tfk("supplier_id", "suppliers"),
        CheckConstraint("scope IN ('po', 'payment', 'all')", name="scope_valid"),
    )
    supplier_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), index=True)
    scope: Mapped[str] = mapped_column(String(20), default="all")
    reason: Mapped[str] = mapped_column(String(1000))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    placed_by: Mapped[str] = mapped_column(String(160), default="")
    released_by: Mapped[str] = mapped_column(String(160), default="")
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


# ---------------------------------------------------------------- intake and approvals


class Intake(Base, TenantRow):
    __tablename__ = "intakes"
    __table_args__ = (
        UniqueConstraint("tenant_id", "number"),
        tfk("branch_id", "branches"),
        tfk("location_id", "locations"),
        tfk("category_id", "categories"),
        tfk("preferred_supplier_id", "suppliers"),
        Index("ix_intakes_status", "tenant_id", "status"),
    )
    number: Mapped[str] = mapped_column(String(40))
    branch_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), index=True)
    location_id: Mapped[PyUUID | None] = mapped_column(UUID(as_uuid=True))
    category_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True))
    requester_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True))
    title: Mapped[str] = mapped_column(String(200))
    justification: Mapped[str] = mapped_column(String(2000), default="")
    needed_by: Mapped[date] = mapped_column(Date)
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    estimated_total: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    status: Mapped[str] = mapped_column(String(30), default="draft")
    route: Mapped[str] = mapped_column(String(20), default="sourcing")
    preferred_supplier_id: Mapped[PyUUID | None] = mapped_column(UUID(as_uuid=True))
    budget_check: Mapped[dict] = mapped_column(Json, default=dict)
    suggestions: Mapped[dict] = mapped_column(Json, default=dict)


class IntakeLine(Base, TenantRow):
    __tablename__ = "intake_lines"
    __table_args__ = (tfk("intake_id", "intakes", "CASCADE"), tfk("item_id", "items"))
    intake_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), index=True)
    line_no: Mapped[int] = mapped_column(Integer)
    item_id: Mapped[PyUUID | None] = mapped_column(UUID(as_uuid=True))
    description: Mapped[str] = mapped_column(String(300))
    hsn: Mapped[str] = mapped_column(String(12), default="")
    quantity: Mapped[Decimal] = mapped_column(Qty)
    unit: Mapped[str] = mapped_column(String(20), default="NOS")
    estimated_price: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    gst_rate: Mapped[Decimal] = mapped_column(Rate, default=Decimal("18"))


class ApprovalRule(Base, TenantRow):
    __tablename__ = "approval_rules"
    __table_args__ = (tfk("branch_id", "branches"), tfk("category_id", "categories"))
    name: Mapped[str] = mapped_column(String(160))
    branch_id: Mapped[PyUUID | None] = mapped_column(UUID(as_uuid=True))
    category_id: Mapped[PyUUID | None] = mapped_column(UUID(as_uuid=True))
    risk_tier: Mapped[str | None] = mapped_column(String(20))
    min_amount: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    max_amount: Mapped[Decimal | None] = mapped_column(Money)
    step: Mapped[int] = mapped_column(Integer, default=1)
    approver_role: Mapped[str] = mapped_column(String(40))
    sla_hours: Mapped[int] = mapped_column(Integer, default=48)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class ApprovalInstance(Base, TenantRow):
    """Rules are snapshotted at submission, so later edits can't change an in-flight approval."""

    __tablename__ = "approval_instances"
    __table_args__ = (
        Index("ix_approval_instances_subject", "tenant_id", "subject_type", "subject_id"),
        tfk("branch_id", "branches"),
    )
    subject_type: Mapped[str] = mapped_column(String(40))
    subject_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True))
    branch_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True))
    requester_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True))
    amount: Mapped[Decimal] = mapped_column(Money)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    current_step: Mapped[int] = mapped_column(Integer, default=1)
    rules_snapshot: Mapped[list] = mapped_column(Json, default=list)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ApprovalTask(Base, TenantRow):
    __tablename__ = "approval_tasks"
    __table_args__ = (
        UniqueConstraint("tenant_id", "instance_id", "step"),
        tfk("instance_id", "approval_instances", "CASCADE"),
        CheckConstraint("decided_by IS NULL OR decided_by <> requester_id", name="no_self_approval"),
        Index("ix_approval_tasks_queue", "tenant_id", "status", "approver_role"),
    )
    instance_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), index=True)
    step: Mapped[int] = mapped_column(Integer)
    approver_role: Mapped[str] = mapped_column(String(40))
    branch_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True))
    requester_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True))
    status: Mapped[str] = mapped_column(String(20), default="waiting")
    decided_by: Mapped[PyUUID | None] = mapped_column(UUID(as_uuid=True))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    comment: Mapped[str] = mapped_column(String(1000), default="")
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Delegation(Base, TenantRow):
    __tablename__ = "delegations"
    from_user_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), index=True)
    to_user_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), index=True)
    starts_on: Mapped[date] = mapped_column(Date)
    ends_on: Mapped[date] = mapped_column(Date)


# ---------------------------------------------------------------- sourcing


class SourcingEvent(Base, TenantRow):
    __tablename__ = "sourcing_events"
    __table_args__ = (
        UniqueConstraint("tenant_id", "number"),
        tfk("intake_id", "intakes"),
        tfk("branch_id", "branches"),
    )
    number: Mapped[str] = mapped_column(String(40))
    intake_id: Mapped[PyUUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    branch_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True))
    title: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(20), default="open")
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    awarded_bid_id: Mapped[PyUUID | None] = mapped_column(UUID(as_uuid=True))


class SourcingLine(Base, TenantRow):
    __tablename__ = "sourcing_lines"
    __table_args__ = (tfk("event_id", "sourcing_events", "CASCADE"), tfk("item_id", "items"))
    event_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), index=True)
    line_no: Mapped[int] = mapped_column(Integer)
    item_id: Mapped[PyUUID | None] = mapped_column(UUID(as_uuid=True))
    description: Mapped[str] = mapped_column(String(300))
    hsn: Mapped[str] = mapped_column(String(12), default="")
    quantity: Mapped[Decimal] = mapped_column(Qty)
    unit: Mapped[str] = mapped_column(String(20), default="NOS")
    gst_rate: Mapped[Decimal] = mapped_column(Rate, default=Decimal("18"))


class SourcingInvite(Base, TenantRow):
    __tablename__ = "sourcing_invites"
    __table_args__ = (
        UniqueConstraint("tenant_id", "event_id", "supplier_id"),
        tfk("event_id", "sourcing_events", "CASCADE"),
        tfk("supplier_id", "suppliers"),
    )
    event_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), index=True)
    supplier_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True))
    status: Mapped[str] = mapped_column(String(20), default="invited")


class Bid(Base, TenantRow):
    __tablename__ = "bids"
    __table_args__ = (
        UniqueConstraint("tenant_id", "event_id", "supplier_id"),
        tfk("event_id", "sourcing_events", "CASCADE"),
        tfk("supplier_id", "suppliers"),
    )
    event_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), index=True)
    supplier_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True))
    lead_days: Mapped[int] = mapped_column(Integer)
    freight: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    subtotal: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    tax: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    total: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    notes: Mapped[str] = mapped_column(String(1000), default="")


class BidLine(Base, TenantRow):
    __tablename__ = "bid_lines"
    __table_args__ = (
        UniqueConstraint("tenant_id", "bid_id", "sourcing_line_id"),
        tfk("bid_id", "bids", "CASCADE"),
        tfk("sourcing_line_id", "sourcing_lines"),
    )
    bid_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), index=True)
    sourcing_line_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True))
    unit_price: Mapped[Decimal] = mapped_column(Money)


# ---------------------------------------------------------------- procure to pay


class PurchaseOrder(Base, TenantRow):
    __tablename__ = "purchase_orders"
    __table_args__ = (
        Index(
            "uq_purchase_orders_number",
            "tenant_id",
            "number",
            unique=True,
            postgresql_where=text("number IS NOT NULL"),
        ),
        Index("ix_purchase_orders_status", "tenant_id", "status"),
        tfk("legal_entity_id", "legal_entities"),
        tfk("branch_id", "branches"),
        tfk("location_id", "locations"),
        tfk("supplier_id", "suppliers"),
        tfk("intake_id", "intakes"),
        tfk("event_id", "sourcing_events"),
        tfk("approval_instance_id", "approval_instances"),
    )
    number: Mapped[str | None] = mapped_column(String(50))
    legal_entity_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True))
    branch_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), index=True)
    location_id: Mapped[PyUUID | None] = mapped_column(UUID(as_uuid=True))
    supplier_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), index=True)
    intake_id: Mapped[PyUUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    event_id: Mapped[PyUUID | None] = mapped_column(UUID(as_uuid=True))
    approval_instance_id: Mapped[PyUUID | None] = mapped_column(UUID(as_uuid=True))
    approved_amount: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    status: Mapped[str] = mapped_column(String(30), default="draft")
    revision: Mapped[int] = mapped_column(Integer, default=0)
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    subtotal: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    cgst: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    sgst: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    igst: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    freight: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    total: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    place_of_supply: Mapped[str] = mapped_column(String(60), default="")
    is_interstate: Mapped[bool] = mapped_column(Boolean, default=False)
    fiscal_year: Mapped[str] = mapped_column(String(7), default="")
    needed_by: Mapped[date | None] = mapped_column(Date)
    payment_terms_days: Mapped[int] = mapped_column(Integer, default=30)
    issued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    issued_by: Mapped[PyUUID | None] = mapped_column(UUID(as_uuid=True))
    notes: Mapped[str] = mapped_column(String(2000), default="")


class PoRevision(Base, TenantRow):
    __tablename__ = "po_revisions"
    __table_args__ = (UniqueConstraint("tenant_id", "po_id", "revision"), tfk("po_id", "purchase_orders", "CASCADE"))
    po_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), index=True)
    revision: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(String(1000), default="")
    snapshot: Mapped[dict] = mapped_column(Json, default=dict)
    created_by: Mapped[str] = mapped_column(String(160), default="")


class PoLine(Base, TenantRow):
    __tablename__ = "po_lines"
    __table_args__ = (
        UniqueConstraint("tenant_id", "po_id", "line_no"),
        tfk("po_id", "purchase_orders", "CASCADE"),
        tfk("item_id", "items"),
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint("unit_price >= 0", name="price_non_negative"),
        CheckConstraint("igst = 0 OR (cgst = 0 AND sgst = 0)", name="igst_or_cgst_sgst"),
        CheckConstraint("qty_received <= receipt_cap", name="no_over_receipt"),
        CheckConstraint("qty_billed <= billing_cap", name="no_over_billing"),
    )
    po_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), index=True)
    line_no: Mapped[int] = mapped_column(Integer)
    item_id: Mapped[PyUUID | None] = mapped_column(UUID(as_uuid=True))
    sku: Mapped[str] = mapped_column(String(60), default="")
    description: Mapped[str] = mapped_column(String(300))
    hsn: Mapped[str] = mapped_column(String(12), default="")
    unit: Mapped[str] = mapped_column(String(20), default="NOS")
    quantity: Mapped[Decimal] = mapped_column(Qty)
    unit_price: Mapped[Decimal] = mapped_column(Money)
    gst_rate: Mapped[Decimal] = mapped_column(Rate, default=Decimal("18"))
    taxable: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    cgst: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    sgst: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    igst: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    qty_received: Mapped[Decimal] = mapped_column(Qty, default=Decimal("0"))
    qty_billed: Mapped[Decimal] = mapped_column(Qty, default=Decimal("0"))
    receipt_cap: Mapped[Decimal] = mapped_column(Qty)
    billing_cap: Mapped[Decimal] = mapped_column(Qty)


class GoodsReceipt(Base, TenantRow):
    __tablename__ = "goods_receipts"
    __table_args__ = (
        UniqueConstraint("tenant_id", "number"),
        UniqueConstraint("tenant_id", "po_id", "idempotency_key"),
        tfk("po_id", "purchase_orders"),
        tfk("location_id", "locations"),
    )
    number: Mapped[str] = mapped_column(String(50))
    po_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), index=True)
    location_id: Mapped[PyUUID | None] = mapped_column(UUID(as_uuid=True))
    received_on: Mapped[date] = mapped_column(Date)
    received_by: Mapped[PyUUID | None] = mapped_column(UUID(as_uuid=True))
    quality_ok: Mapped[bool] = mapped_column(Boolean, default=True)
    note: Mapped[str] = mapped_column(String(1000), default="")
    idempotency_key: Mapped[str] = mapped_column(String(100))


class GrnLine(Base, TenantRow):
    __tablename__ = "grn_lines"
    __table_args__ = (
        UniqueConstraint("tenant_id", "grn_id", "po_line_id"),
        tfk("grn_id", "goods_receipts", "CASCADE"),
        tfk("po_line_id", "po_lines"),
        CheckConstraint("quantity >= 0", name="quantity_non_negative"),
    )
    grn_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), index=True)
    po_line_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), index=True)
    quantity: Mapped[Decimal] = mapped_column(Qty)


class Invoice(Base, TenantRow):
    __tablename__ = "invoices"
    __table_args__ = (
        Index(
            "uq_invoices_supplier_number",
            "tenant_id",
            "supplier_id",
            "fiscal_year",
            "normalized_number",
            unique=True,
            postgresql_where=text("normalized_number <> '' AND status <> 'rejected'"),
        ),
        Index("ix_invoices_status", "tenant_id", "status"),
        tfk("po_id", "purchase_orders"),
        tfk("supplier_id", "suppliers"),
        tfk("document_id", "documents"),
        CheckConstraint("igst = 0 OR (cgst = 0 AND sgst = 0)", name="igst_or_cgst_sgst"),
    )
    po_id: Mapped[PyUUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    supplier_id: Mapped[PyUUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    document_id: Mapped[PyUUID | None] = mapped_column(UUID(as_uuid=True))
    number: Mapped[str] = mapped_column(String(80), default="")
    normalized_number: Mapped[str] = mapped_column(String(80), default="")
    fiscal_year: Mapped[str] = mapped_column(String(7), default="")
    invoice_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(30), default="uploaded")
    supplier_gstin: Mapped[str] = mapped_column(String(15), default="")
    buyer_gstin: Mapped[str] = mapped_column(String(15), default="")
    subtotal: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    cgst: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    sgst: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    igst: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    freight: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    round_off: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    total: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    confirmed_by: Mapped[PyUUID | None] = mapped_column(UUID(as_uuid=True))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    match_result: Mapped[dict] = mapped_column(Json, default=dict)
    approved_by: Mapped[PyUUID | None] = mapped_column(UUID(as_uuid=True))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    uploaded_by: Mapped[str] = mapped_column(String(160), default="")


class InvoiceLine(Base, TenantRow):
    __tablename__ = "invoice_lines"
    __table_args__ = (
        UniqueConstraint("tenant_id", "invoice_id", "line_no"),
        tfk("invoice_id", "invoices", "CASCADE"),
        tfk("po_line_id", "po_lines"),
    )
    invoice_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), index=True)
    line_no: Mapped[int] = mapped_column(Integer)
    po_line_id: Mapped[PyUUID | None] = mapped_column(UUID(as_uuid=True))
    description: Mapped[str] = mapped_column(String(300), default="")
    hsn: Mapped[str] = mapped_column(String(12), default="")
    unit: Mapped[str] = mapped_column(String(20), default="")
    quantity: Mapped[Decimal] = mapped_column(Qty, default=Decimal("0"))
    unit_price: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    taxable: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    gst_rate: Mapped[Decimal | None] = mapped_column(Rate)


class InvoiceAllocation(Base, TenantRow):
    """Approved billing against a PO line. A trigger increments po_lines.qty_billed."""

    __tablename__ = "invoice_allocations"
    __table_args__ = (
        UniqueConstraint("tenant_id", "invoice_line_id"),
        tfk("invoice_line_id", "invoice_lines"),
        tfk("po_line_id", "po_lines"),
        CheckConstraint("quantity >= 0", name="quantity_non_negative"),
    )
    invoice_line_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True))
    po_line_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), index=True)
    quantity: Mapped[Decimal] = mapped_column(Qty)


class ExtractionRun(Base, TenantRow):
    __tablename__ = "extraction_runs"
    __table_args__ = (tfk("invoice_id", "invoices", "CASCADE"), tfk("document_id", "documents"))
    invoice_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), index=True)
    document_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True))
    engine: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(20))
    fields: Mapped[dict] = mapped_column(Json, default=dict)
    overall_confidence: Mapped[Decimal | None] = mapped_column(Numeric(4, 3))
    warnings: Mapped[list] = mapped_column(Json, default=list)
    error: Mapped[str | None] = mapped_column(Text)


class MatchException(Base, TenantRow):
    __tablename__ = "match_exceptions"
    __table_args__ = (
        tfk("invoice_id", "invoices", "CASCADE"),
        Index("ix_match_exceptions_queue", "tenant_id", "status", "assignee_role"),
    )
    invoice_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), index=True)
    code: Mapped[str] = mapped_column(String(40))
    severity: Mapped[str] = mapped_column(String(20), default="blocking")
    message: Mapped[str] = mapped_column(String(600))
    line_no: Mapped[int | None] = mapped_column(Integer)
    expected: Mapped[str] = mapped_column(String(120), default="")
    actual: Mapped[str] = mapped_column(String(120), default="")
    assignee_role: Mapped[str] = mapped_column(String(40), default="finance_ap")
    status: Mapped[str] = mapped_column(String(20), default="open")
    resolution: Mapped[str] = mapped_column(String(1000), default="")
    resolved_by: Mapped[PyUUID | None] = mapped_column(UUID(as_uuid=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Payment(Base, TenantRow):
    """Records payment status only. Orrfin.ai moves no money."""

    __tablename__ = "payments"
    __table_args__ = (
        tfk("invoice_id", "invoices"),
        tfk("supplier_id", "suppliers"),
        CheckConstraint("amount > 0", name="amount_positive"),
    )
    invoice_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), index=True)
    supplier_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True))
    amount: Mapped[Decimal] = mapped_column(Money)
    status: Mapped[str] = mapped_column(String(20), default="scheduled")
    reference: Mapped[str] = mapped_column(String(120), default="")
    paid_on: Mapped[date | None] = mapped_column(Date)


# ---------------------------------------------------------------- contracts


class Clause(Base, TenantRow):
    __tablename__ = "clauses"
    __table_args__ = (UniqueConstraint("tenant_id", "key"),)
    key: Mapped[str] = mapped_column(String(60))
    title: Mapped[str] = mapped_column(String(160))
    body: Mapped[str] = mapped_column(Text)
    mandatory: Mapped[bool] = mapped_column(Boolean, default=True)
    guidance: Mapped[str] = mapped_column(String(1000), default="")


class ContractTemplate(Base, TenantRow):
    __tablename__ = "contract_templates"
    __table_args__ = (UniqueConstraint("tenant_id", "name"),)
    name: Mapped[str] = mapped_column(String(160))
    description: Mapped[str] = mapped_column(String(600), default="")
    clause_keys: Mapped[list] = mapped_column(Json, default=list)


class Contract(Base, TenantRow):
    __tablename__ = "contracts"
    __table_args__ = (
        UniqueConstraint("tenant_id", "number"),
        tfk("supplier_id", "suppliers"),
        tfk("template_id", "contract_templates"),
    )
    number: Mapped[str] = mapped_column(String(50))
    title: Mapped[str] = mapped_column(String(200))
    supplier_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), index=True)
    template_id: Mapped[PyUUID | None] = mapped_column(UUID(as_uuid=True))
    status: Mapped[str] = mapped_column(String(20), default="draft")
    start_on: Mapped[date] = mapped_column(Date)
    end_on: Mapped[date] = mapped_column(Date)
    auto_renew: Mapped[bool] = mapped_column(Boolean, default=False)
    notice_days: Mapped[int] = mapped_column(Integer, default=30)
    value: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    current_version: Mapped[int] = mapped_column(Integer, default=1)
    signature_status: Mapped[str] = mapped_column(String(30), default="not_sent")
    owner_id: Mapped[PyUUID | None] = mapped_column(UUID(as_uuid=True))


class ContractVersion(Base, TenantRow):
    __tablename__ = "contract_versions"
    __table_args__ = (
        UniqueConstraint("tenant_id", "contract_id", "version"),
        tfk("contract_id", "contracts", "CASCADE"),
        tfk("document_id", "documents"),
    )
    contract_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), index=True)
    version: Mapped[int] = mapped_column(Integer)
    body: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(20), default="generated")
    document_id: Mapped[PyUUID | None] = mapped_column(UUID(as_uuid=True))
    created_by: Mapped[str] = mapped_column(String(160), default="")
    review: Mapped[dict] = mapped_column(Json, default=dict)


class Obligation(Base, TenantRow):
    __tablename__ = "obligations"
    __table_args__ = (tfk("contract_id", "contracts", "CASCADE"),)
    contract_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), index=True)
    title: Mapped[str] = mapped_column(String(300))
    due_on: Mapped[date | None] = mapped_column(Date)
    owner_role: Mapped[str] = mapped_column(String(40), default="legal")
    status: Mapped[str] = mapped_column(String(20), default="open")


# ---------------------------------------------------------------- integrations and AI


class ErpConnection(Base, TenantRow):
    __tablename__ = "erp_connections"
    __table_args__ = (UniqueConstraint("tenant_id", "provider"),)
    provider: Mapped[str] = mapped_column(String(30))
    mode: Mapped[str] = mapped_column(String(20), default="mock")
    config: Mapped[dict] = mapped_column(Json, default=dict)
    credentials_encrypted: Mapped[str] = mapped_column(Text, default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ErpMapping(Base, TenantRow):
    __tablename__ = "erp_mappings"
    __table_args__ = (
        UniqueConstraint("tenant_id", "connection_id", "entity_type", "local_key"),
        tfk("connection_id", "erp_connections", "CASCADE"),
    )
    connection_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), index=True)
    entity_type: Mapped[str] = mapped_column(String(30))
    local_key: Mapped[str] = mapped_column(String(120))
    external_id: Mapped[str] = mapped_column(String(160))


class ErpOutbox(Base, TenantRow):
    __tablename__ = "erp_outbox"
    __table_args__ = (
        UniqueConstraint("tenant_id", "connection_id", "doc_type", "doc_id", "revision"),
        tfk("connection_id", "erp_connections"),
        Index("ix_erp_outbox_status", "tenant_id", "status"),
    )
    connection_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), index=True)
    doc_type: Mapped[str] = mapped_column(String(30))
    doc_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True))
    revision: Mapped[int] = mapped_column(Integer, default=0)
    external_key: Mapped[str] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(20), default="pending")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    payload: Mapped[dict] = mapped_column(Json, default=dict)
    external_id: Mapped[str] = mapped_column(String(160), default="")
    last_response: Mapped[dict] = mapped_column(Json, default=dict)
    last_error: Mapped[str] = mapped_column(Text, default="")
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ConciergeDraft(Base, TenantRow):
    __tablename__ = "concierge_drafts"
    user_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), index=True)
    kind: Mapped[str] = mapped_column(String(40))
    payload: Mapped[dict] = mapped_column(Json, default=dict)
    status: Mapped[str] = mapped_column(String(20), default="draft")


class MemoryOutbox(Base, TenantRow):
    """Structured events for Hindsight. Never holds document text."""

    __tablename__ = "memory_outbox"
    __table_args__ = (UniqueConstraint("tenant_id", "source_id", "event_type"), tfk("supplier_id", "suppliers"))
    supplier_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), index=True)
    source_id: Mapped[str] = mapped_column(String(80))
    event_type: Mapped[str] = mapped_column(String(60))
    status: Mapped[str] = mapped_column(String(20), default="pending")


class AiConsent(Base, TenantRow):
    __tablename__ = "ai_consent"
    __table_args__ = (UniqueConstraint("tenant_id"),)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_by: Mapped[str] = mapped_column(String(160), default="")


PLATFORM_TABLES = {"tenants", "users", "memberships", "sessions", "portal_tokens", "job_queue", "alembic_version"}

# Composite foreign keys need a matching unique key on every tenant table.
for _table in Base.metadata.tables.values():
    if "tenant_id" in _table.c and _table.name not in PLATFORM_TABLES:
        _table.append_constraint(UniqueConstraint("tenant_id", "id"))
