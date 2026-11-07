'use client';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { FormEvent, useState } from 'react';
import { Brand } from '../components/Shell';
import { Field, Notice } from '../components/ui';
import { api } from '../lib/api';

export default function Signup() {
  const router = useRouter();
  const [form, setForm] = useState({ company: '', name: '', email: '', password: '' });
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const set = (key: string) => (e: any) => setForm({ ...form, [key]: e.target.value });

  async function submit(event: FormEvent) {
    event.preventDefault(); setBusy(true); setError('');
    try { await api('/api/auth/signup', { body: form }); router.replace('/app/admin'); }
    catch (e: any) { setError(e.message); setBusy(false); }
  }

  return (
    <main className="auth">
      <div className="auth-side"><Brand light /><h1>Set up your<br /><em>organization.</em></h1><p>You become the admin. Next, add your GST registrations, branches, sites and team.</p></div>
      <form className="auth-card" onSubmit={submit}>
        <h2>Create an organization</h2>
        <Field label="Company name"><input required value={form.company} onChange={set('company')} /></Field>
        <Field label="Your name"><input required value={form.name} onChange={set('name')} /></Field>
        <Field label="Work email"><input type="email" required value={form.email} onChange={set('email')} /></Field>
        <Field label="Password" hint="At least 10 characters."><input type="password" minLength={10} required value={form.password} onChange={set('password')} /></Field>
        {error && <Notice tone="error">{error}</Notice>}
        <button className="button" disabled={busy}>{busy ? 'Creating…' : 'Create organization'}</button>
        <p className="muted">Already have an account? <Link href="/login">Sign in</Link></p>
      </form>
    </main>
  );
}
