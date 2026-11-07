"""ERP outbox. Rows are written in the same transaction as the approval, then delivered by the worker."""
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from orrfin.models import ErpConnection, ErpOutbox, Invoice, PurchaseOrder
from orrfin.worker import enqueue


def external_key(db: Session, doc_type: str, doc_id: UUID) -> str:
    """A stable key the ERP stores, so a retry can find what an earlier attempt already created."""
    if doc_type == "purchase_order":
        return db.get(PurchaseOrder, doc_id).number
    invoice = db.get(Invoice, doc_id)
    return f"{invoice.normalized_number}-{str(invoice.id)[:8]}"


def queue_document(db: Session, tenant_id: UUID, doc_type: str, doc_id: UUID, revision: int = 0) -> list[ErpOutbox]:
    connections = db.scalars(select(ErpConnection).where(ErpConnection.active.is_(True))).all()
    rows = []
    for connection in connections:
        existing = db.scalar(
            select(ErpOutbox).where(
                ErpOutbox.connection_id == connection.id,
                ErpOutbox.doc_type == doc_type,
                ErpOutbox.doc_id == doc_id,
                ErpOutbox.revision == revision,
            )
        )
        if existing:
            rows.append(existing)
            continue
        row = ErpOutbox(
            tenant_id=tenant_id,
            connection_id=connection.id,
            doc_type=doc_type,
            doc_id=doc_id,
            revision=revision,
            external_key=external_key(db, doc_type, doc_id),
            status="pending",
        )
        db.add(row)
        db.flush()
        if connection.provider != "tally":
            enqueue(db, tenant_id, "erp_deliver", outbox_id=row.id)
        rows.append(row)
    return rows
