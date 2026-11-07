"""Gapless document numbers.

The upsert takes a row lock held until commit, so concurrent issuers queue and a rollback gives
the number back. Database sequences can't do this: they burn numbers on rollback.
"""
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.orm import Session

_NEXT = text(
    """
    INSERT INTO number_sequences (id, tenant_id, scope, fiscal_year, next_value, created_at)
    VALUES (:id, :tenant, :scope, :fy, 2, now())
    ON CONFLICT (tenant_id, scope, fiscal_year)
    DO UPDATE SET next_value = number_sequences.next_value + 1
    RETURNING next_value - 1
    """
)


def next_value(db: Session, tenant_id: UUID, scope: str, fiscal_year: str) -> int:
    return db.execute(_NEXT, {"id": uuid4(), "tenant": tenant_id, "scope": scope, "fy": fiscal_year}).scalar_one()


def next_number(db: Session, tenant_id: UUID, prefix: str, branch_code: str, fiscal_year: str) -> str:
    value = next_value(db, tenant_id, f"{prefix}/{branch_code}", fiscal_year)
    return f"{prefix}/{branch_code}/{fiscal_year}/{value:06d}"
