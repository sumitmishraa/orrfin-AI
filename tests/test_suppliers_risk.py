"""Supplier onboarding through the portal, automated checks, risk scoring, holds and their enforcement."""
import httpx
import pytest
from conftest import BASE_URL
from factories import add_user, build_world, draft_po, issued_po, make_gstin, ok

from orrfin.documents.samples import InvoiceSpec


@pytest.fixture
def world(tenant):
    return build_world(tenant)


def portal_client(url: str) -> httpx.Client:
    token = url.split("#", 1)[1]
    return httpx.Client(base_url=BASE_URL, headers={"X-Portal-Token": token}, timeout=30)


def answers(gstin: str, **overrides) -> dict:
    data = {
        "legal_name": "Monsoon Rainwear Pvt Ltd",
        "gstin": gstin,
        "pan": gstin[2:12],
        "address": "44 Textile Park, Tiruppur, Tamil Nadu",
        "contact_name": "R. Kumar",
        "contact_email": "accounts@monsoon-rainwear.example",
        "bank_account_number": "123456789012",
        "ifsc": "HDFC0001234",
        "service_cities": ["Bengaluru", "Chennai"],
        "certifications": [{"name": "ISO 9001", "expiry": "2030-01-31"}],
        "declares_no_conflict_of_interest": True,
        "accepts_code_of_conduct": True,
    }
    data.update(overrides)
    return data


def onboard(world, gstin=None, **overrides):
    supplier = ok(world.procurement.post("/api/suppliers", json={"name": "Monsoon Rainwear", "category_id": world.category_id}), 201)
    invite = ok(world.procurement.post(f"/api/suppliers/{supplier['id']}/onboarding"), 201)
    client = portal_client(invite["url"])
    assert client.get("/api/portal/onboarding").json()["supplier"] == "Monsoon Rainwear"
    submitted = client.post("/api/portal/onboarding", json=answers(gstin or make_gstin("33"), **overrides))
    return supplier, invite, client, submitted


def test_full_onboarding_through_the_portal(world):
    supplier, invite, client, submitted = onboard(world)
    assert submitted.status_code == 200, submitted.text
    checks = submitted.json()["checks"]
    assert checks["gstin"]["status"] == "pass"
    assert checks["pan_matches_gstin"]["status"] == "pass"
    assert checks["sanctions_screening"]["status"] == "not_performed"

    for kind in ("gst_certificate", "cancelled_cheque"):
        pdf = InvoiceSpec.__module__ and b"%PDF-1.4\n% sample\n"
        response = client.post("/api/portal/onboarding/documents", data={"kind": kind}, files={"file": (f"{kind}.pdf", pdf, "application/pdf")})
        assert response.status_code == 201, response.text

    approved = ok(world.procurement.post(f"/api/suppliers/onboarding/{invite['case_id']}/approve", json={"note": "Documents verified"}))
    assert approved["status"] == "approved"
    assert approved["state_code"] == "33"
    assert approved["risk"]["tier"] == "low"
    assert len(approved["documents"]) == 2
    assert client.get("/api/portal/onboarding").status_code == 404, "the link is revoked after review"


def test_bank_account_is_masked(world):
    _, invite, _, _ = onboard(world)
    case = ok(world.procurement.get(f"/api/suppliers/{ok(world.procurement.get('/api/suppliers?q=Monsoon'))['items'][0]['id']}"))["onboarding"][0]
    assert case["answers"]["bank_last4"] == "9012"
    assert "bank_account_number" not in case["answers"]


def test_pan_mismatch_and_bad_ifsc_are_flagged(world):
    _, _, _, submitted = onboard(world, pan="ABCDE1234F", ifsc="BAD")
    checks = submitted.json()["checks"]
    assert checks["pan_matches_gstin"]["status"] == "fail"
    assert checks["ifsc_format"]["status"] == "fail"


def test_invalid_gstin_cannot_be_approved(world):
    good = make_gstin("33")
    bad = good[:-1] + ("0" if good[-1] != "0" else "1")
    _, invite, _, submitted = onboard(world, gstin=bad, pan=bad[2:12])
    assert submitted.json()["checks"]["gstin"]["status"] == "fail"
    response = world.procurement.post(f"/api/suppliers/onboarding/{invite['case_id']}/approve", json={})
    assert response.status_code == 409


