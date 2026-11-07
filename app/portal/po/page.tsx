'use client';
import { useEffect, useState } from 'react';
import { Card, Field, Message, Notice, Table, useAction } from '../../components/ui';
import { day, inr, portalApi, qty } from '../../lib/api';
import { PortalFrame, usePortalToken } from '../shared';

export default function PoPortal() {
  const token = usePortalToken();
  const [view, setView] = useState<any>(null);
  const [error, setError] = useState('');
  const { busy, message, run } = useAction();
  useEffect(() => { if (token !== null) portalApi('/api/portal/po', token).then(setView).catch((e) => setError(e.message)); }, [token]);

  if (error) return <PortalFrame title="Purchase order"><Notice tone="error">{error}</Notice></PortalFrame>;
  if (!view) return <PortalFrame title="Purchase order"><p>Loading…</p></PortalFrame>;
  async function downloadPdf() {
    const response = await fetch('/api/portal/po/pdf', { headers: { 'X-Portal-Token': token as string } });
    if (!response.ok) return;
    const url = URL.createObjectURL(await response.blob());
    const a = document.createElement('a'); a.href = url; a.download = `${view.number.replace(/\//g, '-')}.pdf`; a.click(); URL.revokeObjectURL(url);
  }
  async function upload(event: any) {
    const file = event.target.files?.[0];
    if (!file) return;
    const data = new FormData(); data.append('file', file);
    await run(() => portalApi('/api/portal/po/invoices', token as string, { form: data }), 'Invoice received. The buyer will match it against this purchase order and the delivery.');
    event.target.value = '';
  }
  return (
    <PortalFrame title={`Purchase order ${view.number}`}>
      <p className="muted">Deliver by {day(view.needed_by)} · total {inr(view.total)} incl. GST</p>
      <Message message={message} />
      <Card title="Lines" actions={<button className="button secondary" onClick={downloadPdf}>Download PO PDF</button>}>
        <Table rows={view.lines} columns={[{ key: 'description', label: 'Item' }, { key: 'quantity', label: 'Ordered', align: 'right', render: (r: any) => `${qty(r.quantity)} ${r.unit}` }, { key: 'received', label: 'Received', align: 'right', render: (r: any) => qty(r.received) }, { key: 'unit_price', label: 'Rate', align: 'right', render: (r: any) => inr(r.unit_price) }]} />
      </Card>
      <Card title="Send your invoice">
        <Notice>Quote this PO number on the invoice and show your GSTIN, HSN codes and the tax breakup.</Notice>
        <Field label="Invoice (PDF, PNG or JPEG, up to 25 MB)"><input type="file" accept="application/pdf,image/png,image/jpeg" disabled={busy} onChange={upload} /></Field>
      </Card>
    </PortalFrame>
  );
}
