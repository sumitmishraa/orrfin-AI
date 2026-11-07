'use client';
import Link from 'next/link';
import { useParams } from 'next/navigation';
import { useState } from 'react';
import { Card, DownloadLink, Field, Loading, Message, Notice, Page, Status, Table, useAction, useLoad } from '../../../components/ui';
import { can, useMe } from '../../../components/Shell';
import { api, day, inr, qty } from '../../../lib/api';

export default function OrderDetail() {
  const { id } = useParams<{ id: string }>();
  const me = useMe();
  const po = useLoad(() => api(`/api/purchase-orders/${id}`), [id]);
  const { busy, message, run, setMessage } = useAction();
  const [received, setReceived] = useState<Record<string, string>>({});
  const [quality, setQuality] = useState(true);
  const [change, setChange] = useState<Record<string, string>>({});
  const [reason, setReason] = useState('');
  const d = po.data;
  if (!d) return <Page title="Purchase order"><Loading error={po.error} /></Page>;
  const open = ['issued', 'partially_received'].includes(d.status);
  const act = (path: string, body?: any, ok?: string) => run(() => api(path, { method: 'POST', body }), ok).then(po.reload);

  return (
    <Page kicker={d.number || 'Draft purchase order'} title={d.supplier.name} subtitle={`${d.place_of_supply} · ${d.is_interstate ? 'Inter-state (IGST)' : 'Intra-state (CGST + SGST)'} · Revision ${d.revision}`}
      actions={<>
        <Status value={d.status} />
        {d.status === 'draft' && can(me, 'po.write') && <button className="button" disabled={busy} onClick={() => act(`/api/purchase-orders/${id}/issue`, undefined, 'Issued. Connected ERPs will receive it automatically.')}>Issue PO</button>}
        {d.number && <DownloadLink href={`/api/purchase-orders/${id}/pdf`}>Download PDF</DownloadLink>}
        {d.number && can(me, 'po.write') && <button className="button secondary" disabled={busy} onClick={async () => {
          const link = await run(() => api(`/api/purchase-orders/${id}/supplier-link`, { method: 'POST' }));
          if (link) setMessage({ tone: 'ok', text: `Supplier link (expires in 90 days): ${link.url}` });
        }}>Share with supplier</button>}
        {d.number && can(me, 'erp.push') && <button className="button secondary" disabled={busy} onClick={() => act('/api/erp/push', { doc_type: 'purchase_order', doc_id: id }, 'Queued for your ERP.')}>Push to ERP</button>}
      </>}>
      <Message message={message} />
      <Card title="Lines">
        <Table rows={d.lines} columns={[
          { key: 'line_no', label: '#' }, { key: 'description', label: 'Item' }, { key: 'hsn', label: 'HSN' },
          { key: 'quantity', label: 'Ordered', align: 'right', render: (r: any) => `${qty(r.quantity)} ${r.unit}` },
          { key: 'qty_received', label: 'Received', align: 'right', render: (r: any) => qty(r.qty_received) },
          { key: 'qty_billed', label: 'Billed', align: 'right', render: (r: any) => qty(r.qty_billed) },
          { key: 'unit_price', label: 'Rate', align: 'right', render: (r: any) => inr(r.unit_price) },
          { key: 'taxable', label: 'Taxable', align: 'right', render: (r: any) => inr(r.taxable) },
        ]} />
        <div className="totals">
          <span>Subtotal {inr(d.subtotal)}</span>
          {d.is_interstate ? <span>IGST {inr(d.igst)}</span> : <><span>CGST {inr(d.cgst)}</span><span>SGST {inr(d.sgst)}</span></>}
          {Number(d.freight) > 0 && <span>Freight {inr(d.freight)}</span>}
          <strong>Total {inr(d.total)}</strong>
          <span className="muted">Approved ceiling {inr(d.approved_amount)}</span>
        </div>
      </Card>
      <div className="grid-2">
        {open && can(me, 'grn.write') && (
          <Card title="Record a delivery (goods receipt)">
            {d.lines.map((l: any) => <Field key={l.id} label={`${l.description} (${qty(Number(l.quantity) - Number(l.qty_received))} outstanding)`}><input inputMode="decimal" value={received[l.id] || ''} onChange={(e) => setReceived({ ...received, [l.id]: e.target.value })} /></Field>)}
            <label className="check"><input type="checkbox" checked={quality} onChange={(e) => setQuality(e.target.checked)} /> Quality accepted</label>
            <button className="button" disabled={busy} onClick={() => act(`/api/purchase-orders/${id}/receipts`, { lines: Object.entries(received).filter(([, v]) => v).map(([po_line_id, quantity]) => ({ po_line_id, quantity })), quality_ok: quality }, 'Receipt recorded.').then(() => setReceived({}))}>Save receipt</button>
          </Card>
        )}
        <Card title="Receipts and invoices">
          <Table rows={d.receipts} empty="No deliveries yet." columns={[{ key: 'number', label: 'GRN' }, { key: 'received_on', label: 'Received', render: (r: any) => day(r.received_on) }, { key: 'quality_ok', label: 'Quality', render: (r: any) => <Status value={r.quality_ok ? 'pass' : 'fail'} /> }]} />
          <Table rows={d.invoices} empty="No invoices yet." columns={[{ key: 'number', label: 'Invoice', render: (r: any) => <Link href={`/app/invoices/${r.id}`}>{r.number || 'Uploaded file'}</Link> }, { key: 'status', label: 'Status', render: (r: any) => <Status value={r.status} /> }, { key: 'total', label: 'Total', align: 'right', render: (r: any) => inr(r.total) }]} />
        </Card>
      </div>
      {open && can(me, 'po.write') && (
        <Card title="Change order">
          <Notice>Changes within the approved ceiling apply immediately as a new revision. Larger changes go for approval first.</Notice>
          {d.lines.map((l: any) => <Field key={l.id} label={`${l.description}: new quantity (now ${qty(l.quantity)})`}><input inputMode="decimal" value={change[l.id] || ''} onChange={(e) => setChange({ ...change, [l.id]: e.target.value })} /></Field>)}
          <Field label="Reason"><input value={reason} onChange={(e) => setReason(e.target.value)} /></Field>
          <button className="button" disabled={busy || !reason} onClick={() => act(`/api/purchase-orders/${id}/change-order`, { reason, lines: Object.entries(change).filter(([, v]) => v).map(([line_id, quantity]) => ({ line_id, quantity })) }, 'Change order saved.')}>Submit change</button>
        </Card>
      )}
    </Page>
  );
}
