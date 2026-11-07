"""Builds ERP payloads and delivers outbox rows. Called from the worker, one row per job."""
import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from orrfin.erp import tally, zoho
from orrfin.erp.zoho import ErpError, NeedsMapping
from orrfin.models import (
    Branch,
    ErpConnection,
    ErpMapping,
    ErpOutbox,
    Invoice,
    InvoiceLine,
    Item,
    LegalEntity,
    PoLine,
    PurchaseOrder,
    Supplier,
)
from orrfin.security import decrypt_credentials
from orrfin.worker import BACKOFF_SCALE, enqueue

DEAD_LETTER_AFTER = int(os.getenv("ORRFIN_ERP_MAX_ATTEMPTS", "5"))


def _mapping(db: Session, connection: ErpConnection, entity: str, key: str) -> str | None:
    return db.scalar(
        select(ErpMapping.external_id).where(
            ErpMapping.connection_id == connection.id, ErpMapping.entity_type == entity, ErpMapping.local_key == key
        )
    )


def _vendor_id(db: Session, connection: ErpConnection, supplier: Supplier) -> str:
    vendor = _mapping(db, connection, "supplier", str(supplier.id)) or _mapping(db, connection, "supplier", supplier.gstin)
    if not vendor:
        raise NeedsMapping(f"Map supplier '{supplier.name}' to a {connection.provider} vendor before pushing.")
    return vendor


def _tax_id(db: Session, connection: ErpConnection, rate: Decimal, interstate: bool) -> str:
    key = f"{'igst' if interstate else 'gst'}:{rate.normalize():f}"
    found = _mapping(db, connection, "tax", key)
    if not found:
        raise NeedsMapping(f"Map the {key.replace(':', ' ')}% tax to a Zoho tax ID before pushing.")
    return found


def zoho_po_payload(db: Session, connection: ErpConnection, po: PurchaseOrder) -> dict:
    supplier = db.get(Supplier, po.supplier_id)
    entity = db.get(LegalEntity, po.legal_entity_id)
    branch = db.get(Branch, po.branch_id)
    lines = db.scalars(select(PoLine).where(PoLine.po_id == po.id).order_by(PoLine.line_no)).all()
    states = {**zoho.STATE_CODES, **connection.config.get("state_codes", {})}
    payload = {
        "vendor_id": _vendor_id(db, connection, supplier),
        "purchaseorder_number": po.number,
        "reference_number": po.number,
        "date": po.issued_at.date().isoformat(),
        "delivery_date": po.needed_by.isoformat() if po.needed_by else None,
        "gst_treatment": "business_gst" if supplier.gstin else "business_none",
        "gst_no": supplier.gstin or None,
        "source_of_supply": states.get(supplier.state_code or supplier.gstin[:2]),
        "destination_of_supply": states.get(entity.state_code),
        "notes": f"Orrfin.ai PO, revision {po.revision}",
        "line_items": [],
    }
    if branch.erp_location_id:
        payload["location_id"] = branch.erp_location_id
    for line in lines:
        item = {
            "name": line.description[:100],
            "description": line.description,
            "hsn_or_sac": line.hsn,
            "quantity": float(line.quantity),
            "rate": float(line.unit_price),
            "unit": line.unit,
            "tax_id": _tax_id(db, connection, line.gst_rate, po.is_interstate),
            "item_order": line.line_no,
        }
        if (mapped := _mapping(db, connection, "item", line.sku)) if line.sku else None:
            item["item_id"] = mapped
        if branch.erp_location_id:
            item["location_id"] = branch.erp_location_id
        payload["line_items"].append(item)
    return {key: value for key, value in payload.items() if value is not None}


def zoho_bill_payload(db: Session, connection: ErpConnection, invoice: Invoice) -> dict:
    supplier = db.get(Supplier, invoice.supplier_id)
    po = db.get(PurchaseOrder, invoice.po_id)
    lines = db.scalars(select(InvoiceLine).where(InvoiceLine.invoice_id == invoice.id).order_by(InvoiceLine.line_no)).all()
    account = _mapping(db, connection, "account", "purchases")
    if not account:
        raise NeedsMapping("Map the purchases expense account to a Zoho account ID before pushing bills.")
    due = (invoice.invoice_date or datetime.now(timezone.utc).date()) + timedelta(days=supplier.payment_terms_days)
    return {
        "vendor_id": _vendor_id(db, connection, supplier),
        "bill_number": invoice.number,
        "reference_number": po.number,
        "date": invoice.invoice_date.isoformat() if invoice.invoice_date else None,
        "due_date": due.isoformat(),
        "gst_treatment": "business_gst",
        "gst_no": invoice.supplier_gstin,
        "line_items": [
            {
                "account_id": account,
                "description": line.description,
                "hsn_or_sac": line.hsn,
                "quantity": float(line.quantity),
                "rate": float(line.unit_price),
                "tax_id": _tax_id(db, connection, line.gst_rate if line.gst_rate is not None else _po_rate(db, line), po.is_interstate),
            }
            for line in lines
        ],
    }


def _po_rate(db: Session, line: InvoiceLine) -> Decimal:
    po_line = db.get(PoLine, line.po_line_id) if line.po_line_id else None
    return po_line.gst_rate if po_line else Decimal("18")


def tally_ledgers(connection: ErpConnection) -> tally.TallyLedgers:
    config = connection.config or {}
    return tally.TallyLedgers(
        company=config.get("company", "Company"),
        purchase_ledger_format=config.get("purchase_ledger_format", "Purchase GST {rate}%"),
        cgst=config.get("cgst_ledger", "Input CGST"),
        sgst=config.get("sgst_ledger", "Input SGST"),
        igst=config.get("igst_ledger", "Input IGST"),
        freight=config.get("freight_ledger", "Freight Inward"),
        godown=config.get("godown", "Main Location"),
    )


