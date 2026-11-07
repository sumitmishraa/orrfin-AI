import Link from 'next/link';

export default function Privacy() {
  return (
    <main className="policy-page">
      <Link href="/">← Orrfin.ai</Link>
      <h1>Privacy notice</h1>
      <p>Orrfin.ai processes the procurement records your organization creates: people and roles, branches and sites, suppliers, requests, approvals, purchase orders, goods receipts, invoices, contracts and the audit trail. Suppliers submit onboarding details, bids and invoices through private, expiring links.</p>
      <h2>Where data is kept</h2>
      <p>Records are held in your deployment's PostgreSQL database with row-level security separating organizations. Uploaded files are held in its private object store and are only served through the application after a permission check. Bank account numbers are not stored: only the last four digits are kept.</p>
      <h2>Optional services</h2>
      <p>If your administrator turns them on: an AI provider (Anthropic Claude by default) receives contract text or questions with the matching records; Hindsight receives structured supplier events without document text; TinyFish receives public-research queries a person explicitly requests. Each is off unless configured, and AI also needs your organization's consent in the app.</p>
      <h2>Access and retention</h2>
      <p>Members see records allowed by their role and branch. Records are kept until your organization deletes them; the audit trail is append-only. Contact the organization that invited you for access or deletion requests.</p>
      <p>Updated 7 November 2026.</p>
    </main>
  );
}
