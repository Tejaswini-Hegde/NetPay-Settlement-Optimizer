import re
import sys

from netpay.ai import (
    AIError,
    AI_MAX_ATTEMPTS,
    AI_TIMEOUT_SECONDS,
    interpret_settlement_chat,
)
from netpay.config import Settings
from netpay.engine import build_plan
from netpay.ledger import Ledger
from netpay.money import format_amount
from netpay.paypal import PayPalClient, PayPalError
from netpay.pipeline import execute_plan, plan_id_for

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _payer_emails(payments) -> dict[str, str] | None:
    emails = {}
    for payer in dict.fromkeys(payment.payer for payment in payments):
        while True:
            try:
                email = input(f"Sandbox email address for {payer}: ").strip()
            except EOFError:
                print("\nInvoice sending cancelled.")
                return None
            if _EMAIL.fullmatch(email):
                emails[payer] = email
                break
            print("Enter a valid email address.")
    return emails


if __name__ == "__main__":

    print("\nNETPAY AI\n")

    print(
        "Chat naturally about the settlement you want to make. "
        "I may ask follow-up questions before preparing a plan.\n"
        "Type /quit to exit.\n"
    )

    conversation: list[dict[str, str]] = []
    while True:
        try:
            user_message = input("\nYou: ").strip()
        except EOFError:
            print("\nChat ended.")
            break

        if user_message.lower() in {"/quit", "/exit"}:
            print("Chat ended.")
            break
        if not user_message:
            continue

        conversation.append({"role": "user", "content": user_message})
        print(
            f"\nThinking (up to {AI_MAX_ATTEMPTS} attempts, "
            f"{AI_TIMEOUT_SECONDS} seconds each)...",
            flush=True,
        )
        try:
            reply = interpret_settlement_chat(conversation)
        except (AIError, ValueError) as exc:
            print(f"\n{exc}", file=sys.stderr)
            print("No plan was created. You can rephrase or clarify your request.")
            continue

        conversation.append({"role": "assistant", "content": reply.assistant_message})
        print(f"\nNetPay: {reply.assistant_message}")
        if reply.status == "clarify":
            for question in reply.clarifications:
                print(f"- {question}")

        if reply.status == "no_obligations":
            print("No settlement plan was created.")
            break
        if reply.status != "ready":
            continue

        print("\nObligations understood:")
        for obligation in reply.obligations:
            print(
                f"- {obligation.debtor} -> {obligation.creditor}: "
                f"{format_amount(obligation.amount_units)} {obligation.currency}"
            )

        plan = build_plan(reply.obligations)
        print("\nSettlement Plan")
        print(f"Original transactions : {plan.naive_count}")
        print(f"Optimized payments    : {plan.optimized_count}")
        print(f"Payments saved        : {plan.payments_saved}")
        print("\nProposed payments")
        for payment in plan.payments:
            print(
                f"{payment.payer} -> {payment.payee}: "
                f"{format_amount(payment.amount_units)} {payment.currency}"
            )
        try:
            wants_invoices = input(
                "\nDo you want to send the invoices to the respective entities? (yes/no): "
            ).strip().lower() == "yes"
        except EOFError:
            wants_invoices = False
            print()
        if not wants_invoices:
            print("Invoice sending cancelled; no email addresses requested and no invoices sent.")
            break

        print(
            "\nEnter each payer's PayPal sandbox email. "
            "PayPal will send the invoice with the amount and payee in its note."
        )
        try:
            settings = Settings.from_env()
        except RuntimeError as exc:
            print(f"\nCannot send invoices: {exc}", file=sys.stderr)
            break
        payer_emails = _payer_emails(plan.payments)
        if payer_emails is None:
            break

        print("\nInvoices to send")
        for payment in plan.payments:
            print(
                f"{payer_emails[payment.payer]} ({payment.payer}) pays "
                f"{payment.payee}: {format_amount(payment.amount_units)} "
                f"{payment.currency}"
            )
        try:
            approved = input(
                "Send these PayPal sandbox invoices? (yes/no): "
            ).strip().lower() == "yes"
        except EOFError:
            approved = False
            print()
        if not approved:
            print("Invoice sending cancelled; no invoices were sent.")
            break

        try:
            invoice_ids = execute_plan(
                plan_id_for(reply.obligations),
                plan.payments,
                PayPalClient(settings),
                Ledger(),
                approved=True,
                payer_emails=payer_emails,
            )
        except PayPalError as exc:
            print(f"\nInvoice sending failed: {exc}", file=sys.stderr)
            break
        print("Sent PayPal invoices:", ", ".join(invoice_ids) if invoice_ids else "none (already sent)")
        break