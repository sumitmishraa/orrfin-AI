"""Seeds a fictional multi-branch quick-commerce company with a year of realistic procurement history.

Usage (inside the stack):  python -m orrfin.seed
Idempotent: if the demo organization exists it does nothing. For a clean start, run
`docker compose down -v` and bring the stack up again.

Everything runs through the same service functions as the API, so every record passes the same
database guards: approvals, gapless numbering, receipt and billing caps, risk holds.
All names, GSTINs and people are fictional. GSTINs are checksum-valid by construction and could
coincide with real registrations, so every generated document is stamped FICTIONAL.
"""
import os
import random
import secrets
import sys
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from uuid import UUID, uuid4

from sqlalchemy import func, select

import orrfin.api  # noqa: F401  Load the app first so modules initialize in the same order as the API.
from orrfin import approvals, contracts, risk
from orrfin.api.contracts import ContractIn, create_contract
from orrfin.api.intake import IntakeIn, LineIn, create_intake, intake_po, submit_intake
from orrfin.api.sourcing import create_event, invite_supplier, price_bid
from orrfin.db import platform_tx, tenant_tx
from orrfin.documents.samples import InvoiceSpec, SpecLine, render_invoice, render_scanned
from orrfin.erp.outbox import queue_document
from orrfin.gst import STATES, fiscal_year, gstin_check_digit, money
from orrfin.models import (
    ApprovalRule,
    ApprovalTask,
    Bid,
    BidLine,
    Branch,
    Budget,
    Category,
    ContractTemplate,
    ErpConnection,
    ErpMapping,
    Invoice,
    InvoiceLine,
    Item,
    LegalEntity,
    Location,
    Membership,
    MembershipBranch,
    OnboardingCase,
    PoLine,
    PurchaseOrder,
    RiskHold,
    SourcingLine,
    Supplier,
    Tenant,
    User,
)
from orrfin.p2p import invoices as invoice_service
from orrfin.p2p import po as po_service
from orrfin.security import encrypt_credentials, hash_password

ANCHOR = date(2026, 10, 31)
SLUG = "kirnova-demo"
COMPANY = "Kirnova Quick Commerce Pvt. Ltd."
COMPANY_PAN = "AAKCK7421Q"
DOMAIN = "kirnova.example"
rng = random.Random(20261031)

HUBS = [
    ("BLR", "Bengaluru Hub", "Bengaluru", "29", ["Indiranagar", "Koramangala", "HSR Layout", "Whitefield", "Jayanagar", "Hebbal"]),
    ("HYD", "Hyderabad Hub", "Hyderabad", "36", ["Gachibowli", "Madhapur", "Kondapur", "Banjara Hills", "Kukatpally"]),
    ("MUM", "Mumbai Hub", "Mumbai", "27", ["Andheri West", "Bandra", "Powai", "Lower Parel", "Chembur", "Thane"]),
    ("PUN", "Pune Hub", "Pune", "27", ["Kothrud", "Baner", "Viman Nagar", "Hadapsar", "Wakad"]),
    ("DEL", "Delhi Hub", "New Delhi", "07", ["Saket", "Dwarka", "Rohini", "Lajpat Nagar", "Karol Bagh"]),
    ("GGN", "Gurugram Hub", "Gurugram", "06", ["DLF Phase 3", "Sohna Road", "Golf Course Road", "Sector 56"]),
    ("CHE", "Chennai Hub", "Chennai", "33", ["T Nagar", "Velachery", "Anna Nagar", "Thoraipakkam", "Adyar"]),
    ("KOL", "Kolkata Hub", "Kolkata", "19", ["Salt Lake", "New Town", "Park Street", "Behala"]),
    ("AHM", "Ahmedabad Hub", "Ahmedabad", "24", ["Satellite", "Prahlad Nagar", "Navrangpura", "Bopal"]),
    ("JAI", "Jaipur Hub", "Jaipur", "08", ["Malviya Nagar", "Vaishali Nagar", "C Scheme", "Mansarovar"]),
]

