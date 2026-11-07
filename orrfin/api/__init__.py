"""FastAPI application. Routers are added here as each product module lands."""
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import DBAPIError, IntegrityError

from orrfin.api import auth
from orrfin.api.deps import public
from orrfin.config import settings
from orrfin.db import assert_safe_role


@asynccontextmanager
async def lifespan(_app: FastAPI):
    assert_safe_role()
    yield


app = FastAPI(
    title="Orrfin.ai API",
    lifespan=lifespan,
    docs_url="/api/docs" if settings.env != "production" else None,
    openapi_url="/api/openapi.json" if settings.env != "production" else None,
    redoc_url=None,
)

# Constraint names mapped to wording a buyer can act on. Unknown violations stay generic.
_CONSTRAINT_MESSAGES = {
    "no_self_approval": "You can't approve your own request.",
    "no_over_receipt": "That receipt would exceed the quantity allowed on this purchase order.",
    "no_over_billing": "That invoice would bill more than this purchase order allows.",
    "uq_invoices_supplier_number": "This supplier has already submitted an invoice with that number.",
    "uq_documents_tenant_id_sha256_subject_type_subject_id": "That file has already been uploaded here.",
}


@app.exception_handler(IntegrityError)
async def integrity_error(_request: Request, error: IntegrityError):
    text = str(error.orig)
    for name, message in _CONSTRAINT_MESSAGES.items():
        if name in text:
            return JSONResponse({"detail": message}, status_code=409)
    return JSONResponse({"detail": "That change conflicts with existing data."}, status_code=409)


@app.exception_handler(DBAPIError)
async def database_error(_request: Request, error: DBAPIError):
    # Business-rule triggers raise with SQLSTATE OR001 and a human-readable message.
    orig = error.orig
    if getattr(orig, "sqlstate", None) == "OR001":
        primary = orig.diag.message_primary if getattr(orig, "diag", None) else "That action isn't allowed."
        return JSONResponse({"detail": primary}, status_code=409)
    raise error


@app.get("/api/health")
@public
def health():
    return {"status": "ok"}


app.include_router(auth.router)
