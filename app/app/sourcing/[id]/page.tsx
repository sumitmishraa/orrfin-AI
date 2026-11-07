'use client';
import { useParams, useRouter } from 'next/navigation';
import { Card, Loading, Message, Notice, Page, Status, Table, useAction, useLoad } from '../../../components/ui';
import { api, day, inr, qty } from '../../../lib/api';

export default function EventDetail() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const event = useLoad(() => api(`/api/sourcing/${id}`), [id]);
  const { busy, message, run } = useAction();
  const d = event.data;
  if (!d) return <Page title="RFQ"><Loading error={event.error} /></Page>;
  return (
    <Page kicker={d.number} title={d.title} subtitle={`Closes ${day(d.due_at)}`} actions={<Status value={d.status} />}>
      <Message message={message} />
      <div className="grid-2">
        <Card title="Lines requested"><Table rows={d.lines} columns={[{ key: 'description', label: 'Item' }, { key: 'quantity', label: 'Qty', align: 'right', render: (r: any) => `${qty(r.quantity)} ${r.unit}` }, { key: 'gst_rate', label: 'GST', align: 'right', render: (r: any) => `${Number(r.gst_rate)}%` }]} /></Card>
        <Card title="Invited suppliers"><Table rows={d.invites} columns={[{ key: 'supplier', label: 'Supplier' }, { key: 'status', label: 'Status', render: (r: any) => <Status value={r.status} /> }]} /></Card>
      </div>
      <Card title="Bid comparison">
        <Notice>Bids are ranked eligible first, then by total including GST. Delivery and quality history come from your own goods receipts.</Notice>
        <Table rows={d.comparison} empty="No bids yet." columns={[
          { key: 'supplier', label: 'Supplier', render: (r: any) => `${r.supplier.name}${r.supplier.preferred ? ' ★' : ''}` },
          { key: 'total', label: 'Total incl. GST', align: 'right', render: (r: any) => inr(r.bid.total) },
          { key: 'lead', label: 'Lead time', align: 'right', render: (r: any) => `${r.bid.lead_days} days` },
          { key: 'risk', label: 'Risk', render: (r: any) => <Status value={r.supplier.risk_tier} /> },
          { key: 'history', label: 'On time / quality', render: (r: any) => r.performance.receipts ? `${r.performance.on_time_pct}% / ${r.performance.quality_ok_pct}% (${r.performance.receipts} deliveries)` : 'No history' },
          { key: 'eligible', label: 'Eligible', render: (r: any) => r.eligible ? <Status value="pass" /> : <span title={r.reasons.join(' ')}><Status value="fail" /> {r.reasons[0]}</span> },
          { key: 'award', label: '', render: (r: any) => ['open', 'closed'].includes(d.status) && (
            <button className="button small" disabled={busy} onClick={async () => {
              const po = await run(() => api(`/api/sourcing/${id}/award`, { body: { bid_id: r.bid.id, reason: r.eligible ? 'Best eligible bid' : 'Awarded with exceptions noted' } }));
              if (po) router.push(`/app/orders/${po.id}`);
            }}>Award</button>
          ) },
        ]} />
      </Card>
    </Page>
  );
}
