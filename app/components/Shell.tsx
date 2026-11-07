'use client';
import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';
import { createContext, ReactNode, useContext, useEffect, useState } from 'react';
import { BarChart3, Bot, Boxes, Building2, ClipboardCheck, FileSignature, FileText, Inbox, LogOut, Network, PackageCheck, ShieldAlert, Users } from 'lucide-react';
import { api, setCsrf } from '../lib/api';

export type Me = { user: { id: string; name: string; email: string }; tenant: { id: string; name: string }; role: string; permissions: string[]; branch_ids: string[] | null };
const MeContext = createContext<Me | null>(null);
export const useMe = () => useContext(MeContext) as Me;
export const can = (me: Me, permission: string) => me.permissions.includes(permission);

const NAV: { href: string; label: string; icon: any; permission: string; group: string }[] = [
  { href: '/app', label: 'Overview', icon: BarChart3, permission: 'org.read', group: 'Workspace' },
  { href: '/app/intake', label: 'Intake-to-Procure', icon: Inbox, permission: 'intake.read', group: 'Products' },
  { href: '/app/approvals', label: 'Approvals', icon: ClipboardCheck, permission: 'approvals.read', group: 'Products' },
  { href: '/app/sourcing', label: 'Sourcing', icon: Boxes, permission: 'sourcing.read', group: 'Products' },
  { href: '/app/orders', label: 'Procure-to-Pay: Orders', icon: PackageCheck, permission: 'po.read', group: 'Products' },
  { href: '/app/invoices', label: 'Procure-to-Pay: Invoices', icon: FileText, permission: 'invoice.read', group: 'Products' },
  { href: '/app/suppliers', label: 'Supplier Onboarding', icon: Users, permission: 'suppliers.read', group: 'Products' },
  { href: '/app/risk', label: 'Risk Orchestration', icon: ShieldAlert, permission: 'risk.read', group: 'Products' },
  { href: '/app/contracts', label: 'AI Contract Orchestration', icon: FileSignature, permission: 'contracts.read', group: 'Products' },
  { href: '/app/concierge', label: 'AI Procurement Concierge', icon: Bot, permission: 'concierge.use', group: 'Products' },
  { href: '/app/erp', label: 'ERP connections', icon: Network, permission: 'erp.read', group: 'Settings' },
  { href: '/app/admin', label: 'Organization', icon: Building2, permission: 'org.read', group: 'Settings' },
];

export function Brand({ light = false }: { light?: boolean }) {
  return <Link href="/" className={`brand ${light ? 'light' : ''}`}><span className="brand-mark" aria-hidden>o</span>orrfin<span className="brand-dot">.ai</span></Link>;
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
  const groups = ['Workspace', 'Products', 'Settings'];
  return (
    <MeContext.Provider value={me}>
      <div className="shell">
        <aside className="sidebar">
          <Brand light />
          <nav aria-label="Main">
            {groups.map((group) => (
              <div key={group}>
                <p className="nav-group">{group}</p>
                {NAV.filter((item) => item.group === group && can(me, item.permission)).map(({ href, label, icon: Icon }) => {
                  const active = href === '/app' ? pathname === '/app' : pathname?.startsWith(href);
                  return <Link key={href} href={href} className={`nav-link ${active ? 'active' : ''}`}><Icon size={16} aria-hidden />{label}</Link>;
                })}
              </div>
            ))}
          </nav>
          <div className="sidebar-foot">
            <strong>{me.user.name}</strong>
            <span>{me.tenant.name}</span>
            <span className="role">{me.role.replace('_', ' ')}</span>
            <button onClick={logout}><LogOut size={14} aria-hidden /> Sign out</button>
          </div>
        </aside>
        <main className="main">{children}</main>
      </div>
    </MeContext.Provider>
  );
}
