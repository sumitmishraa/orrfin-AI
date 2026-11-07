# Orrfin AI

Orrfin AI connects supplier discovery, quote requests, purchase orders, delivery receipts and three-way invoice matching. The landing page and a separate fictional-data demo remain available alongside an organization-scoped pilot workspace.

## Multi-branch preview status

The **Multi-branch platform** tab includes a fictional ten-branch organization, branch creation and CSV import, owner-reviewed intake, branch/category/amount routing labels, a supplier risk register, supplier onboarding links and questionnaires, contract text versioning with literal keyword excerpts, workspace record search, and local Zoho purchase-order mapping previews. An approved intake creates a sourcing request. The purchase-order view offers a downloadable PDF. Existing sourcing, supplier portal, delivery and structured three-way matching remain available.

Supplier research can call TinyFish only on an explicit buyer request, using `TINYFISH_API_KEY` in the backend. Results are unverified and must be reviewed. The optional Groq-based assistant requires both `GROQ_API_KEY` and organization consent; it sends a question and matching record excerpts, validates source IDs, and cannot initiate transactions. Neither service is contacted from the fictional demo. Live provider access remains unverified.

Searchable PDFs can be read as unverified page text. For scanned PDFs, install Tesseract on the API host, set `ORRFIN_OCR_ENABLED=1`, and optionally set `TESSERACT_CMD` to its executable. OCR is bounded to 10 scanned pages and output must be checked against the original. Invoice matching still uses supplier-entered structured values; PDF fields are not extracted into or automatically compared with those records.

This remains an **incomplete preview**, not production-ready. The existing pilot authorizes at organization level; branch-specific authorization, enforceable assigned approvers, approval delegation and multi-branch requests are not implemented. The approval label identifies a team but does not authenticate that team. Contract checks are keyword searches on pasted text, not legal advice or AI clause analysis; private file/version storage, a configurable playbook and suggested revisions are not implemented. Onboarding does not yet collect document attachments or enforce branch availability. ERP previews are local only: Zoho, SAP and Tally adapters, mapping validation, delivery/retry/reconciliation and sandbox tests remain outstanding. Automated structured PDF extraction and correction remain outstanding. Do not enable real pilot access until these gaps and security, integration, backup, load and operational checks are resolved.

The synthetic demo is shared and uses fictional records. It does not imply affiliation with any real company. No external ERP action is performed. New database tables must be included in reviewed RLS setup before a deployment; `backend/enable_rls.sql` is a draft, not proof that it has been applied.

## Pilot setup

The pilot is intentionally disabled until a **dedicated** Supabase project and database isolation are configured. Do not point it at an unrelated project or enable it for real records before verification.

1. Install Node.js 20+ and Python 3.10+. Run `npm ci` and `python -m pip install -r backend/requirements.txt`.
2. Create a dedicated Supabase project. Set `DATABASE_URL` to its PostgreSQL connection string, `SUPABASE_URL` to its project URL, `SUPABASE_ANON_KEY` to its publishable/anon key, and `SUPABASE_SERVICE_ROLE_KEY` to its secret server-only key. Never expose the service key to the browser or commit it.
3. Configure Supabase Auth email magic links, the site's URL and redirect URL (`/workspace`), and a production SMTP provider. Configure a **private** Storage bucket named `vendormind-invoices`.
4. Restrict or disable Supabase Data API access during setup. Start the backend once with `PILOT_RLS_READY=0` so the tables are created. Apply and review `backend/enable_rls.sql` to the dedicated database, then verify row-level security, revoked Data API privileges and cross-organization isolation. Only after verification set `PILOT_RLS_READY=1` and restart the backend. FastAPI's direct database role is trusted and application authorization checks must remain enabled.
5. Set `PUBLIC_APP_URL` to the public HTTPS frontend URL; it is used for supplier links. Set `COOKIE_SECURE=1` for HTTPS. Keep the API private behind the frontend proxy; use `--no-access-log` when starting the backend.
6. For live supplier discovery, create a restricted, billing-enabled Google Places API key and set `GOOGLE_PLACES_API_KEY` on the backend. The application shows Google Maps attribution and retains only the selected Place ID; supplier information is entered independently by buyers.
7. Add a **replacement** Hindsight Cloud key as `HINDSIGHT_API_KEY` on the backend, not in source control or browser code. Each workspace uses its own memory bank and retains only pseudonymous supplier/event IDs and source references. Memory writes are retriable from the workspace. Hindsight is optional for the structured workflow but required to verify the memory integration.

Set environment variables on the hosting provider or in the backend shell; `.env.example` lists names without secrets. The default local SQLite database is for the fictional demo, not pilot records. Real Hindsight, Google Places, Supabase Auth, Storage and PostgreSQL must be configured before end-to-end service verification.

## Local fictional demo

Set `DEMO_PASSWORD` and a unique long `SESSION_SECRET` in the backend environment, then run:

```text
python -m uvicorn backend.app:app --host 127.0.0.1 --port 8000 --no-access-log
npm run dev
```

Open `http://localhost:3000/demo` and enter the configured demo password. This route now opens the complete supplier, quote, order and invoice workflow with a separate, clearly labelled fictional workspace. It includes example quotes and an invoice mismatch, and lets you create supplier links and try the supplier portal. Use **Reset sample** to restore the examples after exploring; this clears only the shared fictional workspace and its temporary files. Sample search results are fictional, Hindsight is never contacted from this workspace, and sample invoice files are held in temporary server memory only. Never upload real confidential data to this shared demo. The original comparison-only demo remains at `/legacy-demo`. The real pilot is separate at `/workspace`; no supplier messages or purchase orders are sent automatically.

## Workflow

Buyers add or import suppliers, review and approve their details, create requests with line items, and share individual seven-day supplier links. Suppliers submit prices, tax, freight and lead time; buyers see eligible quotes ordered by total and choose one to create an order. Buyers enter deliveries, including partial quantities, and the supplier enters invoice details and optionally uploads a PDF, PNG or JPEG. The matching view compares order, cumulative receipts and cumulative invoices at line level, including unit price, quantities, tax and freight. Exceptions require a human review; no payment is initiated. The expected invoice draft is not a supplier invoice.

Supplier tokens are held in URL fragments and sent in a request header, stored only as hashes on the server, scoped to one supplier/request, expiring and revocable. A new order-stage link can be issued if the original link expires.

## Validation and limitations

Run `python -m pytest backend/test_app.py backend/test_pilot.py backend/test_enterprise.py`, `npm run build` and `npm audit --omit=dev`. The tests exercise the API with synthetic data and mocked authentication; they do **not** replace a live Supabase/RLS, real-storage, Google Places, Hindsight or deployment test. The current version has no organization-invite UI, ERP delivery integration, automated structured invoice extraction, payment processing or self-service retention/deletion controls. Review the privacy and pilot terms, access controls, recovery procedures and hosting costs before onboarding real organizations.

The supplied `render.yaml` describes a frontend and private API using externally supplied Supabase database credentials. It does not create the Supabase project. Its `PILOT_RLS_READY` default is deliberately off. Review the provider plan and costs before applying it.
