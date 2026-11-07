"""Local stand-in for customer ERPs, enforcing the parts of each documented contract we rely on.

It is not Zoho or Tally. It proves our client follows our reading of their docs, and lets tests
inject failures, including "created the record but the response was lost".
"""
import secrets
import threading
from decimal import Decimal
from defusedxml import ElementTree

from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse, Response

app = FastAPI(title="Orrfin.ai mock ERP")
_lock = threading.Lock()
STATE: dict = {"tokens": set(), "purchaseorders": {}, "bills": {}, "ledger": [], "failures": [], "tally": []}
CLIENT_ID, CLIENT_SECRET, REFRESH_TOKEN = "mock-client", "mock-secret", "mock-refresh"
ORGANIZATION_ID = "60012345"
REQUIRED_PO_FIELDS = ("vendor_id", "purchaseorder_number", "line_items", "gst_treatment", "source_of_supply", "destination_of_supply")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/_admin/reset")
def reset():
    with _lock:
        for key in STATE:
            STATE[key] = set() if key == "tokens" else ({} if key in ("purchaseorders", "bills") else [])
    return {"ok": True}


@app.post("/_admin/fail")
async def fail(request: Request):
    """Queue failures: {"mode": "error"|"accept_then_error", "status": 503, "count": 1}."""
    body = await request.json()
    with _lock:
        STATE["failures"] += [{"mode": body.get("mode", "error"), "status": body.get("status", 503)}] * int(body.get("count", 1))
    return {"queued": len(STATE["failures"])}


@app.get("/_ledger")
def ledger(reference: str | None = None):
    rows = STATE["ledger"]
    if reference:
        rows = [row for row in rows if reference in str(row.get("number"))]
    return {"requests": rows, "purchaseorders": list(STATE["purchaseorders"].values()), "bills": list(STATE["bills"].values()), "tally": STATE["tally"]}


def _record(request: Request, number=None, outcome="ok"):
    STATE["ledger"].append({"method": request.method, "path": request.url.path, "number": number, "outcome": outcome})


def _auth(authorization: str | None, organization_id: str | None):
    if not authorization or not authorization.startswith("Zoho-oauthtoken "):
        return JSONResponse({"code": 57, "message": "You are not authorized to perform this operation"}, status_code=401)
    if authorization.removeprefix("Zoho-oauthtoken ") not in STATE["tokens"]:
        return JSONResponse({"code": 14, "message": "Invalid OAuth token"}, status_code=401)
    if organization_id != ORGANIZATION_ID:
        return JSONResponse({"code": 6041, "message": "Organization does not exist"}, status_code=400)
    return None


def _next_failure():
    with _lock:
        return STATE["failures"].pop(0) if STATE["failures"] else None


@app.post("/zoho-accounts/oauth/v2/token")
def token(refresh_token: str = "", client_id: str = "", client_secret: str = "", grant_type: str = ""):
    if grant_type != "refresh_token" or (refresh_token, client_id, client_secret) != (REFRESH_TOKEN, CLIENT_ID, CLIENT_SECRET):
        return JSONResponse({"error": "invalid_client"}, status_code=400)
    access = "1000." + secrets.token_hex(16)
    STATE["tokens"].add(access)
    return {"access_token": access, "api_domain": "mock", "token_type": "Bearer", "expires_in": 3600}


@app.get("/zoho/books/v3/organizations")
def organizations(organization_id: str | None = None, authorization: str | None = Header(default=None)):
    return _auth(authorization, organization_id) or {"code": 0, "organizations": [{"organization_id": ORGANIZATION_ID, "name": "Mock Books"}]}


@app.get("/zoho/books/v3/purchaseorders")
def list_pos(request: Request, organization_id: str | None = None, purchaseorder_number: str | None = None, authorization: str | None = Header(default=None)):
    if denied := _auth(authorization, organization_id):
        return denied
    _record(request, purchaseorder_number, "lookup")
    rows = [row for row in STATE["purchaseorders"].values() if purchaseorder_number in (None, row["purchaseorder_number"])]
    return {"code": 0, "purchaseorders": rows}


