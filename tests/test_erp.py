"""ERP push through the outbox, against the contract-enforcing mock. No live ERP is involved."""
import os
import time
from decimal import Decimal

import httpx
import pytest
from factories import build_world, issued_po, ok

from orrfin.erp.tally import voucher_balance

MOCK = os.environ.get("MOCK_ERP_URL", "http://mock-erp:9100")


@pytest.fixture
def world(tenant):
    httpx.post(f"{MOCK}/_admin/reset")
    return build_world(tenant)


def connect_zoho(world, with_mappings=True):
    connection = ok(
        world.admin.post(
            "/api/erp/connections",
            json={
                "provider": "zoho",
                "mode": "mock",
                "config": {"organization_id": "60012345"},
                "credentials": {"client_id": "mock-client", "client_secret": "mock-secret", "refresh_token": "mock-refresh"},
            },
        ),
        201,
    )
    if with_mappings:
        map_all(world, connection["id"])
    return connection


def map_all(world, connection_id):
    for entity, key, external in (
        ("supplier", world.supplier_id, "460000000011111"),
        ("tax", "gst:18", "460000000022222"),
        ("tax", "igst:18", "460000000033333"),
        ("account", "purchases", "460000000044444"),
    ):
        ok(world.admin.post("/api/erp/mappings", json={"connection_id": connection_id, "entity_type": entity, "local_key": key, "external_id": external}), 201)


def wait_status(world, number, statuses=("delivered",), timeout=60):
    deadline = time.time() + timeout
    while time.time() < deadline:
        rows = [row for row in ok(world.admin.get("/api/erp/outbox")) if row["external_key"] == number]
        if rows and rows[0]["status"] in statuses:
            return rows[0]
        time.sleep(0.5)
    raise AssertionError(f"Outbox for {number} never reached {statuses}: {rows}")


def ledger(number):
    return httpx.get(f"{MOCK}/_ledger", params={"reference": number}).json()


def test_connection_test_uses_oauth_refresh(world):
    connection = connect_zoho(world)
    assert ok(world.admin.post(f"/api/erp/connections/{connection['id']}/test"))["ok"] is True


def test_credentials_are_never_returned(world):
    connect_zoho(world)
    listed = ok(world.admin.get("/api/erp/connections"))
    assert "credentials" not in str(listed).replace("has_credentials", "")
    assert listed[0]["has_credentials"] is True


def test_issued_po_is_pushed_once_with_india_gst_fields(world):
    connect_zoho(world)
    po = issued_po(world, quantity="100", price="1000")
    row = wait_status(world, po["number"])
    assert row["external_id"].startswith("4600")
    created = [item for item in ledger(po["number"])["purchaseorders"] if item["purchaseorder_number"] == po["number"]]
    assert len(created) == 1
    payload = created[0]
    assert payload["reference_number"] == po["number"]
    assert payload["gst_treatment"] == "business_gst"
    assert (payload["source_of_supply"], payload["destination_of_supply"]) == ("KA", "KA")
    assert payload["line_items"][0]["hsn_or_sac"] == "4202"
    assert payload["line_items"][0]["tax_id"] == "460000000022222"


def test_lost_response_does_not_create_a_duplicate(world):
    connect_zoho(world)
    httpx.post(f"{MOCK}/_admin/fail", json={"mode": "accept_then_error", "status": 504, "count": 1})
    po = issued_po(world)
    row = wait_status(world, po["number"], timeout=90)
    assert row["attempts"] >= 2
    outcomes = [entry["outcome"] for entry in ledger(po["number"])["requests"] if entry["method"] == "POST"]
    assert outcomes == ["created"], outcomes
    assert len([p for p in ledger(po["number"])["purchaseorders"] if p["purchaseorder_number"] == po["number"]]) == 1


