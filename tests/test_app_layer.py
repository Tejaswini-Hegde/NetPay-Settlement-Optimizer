import tempfile, os, unittest
from decimal import Decimal
from netpay import Obligation, Payment
from netpay.config import Settings, SANDBOX_URL
from netpay.extract import parse_intent, enforce_budget
from netpay.fx import convert_units
from netpay.ledger import Ledger
from netpay.paypal import PayPalClient, PayPalError
from netpay.pipeline import execute_plan, plan_from_obligations


class R:
    def __init__(self, code, body=None, text=None):
        self.status_code, self._b = code, body or {}
        self.text = text if text is not None else str(body)
    def json(self): return self._b


class FakeSession:
    def __init__(self, token_resp=None, api=None):
        self.token_resp = token_resp or R(200, {"access_token": "T", "expires_in": 3600})
        self.api, self.token_calls, self.calls = list(api or []), 0, []
    def post(self, url, **kw):
        self.token_calls += 1
        return self.token_resp
    def request(self, method, url, **kw):
        self.calls.append((method, url, kw))
        return self.api.pop(0)


class FakeClient:
    def __init__(self, fail_send_on=None):
        self.drafts, self.sends, self.fail_send_on = [], [], fail_send_on
    def create_draft_invoice(self, email, units, ccy, note, request_id):
        self.drafts.append((email, units, ccy, note, request_id))
        return f"INV-{len(self.drafts)}"
    def send_invoice(self, inv, request_id):
        if self.fail_send_on == inv:
            self.fail_send_on = None; raise PayPalError("boom")
        self.sends.append(inv)


