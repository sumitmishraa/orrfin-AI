"""Supplier memory through Hindsight. Optional: the product works fully without it.

Only structured events are retained (supplier id, event type, source record number), never
document text or personal data. Recall results are shown only when they cite a source record
that really exists for that supplier, so memory can't introduce unsupported claims.
"""
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from orrfin.config import settings
from orrfin.models import MemoryOutbox, Supplier


def configured() -> bool:
    return bool(settings.hindsight_api_key)


def _client():
    from hindsight_client import Hindsight

    return Hindsight(base_url=settings.hindsight_api_url, api_key=settings.hindsight_api_key, timeout=8)


def bank(tenant_id: UUID) -> str:
    return f"orrfin-{tenant_id}"


def deliver_pending(db: Session, tenant_id: UUID, limit: int = 50) -> dict:
    rows = db.scalars(select(MemoryOutbox).where(MemoryOutbox.status.in_(("pending", "failed"))).limit(limit)).all()
    if not configured():
        return {"status": "not_configured", "pending": len(rows)}
    client, sent = _client(), 0
    for row in rows:
        supplier = db.get(Supplier, row.supplier_id)
        try:
            client.retain(
                bank_id=bank(tenant_id),
                document_id=str(row.id),
                content=f"Supplier {supplier.id} ({supplier.name}): procurement event {row.event_type}; source record {row.source_id}.",
            )
            row.status = "submitted"
            sent += 1
        except Exception:  # Memory is best-effort; a failure is retried on the next scan.
            row.status = "failed"
    return {"status": "submitted", "sent": sent}


def recall(db: Session, tenant_id: UUID, supplier: Supplier) -> dict:
    if not configured():
        return {"status": "not_configured", "evidence": []}
    known = {row.source_id: row.event_type for row in db.scalars(select(MemoryOutbox).where(MemoryOutbox.supplier_id == supplier.id, MemoryOutbox.status == "submitted"))}
    if not known:
        return {"status": "no_history", "evidence": []}
    try:
        result = _client().recall(bank_id=bank(tenant_id), query=f"Verified procurement outcomes for supplier {supplier.id} {supplier.name}, with source record numbers.")
    except Exception:
        return {"status": "unavailable", "evidence": []}
    evidence = []
    for item in getattr(result, "results", []) or []:
        text = str(getattr(item, "text", ""))
        for source, event in known.items():
            if source in text and str(supplier.id) in text:
                evidence.append({"source": source, "event": event.replace("_", " "), "text": text[:300]})
    return {"status": "available", "evidence": evidence[:5]}
