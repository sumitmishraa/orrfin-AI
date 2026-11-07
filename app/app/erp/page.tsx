'use client';
import { useState } from 'react';
import { Card, Field, Message, Notice, Page, Status, Table, useAction, useLoad } from '../../components/ui';
import { can, useMe } from '../../components/Shell';
import { api, day } from '../../lib/api';

export default function Erp() {
  const me = useMe();
  const connections = useLoad(() => api('/api/erp/connections'));
  const [status, setStatus] = useState('');
  const outbox = useLoad(() => api(`/api/erp/outbox?limit=200${status ? `&status=${status}` : ''}`), [status]);
  const { busy, message, run, setMessage } = useAction();
  const [zoho, setZoho] = useState({ datacenter: 'in', organization_id: '', client_id: '', client_secret: '', refresh_token: '' });
  const [company, setCompany] = useState('');
  const manage = can(me, 'erp.manage');

  return (
    <Page kicker="ERP connections" title="Push to your ERP" subtitle="Issued purchase orders and approved invoices are sent through an outbox: retried with backoff, never duplicated, and parked for attention when a mapping is missing.">
      <Message message={message} />
      <Card title="Connections">
        <Table rows={connections.data} empty="No ERP connected yet." columns={[
          { key: 'provider', label: 'ERP', render: (r: any) => (r.provider === 'zoho' ? 'Zoho Books' : 'Tally Prime') },
          { key: 'mode', label: 'Mode', render: (r: any) => (r.mode === 'mock' ? 'Mock ERP (local test double, not a live Zoho)' : 'Live') },
          { key: 'last_success_at', label: 'Last delivery', render: (r: any) => day(r.last_success_at) },
          { key: 'test', label: '', render: (r: any) => r.provider === 'zoho' && manage && <button className="link" disabled={busy} onClick={async () => { const t = await run(() => api(`/api/erp/connections/${r.id}/test`, { method: 'POST' })); if (t) setMessage({ tone: t.ok ? 'ok' : 'error', text: t.message }); }}>Test</button> },
        ]} />
      </Card>
      {manage && (
        <div className="grid-2">
          <Card title="Connect Zoho Books">
            <Notice>Create a self client in the Zoho API console with the ZohoBooks.purchaseorders and ZohoBooks.bills scopes, then paste the refresh token here. Credentials are encrypted and never shown again.</Notice>
            <Field label="Datacenter"><select value={zoho.datacenter} onChange={(e) => setZoho({ ...zoho, datacenter: e.target.value })}>{['in', 'com', 'eu', 'com.au', 'jp', 'ca', 'sa'].map((d) => <option key={d}>{d}</option>)}</select></Field>
            {(['organization_id', 'client_id', 'client_secret', 'refresh_token'] as const).map((k) => <Field key={k} label={k.replace('_', ' ')}><input type={k === 'organization_id' || k === 'client_id' ? 'text' : 'password'} value={zoho[k]} onChange={(e) => setZoho({ ...zoho, [k]: e.target.value })} /></Field>)}
            <button className="button" disabled={busy} onClick={() => run(() => api('/api/erp/connections', { body: { provider: 'zoho', mode: 'live', config: { datacenter: zoho.datacenter, organization_id: zoho.organization_id }, credentials: { client_id: zoho.client_id, client_secret: zoho.client_secret, refresh_token: zoho.refresh_token } } }), 'Zoho Books connected. Map suppliers and tax rates next.').then(connections.reload)}>Save Zoho connection</button>
          </Card>
          <Card title="Connect Tally Prime">
            <Notice>Tally only listens on its own machine, so Orrfin.ai never calls it directly. Download a voucher as XML from any PO, or run the relay agent (tools/tally_relay.py) next to Tally with the token shown after saving.</Notice>
            <Field label="Tally company name (exactly as in Tally)"><input value={company} onChange={(e) => setCompany(e.target.value)} /></Field>
            <button className="button" disabled={busy || !company} onClick={async () => { const r = await run(() => api('/api/erp/connections', { body: { provider: 'tally', mode: 'live', config: { company } } })); if (r?.relay_token) setMessage({ tone: 'ok', text: `Relay token (shown once): ${r.relay_token}` }); connections.reload(); }}>Save Tally connection</button>
          </Card>
        </div>
      )}
      <Card title="Delivery outbox" actions={<select value={status} onChange={(e) => setStatus(e.target.value)} aria-label="Status"><option value="">All</option>{['pending', 'retrying', 'delivered', 'needs_mapping', 'rejected', 'dead_letter'].map((s) => <option key={s} value={s}>{s.replace('_', ' ')}</option>)}</select>}>
        <Table rows={outbox.data} empty="Nothing sent yet." columns={[
          { key: 'provider', label: 'ERP' }, { key: 'doc_type', label: 'Document', render: (r: any) => `${r.doc_type.replace('_', ' ')} ${r.external_key}` },
          { key: 'status', label: 'Status', render: (r: any) => <Status value={r.status} /> }, { key: 'attempts', label: 'Attempts', align: 'right' },
          { key: 'external_id', label: 'ERP id', render: (r: any) => r.external_id || '-' }, { key: 'last_error', label: 'Last error', render: (r: any) => r.last_error || '-' },
          { key: 'actions', label: '', render: (r: any) => <span className="inline-form">
            {r.provider === 'tally' && r.doc_type === 'purchase_order' && <a className="link" href={`/api/erp/tally/purchase_order/${r.doc_id}.xml`} download>XML</a>}
            {r.status !== 'delivered' && can(me, 'erp.push') && <button className="link" disabled={busy} onClick={() => run(() => api(`/api/erp/outbox/${r.id}/retry`, { method: 'POST' }), 'Retry queued.').then(outbox.reload)}>Retry</button>}
          </span> },
        ]} />
      </Card>
    </Page>
  );
}
