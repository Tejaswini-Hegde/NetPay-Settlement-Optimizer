import unittest
from unittest.mock import patch

import requests

from netpay.ai import (
    AI_MAX_ATTEMPTS,
    AI_TIMEOUT_SECONDS,
    AIClarificationRequired,
    AIConfigurationError,
    AIRequestError,
    AIServiceError,
    AITimeoutError,
    OLLAMA_MODEL,
    _generate_content,
    extract_obligations,
    interpret_settlement_chat,
)


class FakeResponse:
    def __init__(self, content=None, status_code=200):
        self.status_code = status_code
        self._content = content

    def raise_for_status(self):
        if self.status_code >= 400:
            response = type("Response", (), {"status_code": self.status_code})()
            raise requests.HTTPError(response=response)

    def json(self):
        return {"message": {"content": self._content}}


class TestLocalAIHandling(unittest.TestCase):
    @patch("netpay.ai.requests.post")
    def test_request_uses_local_ollama_and_structured_output(self, post):
        post.return_value = FakeResponse('{"ok":true}')

        result = _generate_content("test prompt", {"type": "object"})

        self.assertEqual(result, '{"ok":true}')
        self.assertEqual(post.call_args.args[0], "http://127.0.0.1:11434/api/chat")
        payload = post.call_args.kwargs["json"]
        self.assertEqual(payload["model"], OLLAMA_MODEL)
        self.assertEqual(payload["format"], {"type": "object"})
        self.assertFalse(payload["stream"])
        self.assertEqual(post.call_args.kwargs["timeout"], AI_TIMEOUT_SECONDS)

    @patch("netpay.ai.requests.post", side_effect=requests.ConnectionError)
    def test_missing_local_ollama_has_actionable_message(self, post):
        with self.assertRaisesRegex(AIConfigurationError, "Start Ollama"):
            _generate_content("test prompt")
        post.assert_called_once()

    @patch("netpay.ai.requests.post", side_effect=requests.Timeout("request timed out"))
    def test_timeout_has_actionable_message(self, post):
        with self.assertRaises(AITimeoutError) as raised:
            _generate_content("test prompt")

        self.assertIn(f"{AI_TIMEOUT_SECONDS} seconds", str(raised.exception))
        post.assert_called_once()

    @patch("netpay.ai.time.sleep")
    @patch("netpay.ai.requests.post")
    def test_server_errors_are_retried(self, post, sleep):
        post.side_effect = [
            FakeResponse(status_code=503),
            FakeResponse('{"ok":true}'),
        ]

        self.assertEqual(_generate_content("test prompt"), '{"ok":true}')
        self.assertEqual(post.call_count, 2)
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [1])

    @patch("netpay.ai.time.sleep")
    @patch("netpay.ai.requests.post", return_value=FakeResponse(status_code=503))
    def test_server_error_after_retries_is_reported(self, post, sleep):
        with self.assertRaises(AIServiceError) as raised:
            _generate_content("test prompt")

        self.assertIn(f"{AI_MAX_ATTEMPTS} attempts", str(raised.exception))
        self.assertEqual(post.call_count, AI_MAX_ATTEMPTS)
        self.assertEqual(sleep.call_count, AI_MAX_ATTEMPTS - 1)

    @patch(
        "netpay.ai.requests.post",
        return_value=FakeResponse(status_code=404),
    )
    def test_missing_model_is_reported_as_request_error(self, post):
        with self.assertRaisesRegex(AIRequestError, "model"):
            _generate_content("test prompt")
        post.assert_called_once()

    @patch("netpay.ai.requests.post")
    def test_obligations_preserve_exact_amount_and_use_schema(self, post):
        post.return_value = FakeResponse(
            '{"clarifications":[],"obligations":[{"debtor":"A","creditor":"B",'
            '"amount":"1.2345","currency":"USD","evidence":"A owes B 1.2345 USD"}]}'
        )

        obligations = extract_obligations("A owes B 1.2345 USD")

        self.assertEqual(obligations[0].amount_units, 12_345)
        self.assertEqual(obligations[0].currency, "USD")
        self.assertEqual(post.call_args.kwargs["json"]["model"], OLLAMA_MODEL)
        self.assertEqual(
            post.call_args.kwargs["json"]["format"]["properties"].keys(),
            {"clarifications", "obligations"},
        )
        self.assertIn(
            "never infer it",
            post.call_args.kwargs["json"]["messages"][0]["content"],
        )

    @patch("netpay.ai.requests.post")
    def test_chat_accepts_natural_wording_and_currency_name(self, post):
        post.return_value = FakeResponse(
            '{"assistant_message":"I found the debt.",'
            '"status":"ready","clarifications":[],"obligations":['
            '{"debtor":"A","creditor":"T","amount":"1000",'
            '"currency":"INR",'
            '"evidence":"A has to transfer T 1000 Indian rupees."}]}'
        )

        result = interpret_settlement_chat(
            [{
                "role": "user",
                "content": "A has to transfer T 1000 Indian rupees.",
            }]
        )

        self.assertEqual(result.status, "ready")
        self.assertEqual(
            (
                result.obligations[0].debtor,
                result.obligations[0].creditor,
                result.obligations[0].amount_units,
                result.obligations[0].currency,
            ),
            ("A", "T", 10_000_000, "INR"),
        )
        self.assertIn(
            "full currency names",
            post.call_args.kwargs["json"]["messages"][0]["content"],
        )

    @patch("netpay.ai.requests.post")
    def test_ai_cannot_resolve_ambiguous_currency_symbol(self, post):
        post.return_value = FakeResponse(
            '{"clarifications":[],"obligations":[{"debtor":"A","creditor":"B",'
            '"amount":"20","currency":"USD","evidence":"A owes B $20"}]}'
        )

        with self.assertRaisesRegex(AIRequestError, "does not establish USD"):
            extract_obligations("A owes B $20")

    @patch("netpay.ai.requests.post")
    def test_reimbursement_language_preserves_payer_and_recipient(self, post):
        post.return_value = FakeResponse(
            '{"clarifications":[],"obligations":[{"debtor":"Maya","creditor":"me",'
            '"amount":"20","currency":"EUR","evidence":"Maya should reimburse me 20 euros."}]}'
        )

        obligations = extract_obligations("Maya should reimburse me 20 euros.")

        self.assertEqual(obligations[0].debtor, "Maya")
        self.assertEqual(obligations[0].creditor, "me")
        self.assertEqual(obligations[0].currency, "EUR")
        self.assertIn(
            "Maya should reimburse me 20 euros.",
            post.call_args.kwargs["json"]["messages"][0]["content"],
        )

    @patch(
        "netpay.ai.requests.post",
        return_value=FakeResponse(
            '{"clarifications":["Which currency is this amount in?"],'
            '"obligations":[]}'
        ),
    )
    def test_clarifications_block_obligation_creation(self, post):
        with self.assertRaises(AIClarificationRequired) as raised:
            extract_obligations("Maya should reimburse Alex 20.")

        self.assertIn("Which currency", raised.exception.questions[0])
        post.assert_called_once()

    @patch("netpay.ai.requests.post")
    def test_chat_clarification_returns_reply_and_sends_full_history(self, post):
        post.return_value = FakeResponse(
            '{"assistant_message":"Which currency should I use?",'
            '"status":"clarify","clarifications":["Which currency?"],'
            '"obligations":[]}'
        )
        conversation = [
            {"role": "user", "content": "Help me settle dinner."},
            {"role": "assistant", "content": "Who paid?"},
            {"role": "user", "content": "Maya paid Alex 20."},
        ]

        result = interpret_settlement_chat(conversation)

        self.assertEqual(result.status, "clarify")
        self.assertEqual(result.clarifications, ["Which currency?"])
        self.assertEqual(result.obligations, [])
        messages = post.call_args.kwargs["json"]["messages"]
        self.assertEqual(messages[0]["role"], "system")
        self.assertEqual(messages[1:], conversation)

    @patch("netpay.ai.requests.post")
    def test_chat_extracts_explicit_owed_debts_without_llm(self, post):
        message = (
            "Acme Ltd owes Brightstar 120 USD for consulting. "
            "Brightstar owes Northwind USD 45 for hosting, and "
            "Northwind owes Acme Ltd 20 USD for software."
        )

        result = interpret_settlement_chat([{"role": "user", "content": message}])

        self.assertEqual(result.status, "ready")
        self.assertEqual(
            [
                (item.debtor, item.creditor, item.amount_units, item.currency)
                for item in result.obligations
            ],
            [
                ("Acme Ltd", "Brightstar", 1_200_000, "USD"),
                ("Brightstar", "Northwind", 450_000, "USD"),
                ("Northwind", "Acme Ltd", 200_000, "USD"),
            ],
        )
        post.assert_not_called()

    @patch("netpay.ai.requests.post")
    def test_chat_extracts_needs_to_pay_wording_without_llm(self, post):
        result = interpret_settlement_chat(
            [{"role": "user", "content": "A needs to pay T 1000 INR"}]
        )

        self.assertEqual(result.status, "ready")
        self.assertEqual(len(result.obligations), 1)
        obligation = result.obligations[0]
        self.assertEqual(
            (
                obligation.debtor,
                obligation.creditor,
                obligation.amount_units,
                obligation.currency,
            ),
            ("A", "T", 10_000_000, "INR"),
        )
        post.assert_not_called()

    @patch("netpay.ai.requests.post")
    def test_chat_accepts_zero_and_three_decimal_currency_codes(self, post):
        message = (
            "Acme owes Brightstar 1200 JPY for equipment. "
            "Brightstar owes Northwind KWD 12.345 for services."
        )

        result = interpret_settlement_chat([{"role": "user", "content": message}])

        self.assertEqual(result.status, "ready")
        self.assertEqual(
            [(item.currency, item.amount_units) for item in result.obligations],
            [("JPY", 12_000_000), ("KWD", 123_450)],
        )
        post.assert_not_called()

    @patch("netpay.ai.requests.post")
    def test_chat_asks_for_currency_instead_of_assuming_dollar_currency(self, post):
        result = interpret_settlement_chat(
            [{
                "role": "user",
                "content": "Acme owes Brightstar $120 for consulting.",
            }]
        )

        self.assertEqual(result.status, "clarify")
        self.assertIn("ISO currency code", result.clarifications[0])
        post.assert_not_called()

    @patch("netpay.ai.requests.post")
    def test_chat_uses_currency_answer_to_finish_explicit_debt(self, post):
        result = interpret_settlement_chat(
            [
                {
                    "role": "user",
                    "content": "Acme owes Brightstar $120 for consulting.",
                },
                {
                    "role": "assistant",
                    "content": "What currency should I use for the amount?",
                },
                {"role": "user", "content": "USD"},
            ]
        )

        self.assertEqual(result.status, "ready")
        self.assertEqual(len(result.obligations), 1)
        self.assertEqual(result.obligations[0].currency, "USD")
        self.assertEqual(result.obligations[0].amount_units, 1_200_000)
        post.assert_not_called()

    @patch("netpay.ai.requests.post")
    def test_chat_applies_currency_answer_to_each_dollar_amount(self, post):
        conversation = [
            {
                "role": "user",
                "content": (
                    "Acme Ltd owes Brightstar $120 for consulting. "
                    "Brightstar owes Northwind $45 for hosting, and "
                    "Northwind owes Acme Ltd $20 for software."
                ),
            },
            {
                "role": "assistant",
                "content": (
                    "What currency should I use for the amount(s) without "
                    "an explicit currency code?"
                ),
            },
            {"role": "user", "content": "MYR"},
        ]

        result = interpret_settlement_chat(conversation)

        self.assertEqual(result.status, "ready")
        self.assertEqual(
            [(item.debtor, item.creditor, item.amount_units, item.currency)
             for item in result.obligations],
            [
                ("Acme Ltd", "Brightstar", 1_200_000, "MYR"),
                ("Brightstar", "Northwind", 450_000, "MYR"),
                ("Northwind", "Acme Ltd", 200_000, "MYR"),
            ],
        )
        post.assert_not_called()

    @patch("netpay.ai.requests.post")
    def test_chat_ready_returns_verified_obligation(self, post):
        post.return_value = FakeResponse(
            '{"assistant_message":"Maya will pay Alex EUR 20.",'
            '"status":"ready","clarifications":[],"obligations":['
            '{"debtor":"Maya","creditor":"Alex","amount":"20",'
            '"currency":"EUR","evidence":"Maya should send Alex €20."}]}'
        )

        result = interpret_settlement_chat(
            [{"role": "user", "content": "Maya should send Alex €20."}]
        )

        self.assertEqual(result.status, "ready")
        self.assertEqual(len(result.obligations), 1)
        self.assertEqual(result.obligations[0].debtor, "Maya")
        self.assertEqual(result.obligations[0].creditor, "Alex")

    @patch("netpay.ai.requests.post")
    def test_chat_ready_ignores_nonblocking_model_question(self, post):
        post.return_value = FakeResponse(
            '{"assistant_message":"Maya will pay Alex EUR 20.",'
            '"status":"ready","clarifications":["Anything else to add?"],'
            '"obligations":[{"debtor":"Maya","creditor":"Alex","amount":"20",'
            '"currency":"EUR","evidence":"Maya should send Alex €20."}]}'
        )

        result = interpret_settlement_chat(
            [{"role": "user", "content": "Maya should send Alex €20."}]
        )

        self.assertEqual(result.status, "ready")
        self.assertEqual(result.clarifications, [])
        self.assertEqual(len(result.obligations), 1)

    @patch("netpay.ai.requests.post")
    def test_chat_rejects_obligation_evidence_that_combines_debts(self, post):
        post.return_value = FakeResponse(
            '{"assistant_message":"Here is the plan.",'
            '"status":"ready","clarifications":["Anything else?"],'
            '"obligations":[{"debtor":"Brightstar","creditor":"Northwind",'
            '"amount":"20","currency":"USD",'
            '"evidence":"Brightstar appears with Northwind for $45, and '
            'Northwind with Acme for $20."}]}'
        )

        with self.assertRaisesRegex(AIRequestError, "exactly its stated amount"):
            interpret_settlement_chat(
                [{
                    "role": "user",
                    "content": (
                        "Brightstar appears with Northwind for $45, and "
                        "Northwind with Acme for $20."
                    ),
                }]
            )

    @patch("netpay.ai.requests.post")
    def test_chat_rejects_ready_obligation_with_unsupported_evidence(self, post):
        post.return_value = FakeResponse(
            '{"assistant_message":"Ready.", "status":"ready",'
            '"clarifications":[],"obligations":[{"debtor":"Maya",'
            '"creditor":"Alex","amount":"20","currency":"EUR",'
            '"evidence":"Maya owes Alex €20."}]}'
        )

        with self.assertRaisesRegex(AIRequestError, "evidence not found"):
            interpret_settlement_chat(
                [{"role": "user", "content": "Maya may pay Alex later."}]
            )

    @patch(
        "netpay.ai.requests.post",
        return_value=FakeResponse(
            '{"clarifications":[],"obligations":[{"debtor":"Maya",'
            '"creditor":"Alex","amount":"20","currency":"USD",'
            '"evidence":"invented sentence"}]}'
        ),
    )
    def test_unverifiable_evidence_blocks_obligation_creation(self, post):
        with self.assertRaisesRegex(AIRequestError, "evidence not found"):
            extract_obligations("Maya should reimburse Alex 20 USD.")
        post.assert_called_once()

    @patch(
        "netpay.ai.requests.post",
        return_value=FakeResponse(
            '{"clarifications":[],"obligations":[{"debtor":"A","creditor":"B",'
            '"amount":"1.23456","currency":"USD","evidence":"A owes B"}]}'
        ),
    )
    def test_obligations_reject_more_than_four_decimal_places(self, post):
        with self.assertRaisesRegex(ValueError, "at most 4 decimal places"):
            extract_obligations("A owes B")
        post.assert_called_once()

    @patch(
        "netpay.ai.requests.post",
        return_value=FakeResponse('{"clarifications":[],"obligations":[]}')
    )
    def test_empty_obligations_are_valid(self, post):
        self.assertEqual(extract_obligations("No debts"), [])
        post.assert_called_once()

    @patch(
        "netpay.ai.requests.post",
        return_value=FakeResponse('{"clarifications":[],"unexpected":[]}'),
    )
    def test_obligations_reject_invalid_json_shape(self, post):
        with self.assertRaisesRegex(ValueError, "obligations array"):
            extract_obligations("A owes B")
        post.assert_called_once()


if __name__ == "__main__":
    unittest.main()