CATEGORIES = [
    ("Packaging", "4819", "18", [("Corrugated carton {}", "NOS", 18, ["small", "medium", "large", "XL"]), ("Kraft paper bag {}", "NOS", 4.5, ["small", "medium", "large"]), ("Poly mailer {}", "NOS", 3.2, ["A4", "A3"]), ("Tamper-evident tape 48mm", "ROLL", 85, None), ("Bubble wrap roll 1m x 100m", "ROLL", 1450, None), ("Food-grade container {}", "NOS", 7.5, ["250ml", "500ml", "1L"])]),
    ("Cold Chain", "3923", "18", [("Gel ice pack {}", "NOS", 42, ["250g", "500g", "1kg"]), ("EPS cool box {}", "NOS", 390, ["10L", "20L", "35L"]), ("Insulated pallet liner", "NOS", 1850, None), ("Temperature data logger", "NOS", 2400, None)]),
    ("Delivery Bags", "4202", "18", [("Insulated delivery bag {}", "NOS", 1150, ["30L", "45L"]), ("Rider backpack bag 40L", "NOS", 1320, None), ("Thermal pizza bag", "NOS", 760, None)]),
    ("Rider Gear", "6201", "12", [("Rider rain jacket {}", "NOS", 780, ["M", "L", "XL", "XXL"]), ("Reflective safety vest", "NOS", 165, None), ("Riding gloves {}", "PAIR", 240, ["M", "L"])]),
    ("Store Fixtures", "9403", "18", [("Steel storage rack 5-tier", "NOS", 6800, None), ("Picking trolley 3-shelf", "NOS", 7400, None), ("Plastic bin crate {}", "NOS", 310, ["20L", "40L"]), ("Chiller-ready wire shelf", "NOS", 3900, None)]),
    ("Housekeeping", "3402", "18", [("Floor cleaner concentrate 5L", "CAN", 620, None), ("Hand sanitiser 5L", "CAN", 890, None), ("Garbage bag {}", "PKT", 140, ["medium", "large"]), ("Mop and bucket set", "SET", 1150, None)]),
    ("POS and IT", "8471", "18", [("Handheld barcode scanner", "NOS", 14800, None), ("Thermal label printer", "NOS", 11800, None), ("Thermal label roll 100x150", "ROLL", 210, None), ("Rugged tablet 10-inch", "NOS", 26500, None)]),
    ("Electrical", "8536", "18", [("LED tube light 20W", "NOS", 245, None), ("Extension board 6-socket", "NOS", 560, None), ("UPS 1kVA", "NOS", 7900, None)]),
    ("Uniforms", "6203", "5", [("Staff T-shirt {}", "NOS", 310, ["S", "M", "L", "XL"]), ("Picker apron", "NOS", 190, None), ("Branded cap", "NOS", 120, None)]),
    ("Stationery", "4820", "12", [("Stock register book", "NOS", 145, None), ("A4 copier paper ream", "REAM", 290, None), ("Ball pen box of 50", "BOX", 260, None)]),
    ("Pest Control Services", "9985", "18", [("Monthly pest control visit", "VISIT", 2400, None), ("Rodent control service", "VISIT", 3100, None)]),
    ("Security Services", "9985", "18", [("Security guard (monthly)", "MONTH", 21500, None), ("CCTV maintenance visit", "VISIT", 1850, None)]),
]

SUPPLIER_WORDS = (
    ["Sahyadri", "Deccan", "Coromandel", "Kaveri", "Narmada", "Ganga", "Aravalli", "Konark", "Malabar", "Vindhya", "Sabarmati", "Godavari", "Tapti", "Nilgiri", "Himalaya", "Brahmaputra", "Thar", "Chola", "Satpura", "Kosi"],
    ["Packaging", "Polymers", "Cold Chain", "Supplies", "Enterprises", "Traders", "Industries", "Solutions", "Logistics", "Facility Services", "Safety", "Tech", "Agencies", "Distributors"],
)
STATE_POOL = ["29", "29", "36", "27", "27", "07", "06", "33", "19", "24", "08", "09", "32", "23"]


@dataclass
class Actor:
    tenant_id: UUID
    user_id: UUID
    user_name: str
    role: str
    branch_ids: frozenset | None = None


def gstin_for(state: str, pan: str, entity: str = "1") -> str:
    body = f"{state}{pan}{entity}Z"
    return body + gstin_check_digit(body)


def random_pan() -> str:
    letters = "ABCDEFGHJKLMNPQRSTUVWXYZ"
    return "".join(rng.choice(letters) for _ in range(3)) + "C" + rng.choice(letters) + f"{rng.randint(1000, 9999)}" + rng.choice(letters)


def when(day: date, hour: int = 11) -> datetime:
    return datetime(day.year, day.month, day.day, hour, rng.randint(0, 59), tzinfo=timezone.utc)


def create_user(db, tenant_id: UUID, email: str, name: str, role: str, password_hash: str) -> UUID:
    user = User(id=uuid4(), email=email, name=name, password_hash=password_hash)
    db.add(user)
    db.flush()
    membership = Membership(id=uuid4(), tenant_id=tenant_id, user_id=user.id, role=role)
    db.add(membership)
    db.flush()
    return user.id, membership.id


