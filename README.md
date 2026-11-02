# NetPay - AI-assisted multilateral settlement (PayPal AI Hackathon)

Turn a tangle of unpaid invoices between businesses into the minimum number of PayPal payments.

## Design rule
AI extracts and explains. **Deterministic code decides every amount.** `verify_plan()` must pass before any PayPal call.

## Layout
- `netpay/models.py`  - Obligation, Payment, SettlementPlan (integer 1/10,000 currency units)
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
1. If `.env` does not already exist, copy `.env.example` to `.env`. If it exists, keep it and add/update the required entries instead.
2. Fill in the PayPal SANDBOX client ID/secret and set `OLLAMA_BASE_URL`/`OLLAMA_MODEL` if needed. No AI API key is required. Never commit `.env` or paste keys into source code.
3. Install [Ollama](https://ollama.com/download) and download the local model with `ollama pull qwen2.5:1.5b`.
4. `pip install -r requirements.txt` (inside your venv).
5. `python -m scripts.check_auth`  -> must print "OK" before anything else.
6. Edit the three emails in `scripts/demo_sandbox.py` to your sandbox buyer accounts, then `python -m scripts.demo_sandbox`.

NetPay directly parses clear `owes`, `must pay`, and `has to pay` statements
when amounts have explicit currency codes. Other natural-language requests use
Ollama with the local `qwen2.5:1.5b` model by default; set `OLLAMA_MODEL` or
`OLLAMA_BASE_URL` to override it. Ollama must be running locally, but no cloud
AI account or per-request fee is required. Model downloads use disk space, and
inference consumes your computer's memory and CPU/GPU. Run
`python -m netpay.ai_demo` to chat about a settlement. The assistant keeps the
conversation context, responds conversationally, and asks follow-up questions
when required information is unclear. Currency codes are validated against
Babel's CLDR currency registry; dollar signs alone do not identify a currency,
so specify an ISO code such as `USD`. AI-extracted obligations must include
source evidence and are checked before the deterministic engine builds a plan.
The demo only displays proposed payments; it does not send them through PayPal.
This small local model cannot guarantee correct interpretation for every
wording, so review extracted parties and payment directions.

## Known limits (state these in your submission)
- Execution issues one PayPal invoice per net payment from a single sandbox merchant account. Multi-party
  production use needs Payouts or per-merchant OAuth (PayPal partner flow).
- Internal settlement amounts support up to 4 decimal places, stored as integer units of 1/10,000 of a
  currency unit. Amounts with more than 4 decimals are rejected rather than rounded. PayPal invoice values
  are formatted to each currency's CLDR minor-unit precision (for example, 0 for JPY and 3 for KWD).
- Construct amounts with `netpay.money.to_units("12.3456")` and pass the result as `amount_units`;
  use decimal strings rather than floats for exact input.
- Babel's CLDR currency registry contains current and historical currency codes; it validates codes and
  provides their minor-unit precision. PayPal supports only a subset of currencies, so its Invoicing API
  may reject otherwise valid currency codes. Verify the currencies enabled for your PayPal account in
  the sandbox; the client never rounds an amount to fit a currency's precision.
