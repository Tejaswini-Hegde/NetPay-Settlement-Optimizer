from netpay.models import Obligation
from netpay.engine import build_plan
from netpay.ai import explain_intent
from netpay.money import format_amount

if __name__ == "__main__":

    obligations = [
        Obligation("1", "Alice", "Bob", 1_000_000),
        Obligation("2", "Bob", "Charlie", 800_000),
        Obligation("3", "Charlie", "Alice", 400_000)
    ]

    plan = build_plan(obligations)

    print("\nSETTLEMENT PLAN\n")

    print(f"Original obligations : {plan.naive_count}")
    print(f"Optimized payments   : {plan.optimized_count}")
    print(f"Payments saved       : {plan.payments_saved}")

    print("\nPayments\n")

    for payment in plan.payments:
        print(
            f"{payment.payer} -> "
            f"{payment.payee} : "
            f"{format_amount(payment.amount_units)} {payment.currency}"
        )