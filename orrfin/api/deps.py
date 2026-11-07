"""Request context: authenticates the session cookie and declares each route's permission."""
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID

from fastapi import Cookie, Depends, Header, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from orrfin import db as database
from orrfin.models import AuditLog, Membership, MembershipBranch, User, UserSession
from orrfin.security import BRANCH_SCOPED_ROLES, has_permission, token_hash

SESSION_COOKIE = "orrfin_session"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


@dataclass(frozen=True)
class Ctx:
    user_id: UUID
    user_name: str
    email: str
    tenant_id: UUID
    role: str
    csrf_token: str
    branch_ids: frozenset[UUID] | None  # None means every branch in the tenant.

    def tx(self):
        return database.tenant_tx(self.tenant_id)

    def can_access_branch(self, branch_id: UUID) -> bool:
        return self.branch_ids is None or branch_id in self.branch_ids

    def require_branch(self, branch_id: UUID) -> None:
        if not self.can_access_branch(branch_id):
            raise HTTPException(404, "Record not found.")


def load_context(session_token: str | None) -> Ctx:
    if not session_token:
        raise HTTPException(401, "Sign in to continue.")
    with database.platform_tx() as db:
        session = db.scalar(select(UserSession).where(UserSession.token_hash == token_hash(session_token)))
        if not session or session.expires_at <= datetime.now(timezone.utc):
            raise HTTPException(401, "Your session has expired. Sign in again.")
        user = db.get(User, session.user_id)
        membership = db.scalar(
            select(Membership).where(Membership.tenant_id == session.tenant_id, Membership.user_id == session.user_id)
        )
        if not user or not user.is_active or not membership:
            raise HTTPException(401, "Your access has been removed.")
    branch_ids = None
    if membership.role in BRANCH_SCOPED_ROLES:
        with database.tenant_tx(session.tenant_id) as db:
            rows = db.scalars(
                select(MembershipBranch.branch_id).where(MembershipBranch.membership_id == membership.id)
            ).all()
        branch_ids = frozenset(rows)
    return Ctx(
        user_id=user.id,
        user_name=user.name,
        email=user.email,
        tenant_id=session.tenant_id,
        role=membership.role,
        csrf_token=session.csrf_token,
        branch_ids=branch_ids,
    )


def authenticated(
    request: Request,
    orrfin_session: str | None = Cookie(default=None),
    x_orrfin_csrf: str | None = Header(default=None),
) -> Ctx:
    ctx = load_context(orrfin_session)
    if request.method not in SAFE_METHODS and x_orrfin_csrf != ctx.csrf_token:
        raise HTTPException(403, "Security check failed. Reload the page and try again.")
    return ctx


def require(permission: str) -> Callable[..., Ctx]:
    """Route dependency. Tests walk the OpenAPI routes to prove every route declares one."""

    def dependency(ctx: Ctx = Depends(authenticated)) -> Ctx:
        if not has_permission(ctx.role, permission):
            raise HTTPException(403, "Your role doesn't allow this action.")
        return ctx

    dependency.__orrfin_permission__ = permission  # type: ignore[attr-defined]
    return dependency


def public(func: Callable) -> Callable:
    """Marks a route as intentionally unauthenticated, for the same route-coverage test."""
    func.__orrfin_public__ = True  # type: ignore[attr-defined]
    return func


def encode(value):
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: encode(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [encode(item) for item in value]
    return value


def out(row, exclude: tuple[str, ...] = (), **extra) -> dict:
    """Row to JSON-safe dict. Money stays an exact string, never a float."""
    data = {
        column.key: encode(getattr(row, column.key))
        for column in row.__table__.columns
        if column.key not in exclude and column.key != "tenant_id"
    }
    data.update({key: encode(value) for key, value in extra.items()})
    return data


def audit(db: Session, ctx: Ctx | None, action: str, subject_type: str, subject_id, tenant_id=None, label: str = "", **detail) -> None:
    db.add(
        AuditLog(
            tenant_id=ctx.tenant_id if ctx else tenant_id,
            actor_id=ctx.user_id if ctx else None,
            actor_label=ctx.user_name if ctx else (label or "system"),
            action=action,
            subject_type=subject_type,
            subject_id=subject_id,
            detail=encode(detail),
        )
    )


def owned(db: Session, model, record_id) -> object:
    """Fetch by id. RLS already limits the tenant, so a missing row is simply a 404."""
    row = db.get(model, record_id)
    if row is None:
        raise HTTPException(404, "Record not found.")
    return row
