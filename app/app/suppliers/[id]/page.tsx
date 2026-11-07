'use client';
import { useParams } from 'next/navigation';
import { Card, Loading, Message, Notice, Page, Stat, Status, Table, useAction, useLoad } from '../../../components/ui';
import { can, useMe } from '../../../components/Shell';
import { api, compactInr, day } from '../../../lib/api';

export default function SupplierDetail() {
  const { id } = useParams<{ id: string }>();
  const me = useMe();
  const supplier = useLoad(() => api(`/api/suppliers/${id}`), [id]);
  const { busy, message, run, setMessage } = useAction();
  const d = supplier.data;
  if (!d) return <Page title="Supplier"><Loading error={supplier.error} /></Page>;
  const p = d.performance;
  const pending = d.onboarding.find((c: any) => c.status === 'submitted');
  return (
    <Page kicker="Supplier" title={d.name} subtitle={`${d.gstin || 'No GSTIN yet'} · ${d.address || ''}`}
      actions={<><Status value={d.status} />
        {can(me, 'suppliers.write') && d.status !== 'approved' && <button className="button" disabled={busy} onClick={async () => { const r = await run(() => api(`/api/suppliers/${id}/onboarding`, { method: 'POST' })); if (r) setMessage({ tone: 'ok', text: `Onboarding link (send to the supplier): ${r.url}` }); supplier.reload(); }}>Send onboarding link</button>}
        {can(me, 'risk.write') && <button className="button secondary" disabled={busy} onClick={() => run(() => api(`/api/risk/suppliers/${id}/assess`, { method: 'POST' }), 'Risk re-assessed.').then(supplier.reload)}>Re-assess risk</button>}
      </>}>
      <Message message={message} />
      <div className="stats">
        <Stat label="Spend" value={compactInr(p.spend)} /><Stat label="Deliveries" value={p.receipts} />
        <Stat label="On time" value={p.on_time_pct === null ? '-' : `${p.on_time_pct}%`} /><Stat label="Quality accepted" value={p.quality_ok_pct === null ? '-' : `${p.quality_ok_pct}%`} />
        <Stat label="Invoices with exceptions" value={p.invoice_exception_pct === null ? '-' : `${p.invoice_exception_pct}%`} /><Stat label="Risk" value={<Status value={d.risk_tier} />} hint={d.risk_score !== null ? `score ${d.risk_score}/100` : ''} />
      </div>
      {pending && (
        <Card title="Onboarding questionnaire to review">
          <Table rows={Object.entries(pending.checks).map(([name, check]: any) => ({ id: name, name, ...check }))} columns={[{ key: 'name', label: 'Check', render: (r: any) => r.name.replace(/_/g, ' ') }, { key: 'status', label: 'Result', render: (r: any) => <Status value={r.status} /> }, { key: 'detail', label: 'Detail' }]} />
          <pre className="answers">{JSON.stringify(pending.answers, null, 2)}</pre>
          <div className="actions">
            <button className="button" disabled={busy} onClick={() => run(() => api(`/api/suppliers/onboarding/${pending.id}/approve`, { body: { note: 'Reviewed' } }), 'Approved.').then(supplier.reload)}>Approve supplier</button>
            <button className="button danger" disabled={busy} onClick={() => { const note = prompt('Reason for the supplier'); if (note) run(() => api(`/api/suppliers/onboarding/${pending.id}/reject`, { body: { note } })).then(supplier.reload); }}>Send back</button>
          </div>
        </Card>
      )}
      <div className="grid-2">
        <Card title="Risk assessment">
          {d.risk ? <><p className="muted">Assessed {day(d.risk.created_at)} by {d.risk.assessed_by} · next review {day(d.risk.next_review_on)}</p>
            <Table rows={d.risk.factors} columns={[{ key: 'factor', label: 'Factor', render: (r: any) => r.factor.replace(/_/g, ' ') }, { key: 'points', label: 'Points', align: 'right' }, { key: 'detail', label: 'Evidence' }]} /></> : <p className="empty">Not assessed yet.</p>}
          {d.holds.filter((h: any) => h.active).map((h: any) => <Notice key={h.id} tone="error">Active {h.scope} hold: {h.reason}</Notice>)}
        </Card>
        <Card title="Documents and contracts">
          <Table rows={d.documents} empty="No documents uploaded." columns={[{ key: 'kind', label: 'Document', render: (r: any) => <a href={`/api/suppliers/documents/${r.id}`}>{r.kind.replace(/_/g, ' ')}</a> }, { key: 'created_at', label: 'Uploaded', render: (r: any) => day(r.created_at) }]} />
          <Table rows={d.contracts} empty="No contracts." columns={[{ key: 'number', label: 'Contract' }, { key: 'status', label: 'Status', render: (r: any) => <Status value={r.status} /> }, { key: 'end_on', label: 'Ends', render: (r: any) => day(r.end_on) }]} />
        </Card>
      </div>
    </Page>
  );
}
