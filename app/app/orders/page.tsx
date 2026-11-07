'use client';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useState } from 'react';
import { Card, Page, Status, Table, useLoad } from '../../components/ui';
import { api, day, inr } from '../../lib/api';

export default function Orders() {
  const router = useRouter();
  const [status, setStatus] = useState('');
  const [q, setQ] = useState('');
  const list = useLoad(() => api(`/api/purchase-orders?limit=150${status ? `&status=${status}` : ''}${q ? `&q=${encodeURIComponent(q)}` : ''}`), [status, q]);
  return (
    <Page kicker="Procure-to-Pay" title="Purchase orders" subtitle="Issued from approved requests or awarded RFQs. Download the PDF, record deliveries, raise change orders and push to your ERP.">
      <Card title={`${list.data?.total ?? '…'} orders`} actions={<div className="inline-form">
        <input placeholder="Search PO number" value={q} onChange={(e) => setQ(e.target.value)} />
        <select value={status} onChange={(e) => setStatus(e.target.value)} aria-label="Status"><option value="">All</option>{['draft', 'issued', 'partially_received', 'received', 'change_pending', 'cancelled'].map((s) => <option key={s} value={s}>{s.replace('_', ' ')}</option>)}</select>
      </div>}>
        <Table rows={list.data?.items} onRow={(r: any) => router.push(`/app/orders/${r.id}`)} columns={[
          { key: 'number', label: 'PO', render: (r: any) => <Link href={`/app/orders/${r.id}`}>{r.number || 'Draft'}</Link> },
          { key: 'supplier', label: 'Supplier' }, { key: 'status', label: 'Status', render: (r: any) => <Status value={r.status} /> },
          { key: 'issued_at', label: 'Issued', render: (r: any) => day(r.issued_at) },
          { key: 'gst', label: 'GST', render: (r: any) => (r.is_interstate ? 'IGST' : 'CGST + SGST') },
          { key: 'total', label: 'Total', align: 'right', render: (r: any) => inr(r.total) },
        ]} />
      </Card>
    </Page>
  );
}
