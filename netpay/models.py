"""Domain models. Money is stored as integer 1/10,000 currency units."""
from __future__ import annotations
from dataclasses import dataclass, field

from .money import currency_precision


@dataclass(frozen=True)
class Obligation:
    """`debtor` owes `creditor` an amount in 1/10,000 currency units."""
    id: str
    debtor: str
    creditor: str
    amount_units: int
    currency: str = "USD"

    def __post_init__(self):
        if not isinstance(self.amount_units, int) or isinstance(self.amount_units, bool):
            raise TypeError("amount_units must be an int (1/10,000 currency units)")
        if self.amount_units <= 0:
            raise ValueError(f"{self.id}: amount must be positive")
        if self.debtor == self.creditor:
            raise ValueError(f"{self.id}: debtor and creditor are the same party")
        currency = self.currency.strip().upper()
        currency_precision(currency)
        object.__setattr__(self, "currency", currency)


@dataclass(frozen=True)
class Payment:
    payer: str
    payee: str
    amount_units: int
    currency: str = "USD"

    def __post_init__(self):
        currency = self.currency.strip().upper()
        currency_precision(currency)
        object.__setattr__(self, "currency", currency)


@dataclass
class SettlementPlan:
    payments: list[Payment]
    naive_count: int                      # one payment per obligation
    strategy_by_group: dict[str, str] = field(default_factory=dict)

    @property
    def optimized_count(self) -> int:
        return len(self.payments)

    @property
    def payments_saved(self) -> int:
        return self.naive_count - self.optimized_count

    @property
    def gross_units(self) -> int:
        return sum(p.amount_units for p in self.payments)
