'use client';
import { ReactNode, useCallback, useEffect, useState } from 'react';
import { usePathname } from 'next/navigation';
import { AlertTriangle, CheckCircle2, CircleDashed, Clock, Info, XCircle } from 'lucide-react';
import { guideFor } from './guides';

export function useLoad<T = any>(load: () => Promise<T>, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const reload = useCallback(() => {
    setLoading(true);
    load().then((value) => { setData(value); setError(''); }).catch((e: any) => setError(e.message || 'Something went wrong.')).finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  useEffect(() => { reload(); }, [reload]);
  return { data, error, loading, reload, setData };
}

/** Runs an action, tracking busy state and turning errors into a message. */
export function useAction() {
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ tone: 'ok' | 'error'; text: string } | null>(null);
  async function run(action: () => Promise<any>, success?: string) {
    setBusy(true); setMessage(null);
    try { const result = await action(); if (success) setMessage({ tone: 'ok', text: success }); return result; }
    catch (e: any) { setMessage({ tone: 'error', text: e.message || 'Something went wrong.' }); return undefined; }
    finally { setBusy(false); }
  }
  return { busy, message, run, setMessage };
}

export function Page({ title, kicker, subtitle, actions, children }: { title: string; kicker?: string; subtitle?: string; actions?: ReactNode; children: ReactNode }) {
  const guide = guideFor(usePathname());
  return (
    <div className="page">
      <header className="page-head">
        <div>{kicker && <p className="kicker">{kicker}</p>}<h1>{title}</h1>{subtitle && <p className="subtitle">{subtitle}</p>}</div>
        {actions && <div className="page-actions">{actions}</div>}
      </header>
      {guide && <Guide id={guide.id} title={guide.spec.title} steps={guide.spec.steps} here={guide.spec.here} />}
      {children}
    </div>
  );
}

export function Card({ title, actions, children, className = '' }: { title?: string; actions?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={`card ${className}`}>
      {(title || actions) && <div className="card-head"><h2>{title}</h2>{actions}</div>}
      {children}
    </section>
  );
}

export type Column<T> = { key: string; label: string; render?: (row: T) => ReactNode; align?: 'right' };

export function Table<T = any>({ rows, columns, empty = 'Nothing here yet.', onRow }: { rows: T[] | undefined | null; columns: Column<T>[]; empty?: string; onRow?: (row: T) => void }) {
  if (rows === undefined || rows === null) return <p className="empty">Loading…</p>;
  if (rows.length === 0) return <p className="empty">{empty}</p>;
  return (
    <div className="table-wrap">
      <table>
        <thead><tr>{columns.map((c) => <th key={c.key} className={c.align === 'right' ? 'num' : ''}>{c.label}</th>)}</tr></thead>
        <tbody>
          {rows.map((row: any, index) => (
            <tr key={row.id || index} onClick={onRow ? () => onRow(row) : undefined} className={onRow ? 'clickable' : ''}>
              {columns.map((c) => <td key={c.key} className={c.align === 'right' ? 'num' : ''}>{c.render ? c.render(row) : String(row[c.key] ?? '-')}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

const TONES: Record<string, 'ok' | 'warn' | 'bad' | 'info' | 'idle'> = {
  approved: 'ok', matched: 'ok', delivered: 'ok', paid: 'ok', received: 'ok', signed: 'ok', issued: 'info', low: 'ok', pass: 'ok', standard: 'ok', ordered: 'info', awarded: 'ok', submitted: 'info',
  pending: 'warn', pending_approval: 'warn', waiting: 'idle', extracted: 'warn', uploaded: 'idle', confirmed: 'info', partially_received: 'warn', change_pending: 'warn', review: 'warn', medium: 'warn', sourcing: 'info', open: 'info', retrying: 'warn', onboarding: 'warn', invited: 'idle', draft: 'idle', deviates: 'warn', warn: 'warn', needs_mapping: 'warn', scheduled: 'info',
  rejected: 'bad', exception: 'bad', cancelled: 'bad', high: 'bad', critical: 'bad', fail: 'bad', missing: 'bad', flagged: 'bad', dead_letter: 'bad', extraction_failed: 'bad', suspended: 'bad', blocking: 'bad', expired: 'bad',
};

export function Status({ value }: { value: string | null | undefined }) {
  const text = (value || 'unknown').replace(/_/g, ' ');
  const tone = TONES[value || ''] || 'idle';
  const Icon = { ok: CheckCircle2, warn: Clock, bad: XCircle, info: Info, idle: CircleDashed }[tone];
  return <span className={`status ${tone}`}><Icon size={13} aria-hidden />{text}</span>;
}

export function Notice({ tone = 'info', children }: { tone?: 'info' | 'ok' | 'error' | 'warn'; children: ReactNode }) {
  const Icon = tone === 'error' ? XCircle : tone === 'warn' ? AlertTriangle : tone === 'ok' ? CheckCircle2 : Info;
  return <div className={`notice ${tone}`} role={tone === 'error' ? 'alert' : 'status'}><Icon size={16} aria-hidden /><div>{children}</div></div>;
}

export function Message({ message }: { message: { tone: 'ok' | 'error'; text: string } | null }) {
  return message ? <Notice tone={message.tone}>{message.text}</Notice> : null;
}

export function Field({ label, children, hint }: { label: string; children: ReactNode; hint?: string }) {
  return <label className="field"><span>{label}</span>{children}{hint && <small>{hint}</small>}</label>;
}

export function Stat({ label, value, hint }: { label: string; value: ReactNode; hint?: string }) {
  return <div className="stat"><span>{label}</span><strong>{value}</strong>{hint && <small>{hint}</small>}</div>;
}

export function Loading({ error }: { error?: string }) {
  return error ? <Notice tone="error">{error}</Notice> : <p className="empty">Loading…</p>;
}

export function Tabs({ tabs, value, onChange }: { tabs: [string, string][]; value: string; onChange: (v: string) => void }) {
  return <div className="tabs" role="tablist">{tabs.map(([key, label]) => <button key={key} role="tab" aria-selected={value === key} className={value === key ? 'active' : ''} onClick={() => onChange(key)}>{label}</button>)}</div>;
}

export function DownloadLink({ href, children }: { href: string; children: ReactNode }) {
  return <a className="button secondary" href={href} download>{children}</a>;
}

/**
 * "How this works" strip under a page title: the steps of this workflow and who does each one.
 * `here` marks the step this screen is for. People can hide it; the choice is remembered per screen.
 */
export function Guide({ id, title = 'How this works', steps, here }: { id: string; title?: string; steps: [string, string][]; here?: number }) {
  const key = `orrfin.guide.${id}`;
  const [hidden, setHidden] = useState(false);
  useEffect(() => { try { setHidden(localStorage.getItem(key) === 'hidden'); } catch { /* storage blocked: keep showing */ } }, [key]);
  const toggle = (value: boolean) => { setHidden(value); try { localStorage.setItem(key, value ? 'hidden' : 'shown'); } catch { /* ignore */ } };
  if (hidden) return <p className="muted" style={{ marginTop: -8 }}><button className="link" onClick={() => toggle(false)}>Show how this works</button></p>;
  return (
    <section className="guide" aria-label={title}>
      <div className="guide-head"><strong>{title}</strong><button className="link" onClick={() => toggle(true)}>Hide</button></div>
      <ol>{steps.map(([who, what], n) => <li key={n} className={n === here ? 'here' : ''}><b>{who}</b><span>{what}</span></li>)}</ol>
    </section>
  );
}
