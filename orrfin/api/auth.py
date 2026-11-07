"""Signup, login, sessions and user administration."""
import re
import secrets
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response
from typing import Annotated

from pydantic import BaseModel, Field, field_validator
from sqlalchemy import delete, select

from orrfin import db as database
from orrfin.api.deps import SESSION_COOKIE, Ctx, audit, authenticated, encode, load_context, public, require
from orrfin.config import settings
from orrfin.models import Branch, Membership, MembershipBranch, Tenant, User, UserSession
from orrfin.security import BRANCH_SCOPED_ROLES, PERMISSIONS, ROLES, hash_password, new_token, token_hash, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])

Email = Annotated[str, Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$", max_length=255)]

_attempts: dict[str, deque] = defaultdict(deque)
MAX_ATTEMPTS_PER_MINUTE = 20
LOCK_AFTER_FAILURES = 8
LOCK_MINUTES = 15


class PasswordModel(BaseModel):
    password: str = Field(min_length=10, max_length=200)


class SignupIn(PasswordModel):
    company: str = Field(min_length=2, max_length=200)
    name: str = Field(min_length=2, max_length=160)
    email: Email


class LoginIn(BaseModel):
    email: Email
    password: str = Field(min_length=1, max_length=200)


class UserIn(PasswordModel):
    name: str = Field(min_length=2, max_length=160)
    email: Email
    role: str
    branch_ids: list[UUID] = []

    @field_validator("role")
    @classmethod
    def role_known(cls, value: str) -> str:
        if value not in ROLES:
            raise ValueError("Unknown role.")
        return value


def _throttle(request: Request) -> None:
    ip = request.client.host if request.client else "unknown"
    now = time.monotonic()
    attempts = _attempts[ip]
    while attempts and now - attempts[0] > 60:
        attempts.popleft()
    if len(attempts) >= MAX_ATTEMPTS_PER_MINUTE:
        raise HTTPException(429, "Too many attempts. Wait a minute and try again.")
    attempts.append(now)


def _start_session(db, response: Response, user: User, tenant_id: UUID) -> str:
    token, csrf = new_token(), secrets.token_urlsafe(24)
    db.add(
        UserSession(
            token_hash=token_hash(token),
            user_id=user.id,
            tenant_id=tenant_id,
            csrf_token=csrf,
            expires_at=datetime.now(timezone.utc) + timedelta(hours=settings.session_hours),
        )
    )
    response.set_cookie(
        SESSION_COOKIE,
        token,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        max_age=settings.session_hours * 3600,
        path="/",
    )
    return csrf


def _slug(name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:60] or "org"
    return f"{base}-{secrets.token_hex(3)}"


@router.post("/signup", status_code=201)
@public
def signup(data: SignupIn, request: Request, response: Response):
    if not settings.allow_signup:
        raise HTTPException(403, "Signup is disabled on this deployment.")
    _throttle(request)
    email = data.email.lower()
    with database.platform_tx() as db:
        if db.scalar(select(User.id).where(User.email == email)):
            raise HTTPException(409, "That email already has an account. Sign in instead.")
        tenant = Tenant(id=uuid4(), name=data.company.strip(), slug=_slug(data.company), settings={})
        user = User(id=uuid4(), email=email, name=data.name.strip(), password_hash=hash_password(data.password))
        db.add_all([tenant, user])
        db.flush()
        db.add(Membership(tenant_id=tenant.id, user_id=user.id, role="admin"))
        csrf = _start_session(db, response, user, tenant.id)
    return {"csrf_token": csrf, "tenant": tenant.name, "role": "admin"}


@router.post("/login")
@public
def login(data: LoginIn, request: Request, response: Response):
    _throttle(request)
    email = data.email.lower()
    with database.platform_tx() as db:
        user = db.scalar(select(User).where(User.email == email).with_for_update())
        now = datetime.now(timezone.utc)
        locked = bool(user and user.locked_until and user.locked_until > now)
        valid = verify_password(user.password_hash if user else None, data.password)
        if user and valid and not locked and user.is_active:
            user.failed_logins, user.locked_until = 0, None
            membership = db.scalar(select(Membership).where(Membership.user_id == user.id).order_by(Membership.created_at))
            if membership is None:
                raise HTTPException(403, "This account has no organization.")
            csrf = _start_session(db, response, user, membership.tenant_id)
            return {"csrf_token": csrf, "role": membership.role}
        if user and not valid:
            user.failed_logins += 1
            if user.failed_logins >= LOCK_AFTER_FAILURES:
                user.locked_until, user.failed_logins = now + timedelta(minutes=LOCK_MINUTES), 0
    raise HTTPException(401, "Incorrect email or password.")


@router.post("/logout")
@public
def logout(response: Response, orrfin_session: str | None = Cookie(default=None)):
    if orrfin_session:
        with database.platform_tx() as db:
            db.execute(delete(UserSession).where(UserSession.token_hash == token_hash(orrfin_session)))
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"ok": True}


