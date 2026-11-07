'use client';
import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';
import { FormEvent, Suspense, useEffect, useState } from 'react';
import { Card, Field, Message, Page, Status, Table, useAction, useLoad } from '../../components/ui';
import { can, useMe } from '../../components/Shell';
import { api, day, inr } from '../../lib/api';

type Line = { item_id: string; description: string; quantity: string; estimated_price: string };

function NewRequest({ onCreated }: { onCreated: (id: string) => void }) {
  const params = useSearchParams();
  const org = useLoad(() => Promise.all([api('/api/org/overview'), api('/api/org/categories'), api('/api/org/locations')]));
  const [form, setForm] = useState({ branch_id: '', location_id: '', category_id: '', title: '', justification: '', needed_by: new Date(Date.now() + 10 * 864e5).toISOString().slice(0, 10), route: 'direct' });
  const [lines, setLines] = useState<Line[]>([{ item_id: '', description: '', quantity: '1', estimated_price: '' }]);
  const [items, setItems] = useState<any[]>([]);
  const { busy, message, run } = useAction();

  useEffect(() => {
    const draftId = params.get('draft');
    if (!draftId) return;
    api('/api/concierge/drafts').then((drafts: any[]) => {
      const draft = drafts.find((row) => row.id === draftId);
      if (!draft) return;
      const p = draft.payload;
      setForm((f) => ({ ...f, branch_id: p.branch_id, category_id: p.category_id || '', title: p.title, justification: p.justification, needed_by: p.needed_by }));
      setLines(p.lines.map((l: any) => ({ item_id: l.item_id || '', description: l.description, quantity: l.quantity, estimated_price: l.estimated_price })));
    });
  }, [params]);
  useEffect(() => { if (form.category_id) api(`/api/org/items?category_id=${form.category_id}&limit=200`).then(setItems); }, [form.category_id]);

  if (!org.data) return null;
  const [overview, categories, locations] = org.data as any[];
  const set = (key: string) => (e: any) => setForm({ ...form, [key]: e.target.value });
  const setLine = (i: number, key: keyof Line, value: string) => setLines(lines.map((l, n) => {
    if (n !== i) return l;
    const next = { ...l, [key]: value };
    if (key === 'item_id') { const item = items.find((x) => x.id === value); if (item) { next.description = item.name; next.estimated_price = item.benchmark_price || ''; } }
    return next;
  }));

  async function submit(event: FormEvent) {
    event.preventDefault();
    const created = await run(() => api('/api/intakes', { body: { ...form, location_id: form.location_id || null, lines: lines.map((l) => ({ ...l, item_id: l.item_id || null })) } }));
    if (created) onCreated(created.id);
  }

  return (
    <Card title="New purchase request">
      <form className="form" onSubmit={submit}>
        <div className="row">
          <Field label="Branch"><select required value={form.branch_id} onChange={set('branch_id')}><option value="">Choose…</option>{overview.branches.map((b: any) => <option key={b.id} value={b.id}>{b.code} · {b.name}</option>)}</select></Field>
          <Field label="Deliver to"><select value={form.location_id} onChange={set('location_id')}><option value="">Branch default</option>{locations.filter((l: any) => l.branch_id === form.branch_id).map((l: any) => <option key={l.id} value={l.id}>{l.name}</option>)}</select></Field>
          <Field label="Category"><select required value={form.category_id} onChange={set('category_id')}><option value="">Choose…</option>{categories.map((c: any) => <option key={c.id} value={c.id}>{c.name}</option>)}</select></Field>
        </div>
        <div className="row">
          <Field label="What do you need?"><input required minLength={3} value={form.title} onChange={set('title')} /></Field>
          <Field label="Needed by"><input type="date" required value={form.needed_by} onChange={set('needed_by')} /></Field>
          <Field label="Route"><select value={form.route} onChange={set('route')}><option value="direct">Buy from a preferred supplier</option><option value="sourcing">Get quotes (RFQ)</option></select></Field>
        </div>
        <Field label="Why is this needed?"><textarea value={form.justification} onChange={set('justification')} rows={2} /></Field>
        <table className="lines"><thead><tr><th>Catalogue item</th><th>Description</th><th>Qty</th><th>Est. unit price (₹)</th><th /></tr></thead><tbody>
          {lines.map((l, i) => (
            <tr key={i}>
              <td><select value={l.item_id} onChange={(e) => setLine(i, 'item_id', e.target.value)}><option value="">Free text</option>{items.map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}</select></td>
              <td><input value={l.description} onChange={(e) => setLine(i, 'description', e.target.value)} /></td>
              <td><input required inputMode="decimal" value={l.quantity} onChange={(e) => setLine(i, 'quantity', e.target.value)} /></td>
              <td><input required inputMode="decimal" value={l.estimated_price} onChange={(e) => setLine(i, 'estimated_price', e.target.value)} /></td>
              <td>{lines.length > 1 && <button type="button" className="link" onClick={() => setLines(lines.filter((_, n) => n !== i))}>Remove</button>}</td>
            </tr>
          ))}
        </tbody></table>
        <div className="actions">
          <button type="button" className="button secondary" onClick={() => setLines([...lines, { item_id: '', description: '', quantity: '1', estimated_price: '' }])}>Add line</button>
          <button className="button" disabled={busy}>Save request</button>
        </div>
        <Message message={message} />
      </form>
    </Card>
  );
}

function IntakeList() {
  const me = useMe();
  const router = useRouter();
  const [status, setStatus] = useState('');
  const [creating, setCreating] = useState(false);
  const list = useLoad(() => api(`/api/intakes?limit=100${status ? `&status=${status}` : ''}`), [status]);
  return (
    <Page kicker="Intake-to-Procure" title="Purchase requests" subtitle="Every purchase starts here: budget is checked, preferred suppliers and contracts are suggested, and approvals route automatically."
      actions={can(me, 'intake.write') && <button className="button" onClick={() => setCreating(!creating)}>{creating ? 'Close' : 'New request'}</button>}>
      {creating && <NewRequest onCreated={(id) => router.push(`/app/intake/${id}`)} />}
      <Card title={`${list.data?.total ?? '…'} requests`} actions={
        <select value={status} onChange={(e) => setStatus(e.target.value)} aria-label="Filter by status">
          <option value="">All statuses</option>{['draft', 'pending_approval', 'approved', 'sourcing', 'ordered', 'rejected'].map((s) => <option key={s} value={s}>{s.replace('_', ' ')}</option>)}
        </select>}>
        <Table rows={list.data?.items} onRow={(r: any) => router.push(`/app/intake/${r.id}`)} columns={[
          { key: 'number', label: 'Number', render: (r: any) => <Link href={`/app/intake/${r.id}`}>{r.number}</Link> },
          { key: 'title', label: 'Request' },
          { key: 'status', label: 'Status', render: (r: any) => <Status value={r.status} /> },
          { key: 'needed_by', label: 'Needed by', render: (r: any) => day(r.needed_by) },
          { key: 'estimated_total', label: 'Estimate (incl. GST)', align: 'right', render: (r: any) => inr(r.estimated_total) },
        ]} />
      </Card>
    </Page>
  );
}

export default function IntakePage() {
  return <Suspense><IntakeList /></Suspense>;
}
