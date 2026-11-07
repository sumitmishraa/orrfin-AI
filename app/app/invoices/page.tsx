'use client';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useState } from 'react';
import { Card, Message, Page, Status, Table, Tabs, useAction, useLoad } from '../../components/ui';
import { can, useMe } from '../../components/Shell';
import { api, day, inr } from '../../lib/api';

export default function Invoices() {
  const me = useMe();
  const router = useRouter();
  const [tab, setTab] = useState('review');
  const statusFor: Record<string, string> = { review: 'extracted', exception: 'exception', matched: 'matched', approved: 'approved', all: '' };
  const list = useLoad(() => api(`/api/invoices?limit=150${statusFor[tab] ? `&status=${statusFor[tab]}` : ''}`), [tab]);
  const exceptions = useLoad(() => api('/api/invoices/exceptions'));
  const { busy, message, run } = useAction();

  async function upload(event: any) {
    const file = event.target.files?.[0];
    if (!file) return;
    const form = new FormData();
    form.append('file', file);
    const invoice = await run(() => api('/api/invoices', { form }), 'Uploaded. Fields are being read from the PDF now.');
    event.target.value = '';
    if (invoice) router.push(`/app/invoices/${invoice.id}`);
  }

  return (
    <Page kicker="Procure-to-Pay" title="Invoices" subtitle="Upload a supplier invoice (PDF or scan). Orrfin.ai reads it, a person confirms the fields, and it's matched line by line against the PO and goods receipts."
      actions={can(me, 'invoice.write') && <label className="button">{busy ? 'Uploading…' : 'Upload invoice'}<input type="file" accept="application/pdf,image/png,image/jpeg" hidden onChange={upload} /></label>}>
      <Message message={message} />
      <Tabs value={tab} onChange={setTab} tabs={[['review', 'To review'], ['exception', 'Exceptions'], ['matched', 'Matched'], ['approved', 'Approved'], ['all', 'All']]} />
      <Card>
        <Table rows={list.data?.items} onRow={(r: any) => router.push(`/app/invoices/${r.id}`)} empty="Nothing in this view." columns={[
          { key: 'number', label: 'Invoice', render: (r: any) => <Link href={`/app/invoices/${r.id}`}>{r.number || 'Not read yet'}</Link> },
          { key: 'supplier', label: 'Supplier', render: (r: any) => r.supplier || '-' }, { key: 'po_number', label: 'PO', render: (r: any) => r.po_number || '-' },
          { key: 'status', label: 'Status', render: (r: any) => <Status value={r.status} /> },
          { key: 'invoice_date', label: 'Date', render: (r: any) => day(r.invoice_date) },
          { key: 'total', label: 'Total', align: 'right', render: (r: any) => inr(r.total) },
        ]} />
      </Card>
      <Card title={`Open exceptions (${exceptions.data?.length ?? '…'})`}>
        <Table rows={exceptions.data?.slice(0, 50)} empty="No open exceptions." columns={[
          { key: 'invoice_number', label: 'Invoice', render: (r: any) => <Link href={`/app/invoices/${r.invoice_id}`}>{r.invoice_number}</Link> },
          { key: 'code', label: 'Check', render: (r: any) => <Status value={r.severity} /> }, { key: 'message', label: 'What was found' },
          { key: 'assignee_role', label: 'Team', render: (r: any) => r.assignee_role.replace('_', ' ') },
        ]} />
      </Card>
    </Page>
  );
}
