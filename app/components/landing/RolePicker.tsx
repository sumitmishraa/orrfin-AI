'use client';
/*
  Role-based demo entry. The list mirrors DEMO_PERSONAS in orrfin/api/auth.py (same keys), so it
  renders at once without waiting for the API. Choosing a role calls /api/auth/demo-login, which
  signs in as that seeded person; the server allows it only for the fictional demo company.
*/
import { useDemoLogin } from './DemoPersonas';

const ROLES = [
  { key: 'store', label: 'Store lead, Pune', does: 'Raises purchase requests for a dark store and records what was delivered.', lands: 'Requests' },
  { key: 'manager', label: 'Hub manager, Pune', does: 'Approves requests for the Pune hub and its stores.', lands: 'Approvals' },
  { key: 'procurement', label: 'Head of procurement', does: 'Approves spend, runs RFQs, issues purchase orders and manages suppliers.', lands: 'Overview' },
  { key: 'finance', label: 'Accounts payable lead', does: 'Reviews invoices, resolves three-way match exceptions and approves payment.', lands: 'Invoices' },
  { key: 'legal', label: 'Legal counsel', does: 'Generates, reviews and approves supplier contracts.', lands: 'Contracts' },
  { key: 'risk', label: 'Risk manager', does: 'Scores suppliers, places holds and reviews the evidence.', lands: 'Risk' },
  { key: 'admin', label: 'Company admin', does: 'Sees everything: branches, people, approval rules, ERP and AI settings.', lands: 'Overview' },
];

export default function RolePicker() {
  const { busy, error, signIn } = useDemoLogin();
  return (
    <div className="ol-roles">
      <ul aria-label="Demo roles">
        {ROLES.map((r) => (
          <li key={r.key}>
            <button type="button" className="ol-role" disabled={!!busy} onClick={() => signIn(r.key)}>
              <strong>{r.label}</strong>
              <span>{r.does}</span>
              <em>{busy === r.key ? 'Opening…' : `Enter as ${r.label.split(',')[0].toLowerCase()}`}</em>
            </button>
          </li>
        ))}
      </ul>
      {error && (
        <p className="ol-roles-error" role="alert">
          The demo backend isn&rsquo;t connected to this site yet ({error}). It runs separately from the web pages; please try again in a moment or contact the team.
        </p>
      )}
    </div>
  );
}
