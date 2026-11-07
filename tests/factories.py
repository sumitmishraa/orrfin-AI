"""Builds realistic scenarios through the public API, the same way a customer would."""
import secrets
from dataclasses import dataclass
from datetime import date, timedelta
from uuid import UUID

from conftest import PASSWORD, Api, unique_email
from sqlalchemy import select

from orrfin.db import tenant_tx
from orrfin.gst import gstin_check_digit
from orrfin.models import Supplier


def make_gstin(state: str, seed: str | None = None) -> str:
    letters = "".join(secrets.choice("ABCDEFGHJKLMNPQRSTUVWXYZ") for _ in range(5))
    digits = f"{secrets.randbelow(10000):04d}"
    body = f"{state}{seed or letters}{digits}F1Z"
    return body + gstin_check_digit(body)


@dataclass
class World:
    admin: Api
    entity_id: str
    branch_id: str
    branch_code: str
    location_id: str
    category_id: str
    item_id: str
    supplier_id: str
    buyer_gstin: str
    supplier_gstin: str
    requester: Api
    procurement: Api
    finance: Api


def add_user(admin: Api, role: str, branch_ids: list[str] | None = None) -> Api:
    email = unique_email(role)
    response = admin.post(
        "/api/auth/users",
        json={"name": f"{role} person", "email": email, "password": PASSWORD, "role": role, "branch_ids": branch_ids or []},
    )
    assert response.status_code == 201, response.text
    return Api().login(email)


def ok(response, status: int = 200) -> dict:
    assert response.status_code == status, f"{response.status_code}: {response.text}"
    return response.json()


def add_supplier(admin: Api, category_id: str, name: str = "Acme Packaging", state: str = "29") -> tuple[str, str]:
    """Adds an approved supplier directly in the database. Onboarding has its own tests."""
    from uuid import uuid4

    gstin = make_gstin(state)
    supplier_id = uuid4()
    with tenant_tx(admin.tenant_id) as db:
        db.add(
            Supplier(
                id=supplier_id,
                tenant_id=admin.tenant_id,
                name=name,
                gstin=gstin,
                state_code=state,
                address="12 Industrial Area",
                category_id=UUID(category_id),
                status="approved",
                preferred=True,
                risk_tier="low",
                risk_score=10,
            )
        )
    return str(supplier_id), gstin


def build_world(admin: Api, supplier_state: str = "29") -> World:
    buyer_gstin = make_gstin("29")
    entity = ok(admin.post("/api/org/legal-entities", json={"name": "Test Retail Pvt Ltd", "gstin": buyer_gstin, "address": "1 MG Road, Bengaluru"}), 201)
    code = "BLR" + secrets.token_hex(2).upper()
    branch = ok(admin.post("/api/org/branches", json={"code": code, "name": "Bengaluru Hub", "city": "Bengaluru", "legal_entity_id": entity["id"]}), 201)
    location = ok(admin.post("/api/org/locations", json={"branch_id": branch["id"], "code": code + "-DS1", "name": "Indiranagar Dark Store", "address": "100 Feet Road"}), 201)
    category = ok(admin.post("/api/org/categories", json={"name": "Packaging", "default_hsn": "4819", "default_gst_rate": "18"}), 201)
    item = ok(
        admin.post(
            "/api/org/items",
            json={"sku": "BAG-INS-30L", "name": "Insulated delivery bag 30L", "category_id": category["id"], "hsn": "4202", "unit": "NOS", "gst_rate": "18", "benchmark_price": "1200"},
        ),
        201,
    )
    supplier_id, supplier_gstin = add_supplier(admin, category["id"], state=supplier_state)
    return World(
        admin=admin,
        entity_id=entity["id"],
        branch_id=branch["id"],
        branch_code=code,
        location_id=location["id"],
        category_id=category["id"],
        item_id=item["id"],
        supplier_id=supplier_id,
        buyer_gstin=buyer_gstin,
        supplier_gstin=supplier_gstin,
        requester=add_user(admin, "requester", [branch["id"]]),
        procurement=add_user(admin, "procurement"),
        finance=add_user(admin, "finance_ap"),
    )


def intake_body(world: World, quantity: str = "100", price: str = "1000", title: str = "Insulated bags") -> dict:
    return {
        "branch_id": world.branch_id,
        "location_id": world.location_id,
        "category_id": world.category_id,
        "title": title,
        "justification": "Monsoon demand",
        "needed_by": (date.today() + timedelta(days=30)).isoformat(),
        "route": "direct",
        "preferred_supplier_id": world.supplier_id,
        "lines": [{"item_id": world.item_id, "quantity": quantity, "estimated_price": price}],
    }


def approved_intake(world: World, **kwargs) -> dict:
    intake = ok(world.requester.post("/api/intakes", json=intake_body(world, **kwargs)), 201)
    submitted = ok(world.requester.post(f"/api/intakes/{intake['id']}/submit"))
    for task in submitted["tasks"]:
        approver = world.finance if task["approver_role"] == "finance_ap" else world.procurement
        ok(approver.post(f"/api/approvals/tasks/{task['id']}/approve", json={}))
    return intake


def draft_po(world: World, **kwargs) -> dict:
    intake = approved_intake(world, **kwargs)
    return ok(world.procurement.post(f"/api/intakes/{intake['id']}/purchase-order", json={}), 201)


def issued_po(world: World, **kwargs) -> dict:
    po = draft_po(world, **kwargs)
    return ok(world.procurement.post(f"/api/purchase-orders/{po['id']}/issue"))


__all__ = ["select"]
