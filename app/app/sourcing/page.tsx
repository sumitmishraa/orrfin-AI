'use client';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { Card, Page, Status, Table, useLoad } from '../../components/ui';
import { api, day } from '../../lib/api';

export default function Sourcing() {
  const router = useRouter();
  const events = useLoad(() => api('/api/sourcing'));
  return (
    <Page kicker="Sourcing" title="RFQ events" subtitle="Start an RFQ from an approved request. Suppliers bid through private links; compare price, lead time, risk and history, then award.">
      <Card>
        <Table rows={events.data} empty="No RFQs yet. Open an approved request and choose Run an RFQ." onRow={(r: any) => router.push(`/app/sourcing/${r.id}`)} columns={[
          { key: 'number', label: 'Number', render: (r: any) => <Link href={`/app/sourcing/${r.id}`}>{r.number}</Link> },
          { key: 'title', label: 'Title' }, { key: 'status', label: 'Status', render: (r: any) => <Status value={r.status} /> },
          { key: 'invites', label: 'Invited', align: 'right' }, { key: 'bids', label: 'Bids', align: 'right' },
          { key: 'due_at', label: 'Closes', render: (r: any) => day(r.due_at) },
        ]} />
      </Card>
    </Page>
  );
}
