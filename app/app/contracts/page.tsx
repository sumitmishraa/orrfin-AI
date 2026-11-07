'use client';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { FormEvent, useState } from 'react';
import { Card, Field, Message, Page, Status, Table, useAction, useLoad } from '../../components/ui';
import { can, useMe } from '../../components/Shell';
import { api, day, inr } from '../../lib/api';

export default function Contracts() {
  const me = useMe();
  const router = useRouter();
  const list = useLoad(() => api('/api/contracts'));
  const library = useLoad(() => api('/api/contracts/library'));
  const suppliers = useLoad(() => api('/api/suppliers?status=approved&limit=500'));
  const year = new Date().getFullYear();
  const [form, setForm] = useState({ title: '', supplier_id: '', template_id: '', start_on: `${year}-11-01`, end_on: `${year + 1}-10-31`, value: '0', auto_renew: false, notice_days: '30' });
  const { busy, message, run } = useAction();
  const set = (k: string) => (e: any) => setForm({ ...form, [k]: e.target.type === 'checkbox' ? e.target.checked : e.target.value });

  async function generate(event: FormEvent) {
    event.preventDefault();
    const contract = await run(() => api('/api/contracts', { body: { ...form, notice_days: Number(form.notice_days) } }));
    if (contract) router.push(`/app/contracts/${contract.id}`);
  }

  return (
    <Page kicker="AI Contract Orchestration" title="Contracts" subtitle="Generate from your clause library, upload counterparty paper, compare versions, review against your standards and track renewals.">
      <Message message={message} />
      {can(me, 'contracts.write') && (
        <Card title="Generate a contract">
          <form className="form" onSubmit={generate}>
            <div className="row">
              <Field label="Title"><input required value={form.title} onChange={set('title')} /></Field>
              <Field label="Supplier"><select required value={form.supplier_id} onChange={set('supplier_id')}><option value="">Choose…</option>{(suppliers.data?.items || []).map((s: any) => <option key={s.id} value={s.id}>{s.name}</option>)}</select></Field>
              <Field label="Template"><select required value={form.template_id} onChange={set('template_id')}><option value="">Choose…</option>{(library.data?.templates || []).map((t: any) => <option key={t.id} value={t.id}>{t.name}</option>)}</select></Field>
            </div>
            <div className="row">
              <Field label="Starts"><input type="date" value={form.start_on} onChange={set('start_on')} /></Field>
              <Field label="Ends"><input type="date" value={form.end_on} onChange={set('end_on')} /></Field>
              <Field label="Value (₹)"><input inputMode="decimal" value={form.value} onChange={set('value')} /></Field>
              <Field label="Notice (days)"><input inputMode="numeric" value={form.notice_days} onChange={set('notice_days')} /></Field>
            </div>
            <label className="check"><input type="checkbox" checked={form.auto_renew} onChange={set('auto_renew')} /> Renews automatically</label>
            <button className="button" disabled={busy}>Generate</button>
          </form>
        </Card>
      )}
      <Card title="All contracts">
        <Table rows={list.data} onRow={(r: any) => router.push(`/app/contracts/${r.id}`)} columns={[
          { key: 'number', label: 'Number', render: (r: any) => <Link href={`/app/contracts/${r.id}`}>{r.number}</Link> },
          { key: 'title', label: 'Title' }, { key: 'supplier', label: 'Supplier' }, { key: 'status', label: 'Status', render: (r: any) => <Status value={r.status} /> },
          { key: 'end_on', label: 'Ends', render: (r: any) => <span className={r.days_to_expiry <= 45 ? 'overdue' : ''}>{day(r.end_on)} ({r.days_to_expiry} days)</span> },
          { key: 'value', label: 'Value', align: 'right', render: (r: any) => inr(r.value) },
        ]} />
      </Card>
    </Page>
  );
}
