"""Plan -> human approval -> idempotent execution. Resumable after crashes."""
from __future__ import annotations
import hashlib
from .engine import build_plan
from .models import Obligation, Payment


def plan_id_for(obligations: list[Obligation]) -> str:
    raw = "|".join(sorted(f"{o.id}:{o.debtor}:{o.creditor}:{o.amount_cents}:{o.currency}" for o in obligations))
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def request_key(plan_id: str, i: int, p: Payment) -> str:
    raw = f"{plan_id}:{i}:{p.payer}:{p.payee}:{p.amount_cents}:{p.currency}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def execute_plan(plan_id: str, payments: list[Payment], client, ledger, approved: bool) -> list[str]:
    """Each payer gets an invoice for what they owe. Re-running never duplicates invoices."""
    if not approved:
        raise PermissionError("plan must be explicitly approved before execution")
    sent = []
    for i, p in enumerate(payments):
        key = request_key(plan_id, i, p)
        row = ledger.get(key)
        if row and row["status"] == "SENT":
            continue
        if row:
            invoice_id = row["invoice_id"]          # drafted earlier; just finish sending
        else:
            invoice_id = client.create_draft_invoice(p.payer, p.amount_cents, p.currency,
                                                     f"NetPay settlement {plan_id}", request_id=key)
            ledger.record(key, plan_id, p, invoice_id, "DRAFTED")
        client.send_invoice(invoice_id, request_id=key + "-send")
        ledger.set_status(key, "SENT")
        sent.append(invoice_id)
    return sent


def plan_from_obligations(obligations: list[Obligation]):
    return plan_id_for(obligations), build_plan(obligations)