def seed_org(password: str) -> dict:
    with platform_tx() as db:
        if db.scalar(select(Tenant.id).where(Tenant.slug == SLUG)):
            print("The demo organization already exists. Nothing to do.")
            sys.exit(0)
        tenant = Tenant(id=uuid4(), name=COMPANY, slug=SLUG, settings={"fictional": True, "price_tolerance_pct": "2", "approval_tolerance_pct": "10"})
        db.add(tenant)
        db.flush()
        password_hash = hash_password(password)
        people = {"admin": [], "procurement": [], "finance_ap": [], "legal": [], "risk": [], "branch_manager": {}, "requester": {}}
        directory = [
            ("admin", "owner", "Ananya Rao (Admin)"),
            ("procurement", "procurement.lead", "Vikram Menon"), ("procurement", "buyer.packaging", "Sneha Kulkarni"), ("procurement", "buyer.facilities", "Arjun Iyer"),
            ("finance_ap", "ap.lead", "Meera Joshi"), ("finance_ap", "ap.analyst", "Rahul Bansal"), ("finance_ap", "ap.payments", "Fatima Shaikh"),
            ("legal", "legal", "Kavya Nair"), ("risk", "risk", "Dev Malhotra"),
        ]
        for role, local, name in directory:
            people[role].append((create_user(db, tenant.id, f"{local}@{DOMAIN}", name, role, password_hash), name))
        for code, hub, *_ in HUBS:
            people["branch_manager"][code] = (create_user(db, tenant.id, f"{code.lower()}.manager@{DOMAIN}", f"{hub} Manager", "branch_manager", password_hash), f"{hub} Manager")
            people["requester"][code] = [
                (create_user(db, tenant.id, f"{code.lower()}.store{n}@{DOMAIN}", f"{hub} Store Lead {n}", "requester", password_hash), f"{hub} Store Lead {n}")
                for n in (1, 2)
            ]
    return {"tenant_id": tenant.id, "people": people}


def seed_master(tenant_id: UUID, people: dict) -> dict:
    with tenant_tx(tenant_id) as db:
        entities, branches, locations = {}, {}, {}
        for code, hub, city, state, stores in HUBS:
            if state not in entities:
                gstin = gstin_for(state, COMPANY_PAN)
                entity = LegalEntity(
                    tenant_id=tenant_id, name=COMPANY, gstin=gstin, pan=COMPANY_PAN, state_code=state, state_name=STATES[state],
                    address=f"Registered office for {STATES[state]}, {city}",
                )
                db.add(entity)
                db.flush()
                entities[state] = entity
            branch = Branch(tenant_id=tenant_id, code=code, name=hub, city=city, legal_entity_id=entities[state].id, erp_location_id=f"4600000{len(branches) + 1:05d}")
            db.add(branch)
            db.flush()
            branches[code] = branch
            warehouse = Location(tenant_id=tenant_id, branch_id=branch.id, code=f"{code}-MW1", name=f"{city} Mother Warehouse", kind="warehouse", address=f"Logistics park, {city}")
            db.add(warehouse)
            locations[code] = [warehouse]
            for number, area in enumerate(stores, start=1):
                store = Location(tenant_id=tenant_id, branch_id=branch.id, code=f"{code}-DS{number:02d}", name=f"{area} Dark Store", kind="dark_store", address=f"{area}, {city}")
                db.add(store)
                locations[code].append(store)
        db.flush()

        for code in branches:
            for role in ("branch_manager", "requester"):
                entries = [people["branch_manager"][code]] if role == "branch_manager" else people["requester"][code]
                for (user_id, membership_id), _ in entries:
                    db.add(MembershipBranch(tenant_id=tenant_id, membership_id=membership_id, branch_id=branches[code].id))

        categories, items = {}, {}
        for name, hsn, rate, products in CATEGORIES:
            category = Category(tenant_id=tenant_id, name=name, default_hsn=hsn, default_gst_rate=Decimal(rate))
            db.add(category)
            db.flush()
            categories[name] = category
            items[name] = []
            for template, unit, price, variants in products:
                for variant in variants or [None]:
                    label = template.format(variant) if variant else template
                    sku = "".join(word[:3].upper() for word in label.replace("-", " ").split()[:3]) + f"-{len(items[name]) + 1:02d}"
                    item = Item(tenant_id=tenant_id, sku=sku, name=label, category_id=category.id, hsn=hsn, unit=unit, gst_rate=Decimal(rate), benchmark_price=money(Decimal(str(price))))
                    db.add(item)
                    items[name].append(item)
        db.flush()

        suppliers, used = {}, set()
        for name, *_ in CATEGORIES:
            suppliers[name] = []
            for _ in range(rng.randint(10, 14)):
                while True:
                    label = f"{rng.choice(SUPPLIER_WORDS[0])} {rng.choice(SUPPLIER_WORDS[1])}"
                    if label not in used:
                        used.add(label)
                        break
                state = rng.choice(STATE_POOL)
                pan = random_pan()
                status = "approved" if rng.random() < 0.9 else rng.choice(["onboarding", "draft"])
                supplier = Supplier(
                    tenant_id=tenant_id, name=f"{label} Pvt Ltd", gstin=gstin_for(state, pan) if status != "draft" else "", pan=pan if status != "draft" else "",
                    state_code=state if status != "draft" else "", email=f"accounts@{label.lower().replace(' ', '-')}.example", phone=f"+91 9{rng.randint(100000000, 999999999)}",
                    address=f"{rng.randint(2, 220)}, Industrial Estate, {STATES[state]}", category_id=categories[name].id, status=status,
                    preferred=rng.random() < 0.3, payment_terms_days=rng.choice([15, 30, 30, 45, 60]),
                )
                db.add(supplier)
                db.flush()
                supplier._reliability = rng.choice([0.97, 0.95, 0.92, 0.85, 0.7])  # Hidden profile driving delivery history.
                if status == "approved":
                    db.add(
                        OnboardingCase(
                            tenant_id=tenant_id, supplier_id=supplier.id, status="approved",
                            answers={"legal_name": supplier.name, "gstin": supplier.gstin, "pan": pan, "address": supplier.address, "contact_email": supplier.email,
                                     "bank_last4": f"{rng.randint(1000, 9999)}", "ifsc": f"HDFC000{rng.randint(1000, 9999)}",
                                     "certifications": [{"name": "ISO 9001", "expiry": (ANCHOR + timedelta(days=rng.randint(-20, 700))).isoformat()}]},
                            checks={"gstin": {"status": "pass", "detail": "Format and checksum valid."}, "pan_matches_gstin": {"status": "pass", "detail": "PAN matches the GSTIN."}},
                            submitted_at=when(ANCHOR - timedelta(days=400)), decided_at=when(ANCHOR - timedelta(days=395)),
                        )
                    )
                elif status == "onboarding":
                    db.add(OnboardingCase(tenant_id=tenant_id, supplier_id=supplier.id, status="invited"))
                suppliers[name].append(supplier)
        db.flush()

        rules = [
            ("Hub manager review", None, Decimal(0), 1, "branch_manager", 24),
            ("Central procurement above ₹25,000", None, Decimal(25000), 2, "procurement", 48),
            ("Finance above ₹5 lakh", None, Decimal(500000), 3, "finance_ap", 72),
        ]
        for name, category, minimum, step, role, sla in rules:
            db.add(ApprovalRule(tenant_id=tenant_id, name=name, category_id=category, min_amount=minimum, step=step, approver_role=role, sla_hours=sla))
        for year in ("2025-26", "2026-27"):
            for branch in branches.values():
                for category in categories.values():
                    db.add(Budget(tenant_id=tenant_id, branch_id=branch.id, category_id=category.id, fiscal_year=year, amount=money(Decimal(rng.randint(8, 40)) * 100000)))
        contracts.ensure_library(db, tenant_id)
        db.flush()
        return {
            "branches": {code: branch.id for code, branch in branches.items()},
            "locations": {code: [location.id for location in rows] for code, rows in locations.items()},
            "categories": {name: category.id for name, category in categories.items()},
            "items": {name: [(item.id, item.name, item.benchmark_price, item.unit) for item in rows] for name, rows in items.items()},
            "suppliers": {name: [(row.id, row.status, getattr(row, "_reliability", 0.9)) for row in rows] for name, rows in suppliers.items()},
        }


