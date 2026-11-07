"""The intake to purchase order chain, including the concurrency and control guarantees."""
import io
import re
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

import pdfplumber
import pytest
from factories import add_user, approved_intake, build_world, draft_po, intake_body, issued_po, ok
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from orrfin.db import tenant_tx
from orrfin.models import ApprovalTask


@pytest.fixture
def world(tenant):
    return build_world(tenant)


def test_intake_computes_tax_inclusive_total_and_budget_status(world):
    intake = ok(world.requester.post("/api/intakes", json=intake_body(world, quantity="10", price="100")), 201)
    assert Decimal(intake["estimated_total"]) == Decimal("1180.00")
    assert intake["budget_check"]["status"] == "no_budget"
    assert intake["status"] == "draft"
    assert re.fullmatch(rf"INT/{world.branch_code}/\d{{4}}-\d{{2}}/000001", intake["number"])


def test_suggestions_offer_preferred_suppliers_and_flag_overpricing(world):
    intake = ok(world.requester.post("/api/intakes", json=intake_body(world, price="2000")), 201)
    assert world.supplier_id in [row["id"] for row in intake["suggestions"]["suppliers"]]
    assert "above the benchmark" in intake["suggestions"]["price_flags"][0]["message"]


def test_requester_cannot_act_outside_their_branch(world):
    other = ok(world.admin.post("/api/org/branches", json={"code": "OTHER", "name": "Other", "city": "Mysuru", "legal_entity_id": world.entity_id}), 201)
    body = intake_body(world) | {"branch_id": other["id"], "location_id": None}
    assert world.requester.post("/api/intakes", json=body).status_code == 404


def test_self_approval_is_rejected_by_the_api(world):
    intake = ok(world.procurement.post("/api/intakes", json=intake_body(world)), 201)
    submitted = ok(world.procurement.post(f"/api/intakes/{intake['id']}/submit"))
    response = world.procurement.post(f"/api/approvals/tasks/{submitted['tasks'][0]['id']}/approve", json={})
    assert response.status_code == 409
    assert "own request" in response.json()["detail"]


def test_self_approval_is_rejected_by_the_database_even_if_code_is_bypassed(world):
    intake = ok(world.requester.post("/api/intakes", json=intake_body(world)), 201)
    submitted = ok(world.requester.post(f"/api/intakes/{intake['id']}/submit"))
    task_id = submitted["tasks"][0]["id"]
    with pytest.raises(IntegrityError, match="no_self_approval"):
        with tenant_tx(world.admin.tenant_id) as db:
            db.execute(update(ApprovalTask).where(ApprovalTask.id == task_id).values(status="approved", decided_by=world.requester.user_id))


def test_a_decided_step_cannot_be_changed(world):
    intake = ok(world.requester.post("/api/intakes", json=intake_body(world)), 201)
    submitted = ok(world.requester.post(f"/api/intakes/{intake['id']}/submit"))
    task_id = submitted["tasks"][0]["id"]
    ok(world.procurement.post(f"/api/approvals/tasks/{task_id}/approve", json={}))
    assert world.procurement.post(f"/api/approvals/tasks/{task_id}/approve", json={}).status_code == 409
    with pytest.raises(Exception, match="already been decided"):
        with tenant_tx(world.admin.tenant_id) as db:
            db.execute(update(ApprovalTask).where(ApprovalTask.id == task_id).values(status="rejected"))


def test_wrong_role_cannot_decide(world):
    legal = add_user(world.admin, "legal")
    ok(world.admin.post("/api/org/approval-rules", json={"name": "Finance only", "step": 1, "approver_role": "finance_ap"}), 201)
    intake = ok(world.requester.post("/api/intakes", json=intake_body(world)), 201)
    submitted = ok(world.requester.post(f"/api/intakes/{intake['id']}/submit"))
    response = legal.post(f"/api/approvals/tasks/{submitted['tasks'][0]['id']}/approve", json={})
    assert response.status_code == 403


