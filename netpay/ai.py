import json
import os
import re
import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import requests
from dotenv import load_dotenv

from netpay.models import Obligation
from netpay.money import CURRENCY_CODES, to_units

load_dotenv()

AI_TIMEOUT_SECONDS = 120
AI_MAX_ATTEMPTS = 3
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:1.5b")


class AIError(RuntimeError):
    pass


class AIConfigurationError(AIError):
    pass


class AITimeoutError(AIError, TimeoutError):
    pass


class AIServiceError(AIError):
    pass


class AIRequestError(AIError):
    pass


class AIClarificationRequired(AIError):
    def __init__(self, questions: list[str]):
        self.questions = questions
        super().__init__("The request needs clarification before a safe plan can be made.")


@dataclass(frozen=True)
class SettlementChatReply:
    assistant_message: str
    status: str
    clarifications: list[str]
    obligations: list[Obligation]


def _generate_content(
    prompt: str | list[dict[str, str]],
    response_schema: dict[str, Any] | None = None,
) -> str:
    messages = [{"role": "user", "content": prompt}] if isinstance(prompt, str) else prompt
    payload: dict[str, Any] = {
        "model": OLLAMA_MODEL,
        "messages": messages,
        "stream": False,
        "options": {"temperature": 0},
        "format": response_schema or "json",
    }

    for attempt in range(AI_MAX_ATTEMPTS):
        try:
            response = requests.post(
                f"{OLLAMA_BASE_URL}/api/chat",
                json=payload,
                timeout=AI_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
        except requests.Timeout as exc:
            raise AITimeoutError(
                f"The local AI model did not respond within "
                f"{AI_TIMEOUT_SECONDS} seconds. The first request may need "
                "longer to load the model; try again or increase "
                "AI_TIMEOUT_SECONDS."
            ) from exc
        except requests.ConnectionError as exc:
            raise AIConfigurationError(
                "Could not connect to Ollama at "
                f"{OLLAMA_BASE_URL}. Start Ollama and make sure model "
                f"'{OLLAMA_MODEL}' is installed (ollama pull {OLLAMA_MODEL})."
            ) from exc
        except requests.HTTPError as exc:
            status_code = exc.response.status_code if exc.response else None
            if status_code is not None and status_code >= 500:
                if attempt + 1 == AI_MAX_ATTEMPTS:
                    raise AIServiceError(
                        f"Ollama remained unavailable after {AI_MAX_ATTEMPTS} "
                        f"attempts (HTTP {status_code}). Try again later."
                    ) from exc
                time.sleep(2**attempt)
                continue
            raise AIRequestError(
                f"Ollama rejected the request (HTTP {status_code}). "
                f"Check that model '{OLLAMA_MODEL}' is installed and that "
                "Ollama supports the requested output format."
            ) from exc

        try:
            data = response.json()
        except requests.exceptions.JSONDecodeError as exc:
            raise AIRequestError("Ollama returned an invalid JSON response.") from exc

        message = data.get("message") if isinstance(data, dict) else None
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str) or not content.strip():
            raise AIRequestError("Ollama returned an empty or invalid response.")
        return content

    raise AssertionError("Ollama retry loop ended unexpectedly")


def _parse_json_response(raw: str) -> Any:
    return json.loads(raw, parse_float=Decimal, parse_int=Decimal)


