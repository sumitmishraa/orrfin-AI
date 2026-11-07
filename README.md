# Orrfin.ai

Procurement orchestration for multi-branch businesses. One governed workflow from a store's request to a matched invoice pushed to the ERP:

| Product | What it does |
|---|---|
| **Intake-to-Procure** | Branch requests with budget checks, preferred-supplier and contract suggestions, and multi-step approvals routed by branch, category, amount and supplier risk. A requester can never approve their own request; the database enforces it. |
| **Sourcing** | RFQs sent to suppliers through private links. Bids are compared by total incl. GST, lead time, risk and real delivery history; the award creates the PO. |
| **Procure-to-Pay** | Gapless PO numbers per branch and fiscal year (`PO/BLR/2026-27/000123`), CGST+SGST or IGST by place of supply, downloadable PO PDFs, change orders, goods receipts, invoice PDF upload, extraction, human confirmation, three-way matching, exceptions, approval and payment status. |
| **Supplier Onboarding** | A supplier portal for GSTIN, PAN, bank details (only the last four digits are kept), certificates and documents, with automated checks and review. |
| **Risk Orchestration** | Explainable scores from onboarding, documents, delivery, quality, invoice accuracy and spend concentration. High risk adds a risk approver; critical risk places a hold that blocks POs and payments in the database. |
| **AI Contract Orchestration** | Contracts generated from a clause library as Word or PDF, counterparty PDFs uploaded, versions compared, clause-by-clause review, obligations and renewal alerts. |
| **AI Procurement Concierge** | Questions answered from your own records with citations. It can draft a request; a person submits it. |
| **ERP push** | Issued POs and approved invoices go to Zoho Books through an idempotent outbox, and to Tally Prime as XML or through a relay agent that runs next to Tally. |

The product is in Python (FastAPI, SQLAlchemy, Alembic, worker) with a Next.js UI, on PostgreSQL with row-level security, all in Docker.

## Run it

You need Docker Desktop and Python 3.10+.

```powershell
python tools/bootstrap_env.py          # creates .env with generated secrets (values are never printed)
python tools/stack.py up -d --wait --build
docker compose -p orrfin-platform exec api python -m orrfin.seed   # optional: the fictional demo company
```

Open http://localhost:8080. The seed prints the sign-in emails and one shared password.

**Why `tools/stack.py`:** OneDrive turns synced files into cloud placeholders that Docker's build can't read. The script copies the source to `%LOCALAPPDATA%\orrfin-build` and runs `docker compose` there. In a checkout outside OneDrive, plain `docker compose up -d --wait --build` works.

## Keys (all optional)

Put them in `.env`. Never commit them; `.env` is gitignored.

| Variable | Turns on |
|---|---|
| `ANTHROPIC_API_KEY` | Contract review summaries and the concierge's written answers (model `claude-opus-5-5`). An admin must also switch AI on under AI Procurement Concierge. |
| `HINDSIGHT_API_KEY` | Supplier memory: structured events only, never document text. To give Claude Code access to the same memory, run `claude mcp add --transport http hindsight https://api.hindsight.vectorize.io/mcp/orrfin/` and sign in with `/mcp`. |
| `TINYFISH_API_KEY` | Adverse-media research on a supplier, only when someone clicks Research. |

Without them, every screen still works and says what is off rather than showing invented output.

## The demo company (fictional)

`python -m orrfin.seed` creates **Kirnova Quick Commerce Pvt. Ltd.**, a fictional quick-commerce operator. It is not modelled on, or affiliated with, any real company:

- 10 regional hubs and 58 sites (dark stores plus a mother warehouse per hub).
- 9 GST registrations, because Mumbai and Pune share Maharashtra's, which exercises branch-to-entity mapping.
- 12 categories, about 60 catalogue items and about 150 suppliers across states.
- A year of history built through the same service code the API uses: requests, approvals, POs, receipts, invoices with planted mismatches, payments.
- Work in flight: pending approvals, open RFQs with bids, invoice PDFs in several layouts (including scans) waiting for review, contracts near renewal, risk holds, and a mock Zoho connection receiving recent POs.
- A second organization, so you can see that tenants can't see each other.

GSTINs are checksum-valid by construction and could coincide with real registrations, so every generated document is stamped FICTIONAL.

## Tests

```powershell
$env:ORRFIN_AUTH_RATE_PER_MINUTE=100000; $env:ORRFIN_JOB_BACKOFF_SCALE=0.1
python tools/stack.py up -d --wait --build
python tools/stack.py --profile test run --rm --build tests
```

They run inside the stack, through the gateway. They cover tenant isolation with forced connection reuse, RLS on every table, permission coverage on every route, gapless numbering under 50 parallel issues, database-enforced self-approval and over-receipt/over-billing limits, PO PDF round-trips, extraction on every invoice layout and on a scan, a golden corpus of planted mismatches, and ERP delivery with lost responses, outages, dead-letter and Tally balancing.

## What is not verified

- **ERP:** live Zoho Books and Tally Prime. Both adapters follow the published docs and are tested against `mock_erp/`, a local stand-in that enforces our reading of those docs. Check the first deliveries in a Zoho sandbox and a real Tally company. The Zoho state codes and tax-ID mapping need confirming there.
- **Extraction:** accuracy on real supplier invoices. It is tested on generated layouts. Low-confidence fields are flagged, and nothing reaches matching until a person confirms it.
- **AI, Hindsight and TinyFish:** answer quality and the services themselves, until keys are added.
- **Compliance:** GSTIN checks cover format and checksum only, not GSTN registration. Sanctions screening and bank verification need a data provider and are shown as "not performed". Contract templates and tax treatment need professional review.
- **Not built:** email delivery (supplier links are shown in the UI to share), e-signature (status is recorded by hand) and payments (status only; no money moves).

## Layout

```
orrfin/            Python backend: models, migrations, services, API routers, worker jobs, seed
  api/             FastAPI routers per product
  p2p/             PO lifecycle, invoice extraction, three-way matching
  erp/             outbox, Zoho Books adapter, Tally XML
  migrations/      Alembic: schema, grants, RLS policies and business-rule triggers
mock_erp/          local ERP stand-in for tests and the demo
app/               Next.js UI (product screens under app/app, supplier portal under app/portal)
tools/             bootstrap_env.py, stack.py, tally_relay.py
tests/             end-to-end tests run inside the stack
```
