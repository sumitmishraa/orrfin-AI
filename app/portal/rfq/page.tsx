'use client';
import { FormEvent, useEffect, useState } from 'react';
import { Card, Field, Message, Notice, Table, useAction } from '../../components/ui';
import { day, inr, portalApi, qty } from '../../lib/api';
import { PortalFrame, usePortalToken } from '../shared';

export default function RfqPortal() {
  const token = usePortalToken();
  const [view, setView] = useState<any>(null);
  const [error, setError] = useState('');
  const [prices, setPrices] = useState<Record<string, string>>({});
  const [lead, setLead] = useState('3');
  const [freight, setFreight] = useState('0');
  const [notes, setNotes] = useState('');
  const { busy, message, run } = useAction();
  const load = () => portalApi('/api/portal/rfq', token as string).then(setView).catch((e) => setError(e.message));
  useEffect(() => { if (token !== null) load(); }, [token]); // eslint-disable-line react-hooks/exhaustive-deps

  if (error) return <PortalFrame title="Request for quotation"><Notice tone="error">{error}</Notice></PortalFrame>;
  if (!view) return <PortalFrame title="Request for quotation"><p>Loading…</p></PortalFrame>;
  async function submit(event: FormEvent) {
    event.preventDefault();
    await run(() => portalApi('/api/portal/rfq/bid', token as string, { body: { lead_days: Number(lead), freight, notes, prices: view.lines.map((l: any) => ({ line_id: l.id, unit_price: prices[l.id] })) } }), 'Bid submitted. Thank you.');
    load();
  }
  return (
    <PortalFrame title={`${view.event.number}: ${view.event.title}`}>
      <p className="muted">For {view.supplier} · closes {day(view.event.due_at)} · prices exclude GST, which is added at the rates shown.</p>
      <Message message={message} />
      {view.bid ? <Notice tone="ok">Your bid of {inr(view.bid.total)} (incl. GST) was received.</Notice> : view.event.status !== 'open' ? <Notice tone="warn">This RFQ is closed.</Notice> : (
        <Card title="Your quotation">
          <form className="form" onSubmit={submit}>
            <Table rows={view.lines} columns={[
              { key: 'description', label: 'Item' }, { key: 'hsn', label: 'HSN' }, { key: 'quantity', label: 'Qty', align: 'right', render: (r: any) => `${qty(r.quantity)} ${r.unit}` },
              { key: 'gst_rate', label: 'GST', align: 'right', render: (r: any) => `${Number(r.gst_rate)}%` },
              { key: 'price', label: 'Unit price (₹, excl. GST)', render: (r: any) => <input required inputMode="decimal" value={prices[r.id] || ''} onChange={(e) => setPrices({ ...prices, [r.id]: e.target.value })} /> },
            ]} />
            <div className="row"><Field label="Lead time (days)"><input required inputMode="numeric" value={lead} onChange={(e) => setLead(e.target.value)} /></Field><Field label="Freight (₹)"><input inputMode="decimal" value={freight} onChange={(e) => setFreight(e.target.value)} /></Field><Field label="Notes"><input value={notes} onChange={(e) => setNotes(e.target.value)} /></Field></div>
            <button className="button" disabled={busy}>Submit bid</button>
          </form>
        </Card>
      )}
    </PortalFrame>
  );
}
