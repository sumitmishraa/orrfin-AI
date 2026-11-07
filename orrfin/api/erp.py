"""ERP connections, mappings, the delivery outbox, Tally XML and the Tally relay endpoints."""
import secrets
from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import select

from orrfin import db as database
from orrfin.api.deps import Ctx, audit, out, owned, public, require
from orrfin.config import settings
from orrfin.erp import delivery, tally, zoho
from orrfin.erp.outbox import queue_document
from orrfin.models import ErpConnection, ErpMapping, ErpOutbox, Invoice, PortalToken, PurchaseOrder
from orrfin.security import encrypt_credentials, token_hash
from orrfin.worker import enqueue

router = APIRouter(prefix="/api/erp", tags=["erp"])


class ConnectionIn(BaseModel):
    provider: str = Field(pattern="^(zoho|tally)$")
    mode: str = Field(default="live", pattern="^(live|mock)$")
    config: dict = {}
    credentials: dict[str, str] = {}


class MappingIn(BaseModel):
    connection_id: UUID
    entity_type: str = Field(pattern="^(supplier|item|tax|account)$")
    local_key: str = Field(min_length=1, max_length=120)
    external_id: str = Field(min_length=1, max_length=160)


class PushIn(BaseModel):
    doc_type: str = Field(pattern="^(purchase_order|bill)$")
    doc_id: UUID


class RelayResultIn(BaseModel):
    response_xml: str = Field(max_length=200_000)


def connection_json(row: ErpConnection) -> dict:
    return out(row, exclude=("credentials_encrypted",), has_credentials=bool(row.credentials_encrypted))


@router.get("/connections")
def list_connections(ctx: Ctx = Depends(require("erp.read"))):
    with ctx.tx() as db:
        return [connection_json(row) for row in db.scalars(select(ErpConnection))]


@router.post("/connections", status_code=201)
def create_connection(data: ConnectionIn, ctx: Ctx = Depends(require("erp.manage"))):
    if data.mode == "mock" and not settings.allow_mock_erp:
        raise HTTPException(422, "The mock ERP is disabled on this deployment.")
    if data.provider == "zoho":
        if data.mode == "live" and data.config.get("datacenter") not in zoho.DATACENTERS:
            raise HTTPException(422, "Choose your Zoho datacenter: " + ", ".join(zoho.DATACENTERS) + ".")
        if not data.config.get("organization_id"):
            raise HTTPException(422, "Enter your Zoho Books organization ID.")
        if not {"client_id", "client_secret", "refresh_token"} <= data.credentials.keys():
            raise HTTPException(422, "Zoho needs a client ID, client secret and refresh token.")
    if data.provider == "tally" and not data.config.get("company"):
        raise HTTPException(422, "Enter the Tally company name exactly as it appears in Tally.")
    relay_token = None
    with ctx.tx() as db:
        row = db.scalar(select(ErpConnection).where(ErpConnection.provider == data.provider))
        if row is None:
            row = ErpConnection(tenant_id=ctx.tenant_id, provider=data.provider)
            db.add(row)
        row.mode, row.config, row.active = data.mode, data.config, True
        row.credentials_encrypted = encrypt_credentials(data.credentials) if data.credentials else ""
        db.flush()
        audit(db, ctx, "erp_connection_saved", "erp_connection", row.id, provider=data.provider, mode=data.mode)
        result = connection_json(row)
    if data.provider == "tally":
        relay_token = secrets.token_urlsafe(32)
        with database.platform_tx() as db:
            db.add(
                PortalToken(
                    tenant_id=ctx.tenant_id, kind="tally_relay", subject_id=row.id, token_hash=token_hash(relay_token),
                    expires_at=datetime.now(timezone.utc) + timedelta(days=365),
                )
            )
        result["relay_token"] = relay_token
        result["relay_notice"] = "Copy this token now. It is shown once and lets the relay agent fetch vouchers for this organization."
    return result


@router.post("/connections/{connection_id}/test")
def test_connection(connection_id: UUID, ctx: Ctx = Depends(require("erp.manage"))):
    with ctx.tx() as db:
        connection = owned(db, ErpConnection, connection_id)
        if connection.provider != "zoho":
            raise HTTPException(422, "Test Tally from the relay agent on the Tally machine.")
        try:
            delivery._zoho_client(connection).organizations()
        except zoho.ErpError as error:
            return {"ok": False, "message": str(error)}
        return {"ok": True, "message": f"Connected to Zoho Books ({connection.mode})."}


@router.get("/mappings")
def list_mappings(connection_id: UUID, ctx: Ctx = Depends(require("erp.read"))):
    with ctx.tx() as db:
        return [out(row) for row in db.scalars(select(ErpMapping).where(ErpMapping.connection_id == connection_id))]


@router.post("/mappings", status_code=201)
def save_mapping(data: MappingIn, ctx: Ctx = Depends(require("erp.manage"))):
    with ctx.tx() as db:
        owned(db, ErpConnection, data.connection_id)
        row = db.scalar(
            select(ErpMapping).where(
                ErpMapping.connection_id == data.connection_id, ErpMapping.entity_type == data.entity_type, ErpMapping.local_key == data.local_key
            )
        )
        if row:
            row.external_id = data.external_id
        else:
            row = ErpMapping(tenant_id=ctx.tenant_id, **data.model_dump())
            db.add(row)
        # A newly added mapping unblocks rows that were waiting for it.
        for waiting in db.scalars(select(ErpOutbox).where(ErpOutbox.connection_id == data.connection_id, ErpOutbox.status == "needs_mapping")):
            waiting.status = "pending"
            enqueue(db, ctx.tenant_id, "erp_deliver", outbox_id=waiting.id)
        db.flush()
        return out(row)