def test_duplicate_supplier_is_flagged(world):
    gstin = make_gstin("33")
    onboard(world, gstin=gstin)
    _, _, _, second = onboard(world, gstin=gstin)
    assert second.json()["checks"]["duplicates"]["status"] == "warn"


def test_unapproved_supplier_cannot_get_a_po(world):
    supplier = ok(world.procurement.post("/api/suppliers", json={"name": "Not Yet Ltd", "category_id": world.category_id}), 201)
    from factories import approved_intake

    intake = approved_intake(world)
    response = world.procurement.post(f"/api/intakes/{intake['id']}/purchase-order", json={"supplier_id": supplier["id"]})
    assert response.status_code == 409
    assert "isn't approved" in response.json()["detail"]


def test_risk_hold_blocks_po_issue_and_payment(world):
    risk_user = add_user(world.admin, "risk")
    po = draft_po(world)
    hold = ok(risk_user.post("/api/risk/holds", json={"supplier_id": world.supplier_id, "scope": "all", "reason": "Adverse media under review"}), 201)
    response = world.procurement.post(f"/api/purchase-orders/{po['id']}/issue")
    assert response.status_code == 409
    assert "risk hold" in response.json()["detail"]
    ok(risk_user.post(f"/api/risk/holds/{hold['id']}/release"))
    assert world.procurement.post(f"/api/purchase-orders/{po['id']}/issue").status_code == 200


def test_payment_hold_blocks_payment_but_not_matching(world):
    from test_invoices import process, receive, spec_for

    from orrfin.documents.samples import render_invoice

    po = issued_po(world)
    receive(world, po, "100")
    invoice = process(world, po, render_invoice(spec_for(world, po), "grid"))
    ok(add_user(world.admin, "finance_ap").post(f"/api/invoices/{invoice['id']}/approve"))
    risk_user = add_user(world.admin, "risk")
    ok(risk_user.post("/api/risk/holds", json={"supplier_id": world.supplier_id, "scope": "payment", "reason": "Bank details changed"}), 201)
    response = world.finance.post(f"/api/invoices/{invoice['id']}/payments", json={"amount": "100"})
    assert response.status_code == 409
    assert "payment is blocked" in response.json()["detail"]


def test_assessment_explains_every_point(world):
    risk_user = add_user(world.admin, "risk")
    assessment = ok(risk_user.post(f"/api/risk/suppliers/{world.supplier_id}/assess"), 201)
    assert assessment["score"] == sum(item["points"] for item in assessment["factors"])
    assert {"sanctions_screening", "bank_verification"} <= {item["factor"] for item in assessment["factors"]}
    assert assessment["next_review_on"]


def test_high_risk_supplier_adds_a_risk_approval_step(world):
    risk_user = add_user(world.admin, "risk")
    ok(risk_user.post("/api/risk/reviews", json={"supplier_id": world.supplier_id, "tier": "high", "evidence": "Two late deliveries and a GST notice"}), 201)
    from factories import intake_body

    intake = ok(world.requester.post("/api/intakes", json=intake_body(world)), 201)
    submitted = ok(world.requester.post(f"/api/intakes/{intake['id']}/submit"))
    assert "risk" in [task["approver_role"] for task in submitted["tasks"]]


def test_supplier_portal_po_link_shows_po_and_accepts_invoice(world):
    po = issued_po(world)
    link = ok(world.procurement.post(f"/api/purchase-orders/{po['id']}/supplier-link"), 201)
    client = portal_client(link["url"])
    assert client.get("/api/portal/po").json()["number"] == po["number"]
    pdf = client.get("/api/portal/po/pdf")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    from test_invoices import spec_for

    from orrfin.documents.samples import render_invoice

    uploaded = client.post("/api/portal/po/invoices", files={"file": ("inv.pdf", render_invoice(spec_for(world, po), "grid"), "application/pdf")})
    assert uploaded.status_code == 201, uploaded.text
    assert any(row["id"] == uploaded.json()["id"] for row in ok(world.finance.get("/api/invoices"))["items"])


def test_portal_tokens_cannot_cross_kinds(world):
    po = issued_po(world)
    link = ok(world.procurement.post(f"/api/purchase-orders/{po['id']}/supplier-link"), 201)
    client = portal_client(link["url"])
    assert client.get("/api/portal/onboarding").status_code == 404
    assert client.get("/api/portal/rfq").status_code == 404
