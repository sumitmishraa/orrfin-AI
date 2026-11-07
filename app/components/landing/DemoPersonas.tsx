'use client';
/*
  Demo persona sign-in, used by /login and the app shell's "view as" switcher. The server only
  enables it when ORRFIN_DEMO_LOGIN=1 and the fictional demo company is seeded (orrfin/api/auth.py).
*/
import { useRouter } from 'next/navigation';
import { useEffect, useState } from 'react';
import { api } from '../../lib/api';

export type Persona = { key: string; label: string; role: string; does: string; email: string };
export type DemoInfo = { enabled: boolean; company?: string; personas: Persona[] };

// Where each persona lands first: the screen where their part of the workflow happens.
export const HOME: Record<string, string> = {
  store: '/app/intake', manager: '/app/approvals', procurement: '/app', finance: '/app/invoices',
  legal: '/app/contracts', risk: '/app/risk', admin: '/app',
};

export const safeNext = (next: string | null | undefined) => (next && /^\/app(\/[\w\-/]*)?$/.test(next) ? next : null);

export function useDemo() {
  const [info, setInfo] = useState<DemoInfo | null>(null);
  useEffect(() => { api<DemoInfo>('/api/auth/demo').then(setInfo).catch(() => setInfo({ enabled: false, personas: [] })); }, []);
  return info;
}

export function useDemoLogin() {
  const router = useRouter();
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState('');
  async function signIn(key: string, next?: string | null) {
    setBusy(key); setError('');
    try {
      await api('/api/auth/demo-login', { body: { persona: key } });
      router.push(safeNext(next) || HOME[key] || '/app');
    } catch (e: any) { setError(e.message || 'Demo sign-in failed.'); setBusy(null); }
  }
  return { busy, error, signIn };
}

export default function DemoPersonas({ info, selected, next }: { info: DemoInfo; selected?: string | null; next?: string | null }) {
  const { busy, error, signIn } = useDemoLogin();
  return (
    <>
      <div className="personas">
        {info.personas.map((p) => (
          <button key={p.key} type="button" className={`persona ${selected === p.key ? 'selected' : ''}`} disabled={!!busy} onClick={() => signIn(p.key, selected === p.key ? next : null)}>
            <strong>{p.label}</strong>
            <span>{p.does}</span>
            <em>{busy === p.key ? 'Signing in…' : 'Sign in'}</em>
          </button>
        ))}
      </div>
      {error && <p className="notice error" role="alert">{error}</p>}
    </>
  );
}
