'use client';
import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';
import { createContext, ReactNode, useContext, useEffect, useState } from 'react';
import { BarChart3, Bot, Boxes, Building2, ClipboardCheck, FileSignature, FileText, Inbox, LogOut, Network, PackageCheck, ShieldAlert, Users } from 'lucide-react';
import { api, setCsrf } from '../lib/api';
import { DemoInfo, HOME } from './landing/DemoPersonas';

export type Me = { user: { id: string; name: string; email: string }; tenant: { id: string; name: string }; role: string; permissions: string[]; branch_ids: string[] | null };
const MeContext = createContext<Me | null>(null);
export const useMe = () => useContext(MeContext) as Me;
export const can = (me: Me, permission: string) => me.permissions.includes(permission);

// Ordered the way money moves: ask, approve, buy, receive, pay; then the suppliers behind it.
const NAV: { href: string; label: string; icon: any; permission: string; group: string }[] = [
  { href: '/app', label: 'Overview', icon: BarChart3, permission: 'org.read', group: '' },
  { href: '/app/intake', label: 'Requests', icon: Inbox, permission: 'intake.read', group: 'Buy' },
  { href: '/app/approvals', label: 'Approvals', icon: ClipboardCheck, permission: 'approvals.read', group: 'Buy' },
  { href: '/app/sourcing', label: 'Sourcing (RFQs)', icon: Boxes, permission: 'sourcing.read', group: 'Buy' },
  { href: '/app/orders', label: 'Purchase orders', icon: PackageCheck, permission: 'po.read', group: 'Buy' },
  { href: '/app/invoices', label: 'Invoices and matching', icon: FileText, permission: 'invoice.read', group: 'Pay' },
  { href: '/app/erp', label: 'ERP sync', icon: Network, permission: 'erp.read', group: 'Pay' },
  { href: '/app/suppliers', label: 'Supplier onboarding', icon: Users, permission: 'suppliers.read', group: 'Suppliers' },
  { href: '/app/risk', label: 'Risk', icon: ShieldAlert, permission: 'risk.read', group: 'Suppliers' },
  { href: '/app/contracts', label: 'Contracts', icon: FileSignature, permission: 'contracts.read', group: 'Suppliers' },
  { href: '/app/concierge', label: 'Concierge', icon: Bot, permission: 'concierge.use', group: 'Assist' },
  { href: '/app/admin', label: 'Organization', icon: Building2, permission: 'org.read', group: 'Settings' },
];
const GROUPS = ['', 'Buy', 'Pay', 'Suppliers', 'Assist', 'Settings'];
export const ROLE_LABELS: Record<string, string> = { requester: 'Requester', branch_manager: 'Branch manager', procurement: 'Procurement', finance_ap: 'Accounts payable', legal: 'Legal', risk: 'Risk', admin: 'Admin' };

export function Brand({ light = false }: { light?: boolean }) {
  return <Link href="/" className={`brand ${light ? 'light' : ''}`}><span className="brand-mark" aria-hidden />orrfin<span className="brand-dot">.ai</span></Link>;
}

function PersonaSwitch({ me }: { me: Me }) {
  const [demo, setDemo] = useState<DemoInfo | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => { api<DemoInfo>('/api/auth/demo').then(setDemo).catch(() => undefined); }, []);
  if (!demo?.enabled || demo.company !== me.tenant.name) return null;
  const current = demo.personas.find((p) => p.email === me.user.email)?.key || '';
  async function change(key: string) {
    setBusy(true);
    try {
      await api('/api/auth/demo-login', { body: { persona: key } });
      window.location.assign(HOME[key] || '/app'); // A full load resets permissions and cached data.
    } catch { setBusy(false); }
  }
  return (
    <label>Demo: view as
      <select value={current} disabled={busy} onChange={(e) => change(e.target.value)}>
        {!current && <option value="">Choose a role…</option>}
        {demo.personas.map((p) => <option key={p.key} value={p.key}>{p.label}</option>)}
      </select>
    </label>
  );
}

export default function Shell({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<Me | null>(null);
  const [error, setError] = useState('');
  const router = useRouter();
  const pathname = usePathname();

  useEffect(() => {
    api<Me & { csrf_token: string }>('/api/auth/me')
      .then((data) => { setCsrf(data.csrf_token); setMe(data); })
      .catch((e) => { if (e.status === 401) router.replace('/login'); else setError(e.message); });
  }, [router]);

  async function logout() {
    await api('/api/auth/logout', { method: 'POST' }).catch(() => undefined);
    router.replace('/login');
  }

  if (error) return <div className="center-screen"><p>{error}</p></div>;
  if (!me) return <div className="center-screen"><p>Loading your workspace…</p></div>;
  return (
    <MeContext.Provider value={me}>
      <div className="shell">
        <aside className="sidebar">
          <Brand light />
          <div className="tenant-chip"><strong>{me.tenant.name}</strong><span>{me.branch_ids === null ? 'All branches' : `${me.branch_ids.length} branch${me.branch_ids.length === 1 ? '' : 'es'}`}</span></div>
          <nav aria-label="Main">
            {GROUPS.map((group) => {
              const items = NAV.filter((item) => item.group === group && can(me, item.permission));
              if (!items.length) return null;
              return (
                <div key={group || 'top'}>
                  {group && <p className="nav-group">{group}</p>}
                  {items.map(({ href, label, icon: Icon }) => {
                    const active = href === '/app' ? pathname === '/app' : pathname?.startsWith(href);
                    return <Link key={href} href={href} className={`nav-link ${active ? 'active' : ''}`} aria-current={active ? 'page' : undefined}><Icon size={16} aria-hidden />{label}</Link>;
                  })}
                </div>
              );
            })}
          </nav>
          <div className="sidebar-foot">
            <div className="who"><strong>{me.user.name}</strong><span className="role">{ROLE_LABELS[me.role] || me.role}</span></div>
            <PersonaSwitch me={me} />
            <button className="signout" onClick={logout}><LogOut size={14} aria-hidden /> Sign out</button>
          </div>
        </aside>
        <main className="main">{children}</main>
      </div>
    </MeContext.Provider>
  );
}