def test_multi_step_rule_runs_in_order_and_rejection_stops_it(world):
    ok(world.admin.post("/api/org/approval-rules", json={"name": "Hub", "step": 1, "approver_role": "procurement"}), 201)
    ok(world.admin.post("/api/org/approval-rules", json={"name": "Large", "step": 2, "min_amount": "50000", "approver_role": "finance_ap"}), 201)
    intake = ok(world.requester.post("/api/intakes", json=intake_body(world)), 201)
    submitted = ok(world.requester.post(f"/api/intakes/{intake['id']}/submit"))
    first, second = submitted["tasks"]
    assert (first["status"], second["status"]) == ("pending", "waiting")
    assert world.finance.post(f"/api/approvals/tasks/{second['id']}/approve", json={}).status_code == 409
    ok(world.procurement.post(f"/api/approvals/tasks/{first['id']}/approve", json={}))
    response = world.finance.post(f"/api/approvals/tasks/{second['id']}/reject", json={"comment": "Too expensive"})
    assert response.status_code == 200
    assert ok(world.requester.get(f"/api/intakes/{intake['id']}"))["status"] == "rejected"


def test_rule_edits_do_not_change_an_in_flight_approval(world):
    rule = ok(world.admin.post("/api/org/approval-rules", json={"name": "Hub", "step": 1, "approver_role": "procurement"}), 201)
    intake = ok(world.requester.post("/api/intakes", json=intake_body(world)), 201)
    ok(world.requester.post(f"/api/intakes/{intake['id']}/submit"))
    ok(world.admin.post("/api/org/approval-rules", json={"name": "New step", "step": 2, "approver_role": "legal"}), 201)
    assert rule["id"]
    assert len(ok(world.requester.get(f"/api/intakes/{intake['id']}"))["tasks"]) == 1


def test_over_budget_adds_finance_approval_and_approval_commits_budget(world):
    ok(world.admin.post("/api/org/budgets", json={"branch_id": world.branch_id, "category_id": world.category_id, "amount": "1000"}), 201)
    intake = ok(world.requester.post("/api/intakes", json=intake_body(world, quantity="10", price="100")), 201)
    assert intake["budget_check"]["status"] == "over"
    submitted = ok(world.requester.post(f"/api/intakes/{intake['id']}/submit"))
    assert [task["approver_role"] for task in submitted["tasks"]] == ["procurement", "finance_ap"]

    ok(world.admin.post("/api/org/budgets", json={"branch_id": world.branch_id, "category_id": world.category_id, "amount": "100000"}), 201)
    approved_intake(world, quantity="10", price="100")
    budgets = ok(world.admin.get("/api/org/budgets"))
    assert Decimal(budgets[0]["committed"]) == Decimal("1180.00")


def test_intrastate_po_splits_cgst_and_sgst(tenant):
    world = build_world(tenant, supplier_state="29")
    po = draft_po(world, quantity="100", price="1000")
    assert po["is_interstate"] is False
    assert (Decimal(po["cgst"]), Decimal(po["sgst"]), Decimal(po["igst"])) == (Decimal("9000.00"), Decimal("9000.00"), Decimal("0.00"))
    assert Decimal(po["total"]) == Decimal("118000.00")


def test_interstate_po_uses_igst(tenant):
    world = build_world(tenant, supplier_state="24")
    po = draft_po(world, quantity="100", price="1000")
    assert po["is_interstate"] is True
    assert (Decimal(po["cgst"]), Decimal(po["igst"])) == (Decimal("0.00"), Decimal("18000.00"))


def test_po_cannot_be_created_before_approval(world):
    intake = ok(world.requester.post("/api/intakes", json=intake_body(world)), 201)
    response = world.procurement.post(f"/api/intakes/{intake['id']}/purchase-order", json={})
    assert response.status_code == 409


def test_database_refuses_to_issue_a_po_without_completed_approval(world):
    from orrfin.models import PurchaseOrder

    po = draft_po(world)
    with pytest.raises(Exception, match="needs a completed approval"):
        with tenant_tx(world.admin.tenant_id) as db:
            db.execute(update(PurchaseOrder).where(PurchaseOrder.id == po["id"]).values(status="issued", approval_instance_id=None))


