from __future__ import annotations
from decimal import Decimal, ROUND_HALF_EVEN


def convert_units(units: int, rate: Decimal) -> int:
    """Convert 1/10,000 currency units with banker's rounding."""
    if rate <= 0:
        raise ValueError("rate must be positive")
    return int((Decimal(units) * rate).quantize(Decimal(1), rounding=ROUND_HALF_EVEN))


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
