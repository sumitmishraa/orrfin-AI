"""Passwords, opaque tokens, credential encryption and the role-permission map."""
import base64
import hashlib
import json
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from cryptography.fernet import Fernet

from orrfin.config import settings

_hasher = PasswordHasher()
_DUMMY_HASH = _hasher.hash(secrets.token_urlsafe(16))

ROLES = ("requester", "branch_manager", "procurement", "finance_ap", "legal", "risk", "admin")

# Roles limited to the branches assigned on their membership.
BRANCH_SCOPED_ROLES = {"requester", "branch_manager"}

_READ = {
    "org.read",
    "intake.read",
    "approvals.read",
    "suppliers.read",
    "sourcing.read",
    "po.read",
    "invoice.read",
    "contracts.read",
    "risk.read",
    "concierge.use",
}

PERMISSIONS: dict[str, set[str]] = {
    "requester": {"org.read", "intake.read", "intake.write", "po.read", "grn.write", "suppliers.read", "concierge.use"},
    "branch_manager": _READ | {"intake.write", "approvals.decide", "grn.write"},
    "procurement": _READ
    | {
        "intake.write",
        "approvals.decide",
        "suppliers.write",
        "sourcing.write",
        "po.write",
        "grn.write",
        "contracts.write",
        "erp.push",
    },
    "finance_ap": _READ | {"approvals.decide", "invoice.write", "invoice.approve", "payment.write", "erp.push", "erp.read"},
    "legal": _READ | {"approvals.decide", "contracts.write", "contracts.approve"},
    "risk": _READ | {"approvals.decide", "risk.write", "suppliers.write"},
}
PERMISSIONS["admin"] = set().union(*PERMISSIONS.values()) | {"org.write", "users.manage", "erp.manage", "ai.manage", "audit.read", "erp.read"}
PERMISSIONS["procurement"] |= {"erp.read", "audit.read"}


def has_permission(role: str, permission: str) -> bool:
    return permission in PERMISSIONS.get(role, set())


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(stored_hash: str | None, password: str) -> bool:
    """Verifies against a dummy hash for unknown users so timing doesn't reveal which emails exist."""
    try:
        return _hasher.verify(stored_hash or _DUMMY_HASH, password) and stored_hash is not None
    except (VerificationError, InvalidHashError):
        return False


def new_token() -> str:
    return secrets.token_urlsafe(32)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _fernet() -> Fernet:
    digest = hashlib.sha256(settings.secret_key.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_credentials(values: dict) -> str:
    return _fernet().encrypt(json.dumps(values).encode()).decode()


def decrypt_credentials(blob: str) -> dict:
    return json.loads(_fernet().decrypt(blob.encode())) if blob else {}
