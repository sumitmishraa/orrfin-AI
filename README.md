# VendorMind

A procurement decision workspace with a public landing page and a password-protected synthetic-data demo. It compares eligible quotes, explains structured supplier metrics, captures outcomes and replays a saved decision. Hindsight provides source-linked supporting memory; it never silently changes the numeric score. No purchasing or supplier communication is performed.

## Local setup

Requirements: Node.js 20+, Python 3.10+, and optionally a PostgreSQL database and Hindsight Cloud account.

1. Install dependencies: `npm install` and `python -m pip install -r backend/requirements.txt`.
2. Set `DEMO_PASSWORD` and a long random `SESSION_SECRET` in the backend environment. See `.env.example`. Never commit or send secrets through chat.
3. Start the API: `python -m uvicorn backend.app:app --host 127.0.0.1 --port 8000`.
4. In another terminal start the frontend: `npm run dev`. Open `http://localhost:3000` and use your chosen password at `/demo`.

For PowerShell, set variables with `$env:DEMO_PASSWORD = '...'` and `$env:SESSION_SECRET = '...'` in the terminal that runs the API. The values in `.env.example` are placeholders and are intentionally rejected. SQLite is used locally by default; set `DATABASE_URL` to a PostgreSQL connection string for a deployed demo.

## Hindsight

Create a Hindsight Cloud API key as described in [Hindsight setup](https://docs.hindsight.vectorize.io/cloud/getting-started/) and set `HINDSIGHT_API_KEY`, `HINDSIGHT_API_URL` and `HINDSIGHT_BANK_ID` on the backend. In the workspace, **Sync demo memory** submits up to six unsynced synthetic events at a time. Hindsight indexing is asynchronous: wait briefly and replay or request another decision. New outcomes are saved first and then submitted to memory; failures are visible and can be retried via sync. The application works in degraded mode if Hindsight is unavailable. Only retrieved text containing both a known supplier ID and a known source ID is displayed.

## Demo walkthrough

1. Compare the default 500-litre, Bengaluru, two-day request.
2. Inspect the supplier comparison, exclusions, score and evidence in the decision receipt.
3. Record an outcome for an eligible supplier and use Learning replay to compare the saved snapshot against the current evidence.
4. If Hindsight is configured, sync seed events, wait for indexing, then run replay to see supported recalled evidence.

Price score is the cheapest eligible quote divided by the supplier's quote, multiplied by 100. Delivery, quality and invoice percentages use up to 20 most recent known outcomes. Weights are 35%, 30%, 20%, and 15%; when a metric is unknown, known weights are renormalized. Suppliers with fewer than three delivery outcomes remain eligible but are listed after those with more evidence and marked for manual review. These are illustrative decision aids, not validated predictions. Quotes use unit price times quantity; no tax or freight data is represented.

## Deployment

Deploy the Next.js app and FastAPI service, set `BACKEND_URL` for the frontend, and use PostgreSQL through `DATABASE_URL`. Set `COOKIE_SECURE=1` behind HTTPS and configure unique `DEMO_PASSWORD` and `SESSION_SECRET`. Keep the backend behind the frontend proxy or protect direct network access, and configure API and database secrets on the host. The shared password is suitable only for this controlled synthetic-data demo; it is not tenant-aware authentication. The project has no user accounts, role-based permissions, migrations or real-data privacy guarantees.

## Verification

Run `python -m pytest backend/test_app.py` and `npm run build`. The Hindsight integration requires a real configured account for a live retain/recall/reflect test; without one, tests cover the explicit degraded state.
