"""Domain models. All money is integer minor units (cents) - never floats."""
from __future__ import annotations
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Obligation:
    """`debtor` owes `creditor` `amount_cents` (e.g. one unpaid invoice)."""
    id: str
    debtor: str
    creditor: str
    amount_cents: int
    currency: str = "USD"

    def __post_init__(self):
        if not isinstance(self.amount_cents, int) or isinstance(self.amount_cents, bool):
            raise TypeError("amount_cents must be an int (minor units)")
        if self.amount_cents <= 0:
            raise ValueError(f"{self.id}: amount must be positive")
        if self.debtor == self.creditor:
            raise ValueError(f"{self.id}: debtor and creditor are the same party")


@dataclass(frozen=True)
class Payment:
    payer: str
    payee: str
    amount_cents: int
    currency: str = "USD"


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
    def gross_cents(self) -> int:
        return sum(p.amount_cents for p in self.payments)
