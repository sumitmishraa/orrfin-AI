'use client';
import Link from 'next/link';
import { useParams, useRouter } from 'next/navigation';
import { useState } from 'react';
import { Card, Field, Loading, Message, Notice, Page, Status, Table, useAction, useLoad } from '../../../components/ui';
import { can, useMe } from '../../../components/Shell';
import { api, day, inr, qty } from '../../../lib/api';

export default function IntakeDetail() {
  const { id } = useParams<{ id: string }>();
  const me = useMe();
  const router = useRouter();
  const intake = useLoad(() => api(`/api/intakes/${id}`), [id]);
  const suppliers = useLoad(() => (can(me, 'suppliers.read') ? api('/api/suppliers?status=approved&limit=500') : Promise.resolve({ items: [] })));
  const [supplierId, setSupplierId] = useState('');
  const [invitees, setInvitees] = useState<string[]>([]);
  const [links, setLinks] = useState<any[]>([]);
  const { busy, message, run } = useAction();
  const d = intake.data;
  if (!d) return <Page title="Request"><Loading error={intake.error} /></Page>;
  const inCategory = (suppliers.data?.items || []).filter((s: any) => s.category_id === d.category_id);

  return (
    <Page kicker={d.number} title={d.title} subtitle={`Needed by ${day(d.needed_by)} · ${d.route === 'sourcing' ? 'Quotes requested' : 'Direct purchase'}`}
      actions={<><Status value={d.status} />{d.status === 'draft' && can(me, 'intake.write') && <button className="button" disabled={busy} onClick={() => run(() => api(`/api/intakes/${id}/submit`, { method: 'POST' })).then(intake.reload)}>Submit for approval</button>}</>}>
      <Message message={message} />
      <div className="grid-2">
        <Card title="Lines">
          <Table rows={d.lines} columns={[
            { key: 'description', label: 'Item' }, { key: 'hsn', label: 'HSN' },
            { key: 'quantity', label: 'Qty', align: 'right', render: (r: any) => `${qty(r.quantity)} ${r.unit}` },
            { key: 'estimated_price', label: 'Est. price', align: 'right', render: (r: any) => inr(r.estimated_price) },
            { key: 'gst_rate', label: 'GST', align: 'right', render: (r: any) => `${Number(r.gst_rate)}%` },
          ]} />
          <p className="total">Estimate incl. GST <strong>{inr(d.estimated_total)}</strong></p>
        </Card>
        <Card title="Checks before approval">
          <Notice tone={d.budget_check.status === 'over' ? 'warn' : d.budget_check.status === 'within' ? 'ok' : 'info'}>{d.budget_check.message}</Notice>
          {d.suggestions.price_flags?.map((f: any) => <Notice key={f.line_no} tone="warn">{f.message}</Notice>)}
          <h3>Suggested suppliers</h3>
          <Table rows={d.suggestions.suppliers} empty="No approved suppliers in this category yet." columns={[
            { key: 'name', label: 'Supplier', render: (r: any) => (can(me, 'suppliers.read') ? <Link href={`/app/suppliers/${r.id}`}>{r.name}</Link> : r.name) },
            { key: 'preferred', label: 'Preferred', render: (r: any) => (r.preferred ? 'Yes' : '-') },
            { key: 'risk_tier', label: 'Risk', render: (r: any) => <Status value={r.risk_tier} /> },
            { key: 'contract', label: 'Contract', render: (r: any) => r.contract || '-' },
          ]} />
        </Card>
      </div>
      <Card title="Approval route">
        <Table rows={d.tasks} empty="Not submitted yet." columns={[
          { key: 'step', label: 'Step' }, { key: 'approver_role', label: 'Approver', render: (r: any) => r.approver_role.replace('_', ' ') },
          { key: 'status', label: 'Status', render: (r: any) => <Status value={r.status} /> },
          { key: 'decided_at', label: 'Decided', render: (r: any) => day(r.decided_at) }, { key: 'comment', label: 'Comment', render: (r: any) => r.comment || '-' },
        ]} />
      </Card>
      {d.purchase_order && <Notice tone="ok">Purchase order created: <Link href={`/app/orders/${d.purchase_order.id}`}>{d.purchase_order.number || 'draft'}</Link></Notice>}
      {d.status === 'approved' && can(me, 'po.write') && (
        <div className="grid-2">
          <Card title="Buy directly">
            <Field label="Supplier"><select value={supplierId || d.preferred_supplier_id || ''} onChange={(e) => setSupplierId(e.target.value)}><option value="">Choose…</option>{inCategory.map((s: any) => <option key={s.id} value={s.id}>{s.name} ({s.risk_tier})</option>)}</select></Field>
            <button className="button" disabled={busy} onClick={async () => {
              const po = await run(() => api(`/api/intakes/${id}/purchase-order`, { body: { supplier_id: supplierId || d.preferred_supplier_id } }));
              if (po) router.push(`/app/orders/${po.id}`);
            }}>Create purchase order</button>
          </Card>
          <Card title="Run an RFQ">
            <p className="muted">Invite approved suppliers to quote through private links.</p>
            <div className="checks">{inCategory.slice(0, 15).map((s: any) => (
              <label key={s.id}><input type="checkbox" checked={invitees.includes(s.id)} onChange={(e) => setInvitees(e.target.checked ? [...invitees, s.id] : invitees.filter((x) => x !== s.id))} /> {s.name}</label>
            ))}</div>
            <button className="button" disabled={busy || invitees.length === 0} onClick={async () => {
              const event = await run(() => api('/api/sourcing', { body: { intake_id: id, supplier_ids: invitees, due_in_days: 5 } }));
              if (event) setLinks(event.invite_links.map((l: any) => ({ ...l, event_id: event.id })));
            }}>Send RFQ</button>
            {links.length > 0 && <Notice tone="ok">RFQ created. Share each link with its supplier: {links.map((l) => <code key={l.url} className="link-code">{l.url}</code>)} <Link href={`/app/sourcing/${links[0].event_id}`}>Open the event</Link></Notice>}
          </Card>
        </div>
      )}
    </Page>
  );
}
