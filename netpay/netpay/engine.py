"""Deterministic settlement engine. No AI, no network: money math lives here only.

Pipeline: obligations -> per-currency -> connected groups (Union-Find)
          -> net balances -> minimum-payment plan (exact DP when small, heap greedy otherwise)
          -> verify_plan() invariants before anything may touch PayPal.

Note: computing net balances implicitly cancels circular debts (A->B->C->A nets to 0).
"""
from __future__ import annotations
import heapq
from collections import defaultdict
from typing import Callable, Iterable

from .models import Obligation, Payment, SettlementPlan

EXACT_LIMIT = 16   # exact DP is O(2^n * n); above this fall back to greedy


# ---------- Union-Find ----------
class _UF:
    def __init__(self):
        self.p: dict[str, str] = {}

    def find(self, x: str) -> str:
        self.p.setdefault(x, x)
        root = x
        while self.p[root] != root:
            root = self.p[root]
        while self.p[x] != root:            # path compression
            self.p[x], x = root, self.p[x]
        return root

    def union(self, a: str, b: str):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[max(ra, rb)] = min(ra, rb)   # deterministic root


def components(obligations: Iterable[Obligation]) -> list[set[str]]:
    """Parties connected by at least one obligation = one settlement group."""
    uf = _UF()
    for o in obligations:
        uf.union(o.debtor, o.creditor)
    groups: dict[str, set[str]] = defaultdict(set)
    for party in list(uf.p):
        groups[uf.find(party)].add(party)
    return sorted(groups.values(), key=lambda s: sorted(s))


# ---------- Net balances ----------
def net_balances(obligations: Iterable[Obligation]) -> dict[str, int]:
    """+ve => party is owed money overall, -ve => party owes money overall."""
    bal: dict[str, int] = defaultdict(int)
    for o in obligations:
        bal[o.debtor] -= o.amount_cents
        bal[o.creditor] += o.amount_cents
    return {k: v for k, v in bal.items()}


# ---------- Greedy (heap) ----------
def greedy_settle(balances: dict[str, int], currency: str = "USD") -> list[Payment]:
    """Largest debtor pays largest creditor. <= n-1 payments, O(n log n)."""
    creditors = [(-v, k) for k, v in balances.items() if v > 0]
    debtors = [(v, k) for k, v in balances.items() if v < 0]  # v negative => largest debt first
    heapq.heapify(creditors)
    heapq.heapify(debtors)
    out: list[Payment] = []
    while creditors and debtors:
        c_amt, c = heapq.heappop(creditors)
        d_amt, d = heapq.heappop(debtors)
        c_amt, d_owes = -c_amt, -d_amt
        pay = min(c_amt, d_owes)
        out.append(Payment(d, c, pay, currency))
        if c_amt > pay:
            heapq.heappush(creditors, (-(c_amt - pay), c))
        if d_owes > pay:
            heapq.heappush(debtors, (-(d_owes - pay), d))
    return out


# ---------- Exact (bitmask DP) ----------
def exact_groups(balances: dict[str, int]) -> list[list[str]]:
    """Partition parties into the MAX number of zero-sum subsets.

    A zero-sum subset of size k needs exactly k-1 payments, so
    min payments = n - (max number of zero-sum subsets).
    dp[mask] = best count over orderings of mask; O(2^n * n).
    """
    names = sorted(k for k, v in balances.items() if v != 0)
    n = len(names)
    vals = [balances[k] for k in names]
    if sum(vals) != 0:
        raise ValueError("balances do not sum to zero")
    size = 1 << n
    ssum = [0] * size
    for m in range(1, size):
        low = m & -m
        ssum[m] = ssum[m ^ low] + vals[low.bit_length() - 1]
    dp = [0] * size
    choice = [-1] * size
    for m in range(1, size):
        best, best_i = -1, -1
        mm = m
        while mm:
            low = mm & -mm
            i = low.bit_length() - 1
            cand = dp[m ^ low]
            if cand > best:
                best, best_i = cand, i
            mm ^= low
        dp[m] = best + (1 if ssum[m] == 0 else 0)
        choice[m] = best_i
    order, m = [], size - 1
    while m:
        i = choice[m]
        order.append(i)
        m ^= 1 << i
    order.reverse()
    groups, cur, run = [], [], 0
    for i in order:
        cur.append(names[i])
        run += vals[i]
        if run == 0:
            groups.append(cur)
            cur = []
    return groups


def exact_settle(balances: dict[str, int], currency: str = "USD") -> list[Payment]:
    out: list[Payment] = []
    for g in exact_groups(balances):
        out += greedy_settle({k: balances[k] for k in g}, currency)  # minimal group => k-1 payments
    return out


# ---------- Orchestration ----------
def build_plan(obligations: list[Obligation], exact_limit: int = EXACT_LIMIT) -> SettlementPlan:
    by_ccy: dict[str, list[Obligation]] = defaultdict(list)
    for o in obligations:
        by_ccy[o.currency].append(o)
    payments: list[Payment] = []
    strategy: dict[str, str] = {}
    for ccy in sorted(by_ccy):
        obs = by_ccy[ccy]
        for grp in components(obs):
            gobs = [o for o in obs if o.debtor in grp]
            bal = {k: v for k, v in net_balances(gobs).items() if v != 0}
            key = f"{ccy}:{'|'.join(sorted(grp))}"
            if not bal:
                strategy[key] = "fully-cancelled"
            elif len(bal) <= exact_limit:
                payments += exact_settle(bal, ccy)
                strategy[key] = "exact-dp"
            else:
                payments += greedy_settle(bal, ccy)
                strategy[key] = "greedy-heap"
    plan = SettlementPlan(payments, naive_count=len(obligations), strategy_by_group=strategy)
    verify_plan(obligations, plan.payments)
    return plan


def verify_plan(obligations: list[Obligation], payments: list[Payment]) -> None:
    """Hard invariants. Raise (never silently fix) if any fails - gate before PayPal calls."""
    for p in payments:
        if p.amount_cents <= 0:
            raise AssertionError(f"non-positive payment: {p}")
        if p.payer == p.payee:
            raise AssertionError(f"self payment: {p}")
    owed = defaultdict(int)  # (party, ccy) -> net still owed (+ve = still owed money)
    for o in obligations:
        owed[(o.creditor, o.currency)] += o.amount_cents
        owed[(o.debtor, o.currency)] -= o.amount_cents
    for p in payments:
        owed[(p.payer, p.currency)] += p.amount_cents
        owed[(p.payee, p.currency)] -= p.amount_cents
    bad = {k: v for k, v in owed.items() if v != 0}
    if bad:
        raise AssertionError(f"plan does not settle all balances: {bad}")
    gross_obs = sum(o.amount_cents for o in obligations)
    if sum(p.amount_cents for p in payments) > gross_obs:
        raise AssertionError("plan moves more money than the original obligations")


def estimate_fees(payments: list[Payment], fixed_cents: int = 0, bps: int = 0) -> int:
    """Configurable fee model (placeholder rates - use PayPal's actual fee schedule)."""
    return sum(fixed_cents + (p.amount_cents * bps + 5_000) // 10_000 for p in payments)