def actor(tenant_id: UUID, entry, role: str, branch_id: UUID | None = None) -> Actor:
    (user_id, _), name = entry
    return Actor(tenant_id, user_id, name, role, frozenset([branch_id]) if branch_id else None)


def approve_all(db, tenant_id: UUID, people: dict, code: str, branch_id: UUID, intake, at: datetime, reject: bool = False) -> bool:
    instance_tasks = db.scalars(
        select(ApprovalTask)
        .where(ApprovalTask.requester_id == intake.requester_id, ApprovalTask.status.in_(("pending", "waiting")))
        .where(ApprovalTask.instance_id.in_(select(approvals.ApprovalInstance.id).where(approvals.ApprovalInstance.subject_id == intake.id)))
        .order_by(ApprovalTask.step)
    ).all()
    moment = at
    for task in instance_tasks:
        moment += timedelta(hours=rng.randint(2, 20))
        if task.approver_role == "branch_manager":
            approver = actor(tenant_id, people["branch_manager"][code], "branch_manager", branch_id)
        else:
            approver = actor(tenant_id, rng.choice(people[task.approver_role]), task.approver_role)
        approvals.decide(db, approver, task.id, not reject, "Budget confirmed" if not reject else "Not needed this month", at=moment)
        if reject:
            return False
    return True


def make_invoice(db, tenant_id: UUID, po: PurchaseOrder, quantities: dict[UUID, Decimal], on: date, number: str, finance_confirm: Actor, price_bump: Decimal = Decimal(0), wrong_regime: bool = False) -> Invoice:
    supplier = db.get(Supplier, po.supplier_id)
    entity = db.get(LegalEntity, po.legal_entity_id)
    lines = db.scalars(select(PoLine).where(PoLine.po_id == po.id).order_by(PoLine.line_no)).all()
    interstate = po.is_interstate != wrong_regime
    invoice = Invoice(
        tenant_id=tenant_id, po_id=po.id, supplier_id=supplier.id, number=number, normalized_number=invoice_service.normalize_number(number),
        fiscal_year=fiscal_year(on), invoice_date=on, status="confirmed", supplier_gstin=supplier.gstin, buyer_gstin=entity.gstin,
        confirmed_by=finance_confirm.user_id, confirmed_at=when(on, 15), uploaded_by="Supplier email", created_at=when(on, 14),
    )
    db.add(invoice)
    db.flush()
    subtotal = cgst = sgst = igst = Decimal(0)
    for line in lines:
        quantity = quantities.get(line.id, Decimal(0))
        if quantity <= 0:
            continue
        price = money(line.unit_price * (1 + price_bump))
        taxable = money(quantity * price)
        subtotal += taxable
        if interstate:
            igst += money(taxable * line.gst_rate / 100)
        else:
            half = money(taxable * line.gst_rate / 200)
            cgst, sgst = cgst + half, sgst + half
        db.add(InvoiceLine(tenant_id=tenant_id, invoice_id=invoice.id, line_no=line.line_no, description=line.description, hsn=line.hsn, unit=line.unit, quantity=quantity, unit_price=price, taxable=taxable))
    exact = subtotal + cgst + sgst + igst
    total = exact.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    invoice.subtotal, invoice.cgst, invoice.sgst, invoice.igst, invoice.round_off, invoice.total = subtotal, cgst, sgst, igst, total - exact, total
    db.flush()
    invoice_service.run_match(db, finance_confirm, invoice)
    return invoice