def test_persistent_outage_ends_in_dead_letter_and_manual_retry_recovers(world):
    connect_zoho(world)
    httpx.post(f"{MOCK}/_admin/fail", json={"mode": "error", "status": 503, "count": 5})
    po = issued_po(world)
    row = wait_status(world, po["number"], statuses=("dead_letter",), timeout=120)
    assert "unavailable" in row["last_error"]
    ok(world.procurement.post(f"/api/erp/outbox/{row['id']}/retry"))
    assert wait_status(world, po["number"])["status"] == "delivered"


def test_missing_mapping_waits_then_delivers_once_mapped(world):
    connection = connect_zoho(world, with_mappings=False)
    po = issued_po(world)
    row = wait_status(world, po["number"], statuses=("needs_mapping",))
    assert "Map supplier" in row["last_error"]
    map_all(world, connection["id"])
    assert wait_status(world, po["number"])["status"] == "delivered"


def test_approved_invoice_is_pushed_as_a_bill(world):
    from test_invoices import process, receive, spec_for

    from factories import add_user
    from orrfin.documents.samples import render_invoice

    connect_zoho(world)
    po = issued_po(world)
    receive(world, po, "100")
    invoice = process(world, po, render_invoice(spec_for(world, po), "grid"))
    ok(add_user(world.admin, "finance_ap").post(f"/api/invoices/{invoice['id']}/approve"))
    deadline = time.time() + 60
    while time.time() < deadline:
        bills = [row for row in ok(world.admin.get("/api/erp/outbox")) if row["doc_type"] == "bill"]
        if bills and bills[0]["status"] == "delivered":
            break
        time.sleep(0.5)
    assert bills[0]["status"] == "delivered", bills
    created = ledger(invoice["number"])["bills"]
    assert [bill["bill_number"] for bill in created] == [invoice["number"]]


def test_tally_xml_balances_and_relay_delivers(world):
    connection = ok(
        world.admin.post("/api/erp/connections", json={"provider": "tally", "mode": "live", "config": {"company": "Test Retail Pvt Ltd"}}), 201
    )
    token = connection["relay_token"]
    po = issued_po(world, quantity="100", price="1000")

    xml = world.admin.get(f"/api/erp/tally/purchase_order/{po['id']}.xml")
    assert xml.status_code == 200
    assert voucher_balance(xml.text) == Decimal("0")
    assert 'VCHTYPE="Purchase Order"' in xml.text

    relay = httpx.Client(base_url=world.admin.client.base_url, headers={"X-Orrfin-Relay-Token": token})
    pending = relay.get("/api/erp/relay/pending").json()
    item = next(row for row in pending["items"] if row["external_key"] == po["number"])
    reply = httpx.post(f"{MOCK}/tally", content=item["xml"]).text
    result = relay.post(f"/api/erp/relay/{item['outbox_id']}/result", json={"response_xml": reply}).json()
    assert result["status"] == "delivered"
    assert result["external_id"]
    assert relay.get("/api/erp/relay/pending").json()["items"] == []


def test_tally_rejects_an_unbalanced_voucher():
    from datetime import date

    from orrfin.erp.tally import TallyLedgers, voucher_xml

    xml = voucher_xml(
        voucher_type="Purchase Order", ledgers=TallyLedgers(company="X"), voucher_date=date(2026, 10, 1), number="PO/1",
        reference="PO/1", party="Acme & Sons", lines=[{"description": "Bag", "quantity": Decimal("1"), "unit": "NOS", "rate": Decimal("10"), "taxable": Decimal("10"), "gst_rate": Decimal("18")}],
        cgst=Decimal("0.90"), sgst=Decimal("0.90"), igst=Decimal("0"), freight=Decimal("0"),
    )
    assert "Acme &amp; Sons" in xml
    tampered = xml.replace("<AMOUNT>11.80</AMOUNT>", "<AMOUNT>12.80</AMOUNT>")
    reply = httpx.post(f"{MOCK}/tally", content=tampered).text
    assert "<ERRORS>1</ERRORS>" in reply


def test_bad_relay_token_is_refused(world):
    response = httpx.get(f"{world.admin.client.base_url}/api/erp/relay/pending", headers={"X-Orrfin-Relay-Token": "nope"})
    assert response.status_code == 401
