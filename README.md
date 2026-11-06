# VendorMind

VendorMind connects supplier discovery, quote requests, purchase orders, delivery receipts and three-way invoice matching. The landing page and a separate fictional-data demo remain available alongside an organization-scoped pilot workspace.

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

Open `http://localhost:3000/demo`. This route uses the original synthetic dataset and shared demo password; it is not the real pilot workspace at `/workspace`. Purchase orders and supplier messages are never sent automatically.

## Workflow

Buyers add or import suppliers, review and approve their details, create requests with line items, and share individual seven-day supplier links. Suppliers submit prices, tax, freight and lead time; buyers see eligible quotes ordered by total and choose one to create an order. Buyers enter deliveries, including partial quantities, and the supplier enters invoice details and optionally uploads a PDF, PNG or JPEG. The matching view compares order, cumulative receipts and cumulative invoices at line level, including unit price, quantities, tax and freight. Exceptions require a human review; no payment is initiated. The expected invoice draft is not a supplier invoice.

Supplier tokens are held in URL fragments and sent in a request header, stored only as hashes on the server, scoped to one supplier/request, expiring and revocable. A new order-stage link can be issued if the original link expires.

## Validation and limitations

Run `python -m pytest backend/test_app.py backend/test_pilot.py`, `npm run build` and `npm audit --omit=dev`. The tests exercise the API with synthetic data and mocked authentication; they do **not** replace a live Supabase/RLS, real-storage, Google Places, Hindsight or deployment test. The current version has no organization-invite UI, accounting/ERP integration, automated invoice extraction, payment processing or self-service retention/deletion controls. Review the privacy and pilot terms, access controls, recovery procedures and hosting costs before onboarding real organizations.

The supplied `render.yaml` describes a frontend and private API using externally supplied Supabase database credentials. It does not create the Supabase project. Its `PILOT_RLS_READY` default is deliberately off. Review the provider plan and costs before applying it.