def seed_history(tenant_id: UUID, people: dict, master: dict) -> dict:
    stats = {"intakes": 0, "rejected": 0, "pos": 0, "receipts": 0, "invoices": 0, "exceptions": 0, "paid": 0}
    first = date(ANCHOR.year - 1, ANCHOR.month + 1, 1) if ANCHOR.month < 12 else date(ANCHOR.year, 1, 1)
    month_starts = [date(first.year + (first.month - 1 + n) // 12, (first.month - 1 + n) % 12 + 1, 1) for n in range(12)]
    finance_confirm = actor(tenant_id, people["finance_ap"][1], "finance_ap")
    finance_approve = actor(tenant_id, people["finance_ap"][0], "finance_ap")
    procurement = actor(tenant_id, people["procurement"][0], "procurement")
    approved_suppliers = {name: [row for row in rows if row[1] == "approved"] for name, rows in master["suppliers"].items()}
    invoice_seq: dict[UUID, int] = {}
    started = time.time()
    for month_start in month_starts:
        for code, *_ in HUBS:
            branch_id = master["branches"][code]
            for _ in range(rng.randint(14, 24)):
                day = month_start + timedelta(days=rng.randint(0, 26))
                if day > ANCHOR - timedelta(days=2):
                    continue
                category = rng.choice(list(master["categories"]))
                candidates = approved_suppliers[category]
                if not candidates:
                    continue
                picks = rng.sample(master["items"][category], k=min(len(master["items"][category]), rng.choice([1, 1, 2, 3])))
                requester = actor(tenant_id, rng.choice(people["requester"][code]), "requester", branch_id)
                lines = []
                for item_id, name, price, unit in picks:
                    quantity = Decimal(rng.choice([5, 10, 20, 25, 40, 50, 100, 200, 300, 500])) if price < 2000 else Decimal(rng.choice([1, 2, 3, 4, 6, 10]))
                    lines.append(LineIn(item_id=item_id, quantity=quantity, estimated_price=money(price * Decimal(str(rng.uniform(0.95, 1.08)))), unit=unit))
                supplier_id, _, reliability = rng.choice(candidates)
                with tenant_tx(tenant_id) as db:
                    at = when(day, 9)
                    intake = create_intake(
                        db, requester,
                        IntakeIn(branch_id=branch_id, location_id=rng.choice(master["locations"][code]), category_id=master["categories"][category],
                                 title=f"{picks[0][1]} for {code} stores" if len(picks) == 1 else f"{category} replenishment for {code}",
                                 justification=rng.choice(["Weekly replenishment", "Stock running low", "New dark store opening", "Festive season demand", "Monsoon preparedness", "Replacing damaged stock"]),
                                 needed_by=day + timedelta(days=rng.randint(5, 14)), route="direct", preferred_supplier_id=supplier_id, lines=lines),
                        at=at,
                    )
                    submit_intake(db, requester, intake, at=at)
                    stats["intakes"] += 1
                    if rng.random() < 0.04:
                        approve_all(db, tenant_id, people, code, branch_id, intake, at, reject=True)
                        stats["rejected"] += 1
                        continue
                    approve_all(db, tenant_id, people, code, branch_id, intake, at)
                    issue_at = at + timedelta(days=1, hours=rng.randint(0, 6))
                    po = intake_po(db, procurement, intake, supplier_id, at=issue_at)
                    po = po_service.issue(db, procurement, po.id, at=issue_at)
                    stats["pos"] += 1
                    po_lines = db.scalars(select(PoLine).where(PoLine.po_id == po.id)).all()
                    lead = rng.randint(2, 6) if rng.random() < reliability else rng.randint(9, 18)
                    received_on = issue_at.date() + timedelta(days=lead)
                    if received_on >= ANCHOR - timedelta(days=1):
                        continue
                    partial = rng.random() < 0.07
                    received = {line.id: (line.quantity * Decimal("0.8")).quantize(Decimal("1")) if partial else line.quantity for line in po_lines}
                    po_service.record_receipt(db, requester, po.id, quantities=received, idempotency_key=f"seed-{po.id}", received_on=received_on,
                                              location_id=po.location_id, quality_ok=rng.random() < reliability + 0.05, note="Received at store")
                    stats["receipts"] += 1
                    invoice_on = received_on + timedelta(days=rng.randint(1, 5))
                    if invoice_on >= ANCHOR:
                        continue
                    roll = rng.random()
                    billed = dict(received)
                    bump, regime = Decimal(0), False
                    if roll < 0.05:
                        bump = Decimal("0.06")
                    elif roll < 0.08 and partial:
                        billed = {line.id: line.quantity for line in po_lines}
                    elif roll < 0.10:
                        regime = True
                    invoice_seq[supplier_id] = invoice_seq.get(supplier_id, 0) + 1
                    number = f"INV/{fiscal_year(invoice_on)}/{invoice_seq[supplier_id]:05d}"
                    invoice = make_invoice(db, tenant_id, po, billed, invoice_on, number, finance_confirm, bump, regime)
                    stats["invoices"] += 1
                    if invoice.status == "exception":
                        stats["exceptions"] += 1
                        if invoice_on > ANCHOR - timedelta(days=45) or rng.random() < 0.3:
                            continue
                        for item in db.scalars(select(invoice_service.MatchException).where(invoice_service.MatchException.invoice_id == invoice.id, invoice_service.MatchException.status == "open")):
                            invoice_service.resolve_exception(db, finance_approve, item.id, "Credit note agreed with supplier" if bump else "Reviewed with the branch")
                        if bump or regime:
                            invoice_service.reject(db, finance_approve, invoice.id, "Supplier asked to reissue the invoice")
                            continue
                    invoice_service.approve(db, finance_approve, invoice.id)
                    supplier = db.get(Supplier, supplier_id)
                    if invoice_on + timedelta(days=supplier.payment_terms_days) < ANCHOR:
                        invoice_service.record_payment(db, finance_approve, invoice.id, invoice.total, invoice_on + timedelta(days=supplier.payment_terms_days), f"UTR{rng.randint(10**9, 10**10 - 1)}", "paid")
                        stats["paid"] += 1
        print(f"  {month_start:%b %Y}: {stats['pos']} POs so far ({time.time() - started:.0f}s)", flush=True)
    return stats


def seed_live_work(tenant_id: UUID, people: dict, master: dict) -> dict:
    """Work in flight right now: approvals waiting, open RFQs, invoices awaiting review, contracts."""
    stats = {"pending_approvals": 0, "rfqs": 0, "uploaded_invoices": 0, "contracts": 0}
    procurement = actor(tenant_id, people["procurement"][1], "procurement")
    approved = {name: [row for row in rows if row[1] == "approved"] for name, rows in master["suppliers"].items()}
    today = datetime.now(timezone.utc)
    for code, *_ in HUBS:
        branch_id = master["branches"][code]
        for n in range(3):
            category = rng.choice(list(master["categories"]))
            item_id, name, price, unit = rng.choice(master["items"][category])
            requester = actor(tenant_id, rng.choice(people["requester"][code]), "requester", branch_id)
            with tenant_tx(tenant_id) as db:
                intake = create_intake(
                    db, requester,
                    IntakeIn(branch_id=branch_id, location_id=rng.choice(master["locations"][code]), category_id=master["categories"][category], title=f"{name} for {code}",
                             justification="Requested by store lead", needed_by=today.date() + timedelta(days=10), route="sourcing" if n == 2 else "direct",
                             preferred_supplier_id=None if n == 2 else rng.choice(approved[category])[0],
                             lines=[LineIn(item_id=item_id, quantity=Decimal(rng.choice([20, 50, 100])) if price < 2000 else Decimal(3), estimated_price=money(price), unit=unit)]),
                )
                submit_intake(db, requester, intake)
                stats["pending_approvals"] += 1
                if n == 2 and code in ("BLR", "MUM", "DEL", "HYD", "CHE", "PUN"):
                    approve_all(db, tenant_id, people, code, branch_id, intake, today)
                    event = create_event(db, procurement, intake, None, 5)
                    lines = db.scalars(select(SourcingLine).where(SourcingLine.event_id == event.id)).all()
                    for supplier_id, *_ in rng.sample(approved[category], k=min(3, len(approved[category]))):
                        supplier = db.get(Supplier, supplier_id)
                        invite, _ = invite_supplier(db, procurement, event, supplier)
                        prices = {line.id: money(price * Decimal(str(rng.uniform(0.9, 1.1)))) for line in lines}
                        totals = price_bid(db, event, supplier, prices, Decimal(rng.choice([0, 0, 500])))
                        bid = Bid(tenant_id=tenant_id, event_id=event.id, supplier_id=supplier_id, lead_days=rng.randint(2, 12), freight=Decimal(0),
                                  subtotal=totals["subtotal"], tax=totals["tax"], total=totals["total"], notes="Rates valid for 30 days")
                        db.add(bid)
                        db.flush()
                        for line_id, unit_price in prices.items():
                            db.add(BidLine(tenant_id=tenant_id, bid_id=bid.id, sourcing_line_id=line_id, unit_price=unit_price))
                        invite.status = "bid_submitted"
                    stats["rfqs"] += 1

    # Recent POs whose supplier invoices arrived as real PDFs, waiting for review.
    finance = actor(tenant_id, people["finance_ap"][2], "finance_ap")
    with tenant_tx(tenant_id) as db:
        recent = db.scalars(select(PurchaseOrder).where(PurchaseOrder.status.in_(("received", "partially_received"))).order_by(PurchaseOrder.issued_at.desc()).limit(400)).all()
        candidates = [po for po in recent if not db.scalar(select(Invoice.id).where(Invoice.po_id == po.id))][:36]
        layouts = ["grid", "plain", "compact", "multipage"]
        for index, po in enumerate(candidates):
            supplier = db.get(Supplier, po.supplier_id)
            entity = db.get(LegalEntity, po.legal_entity_id)
            lines = db.scalars(select(PoLine).where(PoLine.po_id == po.id).order_by(PoLine.line_no)).all()
            bump = Decimal("1.07") if index % 6 == 1 else Decimal(1)
            spec = InvoiceSpec(
                number=f"{supplier.name.split()[0][:4].upper()}/{fiscal_year()}/{7000 + index}",
                invoice_date=today.date() - timedelta(days=rng.randint(0, 3)),
                po_number=po.number,
                supplier_name=supplier.name, supplier_gstin=supplier.gstin, supplier_address=supplier.address,
                buyer_name=entity.name, buyer_gstin=entity.gstin, buyer_address=entity.address,
                place_of_supply=f"{entity.state_name} ({entity.state_code})", interstate=po.is_interstate if index % 9 != 4 else not po.is_interstate,
                lines=[SpecLine(line.description, line.qty_received if index % 6 != 3 else line.quantity, money(line.unit_price * bump), line.hsn, line.unit, line.gst_rate) for line in lines if line.qty_received > 0],
            )
            pdf = render_scanned(spec, "grid") if index % 12 == 7 else render_invoice(spec, layouts[index % 4])
            invoice_service.upload(db, finance, pdf, f"{spec.number.replace('/', '-')}.pdf", po.id, uploaded_by="Supplier email")
            stats["uploaded_invoices"] += 1

    legal = actor(tenant_id, people["legal"][0], "legal")
    with tenant_tx(tenant_id) as db:
        templates = {row.name: row.id for row in db.scalars(select(ContractTemplate))}
        top = db.execute(
            select(Supplier.id, Supplier.name, Supplier.category_id)
            .join(PurchaseOrder, PurchaseOrder.supplier_id == Supplier.id)
            .group_by(Supplier.id, Supplier.name, Supplier.category_id)
            .order_by(func.sum(PurchaseOrder.total).desc())
            .limit(28)
        ).all()
        services = {master["categories"]["Pest Control Services"], master["categories"]["Security Services"], master["categories"]["Housekeeping"]}
        for index, (supplier_id, name, category_id) in enumerate(top):
            start = ANCHOR - timedelta(days=rng.randint(200, 700))
            end = ANCHOR + timedelta(days=rng.choice([20, 35, 50, 120, 240, 400])) if index % 3 else ANCHOR + timedelta(days=rng.randint(10, 55))
            template = templates["Facility Services Agreement"] if category_id in services else templates[rng.choice(["Master Supply Agreement", "Annual Rate Contract"])]
            contract = create_contract(
                db, legal,
                ContractIn(title=f"{'Facility Services' if category_id in services else 'Supply'} Agreement - {name}", supplier_id=supplier_id, template_id=template,
                           start_on=start, end_on=end, value=money(Decimal(rng.randint(5, 60)) * 100000), auto_renew=rng.random() < 0.4, notice_days=rng.choice([30, 45, 60])),
            )
            contract.status, contract.signature_status = ("signed", "fully_signed") if index % 5 else ("review", "not_sent")
            stats["contracts"] += 1
            if index == 2:
                from orrfin.api.contracts import _add_version

                body = contracts.render_text(db, db.get(ContractTemplate, template), contract.title, {"buyer_name": COMPANY, "supplier_name": name})
                body = body.replace("each Party's total liability under this Agreement is capped at", "the Supplier shall not be liable for any loss, and the Buyer accepts unlimited liability, notwithstanding")
                body += "\nThis Agreement shall automatically renew for successive one-year terms. Payment within 7 days of invoice.\n"
                _add_version(db, legal, contract, body, "uploaded")
        db.flush()
    return stats


def seed_controls(tenant_id: UUID, people: dict) -> dict:
    risk_actor = actor(tenant_id, people["risk"][0], "risk")
    with tenant_tx(tenant_id) as db:
        assessed = 0
        for supplier in db.scalars(select(Supplier).where(Supplier.status == "approved")):
            risk.assess(db, risk_actor, supplier, ANCHOR)
            assessed += 1
        worst = db.scalars(select(Supplier).where(Supplier.status == "approved").order_by(Supplier.risk_score.desc()).limit(2)).all()
        for supplier in worst:
            db.add(RiskHold(tenant_id=tenant_id, supplier_id=supplier.id, scope="payment", reason="Bank account change request under verification", placed_by=risk_actor.user_name))

        # ERP: the mock Zoho Books stands in for the customer's ERP until real credentials are added.
        zoho = ErpConnection(
            tenant_id=tenant_id, provider="zoho", mode="mock", config={"organization_id": "60012345", "datacenter": "in"},
            credentials_encrypted=encrypt_credentials({"client_id": "mock-client", "client_secret": "mock-secret", "refresh_token": "mock-refresh"}),
        )
        tally = ErpConnection(tenant_id=tenant_id, provider="tally", mode="live", config={"company": COMPANY})
        db.add_all([zoho, tally])
        db.flush()
        for supplier in db.scalars(select(Supplier).where(Supplier.status == "approved")):
            db.add(ErpMapping(tenant_id=tenant_id, connection_id=zoho.id, entity_type="supplier", local_key=str(supplier.id), external_id=f"4600000{rng.randint(10000000, 99999999)}"))
        for rate in ("5", "12", "18", "28"):
            db.add(ErpMapping(tenant_id=tenant_id, connection_id=zoho.id, entity_type="tax", local_key=f"gst:{rate}", external_id=f"46000000{rate}111"))
            db.add(ErpMapping(tenant_id=tenant_id, connection_id=zoho.id, entity_type="tax", local_key=f"igst:{rate}", external_id=f"46000000{rate}222"))
        db.add(ErpMapping(tenant_id=tenant_id, connection_id=zoho.id, entity_type="account", local_key="purchases", external_id="460000000099999"))
        db.flush()
        recent = db.scalars(select(PurchaseOrder).where(PurchaseOrder.issued_at >= when(ANCHOR - timedelta(days=10)), PurchaseOrder.number.is_not(None))).all()
        for po in recent:
            queue_document(db, tenant_id, "purchase_order", po.id, po.revision)
        return {"assessed": assessed, "erp_queued": len(recent)}


def seed_second_tenant(password_hash: str) -> None:
    """A small unrelated organization, so cross-tenant isolation can be seen in the UI."""
    with platform_tx() as db:
        if db.scalar(select(Tenant.id).where(Tenant.slug == "northwind-demo")):
            return
        tenant = Tenant(id=uuid4(), name="Northwind Kitchens Pvt. Ltd.", slug="northwind-demo", settings={"fictional": True})
        db.add(tenant)
        db.flush()
        create_user(db, tenant.id, f"owner@northwind.example", "Northwind Admin", "admin", password_hash)
    with tenant_tx(tenant.id) as db:
        entity = LegalEntity(tenant_id=tenant.id, name="Northwind Kitchens Pvt. Ltd.", gstin=gstin_for("32", "AAPCN5521K"), pan="AAPCN5521K", state_code="32", state_name=STATES["32"], address="Kochi")
        db.add(entity)
        db.flush()
        db.add(Branch(tenant_id=tenant.id, code="KOC", name="Kochi Central Kitchen", city="Kochi", legal_entity_id=entity.id))


def main() -> None:
    password = os.environ.get("SEED_PASSWORD") or ("Demo-" + secrets.token_urlsafe(9))
    print(f"Seeding {COMPANY} (fictional)...")
    created = seed_org(password)
    tenant_id, people = created["tenant_id"], created["people"]
    master = seed_master(tenant_id, people)
    print("  Organization, 10 hubs, sites, catalogue, suppliers and approval rules created.")
    history = seed_history(tenant_id, people, master)
    live = seed_live_work(tenant_id, people, master)
    controls = seed_controls(tenant_id, people)
    seed_second_tenant(hash_password(password))
    with tenant_tx(tenant_id) as db:
        counts = {
            "sites": db.scalar(select(func.count()).select_from(Location)),
            "suppliers": db.scalar(select(func.count()).select_from(Supplier)),
            "items": db.scalar(select(func.count()).select_from(Item)),
        }
    print("\nDone.")
    print(f"  {counts['sites']} sites, {counts['suppliers']} suppliers, {counts['items']} catalogue items")
    print(f"  History: {history}")
    print(f"  In flight: {live}")
    print(f"  Controls: {controls}")
    print("\nSign-in (all users share this password; change it after first use):")
    print(f"  password: {password}")
    for local, role in (("owner", "admin"), ("procurement.lead", "procurement"), ("ap.lead", "finance AP"), ("ap.analyst", "finance AP"), ("legal", "legal"), ("risk", "risk"), ("pun.manager", "Pune hub manager"), ("pun.store1", "Pune store requester")):
        print(f"  {local}@{DOMAIN:<18} {role}")
    print(f"  owner@northwind.example    admin of a second, unrelated organization")


if __name__ == "__main__":
    main()
