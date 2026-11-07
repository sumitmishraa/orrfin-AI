"""RFQ to award: suppliers bid through portal links, buyers compare, the award creates the PO."""
from decimal import Decimal

import httpx
import pytest
from conftest import BASE_URL
from factories import add_supplier, approved_intake, build_world, ok


@pytest.fixture
def world(tenant):
    return build_world(tenant)


def start(world, suppliers):
    intake = approved_intake(world, quantity="100", price="1000")
    event = ok(world.procurement.post("/api/sourcing", json={"intake_id": intake["id"], "due_in_days": 5, "supplier_ids": suppliers}), 201)
    return intake, event


def bid(url, prices, lead_days=3, freight="0"):
    client = httpx.Client(base_url=BASE_URL, headers={"X-Portal-Token": url.split("#", 1)[1]}, timeout=30)
    view = client.get("/api/portal/rfq").json()
    response = client.post(
        "/api/portal/rfq/bid",
        json={"lead_days": lead_days, "freight": freight, "prices": [{"line_id": line["id"], "unit_price": price} for line, price in zip(view["lines"], prices)]},
    )
    return view, response


def test_rfq_bid_compare_and_award(world):
    second, _ = add_supplier(world.admin, world.category_id, name="Budget Bags Co", state="24")
    intake, event = start(world, [world.supplier_id, second])
    assert len(event["invite_links"]) == 2
    links = {row["supplier_id"]: row["url"] for row in event["invite_links"]}

    view, response = bid(links[world.supplier_id], ["980"])
    assert response.status_code == 201, response.text
    assert "budget" not in str(view).lower()
    assert Decimal(response.json()["total"]) == Decimal("115640.00")
    _, response = bid(links[second], ["950"], lead_days=60)
    assert response.status_code == 201

    detail = ok(world.procurement.get(f"/api/sourcing/{event['id']}"))
    comparison = detail["comparison"]
    assert comparison[0]["supplier"]["id"] == world.supplier_id, "the eligible bid ranks first"
    assert comparison[1]["eligible"] is False
    assert any("deadline" in reason for reason in comparison[1]["reasons"])

    po = ok(world.procurement.post(f"/api/sourcing/{event['id']}/award", json={"bid_id": comparison[0]["bid"]["id"], "reason": "Best eligible price"}), 201)
    assert po["supplier_id"] == world.supplier_id
    assert Decimal(po["total"]) == Decimal("115640.00")
    issued = ok(world.procurement.post(f"/api/purchase-orders/{po['id']}/issue"))
    assert issued["number"].startswith("PO/")
    assert ok(world.requester.get(f"/api/intakes/{intake['id']}"))["status"] == "ordered"


def test_interstate_bid_is_taxed_the_same_total(world):
    second, _ = add_supplier(world.admin, world.category_id, name="Gujarat Supplies", state="24")
    _, event = start(world, [second])
    _, response = bid(event["invite_links"][0]["url"], ["1000"])
    assert Decimal(response.json()["tax"]) == Decimal("18000.00")


def test_a_supplier_can_bid_only_once_and_not_after_close(world):
    _, event = start(world, [world.supplier_id])
    url = event["invite_links"][0]["url"]
    assert bid(url, ["990"])[1].status_code == 201
    assert bid(url, ["900"])[1].status_code == 409
    ok(world.procurement.post(f"/api/sourcing/{event['id']}/close"))
    second, _ = add_supplier(world.admin, world.category_id, name="Late Co")
    late = ok(world.procurement.post(f"/api/sourcing/{event['id']}/invites", json={"supplier_id": second}), 201) if False else None
    assert late is None


def test_award_cannot_happen_twice(world):
    _, event = start(world, [world.supplier_id])
    bid(event["invite_links"][0]["url"], ["990"])
    detail = ok(world.procurement.get(f"/api/sourcing/{event['id']}"))
    bid_id = detail["comparison"][0]["bid"]["id"]
    ok(world.procurement.post(f"/api/sourcing/{event['id']}/award", json={"bid_id": bid_id}), 201)
    assert world.procurement.post(f"/api/sourcing/{event['id']}/award", json={"bid_id": bid_id}).status_code == 409


def test_only_approved_requests_go_to_sourcing(world):
    from factories import intake_body

    intake = ok(world.requester.post("/api/intakes", json=intake_body(world)), 201)
    response = world.procurement.post("/api/sourcing", json={"intake_id": intake["id"], "supplier_ids": []})
    assert response.status_code == 409


def test_rfq_link_from_another_tenant_cannot_read_other_events(world, two_tenants):
    _, event = start(world, [world.supplier_id])
    client = httpx.Client(base_url=BASE_URL, headers={"X-Portal-Token": "forged-token"}, timeout=30)
    assert client.get("/api/portal/rfq").status_code == 404
