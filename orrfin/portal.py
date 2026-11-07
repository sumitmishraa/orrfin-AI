"""Supplier-facing links. Only a hash is stored; the token travels in the URL fragment, which
browsers never send to servers or leak through the Referer header."""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select, update

from orrfin import db as database
from orrfin.config import settings
from orrfin.models import PortalToken
from orrfin.security import new_token, token_hash

PATHS = {"onboarding": "/portal/onboarding", "rfq": "/portal/rfq", "po": "/portal/po"}


@dataclass(frozen=True)
class PortalActor:
    """Stands in for a signed-in user when a supplier acts through a link."""

    tenant_id: UUID
    user_name: str = "Supplier (portal)"
    user_id: UUID | None = None
    role: str = "supplier"


def issue(tenant_id: UUID, kind: str, subject_id: UUID, days: int = 14) -> str:
    token = new_token()
    with database.platform_tx() as db:
        db.add(
            PortalToken(
                tenant_id=tenant_id,
                kind=kind,
                subject_id=subject_id,
                token_hash=token_hash(token),
                expires_at=datetime.now(timezone.utc) + timedelta(days=days),
            )
        )
    return token


def link(kind: str, token: str) -> str:
    return f"{settings.public_app_url}{PATHS[kind]}#{token}"


def resolve(token: str | None, kind: str) -> tuple[UUID, UUID]:
    if not token or len(token) > 200:
        raise HTTPException(404, "This link is invalid, expired or revoked.")
    with database.platform_tx() as db:
        row = db.scalar(select(PortalToken).where(PortalToken.token_hash == token_hash(token), PortalToken.kind == kind))
        if row is None or row.revoked or row.expires_at <= datetime.now(timezone.utc):
            raise HTTPException(404, "This link is invalid, expired or revoked.")
        return row.tenant_id, row.subject_id


def revoke(subject_id: UUID, kind: str) -> None:
    with database.platform_tx() as db:
        db.execute(update(PortalToken).where(PortalToken.subject_id == subject_id, PortalToken.kind == kind).values(revoked=True))
