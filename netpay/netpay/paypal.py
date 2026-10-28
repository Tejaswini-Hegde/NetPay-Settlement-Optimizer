"""Minimal PayPal sandbox client: OAuth with token cache, retries, idempotency headers."""
from __future__ import annotations
import time
from .config import Settings


class PayPalError(RuntimeError):
    pass


def _fmt(cents: int) -> str:
    return f"{cents // 100}.{cents % 100:02d}"


class PayPalClient:
    def __init__(self, settings: Settings, session=None, sleep=time.sleep):
        if session is None:
            import requests
            session = requests.Session()
        self.s, self.cfg, self._sleep = session, settings, sleep
        self._tok, self._exp = None, 0.0

    def _token(self) -> str:
        if self._tok and time.time() < self._exp - 60:
            return self._tok
        r = self.s.post(f"{self.cfg.base_url}/v1/oauth2/token", auth=(self.cfg.client_id, self.cfg.client_secret),
                        data={"grant_type": "client_credentials"}, headers={"Accept": "application/json"}, timeout=15)
        if r.status_code != 200:
            raise PayPalError(f"auth failed ({r.status_code}): {r.text[:200]} - check you are using SANDBOX "
                              "credentials from ONE app, and that the secret was not regenerated")
        p = r.json()
        self._tok, self._exp = p["access_token"], time.time() + float(p.get("expires_in", 3600))
        return self._tok

    def check_auth(self) -> bool:
        self._token()
        return True

    def _call(self, method: str, path: str, body=None, request_id: str | None = None) -> dict:
        headers = {"Authorization": f"Bearer {self._token()}", "Content-Type": "application/json"}
        if request_id:
            headers["PayPal-Request-Id"] = request_id     # same id on retry => PayPal dedupes
        for attempt in range(3):
            r = self.s.request(method, f"{self.cfg.base_url}{path}", json=body, headers=headers, timeout=20)
            if r.status_code in (429, 500, 502, 503, 504) and attempt < 2:
                self._sleep(2 ** attempt)
                continue
            if not 200 <= r.status_code < 300:
                raise PayPalError(f"{method} {path} -> {r.status_code}: {r.text[:300]}")
            return r.json() if r.text else {}
        raise PayPalError("unreachable")

    def create_draft_invoice(self, recipient_email: str, amount_cents: int, currency: str,
                             note: str, request_id: str) -> str:
        body = {
            "detail": {"currency_code": currency, "note": note},
            "primary_recipients": [{"billing_info": {"email_address": recipient_email}}],
            "items": [{"name": "NetPay settlement", "quantity": "1",
                       "unit_amount": {"currency_code": currency, "value": _fmt(amount_cents)}}],
        }
        res = self._call("POST", "/v2/invoicing/invoices", body, request_id)
        href = res.get("href", "")
        if not href:
            raise PayPalError(f"no invoice link in response: {res}")
        return href.rstrip("/").rsplit("/", 1)[-1]

    def send_invoice(self, invoice_id: str, request_id: str) -> None:
        self._call("POST", f"/v2/invoicing/invoices/{invoice_id}/send", {"send_to_recipient": True}, request_id)
