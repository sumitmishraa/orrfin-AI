"""Risk orchestration: assessments, manual reviews, holds, review schedule and public research."""
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlsplit
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from orrfin import risk
from orrfin.api.deps import Ctx, audit, out, owned, require
from orrfin.config import settings
from orrfin.models import RiskAssessment, RiskHold, Supplier

router = APIRouter(prefix="/api/risk", tags=["risk"])


class HoldIn(BaseModel):
    supplier_id: UUID
    scope: str = Field(pattern="^(po|payment|all)$")
    reason: str = Field(min_length=5, max_length=1000)


class ReviewIn(BaseModel):
    supplier_id: UUID
    tier: str = Field(pattern="^(low|medium|high|critical)$")
    evidence: str = Field(min_length=5, max_length=2000)
    next_review_on: date | None = None


class ResearchIn(BaseModel):
    confirm_public_search: bool


@router.get("/register")
def register(tier: str | None = None, ctx: Ctx = Depends(require("risk.read"))):
    with ctx.tx() as db:
        query = select(Supplier).where(Supplier.status.in_(("approved", "suspended", "onboarding")))
        if tier:
            query = query.where(Supplier.risk_tier == tier)
        today = datetime.now(timezone.utc).date()
        items = []
        for supplier in db.scalars(query.order_by(Supplier.risk_score.desc().nulls_last()).limit(500)):
            latest = db.scalar(select(RiskAssessment).where(RiskAssessment.supplier_id == supplier.id).order_by(RiskAssessment.created_at.desc()))
            holds = db.scalars(select(RiskHold).where(RiskHold.supplier_id == supplier.id, RiskHold.active.is_(True))).all()
            items.append(
                {
                    "supplier": out(supplier),
                    "assessment": out(latest) if latest else None,
                    "review_due": bool(latest and latest.next_review_on and latest.next_review_on <= today),
                    "active_holds": [out(hold) for hold in holds],
                }
            )
        return items


@router.post("/suppliers/{supplier_id}/assess", status_code=201)
def assess(supplier_id: UUID, ctx: Ctx = Depends(require("risk.write"))):
    with ctx.tx() as db:
        return out(risk.assess(db, ctx, owned(db, Supplier, supplier_id)))


@router.post("/reviews", status_code=201)
def manual_review(data: ReviewIn, ctx: Ctx = Depends(require("risk.write"))):
    """A reviewer's own judgement, with evidence. It overrides the rules until the next review."""
    with ctx.tx() as db:
        supplier = owned(db, Supplier, data.supplier_id)
        review_on = data.next_review_on or datetime.now(timezone.utc).date() + timedelta(days=risk.REVIEW_DAYS[data.tier])
        row = RiskAssessment(
            tenant_id=ctx.tenant_id, supplier_id=supplier.id, score=supplier.risk_score or 0, tier=data.tier,
            factors=[{"factor": "manual_review", "points": 0, "detail": data.evidence}], source="manual",
            next_review_on=review_on, assessed_by=ctx.user_name,
        )
        db.add(row)
        supplier.risk_tier = data.tier
        audit(db, ctx, "risk_reviewed", "supplier", supplier.id, tier=data.tier)
        db.flush()
        return out(row)


@router.post("/holds", status_code=201)
def place_hold(data: HoldIn, ctx: Ctx = Depends(require("risk.write"))):
    with ctx.tx() as db:
        owned(db, Supplier, data.supplier_id)
        hold = RiskHold(tenant_id=ctx.tenant_id, supplier_id=data.supplier_id, scope=data.scope, reason=data.reason, placed_by=ctx.user_name)
        db.add(hold)
        audit(db, ctx, "risk_hold_placed", "supplier", data.supplier_id, scope=data.scope, reason=data.reason)
        db.flush()
        return out(hold)


@router.post("/holds/{hold_id}/release")
def release_hold(hold_id: UUID, ctx: Ctx = Depends(require("risk.write"))):
    with ctx.tx() as db:
        hold = owned(db, RiskHold, hold_id)
        if not hold.active:
            raise HTTPException(409, "This hold is already released.")
        hold.active, hold.released_by, hold.released_at = False, ctx.user_name, datetime.now(timezone.utc)
        audit(db, ctx, "risk_hold_released", "supplier", hold.supplier_id)
        db.flush()
        return out(hold)


@router.post("/suppliers/{supplier_id}/research")
def public_research(supplier_id: UUID, data: ResearchIn, ctx: Ctx = Depends(require("risk.write"))):
    """Adverse-media search on explicit request. Results are unverified and not stored as facts."""
    if not data.confirm_public_search:
        raise HTTPException(422, "Confirm that you want to search public sources.")
    if not settings.tinyfish_api_key:
        raise HTTPException(503, "Public research isn't configured. Add TINYFISH_API_KEY on the server.")
    with ctx.tx() as db:
        supplier = owned(db, Supplier, supplier_id)
        query = f'"{supplier.name}" {supplier.address.split(",")[-1] if supplier.address else ""} fraud OR penalty OR insolvency OR GST notice'
    try:
        response = httpx.get("https://api.search.tinyfish.ai", params={"query": query, "location": "IN", "language": "en"}, headers={"X-API-Key": settings.tinyfish_api_key}, timeout=20)
        response.raise_for_status()
        results = []
        for item in response.json().get("results", [])[:10]:
            url = str(item.get("url", ""))
            parts = urlsplit(url)
            if parts.scheme in ("http", "https") and parts.hostname and not parts.username and not parts.password:
                results.append({"title": str(item.get("title", ""))[:300], "url": url[:2000], "snippet": str(item.get("snippet", ""))[:1000]})
    except (httpx.HTTPError, ValueError) as error:
        raise HTTPException(503, "Public research is unavailable right now. Try again later.") from error
    with ctx.tx() as db:
        audit(db, ctx, "public_research_requested", "supplier", supplier_id)
    return {"results": results, "status": "unverified", "notice": "These results may refer to a different business. Check identity and source before relying on them."}