def tally_xml(db: Session, connection: ErpConnection, doc_type: str, doc_id: UUID) -> str:
    ledgers = tally_ledgers(connection)
    if doc_type == "purchase_order":
        po = db.get(PurchaseOrder, doc_id)
        supplier = db.get(Supplier, po.supplier_id)
        rows = db.scalars(select(PoLine).where(PoLine.po_id == po.id).order_by(PoLine.line_no)).all()
        lines = [
            {
                "description": _mapping(db, connection, "item", row.sku) or row.description,
                "quantity": row.quantity,
                "unit": row.unit,
                "rate": row.unit_price,
                "taxable": row.taxable,
                "gst_rate": row.gst_rate,
            }
            for row in rows
        ]
        return tally.voucher_xml(
            voucher_type="Purchase Order", ledgers=ledgers, voucher_date=po.issued_at.date(), number=po.number, reference=po.number,
            party=_mapping(db, connection, "supplier", str(supplier.id)) or supplier.name, lines=lines,
            cgst=po.cgst, sgst=po.sgst, igst=po.igst, freight=po.freight, due_date=po.needed_by,
        )
    invoice = db.get(Invoice, doc_id)
    supplier = db.get(Supplier, invoice.supplier_id)
    po = db.get(PurchaseOrder, invoice.po_id)
    rows = db.scalars(select(InvoiceLine).where(InvoiceLine.invoice_id == invoice.id).order_by(InvoiceLine.line_no)).all()
    lines = []
    for row in rows:
        po_line = db.get(PoLine, row.po_line_id) if row.po_line_id else None
        lines.append(
            {
                "description": (_mapping(db, connection, "item", po_line.sku) if po_line and po_line.sku else None) or row.description,
                "quantity": row.quantity,
                "unit": row.unit or (po_line.unit if po_line else "NOS"),
                "rate": row.unit_price,
                "taxable": row.taxable,
                "gst_rate": row.gst_rate if row.gst_rate is not None else (po_line.gst_rate if po_line else Decimal("18")),
            }
        )
    return tally.voucher_xml(
        voucher_type="Purchase", ledgers=ledgers, voucher_date=invoice.invoice_date, number=invoice.number, reference=po.number,
        party=_mapping(db, connection, "supplier", str(supplier.id)) or supplier.name, lines=lines,
        cgst=invoice.cgst, sgst=invoice.sgst, igst=invoice.igst, freight=invoice.freight + invoice.round_off,
    )


def _zoho_client(connection: ErpConnection) -> zoho.ZohoClient:
    config = connection.config or {}
    return zoho.ZohoClient(
        zoho.target(connection.mode, config.get("datacenter", "in")),
        decrypt_credentials(connection.credentials_encrypted),
        config.get("organization_id", ""),
    )


def _deliver_zoho(db: Session, connection: ErpConnection, row: ErpOutbox) -> tuple[str, dict]:
    client = _zoho_client(connection)
    if row.doc_type == "purchase_order":
        po = db.get(PurchaseOrder, row.doc_id)
        payload = zoho_po_payload(db, connection, po)
        row.payload = payload
        existing = client.find_purchase_order(po.number)
        if existing and row.revision == 0:
            return existing["purchaseorder_id"], {"found_existing": True}
        if existing:
            updated = client.update_purchase_order(existing["purchaseorder_id"], payload)
            return updated["purchaseorder_id"], {"updated": True}
        created = client.create_purchase_order(payload)
        return created["purchaseorder_id"], {"created": True}
    invoice = db.get(Invoice, row.doc_id)
    payload = zoho_bill_payload(db, connection, invoice)
    row.payload = payload
    existing = client.find_bill(invoice.number, payload["vendor_id"])
    if existing:
        return existing["bill_id"], {"found_existing": True}
    created = client.create_bill(payload)
    return created["bill_id"], {"created": True}


def deliver(db: Session, outbox_id: UUID) -> None:
    """Delivers one row. Transient failures raise so the worker retries with backoff."""
    row = db.scalar(select(ErpOutbox).where(ErpOutbox.id == outbox_id).with_for_update())
    if row is None or row.status in ("delivered", "dead_letter", "needs_mapping", "rejected"):
        return
    connection = db.get(ErpConnection, row.connection_id)
    row.attempts += 1
    now = datetime.now(timezone.utc)
    try:
        if connection.provider != "zoho":
            raise ErpError(f"{connection.provider} deliveries go through the relay agent.", retryable=False)
        external_id, detail = _deliver_zoho(db, connection, row)
    except NeedsMapping as error:
        row.status, row.last_error = "needs_mapping", str(error)
        return
    except ErpError as error:
        row.last_error, row.last_response = str(error), error.response
        if not error.retryable:
            row.status = "rejected"
            return
        if row.attempts >= DEAD_LETTER_AFTER:
            row.status = "dead_letter"
            return
        # Record the attempt and schedule the retry in this same transaction, so both persist together.
        row.status = "retrying"
        delay = min(300, 2 ** row.attempts) * BACKOFF_SCALE
        row.next_attempt_at = now + timedelta(seconds=delay)
        enqueue(db, row.tenant_id, "erp_deliver", delay_seconds=int(delay), outbox_id=row.id)
        return
    row.status, row.external_id, row.last_response = "delivered", external_id, detail
    row.last_error, row.delivered_at = "", now
    connection.last_success_at = now
