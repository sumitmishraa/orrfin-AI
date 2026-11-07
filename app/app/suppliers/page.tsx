'use client';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { FormEvent, useState } from 'react';
import { Card, Field, Message, Page, Status, Table, useAction, useLoad } from '../../components/ui';
import { can, useMe } from '../../components/Shell';
import { api } from '../../lib/api';

export default function Suppliers() {
  const me = useMe();
  const router = useRouter();
  const [q, setQ] = useState('');
  const [status, setStatus] = useState('');
  const list = useLoad(() => api(`/api/suppliers?limit=300${q ? `&q=${encodeURIComponent(q)}` : ''}${status ? `&status=${status}` : ''}`), [q, status]);
  const categories = useLoad(() => api('/api/org/categories'));
  const [form, setForm] = useState({ name: '', email: '', gstin: '', category_id: '' });
  const { busy, message, run } = useAction();

  async function add(event: FormEvent) {
    event.preventDefault();
    const created = await run(() => api('/api/suppliers', { body: { ...form, category_id: form.category_id || null } }));
    if (created) router.push(`/app/suppliers/${created.id}`);
  }
  async function importCsv(event: any) {
    const file = event.target.files?.[0];
    if (!file) return;
    const data = new FormData(); data.append('file', file);
    await run(() => api('/api/suppliers/import', { form: data }), 'Imported. New suppliers stay in draft until onboarding is approved.');
    list.reload();
  }

  return (
    <Page kicker="Supplier Onboarding" title="Suppliers" subtitle="Add or import suppliers, send them an onboarding link, review their answers and documents with automated checks, then approve."
      actions={can(me, 'suppliers.write') && <label className="button secondary">Import CSV<input type="file" accept=".csv,text/csv" hidden onChange={importCsv} /></label>}>
      <Message message={message} />
      {can(me, 'suppliers.write') && (
        <Card title="Add a supplier">
          <form className="row" onSubmit={add}>
            <Field label="Name"><input required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></Field>
            <Field label="Email"><input type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} /></Field>
            <Field label="GSTIN (optional)"><input value={form.gstin} onChange={(e) => setForm({ ...form, gstin: e.target.value.toUpperCase() })} /></Field>
            <Field label="Category"><select value={form.category_id} onChange={(e) => setForm({ ...form, category_id: e.target.value })}><option value="">-</option>{(categories.data || []).map((c: any) => <option key={c.id} value={c.id}>{c.name}</option>)}</select></Field>
            <button className="button" disabled={busy}>Add</button>
          </form>
        </Card>
      )}
      <Card title={`${list.data?.total ?? '…'} suppliers`} actions={<div className="inline-form"><input placeholder="Search name or GSTIN" value={q} onChange={(e) => setQ(e.target.value)} /><select value={status} onChange={(e) => setStatus(e.target.value)} aria-label="Status"><option value="">All</option>{['approved', 'onboarding', 'draft', 'suspended'].map((s) => <option key={s}>{s}</option>)}</select></div>}>
        <Table rows={list.data?.items} onRow={(r: any) => router.push(`/app/suppliers/${r.id}`)} columns={[
          { key: 'name', label: 'Supplier', render: (r: any) => <Link href={`/app/suppliers/${r.id}`}>{r.name}{r.preferred ? ' ★' : ''}</Link> },
          { key: 'category', label: 'Category', render: (r: any) => r.category || '-' }, { key: 'gstin', label: 'GSTIN', render: (r: any) => r.gstin || '-' },
          { key: 'status', label: 'Status', render: (r: any) => <Status value={r.status} /> }, { key: 'risk_tier', label: 'Risk', render: (r: any) => <Status value={r.risk_tier} /> },
        ]} />
      </Card>
    </Page>
  );
}
