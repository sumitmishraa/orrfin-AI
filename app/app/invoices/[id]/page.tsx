'use client';
import Link from 'next/link';
import { useParams } from 'next/navigation';
import { useEffect, useState } from 'react';
import { Card, Field, Loading, Message, Notice, Page, Status, Table, useAction, useLoad } from '../../../components/ui';
import { can, useMe } from '../../../components/Shell';
import { api, inr, qty } from '../../../lib/api';

const HEADER = ['number', 'invoice_date', 'supplier_gstin', 'buyer_gstin', 'subtotal', 'cgst', 'sgst', 'igst', 'freight', 'round_off', 'total'] as const;
const SOURCE: Record<string, string> = { number: 'invoice_number' };

function Confidence({ value }: { value?: number }) {
  if (value === undefined) return <span className="conf none">not read</span>;
  return <span className={`conf ${value >= 0.9 ? 'high' : value >= 0.7 ? 'mid' : 'low'}`}>{Math.round(value * 100)}%</span>;
}

export default function InvoiceDetail() {
  const { id } = useParams<{ id: string }>();
  const me = useMe();
  const invoice = useLoad(() => api(`/api/invoices/${id}`), [id]);
  const orders = useLoad(() => api('/api/purchase-orders?limit=200&status=received').then(async (a: any) => [...a.items, ...(await api('/api/purchase-orders?limit=200&status=partially_received')).items]));
  const { busy, message, run } = useAction();
  const [form, setForm] = useState<any>(null);
  const [resolution, setResolution] = useState<Record<string, string>>({});
  const d = invoice.data;

  useEffect(() => {
    if (!d) return;
    if (d.status === 'uploaded') { const t = setTimeout(invoice.reload, 1500); return () => clearTimeout(t); }
    if (form) return;
    const header = d.extraction?.fields?.header || {};
    const lines = d.lines?.length ? d.lines : d.extraction?.fields?.lines || [];
    const value = (key: string) => (d.confirmed_at ? d[key] : header[SOURCE[key] || key]?.value) ?? (['number', 'invoice_date', 'supplier_gstin', 'buyer_gstin'].includes(key) ? '' : '0');
    setForm({ po_id: d.po_id || '', ...Object.fromEntries(HEADER.map((k) => [k, String(value(k))])), lines: lines.map((l: any) => ({ description: l.description, hsn: l.hsn || '', unit: l.unit || '', quantity: String(l.quantity), unit_price: String(l.unit_price), taxable: String(l.taxable) })) });
  }, [d, form, invoice.reload]);

  if (!d) return <Page title="Invoice"><Loading error={invoice.error} /></Page>;
  const header = d.extraction?.fields?.header || {};
  const closed = ['approved', 'paid', 'rejected'].includes(d.status);
  const blocking = d.exceptions.filter((x: any) => x.status === 'open' && x.severity === 'blocking').length;
  const set = (k: string) => (e: any) => setForm({ ...form, [k]: e.target.value });
  const setLine = (i: number, k: string, v: string) => setForm({ ...form, lines: form.lines.map((l: any, n: number) => (n === i ? { ...l, [k]: v } : l)) });
  const confirm = () => run(() => api(`/api/invoices/${id}/confirm`, { method: 'PUT', body: form }), 'Confirmed and matched.').then((r) => { if (r) { invoice.setData(r); setForm(null); } });

  return (
    <Page kicker={d.purchase_order ? `Against ${d.purchase_order.number}` : 'Supplier invoice'} title={d.number || 'Invoice awaiting review'} subtitle={d.document?.filename}
      actions={<><Status value={d.status} />
        {['matched', 'exception'].includes(d.status) && can(me, 'invoice.approve') && <button className="button" disabled={busy || blocking > 0} title={blocking ? 'Resolve blocking exceptions first' : ''} onClick={() => run(() => api(`/api/invoices/${id}/approve`, { method: 'POST' }), 'Approved. The bill is queued for your ERP.').then((r) => r && invoice.setData(r))}>Approve for payment</button>}
        {d.status === 'approved' && can(me, 'payment.write') && <button className="button secondary" disabled={busy} onClick={() => run(() => api(`/api/invoices/${id}/payments`, { body: { amount: d.total, status: 'paid', reference: 'Recorded in Orrfin.ai' } }), 'Payment recorded. No money moves through Orrfin.ai.').then(invoice.reload)}>Mark paid</button>}
        {!closed && can(me, 'invoice.write') && <button className="button danger" disabled={busy} onClick={() => { const reason = prompt('Why reject this invoice?'); if (reason) run(() => api(`/api/invoices/${id}/reject`, { body: { reason } })).then(invoice.reload); }}>Reject</button>}
      </>}>
      <Message message={message} />
      {d.status === 'uploaded' && <Notice>Reading the document… this page refreshes on its own.</Notice>}
      {d.status === 'extraction_failed' && <Notice tone="error">The file couldn't be read: {d.extraction?.error}. Enter the fields by hand below.</Notice>}
      {d.extraction?.warnings?.map((w: string) => <Notice key={w} tone="warn">{w}</Notice>)}
      <div className="review">
        <Card title="Original document" className="doc">
          {d.document?.content_type === 'application/pdf' ? <iframe title="Invoice PDF" src={`/api/invoices/${id}/file?inline=true`} /> : <img alt="Invoice" src={`/api/invoices/${id}/file?inline=true`} />}
          <a className="link" href={`/api/invoices/${id}/file`} download>Download original</a>
        </Card>
        {form && (
          <Card title={d.confirmed_at ? 'Confirmed fields' : `Check the extracted fields (${d.extraction?.engine?.replace('_', ' ') || 'manual'})`}>
            <p className="muted">Only fields a person confirms are used for matching. Percentages show how sure the reader is.</p>
            <Field label="Purchase order"><select value={form.po_id} disabled={closed} onChange={set('po_id')}><option value="">Choose…</option>{d.purchase_order && <option value={d.purchase_order.id}>{d.purchase_order.number}</option>}{(orders.data || []).filter((o: any) => o.id !== d.purchase_order?.id).map((o: any) => <option key={o.id} value={o.id}>{o.number} · {o.supplier}</option>)}</select></Field>
            <div className="field-grid">{HEADER.map((k) => (
              <Field key={k} label={k.replace('_', ' ')}><div className="with-conf"><input value={form[k]} disabled={closed} type={k === 'invoice_date' ? 'date' : 'text'} onChange={set(k)} /><Confidence value={header[SOURCE[k] || k]?.confidence} /></div></Field>
            ))}</div>
            <table className="lines"><thead><tr><th>Description</th><th>HSN</th><th>Qty</th><th>Rate</th><th>Amount</th></tr></thead><tbody>
              {form.lines.map((l: any, i: number) => <tr key={i}>{['description', 'hsn', 'quantity', 'unit_price', 'taxable'].map((k) => <td key={k}><input value={l[k]} disabled={closed} onChange={(e) => setLine(i, k, e.target.value)} /></td>)}</tr>)}
            </tbody></table>
            {!closed && <div className="actions">
              <button type="button" className="button secondary" onClick={() => setForm({ ...form, lines: [...form.lines, { description: '', hsn: '', unit: '', quantity: '0', unit_price: '0', taxable: '0' }] })}>Add line</button>
              <button className="button" disabled={busy || !form.po_id} onClick={confirm}>{d.confirmed_at ? 'Save and re-match' : 'Confirm and match'}</button>
            </div>}
          </Card>
        )}
      </div>
      {d.match_result?.lines && (
        <Card title="Three-way match: PO, receipts, invoice">
          <Table rows={d.match_result.lines} columns={[
            { key: 'description', label: 'Invoice line' }, { key: 'po_line_no', label: 'PO line', align: 'right' },
            { key: 'ordered', label: 'Ordered', align: 'right', render: (r: any) => qty(r.ordered) }, { key: 'received', label: 'Received', align: 'right', render: (r: any) => qty(r.received) },
            { key: 'previously_billed', label: 'Billed before', align: 'right', render: (r: any) => qty(r.previously_billed) }, { key: 'billed', label: 'This invoice', align: 'right', render: (r: any) => qty(r.billed) },
            { key: 'po_price', label: 'PO rate', align: 'right', render: (r: any) => inr(r.po_price) }, { key: 'invoice_price', label: 'Invoice rate', align: 'right', render: (r: any) => inr(r.invoice_price) },
          ]} />
        </Card>
      )}
      <Card title={`Exceptions (${d.exceptions.length})`}>
        <Table rows={d.exceptions} empty={d.confirmed_at ? 'No exceptions. Everything matches within tolerance.' : 'Confirm the fields to run the match.'} columns={[
          { key: 'severity', label: '', render: (r: any) => <Status value={r.status === 'resolved' ? 'approved' : r.severity} /> },
          { key: 'message', label: 'Finding' }, { key: 'expected', label: 'Expected' }, { key: 'actual', label: 'On invoice' },
          { key: 'resolve', label: 'Resolution', render: (r: any) => r.status === 'resolved' ? r.resolution : (
            <div className="inline-form"><input placeholder="How was this resolved?" value={resolution[r.id] || ''} onChange={(e) => setResolution({ ...resolution, [r.id]: e.target.value })} />
              <button className="button small" disabled={busy || !resolution[r.id]} onClick={() => run(() => api(`/api/invoices/exceptions/${r.id}/resolve`, { body: { reason: resolution[r.id] } })).then(invoice.reload)}>Resolve</button></div>) },
        ]} />
      </Card>
      {d.purchase_order && <p className="muted">PO <Link href={`/app/orders/${d.purchase_order.id}`}>{d.purchase_order.number}</Link> total {inr(d.purchase_order.total)}</p>}
    </Page>
  );
}
