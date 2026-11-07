"""Proves tenant isolation by showing denials, not just that the happy path works."""
import os
from contextlib import contextmanager
from uuid import uuid4

import pytest
from fastapi.routing import APIRoute
from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import DBAPIError, ProgrammingError
from sqlalchemy.orm import sessionmaker

from orrfin.config import settings
from orrfin.db import tenant_tx
from orrfin.models import PLATFORM_TABLES, AuditLog, Base, LegalEntity

GSTIN = "29AAACK0001A1Z5"


def add_entity(tenant_id, name="Entity"):
    with tenant_tx(tenant_id) as db:
        row = LegalEntity(tenant_id=tenant_id, name=name, gstin=GSTIN, state_code="29", state_name="Karnataka")
        db.add(row)
        db.flush()
        return row.id


def test_tenant_sees_only_its_rows(two_tenants):
    add_entity(two_tenants.a.tenant_id, "A only")
    with tenant_tx(two_tenants.b.tenant_id) as db:
        assert db.scalars(select(LegalEntity)).all() == []
    with tenant_tx(two_tenants.a.tenant_id) as db:
        assert [row.name for row in db.scalars(select(LegalEntity))] == ["A only"]


def test_no_tenant_set_returns_zero_rows(two_tenants):
    add_entity(two_tenants.a.tenant_id)
    engine = create_engine(settings.database_url)
    with engine.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM legal_entities")).scalar_one() == 0


def test_write_tagged_for_another_tenant_is_rejected(two_tenants):
    with pytest.raises(ProgrammingError, match="row-level security"):
        with tenant_tx(two_tenants.a.tenant_id) as db:
            db.add(
                LegalEntity(
                    tenant_id=two_tenants.b.tenant_id, name="x", gstin=GSTIN, state_code="29", state_name="Karnataka"
                )
            )
            db.flush()


def test_setting_does_not_leak_across_a_reused_pooled_connection(two_tenants):
    """pool_size=1 forces every transaction onto one physical connection."""
    add_entity(two_tenants.a.tenant_id, "A row")
    add_entity(two_tenants.b.tenant_id, "B row")
    engine = create_engine(settings.database_url, pool_size=1, max_overflow=0)
    factory = sessionmaker(bind=engine)

    @contextmanager
    def scoped(tenant_id):
        with factory() as session, session.begin():
            session.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant_id)})
            yield session

    for _ in range(5):
        with scoped(two_tenants.a.tenant_id) as db:
            assert db.scalar(text("SELECT string_agg(name, ',') FROM legal_entities")) == "A row"
        with scoped(two_tenants.b.tenant_id) as db:
            assert db.scalar(text("SELECT string_agg(name, ',') FROM legal_entities")) == "B row"
        # With no tenant, the reverted '' setting must deny rows rather than raise a uuid cast error.
        with engine.connect() as connection:
            assert connection.execute(text("SELECT count(*) FROM legal_entities")).scalar_one() == 0


def test_composite_key_blocks_cross_tenant_reference(two_tenants):
    from orrfin.models import Branch

    entity_in_a = add_entity(two_tenants.a.tenant_id)
    with pytest.raises(Exception, match="fk_branches"):
        with tenant_tx(two_tenants.b.tenant_id) as db:
            db.add(
                Branch(tenant_id=two_tenants.b.tenant_id, code="X", name="X", city="X", legal_entity_id=entity_in_a)
            )
            db.flush()


def test_every_tenant_table_has_rls_forced_and_a_policy():
    owner = create_engine(os.environ["OWNER_DATABASE_URL"])
    with owner.connect() as connection:
        rows = connection.execute(
            text(
                """
                SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity,
                       (SELECT count(*) FROM pg_policies p WHERE p.tablename = c.relname) AS policies
                FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = 'public' AND c.relkind = 'r'
                """
            )
        ).all()
    state = {row.relname: row for row in rows}
    expected = {table.name for table in Base.metadata.sorted_tables} - PLATFORM_TABLES
    assert expected <= state.keys()
    unprotected = [
        name
        for name in expected
        if not (state[name].relrowsecurity and state[name].relforcerowsecurity and state[name].policies >= 1)
    ]
    assert unprotected == []


def test_every_tenant_table_is_indexed_on_tenant_id():
    owner = create_engine(os.environ["OWNER_DATABASE_URL"])
    with owner.connect() as connection:
        indexes = connection.execute(text("SELECT tablename, indexdef FROM pg_indexes WHERE schemaname = 'public'")).all()
    leading = {row.tablename for row in indexes if "(tenant_id" in row.indexdef}
    expected = {table.name for table in Base.metadata.sorted_tables} - PLATFORM_TABLES
    assert sorted(expected - leading) == []


def test_application_role_cannot_bypass_rls():
    engine = create_engine(settings.database_url)
    with engine.connect() as connection:
        row = connection.execute(
            text("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user")
        ).one()
    assert (row.rolsuper, row.rolbypassrls) == (False, False)


def test_audit_log_is_append_only(tenant):
    with tenant_tx(tenant.tenant_id) as db:
        entry = AuditLog(tenant_id=tenant.tenant_id, action="test", subject_type="x", subject_id=uuid4())
        db.add(entry)
    for statement in ("UPDATE audit_log SET action = 'tampered'", "DELETE FROM audit_log"):
        with pytest.raises(DBAPIError, match="permission denied"):
            with tenant_tx(tenant.tenant_id) as db:
                db.execute(text(statement))


def _dependency_calls(dependant):
    for dep in dependant.dependencies:
        yield dep.call
        yield from _dependency_calls(dep)


def test_every_route_declares_a_permission_or_is_explicitly_public():
    from orrfin.api import app
    from orrfin.api.deps import authenticated

    undeclared = []
    for route in app.routes:
        if not isinstance(route, APIRoute) or not route.path.startswith("/api"):
            continue
        calls = list(_dependency_calls(route.dependant))
        guarded = any(hasattr(call, "__orrfin_permission__") or call is authenticated for call in calls)
        if not guarded and not getattr(route.endpoint, "__orrfin_public__", False):
            undeclared.append(f"{sorted(route.methods)} {route.path}")
    assert undeclared == []


def test_login_lifecycle_and_csrf(tenant):
    assert tenant.get("/api/auth/me").status_code == 200

    missing_csrf = tenant.client.post("/api/auth/users", json={})
    assert missing_csrf.status_code == 403

    tenant.post("/api/auth/logout")
    assert tenant.get("/api/auth/me").status_code == 401


def test_wrong_password_is_rejected_without_revealing_the_account(tenant):
    from conftest import Api

    other = Api()
    known = other.client.post("/api/auth/login", json={"email": tenant.email, "password": "wrong-password-1"})
    unknown = other.client.post("/api/auth/login", json={"email": "nobody@orrfin-tests.example", "password": "wrong-password-1"})
    assert known.status_code == unknown.status_code == 401
    assert known.json() == unknown.json()


def test_role_limits_are_enforced(tenant):
    from conftest import PASSWORD, Api, unique_email

    email = unique_email("finance")
    created = tenant.post(
        "/api/auth/users", json={"name": "Finance", "email": email, "password": PASSWORD, "role": "finance_ap"}
    )
    assert created.status_code == 201, created.text
    finance = Api().login(email)
    assert finance.get("/api/auth/users").status_code == 403