@app.post("/zoho/books/v3/purchaseorders")
async def create_po(request: Request, organization_id: str | None = None, ignore_auto_number_generation: str | None = None, authorization: str | None = Header(default=None)):
    if denied := _auth(authorization, organization_id):
        return denied
    body = await request.json()
    number = body.get("purchaseorder_number")
    failure = _next_failure()
    if failure and failure["mode"] == "error":
        _record(request, number, f"injected_{failure['status']}")
        return JSONResponse({"code": 1, "message": "Injected failure"}, status_code=failure["status"])
    missing = [field for field in REQUIRED_PO_FIELDS if not body.get(field)]
    if missing:
        _record(request, number, "rejected")
        return JSONResponse({"code": 4, "message": f"Missing fields: {', '.join(missing)}"}, status_code=400)
    if ignore_auto_number_generation != "true":
        return JSONResponse({"code": 4, "message": "purchaseorder_number needs ignore_auto_number_generation"}, status_code=400)
    for line in body["line_items"]:
        if not line.get("tax_id") or not line.get("hsn_or_sac") or float(line.get("quantity", 0)) <= 0:
            return JSONResponse({"code": 4, "message": "Each line needs tax_id, hsn_or_sac and a positive quantity"}, status_code=400)
    with _lock:
        if any(row["purchaseorder_number"] == number for row in STATE["purchaseorders"].values()):
            _record(request, number, "duplicate")
            return JSONResponse({"code": 1001, "message": "Purchase order number already exists"}, status_code=400)
        record = {**body, "purchaseorder_id": str(460000000000000 + len(STATE["purchaseorders"]) + 1)}
        STATE["purchaseorders"][record["purchaseorder_id"]] = record
    _record(request, number, "created")
    if failure and failure["mode"] == "accept_then_error":
        return JSONResponse({"code": 1, "message": "Gateway timeout"}, status_code=failure["status"])
    return {"code": 0, "message": "Purchase Order has been added.", "purchaseorder": record}


@app.put("/zoho/books/v3/purchaseorders/{purchaseorder_id}")
async def update_po(purchaseorder_id: str, request: Request, organization_id: str | None = None, authorization: str | None = Header(default=None)):
    if denied := _auth(authorization, organization_id):
        return denied
    if purchaseorder_id not in STATE["purchaseorders"]:
        return JSONResponse({"code": 1002, "message": "Purchase order not found"}, status_code=404)
    body = await request.json()
    STATE["purchaseorders"][purchaseorder_id].update(body)
    _record(request, body.get("purchaseorder_number"), "updated")
    return {"code": 0, "purchaseorder": STATE["purchaseorders"][purchaseorder_id]}


@app.get("/zoho/books/v3/bills")
def list_bills(request: Request, organization_id: str | None = None, bill_number: str | None = None, vendor_id: str | None = None, authorization: str | None = Header(default=None)):
    if denied := _auth(authorization, organization_id):
        return denied
    _record(request, bill_number, "lookup")
    rows = [row for row in STATE["bills"].values() if row["bill_number"] == bill_number and row["vendor_id"] == vendor_id]
    return {"code": 0, "bills": rows}


@app.post("/zoho/books/v3/bills")
async def create_bill(request: Request, organization_id: str | None = None, authorization: str | None = Header(default=None)):
    if denied := _auth(authorization, organization_id):
        return denied
    body = await request.json()
    if not body.get("vendor_id") or not body.get("bill_number") or not body.get("line_items"):
        return JSONResponse({"code": 4, "message": "vendor_id, bill_number and line_items are required"}, status_code=400)
    with _lock:
        record = {**body, "bill_id": str(470000000000000 + len(STATE["bills"]) + 1)}
        STATE["bills"][record["bill_id"]] = record
    _record(request, body["bill_number"], "created")
    return {"code": 0, "bill": record}


def _tally_reply(created: int, errors: int, message: str = "") -> Response:
    vch = str(800 + len(STATE["tally"])) if created else ""
    error = f"<LINEERROR>{message}</LINEERROR>" if message else ""
    return Response(f"<RESPONSE><CREATED>{created}</CREATED><ALTERED>0</ALTERED><LASTVCHID>{vch}</LASTVCHID><ERRORS>{errors}</ERRORS>{error}</RESPONSE>", media_type="text/xml")


@app.post("/tally")
async def tally(request: Request):
    """Behaves like Tally's XML server for the checks Tally applies to an imported voucher."""
    raw = (await request.body()).decode("utf-8")
    try:
        root = ElementTree.fromstring(raw)
    except ElementTree.ParseError:
        return _tally_reply(0, 1, "Could not parse XML")
    if root.findtext("./HEADER/TALLYREQUEST") != "Import Data" or root.findtext(".//REPORTNAME") != "Vouchers":
        return _tally_reply(0, 1, "Unknown request")
    if not root.findtext(".//SVCURRENTCOMPANY"):
        return _tally_reply(0, 1, "No company is open")
    for voucher in root.iter("VOUCHER"):
        date = voucher.findtext("DATE") or ""
        if len(date) != 8 or not date.isdigit():
            return _tally_reply(0, 1, "Voucher date is missing or not YYYYMMDD")
        amounts = [Decimal(e.findtext("AMOUNT")) for e in voucher.findall("LEDGERENTRIES.LIST")]
        amounts += [Decimal(e.findtext("AMOUNT")) for e in voucher.findall("ALLINVENTORYENTRIES.LIST")]
        if sum(amounts, Decimal(0)) != 0:
            return _tally_reply(0, 1, "Voucher totals do not match")
        STATE["tally"].append({"type": voucher.get("VCHTYPE"), "number": voucher.findtext("VOUCHERNUMBER"), "party": voucher.findtext("PARTYLEDGERNAME")})
    return _tally_reply(1, 0)
