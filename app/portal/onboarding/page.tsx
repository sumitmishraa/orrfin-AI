'use client';
import { FormEvent, useEffect, useState } from 'react';
import { Card, Field, Message, Notice, Status, Table, useAction } from '../../components/ui';
import { portalApi } from '../../lib/api';
import { PortalFrame, usePortalToken } from '../shared';

export default function OnboardingPortal() {
  const token = usePortalToken();
  const [view, setView] = useState<any>(null);
  const [error, setError] = useState('');
  const [checks, setChecks] = useState<any>(null);
  const [form, setForm] = useState({ legal_name: '', gstin: '', pan: '', address: '', contact_name: '', contact_email: '', phone: '', bank_account_number: '', ifsc: '', msme_number: '', cert_name: '', cert_expiry: '', declares_no_conflict_of_interest: false, accepts_code_of_conduct: false });
  const { busy, message, run } = useAction();

  useEffect(() => { if (token !== null) portalApi('/api/portal/onboarding', token).then(setView).catch((e) => setError(e.message)); }, [token]);
  if (error) return <PortalFrame title="Supplier onboarding"><Notice tone="error">{error}</Notice></PortalFrame>;
  if (!view || token === null) return <PortalFrame title="Supplier onboarding"><p>Loading…</p></PortalFrame>;
  const set = (k: string) => (e: any) => setForm({ ...form, [k]: e.target.type === 'checkbox' ? e.target.checked : e.target.value });

  async function submit(event: FormEvent) {
    event.preventDefault();
    const { cert_name, cert_expiry, ...rest } = form;
    const result = await run(() => portalApi('/api/portal/onboarding', token as string, { body: { ...rest, certifications: cert_name && cert_expiry ? [{ name: cert_name, expiry: cert_expiry }] : [] } }), 'Submitted. The buyer will review your details.');
    if (result) setChecks(result.checks);
  }
  async function upload(kind: string, event: any) {
    const file = event.target.files?.[0];
    if (!file) return;
    const data = new FormData(); data.append('kind', kind); data.append('file', file);
    await run(() => portalApi('/api/portal/onboarding/documents', token as string, { form: data }), `${kind.replace(/_/g, ' ')} uploaded.`);
  }

  return (
    <PortalFrame title={`Welcome, ${view.supplier}`}>
      <Message message={message} />
      <Card title="Company and tax details">
        <form className="form" onSubmit={submit}>
          <div className="row"><Field label="Legal name"><input required value={form.legal_name} onChange={set('legal_name')} /></Field><Field label="GSTIN"><input required minLength={15} maxLength={15} value={form.gstin} onChange={(e) => setForm({ ...form, gstin: e.target.value.toUpperCase() })} /></Field><Field label="PAN"><input required minLength={10} maxLength={10} value={form.pan} onChange={(e) => setForm({ ...form, pan: e.target.value.toUpperCase() })} /></Field></div>
          <Field label="Registered address"><input required value={form.address} onChange={set('address')} /></Field>
          <div className="row"><Field label="Contact name"><input required value={form.contact_name} onChange={set('contact_name')} /></Field><Field label="Accounts email"><input type="email" required value={form.contact_email} onChange={set('contact_email')} /></Field><Field label="Phone"><input value={form.phone} onChange={set('phone')} /></Field></div>
          <div className="row"><Field label="Bank account number" hint="Only the last four digits are kept."><input required inputMode="numeric" value={form.bank_account_number} onChange={set('bank_account_number')} /></Field><Field label="IFSC"><input required value={form.ifsc} onChange={(e) => setForm({ ...form, ifsc: e.target.value.toUpperCase() })} /></Field><Field label="MSME (Udyam) number"><input value={form.msme_number} onChange={set('msme_number')} /></Field></div>
          <div className="row"><Field label="Certification (e.g. ISO 9001)"><input value={form.cert_name} onChange={set('cert_name')} /></Field><Field label="Valid until"><input type="date" value={form.cert_expiry} onChange={set('cert_expiry')} /></Field></div>
          <label className="check"><input type="checkbox" checked={form.declares_no_conflict_of_interest} onChange={set('declares_no_conflict_of_interest')} /> No employee of the buyer has a financial interest in our company.</label>
          <label className="check"><input type="checkbox" checked={form.accepts_code_of_conduct} onChange={set('accepts_code_of_conduct')} /> We accept the supplier code of conduct.</label>
          <button className="button" disabled={busy}>Submit</button>
        </form>
      </Card>
      <Card title="Documents">
        {view.document_kinds.map((kind: string) => <Field key={kind} label={`${kind.replace(/_/g, ' ')}${view.required_documents.includes(kind) ? ' (required)' : ''}`}><input type="file" accept="application/pdf,image/png,image/jpeg" onChange={(e) => upload(kind, e)} /></Field>)}
      </Card>
      {checks && <Card title="Automatic checks"><Table rows={Object.entries(checks).map(([name, c]: any) => ({ id: name, name, ...c }))} columns={[{ key: 'name', label: 'Check', render: (r: any) => r.name.replace(/_/g, ' ') }, { key: 'status', label: 'Result', render: (r: any) => <Status value={r.status} /> }, { key: 'detail', label: 'Detail' }]} /></Card>}
    </PortalFrame>
  );
}