def _validate_obligations(
    items: list[Any],
    user_messages: list[str],
) -> list[Obligation]:
    obligations = []
    for idx, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"Obligation {idx} must be a JSON object.")

        debtor = item.get("debtor")
        creditor = item.get("creditor")
        currency = item.get("currency")
        amount = item.get("amount")
        evidence = item.get("evidence")
        if not isinstance(debtor, str) or not debtor.strip():
            raise ValueError(f"Obligation {idx} has an invalid debtor.")
        if not isinstance(creditor, str) or not creditor.strip():
            raise ValueError(f"Obligation {idx} has an invalid creditor.")
        if not isinstance(currency, str) or not currency.strip():
            raise ValueError(f"Obligation {idx} has an invalid currency.")
        if not isinstance(amount, str):
            raise ValueError(f"Obligation {idx} amount must be a decimal string.")
        amount_units = to_units(amount, currency)
        if not isinstance(evidence, str) or not evidence.strip():
            raise ValueError(f"Obligation {idx} is missing source evidence.")
        if not any(evidence in message for message in user_messages):
            raise AIRequestError(
                f"Obligation {idx} evidence not found verbatim in your message. "
                "The AI may have paraphrased or invented its citation, so NetPay "
                "blocked the plan. Restate the debt with its parties, amount, and "
                "ISO currency code; no settlement plan was created."
            )
        evidence_amounts = re.findall(
            r"(?<!\d)(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?!\d)",
            evidence,
        )
        if len(evidence_amounts) != 1 or evidence_amounts[0].replace(",", "") != amount:
            raise AIRequestError(
                f"Obligation {idx} evidence must support exactly its stated "
                "amount; no settlement plan was created."
            )
        if debtor.casefold() not in evidence.casefold() or creditor.casefold() not in evidence.casefold():
            raise AIRequestError(
                f"Obligation {idx} evidence must name both parties; "
                "no settlement plan was created."
            )

        obligations.append(
            Obligation(
                id=str(idx),
                debtor=debtor.strip(),
                creditor=creditor.strip(),
                amount_units=amount_units,
                currency=currency.strip().upper(),
            )
        )
    return obligations


_OBLIGATION_SCHEMA = {
    "type": "object",
    "properties": {
        "obligations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "debtor": {"type": "string"},
                    "creditor": {"type": "string"},
                    "amount": {
                        "type": "string",
                        "pattern": "^[0-9]+(\\.[0-9]{1,4})?$",
                    },
                    "currency": {"type": "string", "pattern": "^[A-Z]{3}$"},
                    "evidence": {"type": "string"},
                },
                "required": ["debtor", "creditor", "amount", "currency", "evidence"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["obligations"],
    "additionalProperties": False,
}


_CHAT_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "assistant_message": {"type": "string"},
        "status": {
            "type": "string",
            "enum": ["chat", "clarify", "ready", "no_obligations"],
        },
        "clarifications": {"type": "array", "items": {"type": "string"}},
        **_OBLIGATION_SCHEMA["properties"],
    },
    "required": [
        "assistant_message",
        "status",
        "clarifications",
        "obligations",
    ],
    "additionalProperties": False,
}


_CHAT_SYSTEM_PROMPT = """
You are NetPay's conversational settlement assistant. Talk naturally and
respond to the user's latest message while considering the full conversation.
The user may explain debts in any ordinary wording; do not require a fixed
phrase or keyword.

Your only job is to extract the user's original debts. Do not calculate,
optimize, summarize, or propose settlement payments; deterministic code does
that after extraction. Return one obligation for each debt, preserving its
original amount and direction exactly. Never combine, split, or omit debts.

Extract only current, definite, unpaid obligations. Debtor is the party
required to pay; creditor is the recipient. Determine direction from meaning,
not word order. Never invent or reverse a payer, recipient, amount, or currency.
Do not treat past payments, estimates, plans, or conditional amounts as debts.
Use prior user and assistant messages to resolve pronouns and references.

Use status "chat" for greetings, general questions, or when the user has not
yet asked to make a settlement plan. Use "clarify" when a settlement request
is missing or conflicts on a fact needed to build the plan. Ask concise,
specific follow-up questions in both assistant_message and clarifications.
Do not ask generic questions such as whether the user has anything else to add.
Use "ready" only when every obligation to be included has a clear debtor,
creditor, exact amount, and explicit currency. Use "no_obligations" when the
user confirms there are no current debts or asks to stop.

When ready, return every current obligation supported by the conversation.
Amounts must be plain decimal strings with no currency symbol. Currency must
be a three-letter ISO code explicit in the conversation; do not assume USD.
Each obligation's evidence must be the shortest verbatim text that states that
single debt and supports its parties, direction, amount, and currency. Do not
include evidence spanning multiple debts. Do not output obligations while
status is chat or clarify. Return only data matching the JSON schema.
"""


