"""End-to-end sandbox demo. Replace the emails below with your PayPal SANDBOX buyer account emails."""
from netpay import Obligation
from netpay.config import Settings
from netpay.ledger import Ledger
from netpay.paypal import PayPalClient
from netpay.pipeline import plan_from_obligations, execute_plan

A, B, C = "buyer-a@example.com", "buyer-b@example.com", "buyer-c@example.com"
OBLIGATIONS = [
    Obligation("inv1", A, B, 10_000), Obligation("inv2", B, C, 7_000), Obligation("inv3", C, A, 4_000),
]

if __name__ == "__main__":
    plan_id, plan = plan_from_obligations(OBLIGATIONS)
    print(f"Plan {plan_id}: {plan.naive_count} invoices -> {plan.optimized_count} payments")
    for p in plan.payments:
        print(f"  {p.payer} pays {p.payee}: {p.amount_cents / 100:.2f} {p.currency}")
    if input("Approve and send invoices? (yes/no): ").strip().lower() == "yes":
        ids = execute_plan(plan_id, plan.payments, PayPalClient(Settings.from_env()), Ledger(), approved=True)
        print("Sent invoices:", ids)
