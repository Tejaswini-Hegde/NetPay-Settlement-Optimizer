"""Validate untrusted LLM output. The model suggests; this code decides what is acceptable."""
from __future__ import annotations
import json, re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.I)


@dataclass(frozen=True)
class Intent:
    action: str
    recipient: str
    currency: str
    item_name: str
    quantity: int
    budget_cap_cents: int | None


def _cents(value) -> int:
    try:
        d = Decimal(str(value))
    except InvalidOperation as e:
        raise ValueError(f"bad amount: {value!r}") from e
    if d <= 0:
        raise ValueError("amount must be positive")
    return int((d * 100).to_integral_value())


def parse_intent(raw) -> Intent:
    data = raw if isinstance(raw, dict) else json.loads(_FENCE.sub("", str(raw).strip()))
    if data.get("action") != "CREATE_INVOICE":
        raise ValueError(f"unsupported action: {data.get('action')!r}")
    email = str(data.get("recipient", "")).strip()
    if not _EMAIL.match(email):
        raise ValueError(f"invalid recipient email: {email!r}")
    ccy = str(data.get("target_currency", "")).strip().upper()
    if not re.fullmatch(r"[A-Z]{3}", ccy):
        raise ValueError(f"invalid currency: {ccy!r}")
    try:
        qty = int(str(data.get("quantity", "")).strip())
    except ValueError as e:
        raise ValueError("quantity must be an integer") from e
    if qty <= 0:
        raise ValueError("quantity must be positive")
    item = str(data.get("item_name", "")).strip()
    if not item:
        raise ValueError("item_name missing")
    cap = data.get("source_budget_cap")
    return Intent("CREATE_INVOICE", email, ccy, item, qty, _cents(cap) if cap not in (None, "") else None)


def enforce_budget(total_cents: int, intent: Intent) -> None:
    if intent.budget_cap_cents is not None and total_cents > intent.budget_cap_cents:
        raise ValueError(f"total {total_cents} exceeds budget cap {intent.budget_cap_cents} (cents)")
