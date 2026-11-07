"""Zoho Books adapter: purchase orders and bills, built against the Books v3 API docs.

Auth: OAuth refresh token, sent as "Authorization: Zoho-oauthtoken <token>". Hosts depend on the
customer's datacenter. Before every create we look the document up by its number, so a retry
after a lost response finds the existing record instead of creating a duplicate.

Not verified against a live Zoho organization: the state codes, tax_id use and bill fields below
follow the published docs and must be checked against a sandbox before production.
"""
import time
from dataclasses import dataclass

import httpx

from orrfin.config import settings

DATACENTERS = {
    "com": ("https://www.zohoapis.com", "https://accounts.zoho.com"),
    "in": ("https://www.zohoapis.in", "https://accounts.zoho.in"),
    "eu": ("https://www.zohoapis.eu", "https://accounts.zoho.eu"),
    "com.au": ("https://www.zohoapis.com.au", "https://accounts.zoho.com.au"),
    "jp": ("https://www.zohoapis.jp", "https://accounts.zoho.jp"),
    "ca": ("https://www.zohoapis.ca", "https://accounts.zohocloud.ca"),
    "sa": ("https://www.zohoapis.sa", "https://accounts.zoho.sa"),
}

# GST state code to the two-letter code Zoho India uses for source/destination of supply.
STATE_CODES = {
    "01": "JK", "02": "HP", "03": "PB", "04": "CH", "05": "UT", "06": "HR", "07": "DL", "08": "RJ",
    "09": "UP", "10": "BR", "11": "SK", "12": "AR", "13": "NL", "14": "MN", "15": "MZ", "16": "TR",
    "17": "ML", "18": "AS", "19": "WB", "20": "JH", "21": "OR", "22": "CG", "23": "MP", "24": "GJ",
    "26": "DN", "27": "MH", "29": "KA", "30": "GA", "31": "LD", "32": "KL", "33": "TN", "34": "PY",
    "35": "AN", "36": "TG", "37": "AP", "38": "LA",
}


class ErpError(Exception):
    def __init__(self, message: str, retryable: bool, response: dict | None = None):
        super().__init__(message)
        self.retryable = retryable
        self.response = response or {}


class NeedsMapping(ErpError):
    def __init__(self, message: str):
        super().__init__(message, retryable=False)


@dataclass
class ZohoTarget:
    api_base: str
    accounts_base: str


def target(mode: str, datacenter: str) -> ZohoTarget:
    if mode == "mock":
        if not settings.allow_mock_erp:
            raise ErpError("The mock ERP is disabled on this deployment.", retryable=False)
        return ZohoTarget(settings.mock_erp_url + "/zoho", settings.mock_erp_url + "/zoho-accounts")
    if datacenter not in DATACENTERS:
        raise ErpError(f"Unknown Zoho datacenter '{datacenter}'.", retryable=False)
    api, accounts = DATACENTERS[datacenter]
    return ZohoTarget(api, accounts)


_token_cache: dict[str, tuple[str, float]] = {}


class ZohoClient:
    def __init__(self, zoho: ZohoTarget, credentials: dict, organization_id: str, timeout: float = 20):
        self.zoho, self.credentials, self.organization_id = zoho, credentials, organization_id
        self.http = httpx.Client(timeout=timeout)

    def _token(self) -> str:
        key = self.credentials.get("client_id", "") + self.zoho.accounts_base
        cached = _token_cache.get(key)
        if cached and cached[1] > time.time() + 60:
            return cached[0]
        try:
            response = self.http.post(
                f"{self.zoho.accounts_base}/oauth/v2/token",
                params={
                    "refresh_token": self.credentials.get("refresh_token", ""),
                    "client_id": self.credentials.get("client_id", ""),
                    "client_secret": self.credentials.get("client_secret", ""),
                    "grant_type": "refresh_token",
                },
            )
        except httpx.HTTPError as error:
            raise ErpError(f"Couldn't reach Zoho sign-in: {error.__class__.__name__}.", retryable=True) from error
        body = _json(response)
        if response.status_code != 200 or "access_token" not in body:
            raise ErpError("Zoho rejected the saved credentials. Reconnect Zoho Books.", retryable=False, response=body)
        _token_cache[key] = (body["access_token"], time.time() + float(body.get("expires_in", 3600)))
        return body["access_token"]

    def _request(self, method: str, path: str, params: dict | None = None, json: dict | None = None) -> dict:
        try:
            response = self.http.request(
                method,
                f"{self.zoho.api_base}/books/v3/{path}",
                params={"organization_id": self.organization_id, **(params or {})},
                json=json,
                headers={"Authorization": f"Zoho-oauthtoken {self._token()}"},
            )
        except httpx.HTTPError as error:
            raise ErpError(f"Zoho didn't respond: {error.__class__.__name__}.", retryable=True) from error
        body = _json(response)
        if response.status_code == 429 or response.status_code >= 500:
            raise ErpError(f"Zoho is unavailable (HTTP {response.status_code}).", retryable=True, response=body)
        if response.status_code >= 400 or body.get("code", 0) != 0:
            raise ErpError(f"Zoho rejected the request: {body.get('message', response.status_code)}", retryable=False, response=body)
        return body

    def find_purchase_order(self, number: str) -> dict | None:
        body = self._request("GET", "purchaseorders", params={"purchaseorder_number": number})
        found = [row for row in body.get("purchaseorders", []) if row.get("purchaseorder_number") == number]
        return found[0] if found else None

    def create_purchase_order(self, payload: dict) -> dict:
        return self._request("POST", "purchaseorders", params={"ignore_auto_number_generation": "true"}, json=payload)["purchaseorder"]

    def update_purchase_order(self, purchaseorder_id: str, payload: dict) -> dict:
        return self._request("PUT", f"purchaseorders/{purchaseorder_id}", json=payload)["purchaseorder"]

    def find_bill(self, bill_number: str, vendor_id: str) -> dict | None:
        body = self._request("GET", "bills", params={"bill_number": bill_number, "vendor_id": vendor_id})
        found = [row for row in body.get("bills", []) if row.get("bill_number") == bill_number]
        return found[0] if found else None

    def create_bill(self, payload: dict) -> dict:
        return self._request("POST", "bills", json=payload)["bill"]

    def organizations(self) -> dict:
        return self._request("GET", "organizations")


def _json(response: httpx.Response) -> dict:
    try:
        data = response.json()
        return data if isinstance(data, dict) else {"data": data}
    except ValueError:
        return {"raw": response.text[:500]}
