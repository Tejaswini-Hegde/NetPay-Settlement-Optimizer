# NetPay — AI-assisted multilateral settlement

Turn a tangle of unpaid invoices between businesses into fewer net payments.
NetPay's AI can extract and explain obligations, but deterministic code
calculates every amount and verifies every settlement plan before it can be
sent to PayPal.

Copyright (c) 2026 Tejaswini Hegde.

No open-source license is specified in this repository; the copyright notice
does not grant a reuse license.

## What is included

- A deterministic settlement engine that nets obligations by currency and
  connected group. It uses exact optimization for groups of up to 16 parties
  and a greedy algorithm for larger groups.
- A conversational demo powered by a local Ollama model.
- PayPal **Sandbox** invoice creation with explicit approval and an idempotent
  local SQLite ledger.
- Unit tests and a benchmark comparing naive, greedy, and exact settlement.

This repository is a local milestone/demo, not a production service. It does
not include the planned hosted API, production PayPal onboarding, or dashboard.

## What NetPay does

NetPay helps a group of parties settle a web of unpaid invoices by turning many
individual obligations into a smaller number of net payments. The project reads
obligations, groups them by connected parties and currency, and computes the
lowest-effort payment plan before any invoice is sent.

The expected outcome is a verified settlement plan that reduces duplicate
transactions, shows who owes whom, and optionally drafts PayPal Sandbox
invoices only after a human explicitly approves the plan.

## Quick start

1. Create a virtual environment and install dependencies:

   ```sh
   python3 -m venv .venv
   source .venv/bin/activate
   python -m pip install --upgrade pip
   python -m pip install -r requirements.txt
   ```

2. Run the test suite:

   ```sh
   python -m unittest discover -s tests -t . -v
   ```

3. Run the benchmark or demo:

   ```sh
   python -m scripts.benchmark
   python -m netpay.ai_demo
   ```

The engine can also be used programmatically without Ollama or PayPal access.

## Requirements

- Python 3.10 or later and `pip`.
- Ollama and the `qwen2.5:1.5b` model are needed only for the conversational
  AI demo.
- PayPal Developer Sandbox app credentials and Sandbox buyer accounts are
  needed only to authenticate with PayPal or send Sandbox invoices.

The settlement engine and tests do not require Ollama or PayPal credentials.
Python dependencies are listed in [`requirements.txt`](requirements.txt);
install them before running the tests or demos.

## Install

From the project directory, create and activate a virtual environment:

Linux/macOS:

```sh
python3 -m venv .venv
```

Windows PowerShell:

```powershell
py -3 -m venv .venv
```

Activate it:

```powershell
.\.venv\Scripts\Activate.ps1
```

On Linux/macOS, activate it with:

```sh
source .venv/bin/activate
```

Then install the dependencies:

```sh
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

## Run and test

Run the unit tests:

```sh
python -m unittest discover -s tests -t . -v
```

Run the benchmark:

```sh
python -m scripts.benchmark
```

Start the conversational AI demo (requires Ollama; see below):

```sh
python -m netpay.ai_demo
```

Type `/quit` to end the chat. The demo displays the extracted obligations and
proposed plan. If you choose to send invoices, it asks for payer email
addresses, previews the invoices, and requests final confirmation before
sending. You can decline and use the plan without sending anything.

## Optional: local AI with Ollama

Install [Ollama](https://ollama.com/download), start it, and download the
default model:

```sh
ollama pull qwen2.5:1.5b
```

The application connects to `http://127.0.0.1:11434` by default. To use
different settings, set `OLLAMA_BASE_URL` and/or `OLLAMA_MODEL` in your
environment or in a local `.env` file. No cloud AI account or API key is
required. Model downloads use disk space, and inference uses local memory and
CPU/GPU resources.

The local model may misunderstand a request. Review the parties, payment
directions, currencies, and amounts before approving any plan.

## Optional: PayPal Sandbox

1. Create a PayPal Developer Sandbox app and Sandbox buyer accounts.
2. Copy the example environment file:

   Linux/macOS:

   ```sh
   cp .env.example .env
   ```

   Windows PowerShell:

   ```powershell
   Copy-Item .env.example .env
   ```

3. Put your Sandbox app's client ID and secret in `.env` as
   `PAYPAL_CLIENT_ID` and `PAYPAL_CLIENT_SECRET`. Keep
   `PAYPAL_BASE_URL=https://api-m.sandbox.paypal.com`.
4. Verify the credentials:

   ```sh
   python -m scripts.check_auth
   ```

   A successful check prints `OK: sandbox authentication works`.
5. To run the fixed end-to-end demo, edit the three example addresses
   (`buyer-a@example.com`, `buyer-b@example.com`, and
   `buyer-c@example.com`) in [`scripts/demo_sandbox.py`](scripts/demo_sandbox.py)
   to match your Sandbox buyer accounts, then run:

   ```sh
   python -m scripts.demo_sandbox
   ```

   Review the displayed plan and answer `yes` only if you want to send the
   Sandbox invoices.

The conversational demo can also send invoices after approval. Configure the
Sandbox credentials first; it will ask for each payer's Sandbox email address.
The PayPal Invoicing API sends the invoice email, including a note describing
the settlement payment.

**Safety:** The application's configuration loader rejects non-Sandbox API
URLs. Never put credentials in source code, commit `.env`, or use real
customer data in a demo. `.env` is ignored by Git.

## Currency and settlement notes

- Amounts are represented internally as integer units of 1/10,000 of a
  currency unit. More than four decimal places are rejected, not rounded.
- Use decimal strings rather than floating-point values for exact amounts. For
  example: `netpay.money.to_units("12.3456")`.
- Currency codes are checked against Babel's CLDR currency registry, which
  includes current and historical codes. PayPal supports only a subset, so its
  API may reject a code that passes local validation.
- The AI can map ISO codes and recognized English currency names to codes.
  Unambiguous symbols are accepted; ambiguous names or symbols (such as
  “dollars” or `$`) require clarification rather than a guess. Natural-language
  extraction depends on the configured local model and is not guaranteed for
  every phrasing.
- The client formats PayPal invoice values to the currency's CLDR minor-unit
  precision (for example, 0 decimal places for JPY and 3 for KWD), and rejects
  amounts that would require rounding.
- Settlement groups contain parties connected by at least one obligation;
  currencies are never mixed.
- The configurable fee estimate is a placeholder, not PayPal's actual fee
  schedule.
- Each net payment is sent as a PayPal invoice from one Sandbox merchant
  account. Production multi-merchant use would require a PayPal partner flow
  or another suitable payout integration.

## Project layout

- `netpay/engine.py` — deterministic netting, settlement algorithms, and plan
  verification.
- `netpay/ai.py` and `netpay/ai_demo.py` — local-model integration and chat
  demo.
- `netpay/paypal.py`, `netpay/pipeline.py`, and `netpay/ledger.py` — Sandbox
  invoice flow, approval gate, and SQLite idempotency ledger.
- `scripts/` — authentication check, Sandbox demo, and benchmark.
- `tests/` — unit tests for the engine, AI handling, and application layer.

## Managing and maintaining the project

- Run the unit tests after changes to the settlement logic or invoice pipeline.
- Keep environment secrets in `.env` and never commit them to source control.
- Use the local SQLite ledger to prevent duplicate invoice sends when a plan is
  re-run.
- Review any AI-generated plan carefully before approving real payments or
  invoice drafts.
- For local development, keep Ollama running only when you need the chat demo;
  the core settlement engine does not require it.
