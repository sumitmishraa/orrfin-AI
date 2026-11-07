"""Grants, row-level security and the business invariants the database enforces itself.

Revision ID: 0002
Revises: 0001
"""
from alembic import op
from sqlalchemy import text

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

PLATFORM_TABLES = {"tenants", "users", "memberships", "sessions", "portal_tokens", "job_queue", "alembic_version"}
APPEND_ONLY_TABLES = ("documents", "audit_log")

POLICY_EXPR = "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid"

INVARIANTS = r"""
CREATE FUNCTION orrfin_po_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    instance_status text;
BEGIN
    IF NEW.status IN ('issued', 'partially_received', 'received') AND NEW.total > NEW.approved_amount THEN
        RAISE EXCEPTION 'This purchase order total exceeds the approved amount. Get the change approved first.'
            USING ERRCODE = 'OR001';
    END IF;

    IF NEW.status = 'issued' AND (TG_OP = 'INSERT' OR OLD.status IS DISTINCT FROM 'issued') THEN
        IF NEW.approval_instance_id IS NULL THEN
            RAISE EXCEPTION 'A purchase order needs a completed approval before it can be issued.'
                USING ERRCODE = 'OR001';
        END IF;
        SELECT status INTO instance_status FROM approval_instances
            WHERE id = NEW.approval_instance_id AND tenant_id = NEW.tenant_id;
        IF instance_status IS DISTINCT FROM 'approved' THEN
            RAISE EXCEPTION 'This purchase order''s approval is not complete.' USING ERRCODE = 'OR001';
        END IF;
        IF EXISTS (
            SELECT 1 FROM risk_holds
            WHERE supplier_id = NEW.supplier_id AND tenant_id = NEW.tenant_id
              AND active AND scope IN ('po', 'all')
        ) THEN
            RAISE EXCEPTION 'This supplier has an active risk hold, so a purchase order can''t be issued.'
                USING ERRCODE = 'OR001';
        END IF;
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER trg_po_guard BEFORE INSERT OR UPDATE ON purchase_orders
    FOR EACH ROW EXECUTE FUNCTION orrfin_po_guard();

CREATE FUNCTION orrfin_payment_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    invoice_status text;
BEGIN
    SELECT status INTO invoice_status FROM invoices WHERE id = NEW.invoice_id AND tenant_id = NEW.tenant_id;
    IF invoice_status NOT IN ('approved', 'paid') THEN
        RAISE EXCEPTION 'Only an approved invoice can be scheduled for payment.' USING ERRCODE = 'OR001';
    END IF;
    IF EXISTS (
        SELECT 1 FROM risk_holds
        WHERE supplier_id = NEW.supplier_id AND tenant_id = NEW.tenant_id
          AND active AND scope IN ('payment', 'all')
    ) THEN
        RAISE EXCEPTION 'This supplier has an active risk hold, so payment is blocked.' USING ERRCODE = 'OR001';
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER trg_payment_guard BEFORE INSERT OR UPDATE ON payments
    FOR EACH ROW EXECUTE FUNCTION orrfin_payment_guard();

CREATE FUNCTION orrfin_grn_line_applied() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    UPDATE po_lines SET qty_received = qty_received + NEW.quantity
        WHERE id = NEW.po_line_id AND tenant_id = NEW.tenant_id;
    RETURN NEW;
END $$;

CREATE TRIGGER trg_grn_line_applied AFTER INSERT ON grn_lines
    FOR EACH ROW EXECUTE FUNCTION orrfin_grn_line_applied();

CREATE FUNCTION orrfin_allocation_applied() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    UPDATE po_lines SET qty_billed = qty_billed + NEW.quantity
        WHERE id = NEW.po_line_id AND tenant_id = NEW.tenant_id;
    RETURN NEW;
END $$;

CREATE TRIGGER trg_allocation_applied AFTER INSERT ON invoice_allocations
    FOR EACH ROW EXECUTE FUNCTION orrfin_allocation_applied();

CREATE FUNCTION orrfin_task_decided_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF OLD.status IN ('approved', 'rejected') AND
       (NEW.status IS DISTINCT FROM OLD.status OR NEW.decided_by IS DISTINCT FROM OLD.decided_by) THEN
        RAISE EXCEPTION 'This approval step has already been decided.' USING ERRCODE = 'OR001';
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER trg_task_decided_guard BEFORE UPDATE ON approval_tasks
    FOR EACH ROW EXECUTE FUNCTION orrfin_task_decided_guard();
"""


def upgrade() -> None:
    bind = op.get_bind()
    tables = [
        row[0]
        for row in bind.execute(
            text("SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename")
        )
    ]

    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO orrfin_app")
    op.execute("REVOKE ALL ON alembic_version FROM orrfin_app")
    op.execute("REVOKE DELETE ON tenants FROM orrfin_app")
    for table in APPEND_ONLY_TABLES:
        op.execute(f"REVOKE UPDATE, DELETE ON {table} FROM orrfin_app")

    for table in tables:
        if table in PLATFORM_TABLES:
            continue
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY tenant_isolation ON {table} USING ({POLICY_EXPR}) WITH CHECK ({POLICY_EXPR})")

    op.execute(INVARIANTS)


def downgrade() -> None:
    raise NotImplementedError("Restore from backup rather than removing tenant isolation.")
