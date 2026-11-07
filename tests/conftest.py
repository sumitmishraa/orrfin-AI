"""Tests run in a container against the real stack, through the gateway."""
import os
import secrets
from dataclasses import dataclass
from uuid import UUID

import httpx
import pytest

BASE_URL = os.environ.get("ORRFIN_BASE_URL", "http://gateway:80")
PASSWORD = "correct-horse-battery-1"


class Api:
    """An authenticated browser-like client: cookie jar plus CSRF header."""

    def __init__(self) -> None:
        self.client = httpx.Client(base_url=BASE_URL, timeout=60, follow_redirects=False)
        self.csrf = ""
        self.tenant_id: UUID | None = None
        self.user_id: UUID | None = None
        self.email = ""

    def _headers(self) -> dict[str, str]:
        return {"X-Orrfin-CSRF": self.csrf} if self.csrf else {}

    def get(self, path: str, **kwargs) -> httpx.Response:
        return self.client.get(path, **kwargs)

    def post(self, path: str, **kwargs) -> httpx.Response:
        return self.client.post(path, headers=self._headers(), **kwargs)

    def put(self, path: str, **kwargs) -> httpx.Response:
        return self.client.put(path, headers=self._headers(), **kwargs)

    def delete(self, path: str, **kwargs) -> httpx.Response:
        return self.client.delete(path, headers=self._headers(), **kwargs)

    def login(self, email: str, password: str = PASSWORD) -> "Api":
        response = self.client.post("/api/auth/login", json={"email": email, "password": password})
        assert response.status_code == 200, response.text
        self.csrf = response.json()["csrf_token"]
        self.email = email
        self._load_me()
        return self

    def _load_me(self) -> None:
        me = self.client.get("/api/auth/me").json()
        self.tenant_id = UUID(me["tenant"]["id"])
        self.user_id = UUID(me["user"]["id"])


def unique_email(prefix: str = "user") -> str:
    return f"{prefix}-{secrets.token_hex(5)}@orrfin-tests.example"


def new_tenant(company: str = "Test Co") -> Api:
    api = Api()
    email = unique_email("admin")
    response = api.client.post(
        "/api/auth/signup",
        json={"company": company, "name": "Test Admin", "email": email, "password": PASSWORD},
    )
    assert response.status_code == 201, response.text
    api.csrf = response.json()["csrf_token"]
    api.email = email
    api._load_me()
    return api


@dataclass
class TwoTenants:
    a: Api
    b: Api


@pytest.fixture
def tenant() -> Api:
    return new_tenant()


@pytest.fixture
def two_tenants() -> TwoTenants:
    return TwoTenants(new_tenant("Tenant A"), new_tenant("Tenant B"))
