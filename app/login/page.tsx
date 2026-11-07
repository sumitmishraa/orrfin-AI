'use client';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { FormEvent, useState } from 'react';
import { Brand } from '../components/Shell';
import { Field, Notice } from '../components/ui';
import { api } from '../lib/api';

export default function Login() {
  const router = useRouter();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault(); setBusy(true); setError('');
    try { await api('/api/auth/login', { body: { email, password } }); router.replace('/app'); }
    catch (e: any) { setError(e.message); setBusy(false); }
  }

  return (
    <main className="auth">
      <div className="auth-side"><Brand light /><h1>Every branch.<br /><em>One clear view.</em></h1><p>Requests, approvals, sourcing, purchase orders, invoice matching, contracts and supplier risk in one governed workflow.</p></div>
      <form className="auth-card" onSubmit={submit}>
        <h2>Sign in</h2>
        <Field label="Work email"><input type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} /></Field>
        <Field label="Password"><input type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} /></Field>
        {error && <Notice tone="error">{error}</Notice>}
        <button className="button" disabled={busy}>{busy ? 'Signing in…' : 'Sign in'}</button>
        <p className="muted">New to Orrfin.ai? <Link href="/signup">Create an organization</Link></p>
      </form>
    </main>
  );
}