@router.get("/me")
def me(ctx: Ctx = Depends(authenticated)):
    with database.platform_tx() as db:
        tenant = db.get(Tenant, ctx.tenant_id)
        memberships = db.execute(
            select(Tenant.id, Tenant.name, Membership.role)
            .join(Membership, Membership.tenant_id == Tenant.id)
            .where(Membership.user_id == ctx.user_id)
        ).all()
    return {
        "user": {"id": str(ctx.user_id), "name": ctx.user_name, "email": ctx.email},
        "tenant": {"id": str(ctx.tenant_id), "name": tenant.name},
        "role": ctx.role,
        "permissions": sorted(PERMISSIONS.get(ctx.role, set())),
        "branch_ids": None if ctx.branch_ids is None else [str(item) for item in ctx.branch_ids],
        "csrf_token": ctx.csrf_token,
        "organizations": [{"id": str(row.id), "name": row.name, "role": row.role} for row in memberships],
    }


@router.get("/users")
def list_users(ctx: Ctx = Depends(require("users.manage"))):
    with database.platform_tx() as db:
        rows = db.execute(
            select(User, Membership)
            .join(Membership, Membership.user_id == User.id)
            .where(Membership.tenant_id == ctx.tenant_id)
            .order_by(User.name)
        ).all()
    with ctx.tx() as db:
        scopes = db.execute(select(MembershipBranch.membership_id, MembershipBranch.branch_id)).all()
    by_membership: dict[UUID, list[str]] = defaultdict(list)
    for membership_id, branch_id in scopes:
        by_membership[membership_id].append(str(branch_id))
    return [
        {
            "id": str(user.id),
            "name": user.name,
            "email": user.email,
            "role": membership.role,
            "branch_ids": by_membership.get(membership.id, []),
            "is_active": user.is_active,
        }
        for user, membership in rows
    ]


@router.post("/users", status_code=201)
def create_user(data: UserIn, ctx: Ctx = Depends(require("users.manage"))):
    email = data.email.lower()
    if data.role in BRANCH_SCOPED_ROLES and not data.branch_ids:
        raise HTTPException(422, "Assign at least one branch to this role.")
    with ctx.tx() as db:
        found = set(db.scalars(select(Branch.id).where(Branch.id.in_(data.branch_ids))).all()) if data.branch_ids else set()
        if found != set(data.branch_ids):
            raise HTTPException(422, "One of those branches doesn't exist.")
    with database.platform_tx() as db:
        user = db.scalar(select(User).where(User.email == email))
        if user is None:
            user = User(id=uuid4(), email=email, name=data.name.strip(), password_hash=hash_password(data.password))
            db.add(user)
            db.flush()
        elif db.scalar(select(Membership.id).where(Membership.tenant_id == ctx.tenant_id, Membership.user_id == user.id)):
            raise HTTPException(409, "That user is already in this organization.")
        membership = Membership(id=uuid4(), tenant_id=ctx.tenant_id, user_id=user.id, role=data.role)
        db.add(membership)
    with ctx.tx() as db:
        for branch_id in data.branch_ids:
            db.add(MembershipBranch(tenant_id=ctx.tenant_id, membership_id=membership.id, branch_id=branch_id))
        audit(db, ctx, "user_added", "user", user.id, role=data.role)
    return encode({"id": user.id, "email": email, "role": data.role})


__all__ = ["router", "load_context"]
