"""Database access. Tenant data is only reachable through tenant_tx, which arms Postgres RLS.

The tenant id is applied with set_config(..., true) as the first statement of every
transaction, so it reverts on commit or rollback and can't leak across pooled connections.
"""
from contextlib import contextmanager
from typing import Iterator
from uuid import UUID

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker

from orrfin.config import settings

engine = create_engine(
    settings.database_url,
    pool_size=settings.pool_size,
    max_overflow=settings.pool_size,
    pool_pre_ping=True,
)
_SessionFactory = sessionmaker(bind=engine, expire_on_commit=False)


@event.listens_for(_SessionFactory, "after_begin")
def _apply_tenant(session: Session, _transaction, connection) -> None:
    tenant_id = session.info.get("tenant_id")
    if tenant_id:
        connection.execute(
            text("SELECT set_config('app.tenant_id', :tenant, true)"),
            {"tenant": str(tenant_id)},
        )


@contextmanager
def tenant_tx(tenant_id: UUID | str) -> Iterator[Session]:
    """One transaction scoped to one tenant. Commits on exit, rolls back on any exception."""
    session = _SessionFactory(info={"tenant_id": str(tenant_id)})
    try:
        with session.begin():
            yield session
    finally:
        session.close()


@contextmanager
def platform_tx() -> Iterator[Session]:
    """A transaction with no tenant set. RLS returns zero tenant rows here by design."""
    session = _SessionFactory()
    try:
        with session.begin():
            yield session
    finally:
        session.close()


def assert_safe_role() -> None:
    """Refuse to serve traffic through a role that would silently bypass RLS."""
    with engine.connect() as connection:
        row = connection.execute(
            text("SELECT rolname, rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user")
        ).one()
    if row.rolsuper or row.rolbypassrls:
        raise RuntimeError(f"Database role {row.rolname} can bypass row-level security; refusing to start.")
