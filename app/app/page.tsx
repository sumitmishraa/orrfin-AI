'use client';
import Link from 'next/link';
import { Card, Loading, Page, Stat, Status, Table, useLoad } from '../components/ui';
import { useMe } from '../components/Shell';
import { api, compactInr, day } from '../lib/api';

export default function Overview() {
  const me = useMe();
  const { data, error } = useLoad(() => api('/api/dashboard'));
  const alerts = useLoad(() => api('/api/dashboard/alerts'));
  if (!data) return <Page title="Overview"><Loading error={error} /></Page>;
  const max = Math.max(1, ...data.monthly_spend.map((m: any) => Number(m.spend)));
  const c = data.counts;
  return (
    <Page kicker={`FY ${data.fiscal_year}`} title={`Good to see you, ${me.user.name.split(' ')[0]}`} subtitle={`${me.tenant.name} · ${data.spend_by_branch.length} branches with spend this year`}>
      <div className="stats">
        <Link href="/app/approvals"><Stat label="Waiting for you" value={c.my_pending_approvals} hint="approval steps" /></Link>
        <Link href="/app/intake"><Stat label="Open requests" value={c.open_requests} /></Link>
        <Link href="/app/orders"><Stat label="Open orders" value={c.open_orders} /></Link>
        <Link href="/app/invoices"><Stat label="Invoices to review" value={c.invoices_to_review} hint={`${c.open_exceptions} with exceptions`} /></Link>
        <Link href="/app/erp"><Stat label="ERP needs attention" value={c.erp_attention} /></Link>
        <Link href="/app/contracts"><Stat label="Contracts ending ≤ 60 days" value={c.contracts_expiring_60d} /></Link>
        <Link href="/app/risk"><Stat label="High-risk suppliers" value={c.high_risk_suppliers} /></Link>
      </div>
      <div className="grid-2">
        <Card title="Monthly spend (issued POs)">
          <div className="bars" role="img" aria-label="Monthly spend chart">
            {data.monthly_spend.map((m: any) => (
              <div key={m.month} className="bar-col" title={`${m.month}: ${compactInr(m.spend)} across ${m.orders} orders`}>
                <div className="bar" style={{ height: `${(Number(m.spend) / max) * 100}%` }} />
                <span>{m.month.slice(5)}</span>
              </div>
            ))}
          </div>
        </Card>
        <Card title="Spend by branch, this fiscal year">
          <Table rows={data.spend_by_branch} columns={[
            { key: 'code', label: 'Branch', render: (r: any) => `${r.code} · ${r.name}` },
            { key: 'orders', label: 'Orders', align: 'right' },
            { key: 'spend', label: 'Spend', align: 'right', render: (r: any) => compactInr(r.spend) },
          ]} />
        </Card>
        <Card title="Spend by category">
          <Table rows={data.spend_by_category} columns={[{ key: 'category', label: 'Category' }, { key: 'spend', label: 'Spend', align: 'right', render: (r: any) => compactInr(r.spend) }]} />
        </Card>
        <Card title="Top suppliers">
          <Table rows={data.top_suppliers} columns={[
            { key: 'name', label: 'Supplier', render: (r: any) => <Link href={`/app/suppliers/${r.id}`}>{r.name}</Link> },
            { key: 'risk_tier', label: 'Risk', render: (r: any) => <Status value={r.risk_tier} /> },
            { key: 'spend', label: 'Spend', align: 'right', render: (r: any) => compactInr(r.spend) },
          ]} />
        </Card>
      </div>
      <Card title="Alerts">
        <Table rows={alerts.data} empty="No open alerts. The background scan checks renewals, review dates, certificates and SLAs every few minutes." columns={[
          { key: 'severity', label: 'Severity', render: (r: any) => <Status value={r.severity} /> },
          { key: 'message', label: 'Alert' },
          { key: 'due_on', label: 'Due', render: (r: any) => day(r.due_on) },
        ]} />
      </Card>
    </Page>
  );
}
