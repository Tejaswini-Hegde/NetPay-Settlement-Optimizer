# NetPay - AI-assisted multilateral settlement (PayPal AI Hackathon)

Turn a tangle of unpaid invoices between businesses into the minimum number of PayPal payments.

## Design rule
AI extracts and explains. **Deterministic code decides every amount.** `verify_plan()` must pass before any PayPal call.

## Layout
- `netpay/models.py`  - Obligation, Payment, SettlementPlan (integer cents only)
- `netpay/engine.py`  - Union-Find groups, net balances, heap greedy, exact bitmask DP, invariants
- `tests/`            - unit + randomized property tests (stdlib unittest, no dependencies)
- `scripts/benchmark.py` - naive vs greedy vs exact

## Run
    python3 -m unittest discover -s tests -t . -v
    python3 -m scripts.benchmark

## Roadmap
1. [done] Settlement engine + tests
2. Ingestion: Bedrock extracts obligations from invoice text/PDF -> schema validation -> confidence flags
3. API layer: Lambda + SQS + DynamoDB (idempotent plan IDs), approval endpoint
4. PayPal sandbox: create invoices/payouts with idempotency keys, webhook handler, reconciliation
5. Dashboard (AG Grid), Postman collection, demo video

## Assumptions to document
- Settlement groups = parties connected by at least one obligation, per currency
- Exact DP up to 16 parties per group, heap greedy above that
- Fee model is a configurable placeholder, not PayPal's real schedule

## Setup (milestone 2)
1. `cp .env.example .env` and paste your SANDBOX client id/secret into `.env` (this is the ONLY place keys go).
2. `pip install requests` (inside your venv).
3. `python -m scripts.check_auth`  -> must print "OK" before anything else.
4. Edit the three emails in `scripts/demo_sandbox.py` to your sandbox buyer accounts, then `python -m scripts.demo_sandbox`.

## Known limits (state these in your submission)
- Execution issues one PayPal invoice per net payment from a single sandbox merchant account. Multi-party
  production use needs Payouts or per-merchant OAuth (PayPal partner flow).
- 2-decimal currencies only. Verify Invoicing API behaviour (e.g. auto invoice number) in your sandbox.