_EXPLICIT_DEBT_PATTERN = re.compile(
    r"^\s*(?P<debtor>[A-Za-z][A-Za-z0-9&.'’-]*(?:\s+[A-Za-z][A-Za-z0-9&.'’-]*?)*)"
    r"\s+(?:owes|must\s+pay|has\s+to\s+pay)\s+"
    r"(?P<creditor>[A-Za-z][A-Za-z0-9&.'’-]*(?:\s+[A-Za-z][A-Za-z0-9&.'’-]*?)*)"
    r"\s+(?:(?P<symbol>[$€£])\s*)?(?:(?P<currency_before>(?-i:[A-Z]{3}))\s*)?"
    r"(?P<amount>(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d{1,4})?)"
    r"(?!\d|\.\d)"
    r"(?:\s*(?P<currency_after>(?-i:[A-Z]{3})))?",
    re.IGNORECASE,
)
_CURRENCY_PATTERN = "|".join(
    re.escape(code) for code in sorted(CURRENCY_CODES, key=len, reverse=True)
)
_CURRENCY_BEFORE_AMOUNT = re.compile(
    rf"\b(?P<currency>{_CURRENCY_PATTERN})\s+"
    r"(?P<amount>(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d{1,4})?)\b",
    re.IGNORECASE,
)


def _extract_explicit_debts(message: str) -> SettlementChatReply | None:
    if message.rstrip().endswith("?"):
        return None
    message = _CURRENCY_BEFORE_AMOUNT.sub(
        lambda match: f"{match.group('amount')} {match.group('currency').upper()}",
        message,
    )
    clauses = re.split(r"(?<=[.!?])\s+|;\s*|,\s+and\s+", message)
    matches = []
    for clause in clauses:
        if not re.search(
            r"\b(?:owes|must\s+pay|has\s+to\s+pay)\b", clause, re.IGNORECASE
        ):
            continue
        match = _EXPLICIT_DEBT_PATTERN.match(clause)
        if match is None:
            return None
        matches.append(match)
    if not matches:
        return None

    obligations = []
    missing_currency = False
    for idx, match in enumerate(matches, start=1):
        symbol = match.group("symbol")
        currency = match.group("currency_before") or match.group("currency_after")
        if symbol == "€":
            currency = currency or "EUR"
        elif symbol == "£":
            currency = currency or "GBP"
        elif symbol == "$" and not currency:
            missing_currency = True
            continue
        elif not currency:
            missing_currency = True
            continue

        amount = match.group("amount").replace(",", "")
        try:
            amount_units = to_units(amount, currency)
        except ValueError:
            return None
        obligations.append(
            Obligation(
                id=str(idx),
                debtor=match.group("debtor").strip(),
                creditor=match.group("creditor").strip(),
                amount_units=amount_units,
                currency=currency.upper(),
            )
        )

    if missing_currency:
        return SettlementChatReply(
            "What currency should I use for the amount(s) without an explicit currency code?",
            "clarify",
            ["Please specify the ISO currency code, such as USD or EUR."],
            [],
        )
    return SettlementChatReply(
        f"I found {len(obligations)} obligation(s) with explicit amounts and currencies.",
        "ready",
        [],
        obligations,
    )


