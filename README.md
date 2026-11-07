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

Open http://localhost:8080. The seed prints the sign-in emails and one shared password; with `ORRFIN_DEMO_LOGIN=1` (the Docker default), **http://localhost:8080/demo** lets anyone pick a role and enter the app with no password. The landing page's "Open the live demo" goes there.

**Why `tools/stack.py`:** OneDrive turns synced files into cloud placeholders that Docker's build can't read. The script copies the source to `%LOCALAPPDATA%\orrfin-build` and runs `docker compose` there. In a checkout outside OneDrive, plain `docker compose up -d --wait --build` works.

## Keys (all optional)

Put them in `.env`. Never commit them; `.env` is gitignored.

<!-- AUTO-GENERATED from .env.example -->
| Variable | Turns on |
|---|---|
| `GEMINI_API_KEY` | Google Gemini for the concierge's written answers and contract review summaries. Default model `gemini-3.5-flash`; when its quota runs out the app falls back to `gemini-3.5-flash-lite`, then `gemini-3.1-flash-lite`. `GEMINI_MODEL` overrides the first choice. |
| `ANTHROPIC_API_KEY` | The same AI features on Claude (model `claude-opus-5-5`). Preferred over Gemini when both are set. |
| `GROQ_API_KEY` | Contract summaries on Groq. The concierge's tool use needs Anthropic or Gemini. |
| `ORRFIN_AI_PROVIDER` | Forces `anthropic`, `gemini` or `groq`. Blank picks from the keys that are set. |
| `HINDSIGHT_API_KEY` | Supplier memory: structured events only, never document text. The worker sends up to 10 events per scan within a 4-second budget so it never holds up other jobs. To give Claude Code the same memory, run `claude mcp add --transport http hindsight https://api.hindsight.vectorize.io/mcp/orrfin/` and sign in with `/mcp`. |
| `TINYFISH_API_KEY` | Adverse-media research on a supplier, only when someone clicks Research. A rejected key is reported as such on screen. |
| `ORRFIN_DEMO_LOGIN` | One-click sign-in as a seeded persona (store lead, hub manager, procurement, accounts payable, legal, risk, admin) on `/login`. Works only for the fictional demo company. Set `0` for any real deployment. |
| `ORRFIN_API_URL` | Vercel only: the hosted backend that `/api` is proxied to. |
<!-- END AUTO-GENERATED -->

AI also needs an admin to switch it on for the organization under Concierge. Without keys, every screen still works and says what is off rather than showing invented output. Gemini's free tier allows 20 requests per model per day, and one concierge question can use several; enable billing for demos.

## Deploy the web app on Vercel

The repository root is a Next.js app, so Vercel detects it with no settings. Vercel hosts only the web app: the Python API, PostgreSQL and the worker run elsewhere (Render, Railway, a VM, or this Docker stack).

1. Import the GitHub repository in Vercel. `.vercelignore` keeps the Python stack out of the upload, and `next.config.ts` skips the `standalone` output when it detects Vercel.
2. The landing page works with no backend.
3. To make sign-in and the role-based demo at `/demo` work, deploy the backend, then set `ORRFIN_API_URL` in Vercel to its address. `/api/*` is proxied there on the same origin, so session cookies stay first-party. Set `PUBLIC_APP_URL` on the backend to the Vercel address so supplier links point to it.

Check a build locally the way Vercel runs it: `VERCEL=1 npm run build`.

<!-- AUTO-GENERATED from package.json -->
| Command | Description |
|---|---|
| `npm run dev` | Next.js dev server with hot reload; `/api` goes to `http://localhost:8080` (the Docker stack) unless `ORRFIN_API_URL` is set |
| `npm run build` | Production build with type checking |
| `npm run start` | Serve the production build |
<!-- END AUTO-GENERATED -->

## Landing page

`app/page.tsx`, with the tabbed product screens and scroll entrances in `app/components/landing/Landing.tsx` and styles in `app/landing.css`. It uses the app's own tokens from `app/globals.css` (navy, brand blue, Archivo) so the page and the product match. Screenshots in `public/landing/ui/` come from the demo company. `/demo` (`app/demo/page.tsx`) is the role picker judges use to enter the app without a password.

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
- **AI, Hindsight and TinyFish:** answer quality depends on the provider. Gemini answers have been checked by hand on a few demo questions only.
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
app/               Next.js UI: landing page (page.tsx, landing.css, components/landing),
                   product screens under app/app, supplier portal under app/portal,
                   shared shell, UI kit and per-screen workflow guides in components/
public/landing/    landing photographs (with credits.json) and product screenshots
tools/             bootstrap_env.py, stack.py, tally_relay.py
tests/             end-to-end tests run inside the stack
```
