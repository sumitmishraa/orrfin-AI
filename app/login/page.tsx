'use client';
import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';
import { FormEvent, Suspense, useEffect, useRef, useState } from 'react';
import { Brand } from '../components/Shell';
import { Field, Notice } from '../components/ui';
import DemoPersonas, { safeNext, useDemo, useDemoLogin } from '../components/landing/DemoPersonas';
import { api } from '../lib/api';

function LoginForm() {
  const router = useRouter();
  const params = useSearchParams();
  const demo = useDemo();
  const persona = params.get('persona');
  const next = safeNext(params.get('next'));
  const auto = useDemoLogin();
  const started = useRef(false);
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  // A link from the landing page ("Try it as the AP lead") signs in as that persona straight away.
  useEffect(() => {
    if (started.current || !demo?.enabled || !persona) return;
    if (!demo.personas.some((p) => p.key === persona)) return;
    started.current = true;
    auto.signIn(persona, next);
  }, [demo, persona, next, auto]);

  async function submit(event: FormEvent) {
    event.preventDefault(); setBusy(true); setError('');
    try { await api('/api/auth/login', { body: { email, password } }); router.replace(next || '/app'); }
    catch (e: any) { setError(e.message); setBusy(false); }
  }

  const label = demo?.personas.find((p) => p.key === persona)?.label;

  return (
    <main className="auth">
      <div className="auth-side">
        <Brand light />
        <div style={{ display: 'grid', gap: 18 }}>
          <h1>Every branch. One way to buy.</h1>
          <p>Requests, approvals, sourcing, purchase orders, receipts, invoice matching, contracts and supplier risk, in one governed workflow connected to Zoho Books or Tally Prime.</p>
        </div>
        <p style={{ fontSize: 13 }}><Link href="/" style={{ color: 'var(--sky)' }}>Back to the product overview</Link></p>
      </div>
      <div className="auth-card">
        {demo?.enabled && (
          <>
            <h2>Explore the demo</h2>
            <p className="muted">{demo.company} is fictional. Pick a role to sign in with that person’s permissions; you can switch roles any time from the menu.</p>
            {auto.busy && label && <Notice>Signing you in as {label}…</Notice>}
            {auto.error && <Notice tone="error">{auto.error}</Notice>}
            <DemoPersonas info={demo} selected={persona} next={next} />
            <p className="auth-or">or sign in with your account</p>
          </>
        )}
        <form onSubmit={submit} style={{ display: 'grid', gap: 14 }}>
          {!demo?.enabled && <h2>Sign in</h2>}
          <Field label="Work email"><input type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} /></Field>
          <Field label="Password"><input type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} /></Field>
          {error && <Notice tone="error">{error}</Notice>}
          <button className={demo?.enabled ? 'button secondary' : 'button'} disabled={busy}>{busy ? 'Signing in…' : 'Sign in'}</button>
          <p className="muted">New to Orrfin.ai? <Link href="/signup">Create an organization</Link></p>
        </form>
      </div>
    </main>
  );
}

export default function Login() {
  return <Suspense><LoginForm /></Suspense>;
}