def test_price_above_approved_amount_blocks_issue(world):
    intake = approved_intake(world, quantity="10", price="100")
    high = ok(world.requester.get(f"/api/intakes/{intake['id']}"))["lines"][0]["id"]
    po = ok(world.procurement.post(f"/api/intakes/{intake['id']}/purchase-order", json={"prices": {high: "500"}}), 201)
    response = world.procurement.post(f"/api/purchase-orders/{po['id']}/issue")
    assert response.status_code == 409
    assert "exceeds the approved amount" in response.json()["detail"]


def test_po_numbers_are_gapless_under_parallel_issue(world):
    drafts = [draft_po(world, quantity="1", price="10") for _ in range(50)]

    def issue(po):
        return world.procurement.post(f"/api/purchase-orders/{po['id']}/issue")

    with ThreadPoolExecutor(max_workers=16) as pool:
        responses = list(pool.map(issue, drafts))
    assert [response.status_code for response in responses] == [200] * 50
    numbers = sorted(int(response.json()["number"].rsplit("/", 1)[1]) for response in responses)
    assert numbers == list(range(1, 51))


def test_a_failed_issue_does_not_consume_a_number(world):
    intake = approved_intake(world, quantity="10", price="100")
    line_id = ok(world.requester.get(f"/api/intakes/{intake['id']}"))["lines"][0]["id"]
    blocked = ok(world.procurement.post(f"/api/intakes/{intake['id']}/purchase-order", json={"prices": {line_id: "500"}}), 201)
    assert world.procurement.post(f"/api/purchase-orders/{blocked['id']}/issue").status_code == 409
    assert issued_po(world, quantity="1", price="10")["number"].endswith("/000001")


def test_downloaded_po_pdf_round_trips_with_rupee_sign(world):
    po = issued_po(world, quantity="100", price="1000")
    response = world.procurement.get(f"/api/purchase-orders/{po['id']}/pdf")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert "attachment" in response.headers["content-disposition"]
    with pdfplumber.open(io.BytesIO(response.content)) as pdf:
        text = "\n".join(page.extract_text() for page in pdf.pages)
    assert po["number"] in text
    assert world.buyer_gstin in text and world.supplier_gstin in text
    assert "₹1,18,000.00" in text
    assert "Insulated delivery bag 30L" in text
    assert "CGST" in text and "SGST" in text


def test_repeat_download_returns_identical_bytes_and_one_document(world):
    from orrfin.models import Document

    po = issued_po(world)
    first = world.procurement.get(f"/api/purchase-orders/{po['id']}/pdf").content
    second = world.procurement.get(f"/api/purchase-orders/{po['id']}/pdf").content
    assert first == second
    with tenant_tx(world.admin.tenant_id) as db:
        assert len(db.scalars(select(Document).where(Document.subject_id == po["id"])).all()) == 1


def test_draft_po_has_no_pdf(world):
    po = draft_po(world)
    assert world.procurement.get(f"/api/purchase-orders/{po['id']}/pdf").status_code == 409


def test_pdf_is_invisible_across_tenants(world):
    from factories import build_world as build
    from conftest import new_tenant

    po = issued_po(world)
    other = build(new_tenant("Other"))
    assert other.procurement.get(f"/api/purchase-orders/{po['id']}/pdf").status_code == 404


def test_partial_receipt_then_over_receipt_is_rejected(world):
    po = issued_po(world, quantity="100", price="10")
    detail = ok(world.procurement.get(f"/api/purchase-orders/{po['id']}"))
    line = detail["lines"][0]["id"]
    ok(world.requester.post(f"/api/purchase-orders/{po['id']}/receipts", json={"lines": [{"po_line_id": line, "quantity": "80"}]}), 201)
    assert ok(world.procurement.get(f"/api/purchase-orders/{po['id']}"))["status"] == "partially_received"
    response = world.requester.post(f"/api/purchase-orders/{po['id']}/receipts", json={"lines": [{"po_line_id": line, "quantity": "21"}]})
    assert response.status_code == 409
    assert "exceed" in response.json()["detail"]
    assert Decimal(ok(world.procurement.get(f"/api/purchase-orders/{po['id']}"))["lines"][0]["qty_received"]) == Decimal("80.000")


