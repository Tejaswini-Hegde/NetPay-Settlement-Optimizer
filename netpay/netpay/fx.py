from __future__ import annotations
from decimal import Decimal, ROUND_HALF_EVEN


def convert_cents(cents: int, rate: Decimal) -> int:
    """Convert minor units with banker's rounding. Assumes 2-decimal currencies."""
    if rate <= 0:
        raise ValueError("rate must be positive")
    return int((Decimal(cents) * rate).quantize(Decimal(1), rounding=ROUND_HALF_EVEN))


def fetch_rate(session, src: str, tgt: str) -> Decimal:
    """Live rate; raises on any failure (no silent fallback rate for money)."""
    r = session.get(f"https://open.er-api.com/v6/latest/{src.upper().strip()}", timeout=10)
    r.raise_for_status()
    data = r.json()
    if data.get("result") != "success":
        raise RuntimeError(f"rate provider error: {data.get('error-type', data)}")
    rate = Decimal(str(data["rates"][tgt.upper().strip()]))
    if rate <= 0:
        raise RuntimeError("provider returned non-positive rate")
    return rate
