'use client';
import Link from 'next/link';
import { useState } from 'react';
import { Card, Message, Notice, Page, Status, Table, useAction, useLoad } from '../../components/ui';
import { can, useMe } from '../../components/Shell';
import { api, day } from '../../lib/api';

export default function Risk() {
  const me = useMe();
  const [tier, setTier] = useState('');
  const register = useLoad(() => api(`/api/risk/register${tier ? `?tier=${tier}` : ''}`), [tier]);
  const { busy, message, run } = useAction();
  const [research, setResearch] = useState<any>(null);
  return (
    <Page kicker="Risk Orchestration" title="Supplier risk register" subtitle="Scores come from onboarding checks, documents, delivery, quality and invoice history, and spend concentration. High and critical tiers add a risk approval step; critical places an automatic PO hold.">
      <Message message={message} />
      <Notice>Sanctions screening, bank verification and GSTN registration lookups need a connected data provider, so they are shown as not performed.</Notice>
      {research && <Card title="Public research (unverified)" actions={<button className="link" onClick={() => setResearch(null)}>Close</button>}><Notice tone="warn">{research.notice}</Notice><Table rows={research.results} empty="No results." columns={[{ key: 'title', label: 'Result', render: (r: any) => <a href={r.url} target="_blank" rel="noreferrer noopener">{r.title}</a> }, { key: 'snippet', label: 'Snippet' }]} /></Card>}
      <Card actions={<select value={tier} onChange={(e) => setTier(e.target.value)} aria-label="Tier"><option value="">All tiers</option>{['critical', 'high', 'medium', 'low'].map((t) => <option key={t}>{t}</option>)}</select>}>
        <Table rows={register.data} columns={[
          { key: 'supplier', label: 'Supplier', render: (r: any) => <Link href={`/app/suppliers/${r.supplier.id}`}>{r.supplier.name}</Link> },
          { key: 'tier', label: 'Tier', render: (r: any) => <Status value={r.supplier.risk_tier} /> },
          { key: 'score', label: 'Score', align: 'right', render: (r: any) => r.supplier.risk_score ?? '-' },
          { key: 'review', label: 'Next review', render: (r: any) => <span className={r.review_due ? 'overdue' : ''}>{day(r.assessment?.next_review_on)}</span> },
          { key: 'holds', label: 'Holds', render: (r: any) => r.active_holds.length ? r.active_holds.map((h: any) => (
            <span key={h.id} className="inline-form"><Status value="blocking" /> {h.scope} {can(me, 'risk.write') && <button className="link" onClick={() => run(() => api(`/api/risk/holds/${h.id}/release`, { method: 'POST' }), 'Hold released.').then(register.reload)}>Release</button>}</span>
          )) : '-' },
          { key: 'actions', label: '', render: (r: any) => can(me, 'risk.write') && <span className="inline-form">
            <button className="link" disabled={busy} onClick={() => { const reason = prompt('Reason for the hold'); if (reason) run(() => api('/api/risk/holds', { body: { supplier_id: r.supplier.id, scope: 'all', reason } }), 'Hold placed. New POs and payments are blocked.').then(register.reload); }}>Place hold</button>
            <button className="link" disabled={busy} onClick={async () => { const result = await run(() => api(`/api/risk/suppliers/${r.supplier.id}/research`, { body: { confirm_public_search: true } })); if (result) setResearch(result); }}>Research</button>
          </span> },
        ]} />
      </Card>
    </Page>
  );
}