def test_concurrent_receipts_cannot_exceed_the_po(world):
    po = issued_po(world, quantity="100", price="10")
    line = ok(world.procurement.get(f"/api/purchase-orders/{po['id']}"))["lines"][0]["id"]

    def receive(_):
        return world.requester.post(f"/api/purchase-orders/{po['id']}/receipts", json={"lines": [{"po_line_id": line, "quantity": "40"}]}).status_code

    with ThreadPoolExecutor(max_workers=6) as pool:
        statuses = list(pool.map(receive, range(6)))
    assert statuses.count(201) == 2
    assert statuses.count(409) == 4
    assert Decimal(ok(world.procurement.get(f"/api/purchase-orders/{po['id']}"))["lines"][0]["qty_received"]) == Decimal("80.000")


def test_receipt_retry_with_same_key_is_not_double_counted(world):
    po = issued_po(world, quantity="100", price="10")
    line = ok(world.procurement.get(f"/api/purchase-orders/{po['id']}"))["lines"][0]["id"]
    body = {"lines": [{"po_line_id": line, "quantity": "10"}], "idempotency_key": "retry-key-0001"}
    first = ok(world.requester.post(f"/api/purchase-orders/{po['id']}/receipts", json=body), 201)
    second = ok(world.requester.post(f"/api/purchase-orders/{po['id']}/receipts", json=body), 201)
    assert first["id"] == second["id"]
    assert Decimal(ok(world.procurement.get(f"/api/purchase-orders/{po['id']}"))["lines"][0]["qty_received"]) == Decimal("10.000")


def test_change_within_approved_amount_applies_and_revises_pdf(world):
    po = issued_po(world, quantity="100", price="100")
    detail = ok(world.procurement.get(f"/api/purchase-orders/{po['id']}"))
    first_pdf = world.procurement.get(f"/api/purchase-orders/{po['id']}/pdf").content
    changed = ok(
        world.procurement.post(
            f"/api/purchase-orders/{po['id']}/change-order",
            json={"reason": "Reduced demand", "lines": [{"line_id": detail["lines"][0]["id"], "quantity": "90"}]},
        )
    )
    assert changed["revision"] == 1
    assert Decimal(changed["total"]) == Decimal("10620.00")
    assert world.procurement.get(f"/api/purchase-orders/{po['id']}/pdf").content != first_pdf


def test_change_above_approved_amount_needs_new_approval(world):
    po = issued_po(world, quantity="100", price="100")
    detail = ok(world.procurement.get(f"/api/purchase-orders/{po['id']}"))
    changed = ok(
        world.procurement.post(
            f"/api/purchase-orders/{po['id']}/change-order",
            json={"reason": "Bigger order", "lines": [{"line_id": detail["lines"][0]["id"], "quantity": "500"}]},
        )
    )
    assert changed["status"] == "change_pending"
    assert Decimal(changed["total"]) == Decimal("11800.00")

    other_reviewer = add_user(world.admin, "procurement")
    queue = ok(other_reviewer.get("/api/approvals/queue"))
    task = next(row for row in queue if row["subject_id"] == po["id"])
    ok(other_reviewer.post(f"/api/approvals/tasks/{task['id']}/approve", json={}))
    after = ok(world.procurement.get(f"/api/purchase-orders/{po['id']}"))
    assert (after["status"], after["revision"]) == ("issued", 1)
    assert Decimal(after["total"]) == Decimal("59000.00")
    assert Decimal(after["approved_amount"]) == Decimal("59000.00")


def test_change_cannot_go_below_received_quantity(world):
    po = issued_po(world, quantity="100", price="10")
    line = ok(world.procurement.get(f"/api/purchase-orders/{po['id']}"))["lines"][0]["id"]
    ok(world.requester.post(f"/api/purchase-orders/{po['id']}/receipts", json={"lines": [{"po_line_id": line, "quantity": "60"}]}), 201)
    response = world.procurement.post(
        f"/api/purchase-orders/{po['id']}/change-order", json={"reason": "Cut", "lines": [{"line_id": line, "quantity": "50"}]}
    )
    assert response.status_code == 422


def test_full_audit_trail_is_recorded(world):
    po = issued_po(world)
    trail = ok(world.admin.get(f"/api/org/audit?subject_id={po['id']}"))
    assert {"po_drafted", "po_issued"} <= {row["action"] for row in trail}
