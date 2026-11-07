"""Per-tenant procurement policy, stored on the tenant with these defaults."""
from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from sqlalchemy.orm import Session

from orrfin.models import Tenant

DEFAULTS = {
    "qty_tolerance_pct": "0",
    "price_tolerance_pct": "2",
    "tax_tolerance_abs": "5",
    "total_tolerance_abs": "10",
    "approval_tolerance_pct": "10",
    "over_receipt_pct": "0",
    "fictional": False,
}


@dataclass(frozen=True)
class Policy:
    qty_tolerance_pct: Decimal
    price_tolerance_pct: Decimal
    tax_tolerance_abs: Decimal
    total_tolerance_abs: Decimal
    approval_tolerance_pct: Decimal
    over_receipt_pct: Decimal
    fictional: bool


def policy_for(db: Session, tenant_id: UUID) -> Policy:
    """Tenants aren't RLS-protected, so this reads inside the caller's own transaction."""
    tenant = db.get(Tenant, tenant_id)
    merged = {**DEFAULTS, **(tenant.settings or {})}
    return Policy(
        qty_tolerance_pct=Decimal(str(merged["qty_tolerance_pct"])),
        price_tolerance_pct=Decimal(str(merged["price_tolerance_pct"])),
        tax_tolerance_abs=Decimal(str(merged["tax_tolerance_abs"])),
        total_tolerance_abs=Decimal(str(merged["total_tolerance_abs"])),
        approval_tolerance_pct=Decimal(str(merged["approval_tolerance_pct"])),
        over_receipt_pct=Decimal(str(merged["over_receipt_pct"])),
        fictional=bool(merged["fictional"]),
    )