def interpret_settlement_chat(
    conversation: list[dict[str, str]],
) -> SettlementChatReply:
    if not conversation or any(
        message.get("role") != "user"
        and message.get("role") != "assistant"
        or not isinstance(message.get("content"), str)
        or not message["content"].strip()
        for message in conversation
    ):
        raise ValueError("Conversation must contain non-empty user/assistant messages.")

    latest_user_message = next(
        (
            message["content"]
            for message in reversed(conversation)
            if message["role"] == "user"
        ),
        "",
    )
    explicit_reply = _extract_explicit_debts(latest_user_message)
    if explicit_reply is not None:
        return explicit_reply

    currency_answer = latest_user_message.strip().upper()
    if conversation[-1]["role"] == "user" and re.fullmatch(
        r"[A-Z]{3}", currency_answer
    ):
        preceding_assistant = next(
            (
                message["content"]
                for message in reversed(conversation[:-1])
                if message["role"] == "assistant"
            ),
            "",
        )
        preceding_user = next(
            (
                message["content"]
                for message in reversed(conversation[:-1])
                if message["role"] == "user"
            ),
            "",
        )
        if "currency" in preceding_assistant.casefold() and "$" in preceding_user:
            resolved_message = re.sub(
                r"\$\s*((?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d{1,4})?)",
                lambda match: f"{match.group(1)} {currency_answer}",
                preceding_user,
            )
            explicit_reply = _extract_explicit_debts(resolved_message)
            if explicit_reply is not None and explicit_reply.status == "ready":
                return explicit_reply

    messages = [
        {"role": "system", "content": _CHAT_SYSTEM_PROMPT},
        *conversation,
    ]
    data = _parse_json_response(_generate_content(messages, _CHAT_RESPONSE_SCHEMA))
    if not isinstance(data, dict):
        raise ValueError("AI response must be a JSON object.")

    assistant_message = data.get("assistant_message")
    status = data.get("status")
    questions = data.get("clarifications")
    items = data.get("obligations")
    if not isinstance(assistant_message, str) or not assistant_message.strip():
        raise ValueError("AI response must contain a chat message.")
    if status not in {"chat", "clarify", "ready", "no_obligations"}:
        raise ValueError("AI response has an invalid conversation status.")
    if not isinstance(questions, list) or not all(
        isinstance(question, str) and question.strip() for question in questions
    ):
        raise ValueError("AI response must contain valid clarification questions.")
    if not isinstance(items, list):
        raise ValueError("AI response must contain an obligations array.")

    if status == "ready":
        if not items:
            raise AIRequestError(
                "AI marked the request ready without any obligations; no plan was created."
            )
        user_messages = [
            message["content"] for message in conversation if message["role"] == "user"
        ]
        obligations = _validate_obligations(items, user_messages)
        return SettlementChatReply(assistant_message.strip(), "ready", [], obligations)
    if status == "clarify":
        return SettlementChatReply(
            assistant_message.strip(),
            status,
            questions or [assistant_message.strip()],
            [],
        )
    if status in {"chat", "no_obligations"}:
        if items:
            raise AIRequestError(
                "AI returned obligations before the settlement request was ready."
            )
        return SettlementChatReply(assistant_message.strip(), status, [], [])
    raise AIRequestError("AI returned an unsupported conversation status.")


def extract_obligations(text: str) -> list[Obligation]:
    schema = {
        "type": "object",
        "properties": {
            "clarifications": {"type": "array", "items": {"type": "string"}},
            **_OBLIGATION_SCHEMA["properties"],
        },
        "required": ["clarifications", "obligations"],
        "additionalProperties": False,
    }
    prompt = f"""
Read the whole text as natural conversation; do not require a fixed phrase or
keyword. Extract every current, definite, unpaid obligation, not past payments,
plans, or conditional amounts. A clear repayment request is enough to count as
currently due unless the text says it was paid or cancelled.

For each debt, debtor means the party required to pay; creditor means the
recipient. Determine direction from meaning, never word order. "I/me/my"
means the speaker; if no name is given, use the literal label "me". Do not ask
for a real name just to understand direction.

Do not guess, reverse, merge, split, or omit debts. Amounts must be plain
decimal strings, with no symbols or words. Currency must be an explicit,
unambiguous three-letter ISO code; never assume USD. Include exact source text
as evidence for every debt. If a necessary fact is unclear or contradictory,
exclude that debt and ask one specific clarification instead of guessing.
Return only JSON matching the supplied schema.

Text:
{text}
"""
    data = _parse_json_response(_generate_content(prompt, schema))
    if not isinstance(data, dict):
        raise ValueError("AI response must be a JSON object.")

    clarifications = data.get("clarifications")
    items = data.get("obligations")
    if not isinstance(clarifications, list) or not all(
        isinstance(question, str) and question.strip()
        for question in clarifications
    ):
        raise ValueError("AI response must contain valid clarification questions.")
    if clarifications:
        raise AIClarificationRequired(clarifications)
    if not isinstance(items, list):
        raise ValueError("AI response must contain an obligations array.")

    return _validate_obligations(items, [text])


def extract_intent_from_text(user_request: str) -> Any:
    prompt = f"""
Convert the user's request into a JSON object.
Return JSON only. Do not invent missing information.

Request:
{user_request}
"""
    return _parse_json_response(_generate_content(prompt))