@router.get("/outbox")
def list_outbox(status: str | None = None, limit: int = 100, ctx: Ctx = Depends(require("erp.read"))):
    with ctx.tx() as db:
        query = select(ErpOutbox).order_by(ErpOutbox.created_at.desc()).limit(min(limit, 500))
        if status:
            query = query.where(ErpOutbox.status == status)
        rows = db.scalars(query).all()
        connections = {row.id: row.provider for row in db.scalars(select(ErpConnection))}
        return [out(row, provider=connections.get(row.connection_id)) for row in rows]


@router.post("/outbox/{outbox_id}/retry")
def retry(outbox_id: UUID, ctx: Ctx = Depends(require("erp.push"))):
    with ctx.tx() as db:
        row = owned(db, ErpOutbox, outbox_id)
        if row.status == "delivered":
            raise HTTPException(409, "This document was already delivered.")
        row.status, row.attempts = "pending", 0
        enqueue(db, ctx.tenant_id, "erp_deliver", outbox_id=row.id)
        audit(db, ctx, "erp_retry_requested", row.doc_type, row.doc_id)
        return out(row)


@router.post("/push", status_code=201)
def push(data: PushIn, ctx: Ctx = Depends(require("erp.push"))):
    with ctx.tx() as db:
        if data.doc_type == "purchase_order":
            po = owned(db, PurchaseOrder, data.doc_id)
            if not po.number:
                raise HTTPException(409, "Issue the purchase order before pushing it.")
            revision = po.revision
        else:
            invoice = owned(db, Invoice, data.doc_id)
            if invoice.status not in ("approved", "paid"):
                raise HTTPException(409, "Approve the invoice before pushing it.")
            revision = 0
        rows = queue_document(db, ctx.tenant_id, data.doc_type, data.doc_id, revision)
        if not rows:
            raise HTTPException(409, "Connect an ERP first.")
        return [out(row) for row in rows]


@router.get("/tally/{doc_type}/{doc_id}.xml")
def tally_download(doc_type: str, doc_id: UUID, ctx: Ctx = Depends(require("erp.read"))):
    if doc_type not in ("purchase_order", "bill"):
        raise HTTPException(404, "Record not found.")
    with ctx.tx() as db:
        connection = db.scalar(select(ErpConnection).where(ErpConnection.provider == "tally"))
        if connection is None:
            raise HTTPException(409, "Connect Tally first, so the right company and ledger names are used.")
        model = PurchaseOrder if doc_type == "purchase_order" else Invoice
        document = owned(db, model, doc_id)
        if doc_type == "purchase_order" and not document.number:
            raise HTTPException(409, "Issue the purchase order first.")
        xml = delivery.tally_xml(db, connection, doc_type, doc_id)
        name = (document.number or str(doc_id)).replace("/", "-")
    return Response(xml, media_type="application/xml", headers={"Content-Disposition": f'attachment; filename="tally-{name}.xml"', "Cache-Control": "no-store"})


def _relay(token: str) -> tuple[UUID, UUID]:
    with database.platform_tx() as db:
        row = db.scalar(select(PortalToken).where(PortalToken.token_hash == token_hash(token), PortalToken.kind == "tally_relay"))
        if row is None or row.revoked or row.expires_at <= datetime.now(timezone.utc):
            raise HTTPException(401, "This relay token is invalid or revoked.")
        return row.tenant_id, row.subject_id


@router.get("/relay/pending")
@public
def relay_pending(x_orrfin_relay_token: str = Header()):
    tenant_id, connection_id = _relay(x_orrfin_relay_token)
    with database.tenant_tx(tenant_id) as db:
        connection = db.get(ErpConnection, connection_id)
        rows = db.scalars(
            select(ErpOutbox).where(ErpOutbox.connection_id == connection_id, ErpOutbox.status.in_(("pending", "retrying"))).order_by(ErpOutbox.created_at).limit(25)
        ).all()
        items = []
        for row in rows:
            if row.revision > 0:
                row.status, row.last_error = "needs_mapping", "Revised purchase orders must be updated in Tally by hand."
                continue
            xml = delivery.tally_xml(db, connection, row.doc_type, row.doc_id)
            items.append({"outbox_id": str(row.id), "doc_type": row.doc_type, "external_key": row.external_key, "xml": xml})
        return {"company": connection.config.get("company"), "items": items}


@router.post("/relay/{outbox_id}/result")
@public
def relay_result(outbox_id: UUID, data: RelayResultIn, x_orrfin_relay_token: str = Header()):
    tenant_id, connection_id = _relay(x_orrfin_relay_token)
    parsed = tally.parse_response(data.response_xml)
    with database.tenant_tx(tenant_id) as db:
        row = db.scalar(select(ErpOutbox).where(ErpOutbox.id == outbox_id, ErpOutbox.connection_id == connection_id).with_for_update())
        if row is None:
            raise HTTPException(404, "Record not found.")
        row.attempts += 1
        row.last_response = parsed
        if parsed["created"] >= 1 and parsed["errors"] == 0:
            row.status, row.external_id, row.last_error = "delivered", parsed["last_voucher_id"], ""
            row.delivered_at = datetime.now(timezone.utc)
        else:
            row.status, row.last_error = "rejected", parsed["line_error"] or "Tally reported an error."
        audit(db, None, "tally_relay_result", row.doc_type, row.doc_id, tenant_id=tenant_id, label="Tally relay", status=row.status)
        return out(row)