class TestApp(unittest.TestCase):
    def test_settings(self):
        s = Settings.from_env(env_file="/nonexistent", environ={"PAYPAL_CLIENT_ID": "a", "PAYPAL_CLIENT_SECRET": "b"})
        self.assertEqual(s.base_url, SANDBOX_URL)
        with self.assertRaises(RuntimeError):
            Settings.from_env(env_file="/nonexistent", environ={})
        with self.assertRaises(RuntimeError):
            Settings.from_env(env_file="/nonexistent", environ={"PAYPAL_CLIENT_ID": "a", "PAYPAL_CLIENT_SECRET": "b",
                                                                "PAYPAL_BASE_URL": "https://api-m.paypal.com"})

    def test_parse_intent_and_budget(self):
        raw = '```json\n{"action":"CREATE_INVOICE","recipient":"s@x.com","target_currency":"eur","source_budget_cap":"2500.00","item_name":"Parts","quantity":"50"}\n```'
        i = parse_intent(raw)
        self.assertEqual((i.quantity, i.currency, i.budget_cap_units), (50, "EUR", 25_000_000))
        enforce_budget(22_500_000, i)
        with self.assertRaises(ValueError): enforce_budget(25_000_001, i)
        precise = parse_intent({
            "action": "CREATE_INVOICE", "recipient": "s@x.com", "target_currency": "usd",
            "item_name": "Parts", "quantity": 1, "source_budget_cap": "1.2345",
        })
        self.assertEqual(precise.budget_cap_units, 12_345)
        with self.assertRaises(ValueError):
            parse_intent({
                "action": "CREATE_INVOICE", "recipient": "s@x.com", "target_currency": "usd",
                "item_name": "Parts", "quantity": 1, "source_budget_cap": "1.23456",
            })
        for bad in ({"action": "X"}, {"action": "CREATE_INVOICE", "recipient": "nope"}):
            with self.assertRaises(ValueError): parse_intent(bad)

    def test_fx_rounding(self):
        self.assertEqual(convert_units(22_500_000, Decimal("0.92")), 20_700_000)
        with self.assertRaises(ValueError): convert_units(1, Decimal("0"))

    def test_client_token_cache_and_auth_error(self):
        s = FakeSession(api=[R(200, {"a": 1}), R(200, {"b": 2})])
        c = PayPalClient(Settings("i", "s"), session=s)
        c._call("GET", "/x"); c._call("GET", "/y")
        self.assertEqual(s.token_calls, 1)
        bad = PayPalClient(Settings("i", "s"), session=FakeSession(token_resp=R(401, text='{"error":"invalid_client"}')))
        with self.assertRaises(PayPalError): bad.check_auth()

    def test_client_retries_with_same_request_id(self):
        s = FakeSession(api=[R(503, text="x"), R(201, {"href": "https://x/v2/invoicing/invoices/INV2-ABC"})])
        c = PayPalClient(Settings("i", "s"), session=s, sleep=lambda _: None)
        self.assertEqual(c.create_draft_invoice("a@b.com", 1_234_500, "USD", "n", "rid"), "INV2-ABC")
        ids = {kw["headers"]["PayPal-Request-Id"] for _, _, kw in s.calls}
        self.assertEqual(ids, {"rid"})
        self.assertEqual(s.calls[1][2]["json"]["items"][0]["unit_amount"]["value"], "123.45")

    def test_paypal_formats_currency_minor_units_and_rejects_excess_precision(self):
        session = FakeSession(api=[
            R(201, {"href": "https://x/v2/invoicing/invoices/JPY"}),
            R(201, {"href": "https://x/v2/invoicing/invoices/KWD"}),
        ])
        client = PayPalClient(Settings("i", "s"), session=session)
        client.create_draft_invoice("a@b.com", 12_000_000, "jpy", "n", "jpy")
        client.create_draft_invoice("a@b.com", 123_450, "KWD", "n", "kwd")
        values = [
            call[2]["json"]["items"][0]["unit_amount"]["value"]
            for call in session.calls
        ]
        self.assertEqual(values, ["1200", "12.345"])

        client = PayPalClient(Settings("i", "s"), session=FakeSession())
        with self.assertRaisesRegex(PayPalError, "at most 2 decimal places"):
            client.create_draft_invoice("a@b.com", 12_345, "USD", "n", "rid")

    def test_execute_requires_approval_and_is_resumable(self):
        obs = [Obligation("1", "a@x.com", "b@x.com", 100), Obligation("2", "c@x.com", "d@x.com", 200)]
        pid, plan = plan_from_obligations(obs)
        with tempfile.TemporaryDirectory() as d:
            led, cl = Ledger(os.path.join(d, "t.db")), FakeClient(fail_send_on="INV-2")
            with self.assertRaises(PermissionError): execute_plan(pid, plan.payments, cl, led, approved=False)
            with self.assertRaises(PayPalError): execute_plan(pid, plan.payments, cl, led, approved=True)
            execute_plan(pid, plan.payments, cl, led, approved=True)    # resume
            execute_plan(pid, plan.payments, cl, led, approved=True)    # no-op
            self.assertEqual(len(cl.drafts), 2)                          # never duplicated
            self.assertEqual(sorted(cl.sends), ["INV-1", "INV-2"])

    def test_execute_uses_payer_email_and_amount_note(self):
        payment = Payment("Northstar Labs", "Bluebird Cafe", 12_500_000, "USD")
        with tempfile.TemporaryDirectory() as d:
            client = FakeClient()
            execute_plan(
                "plan",
                [payment],
                client,
                Ledger(os.path.join(d, "t.db")),
                approved=True,
                payer_emails={"Northstar Labs": "northstar@example.com"},
            )
        email, units, currency, note, _ = client.drafts[0]
        self.assertEqual(email, "northstar@example.com")
        self.assertEqual((units, currency), (12_500_000, "USD"))
        self.assertIn("You have to pay 1250 USD to Bluebird Cafe", note)

    def test_ledger_migrates_existing_cent_values(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "legacy.db")
            import sqlite3
            db = sqlite3.connect(path)
            db.execute("""CREATE TABLE settlements(
                request_key TEXT PRIMARY KEY, plan_id TEXT, payer TEXT, payee TEXT,
                amount_cents INTEGER, currency TEXT, invoice_id TEXT, status TEXT, updated_at REAL)""")
            db.execute("INSERT INTO settlements VALUES(?,?,?,?,?,?,?,?,?)",
                       ("rid", "plan", "a", "b", 123, "USD", "INV", "SENT", 0))
            db.commit()
            db.close()

            ledger = Ledger(path)
            row = ledger.get("rid")
            self.assertEqual(row["amount_units"], 12_300)
            self.assertNotIn("amount_cents", row)


if __name__ == "__main__":
    unittest.main()
