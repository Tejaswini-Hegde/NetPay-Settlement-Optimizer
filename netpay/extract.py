"""Validate untrusted LLM output. The model suggests; this code decides what is acceptable."""
from __future__ import annotations
import json, re
from dataclasses import dataclass
from decimal import Decimal
from .money import currency_precision, format_amount, to_units

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.I)


@dataclass(frozen=True)
class Intent:
    action: str
    recipient: str
    currency: str
    item_name: str
    quantity: int
    budget_cap_units: int | None


def _units(value, currency: str) -> int:
    try:
        units = to_units(value, currency)
    except ValueError as e:
        raise ValueError(f"bad amount: {value!r}") from e
    if units <= 0:
        raise ValueError("amount must be positive")
    return units


def parse_intent(raw) -> Intent:
    data = raw if isinstance(raw, dict) else json.loads(
        _FENCE.sub("", str(raw).strip()), parse_float=Decimal
    )
    if data.get("action") != "CREATE_INVOICE":
        raise ValueError(f"unsupported action: {data.get('action')!r}")
    email = str(data.get("recipient", "")).strip()
    if not _EMAIL.match(email):
        raise ValueError(f"invalid recipient email: {email!r}")
    ccy = str(data.get("target_currency", "")).strip().upper()
    if not re.fullmatch(r"[A-Z]{3}", ccy):
        raise ValueError(f"invalid currency: {ccy!r}")
    currency_precision(ccy)
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
    return Intent(
        "CREATE_INVOICE",
        email,
        ccy,
        item,
        qty,
        _units(cap, ccy) if cap not in (None, "") else None,
    )


def enforce_budget(total_units: int, intent: Intent) -> None:
    if intent.budget_cap_units is not None and total_units > intent.budget_cap_units:
        raise ValueError(
            f"total {format_amount(total_units)} exceeds budget cap "
            f"{format_amount(intent.budget_cap_units)}"
        )
