'use client';
import Link from 'next/link';
import { FormEvent, useState } from 'react';
import { Card, Message, Notice, Page, Table, useAction, useLoad } from '../../components/ui';
import { can, useMe } from '../../components/Shell';
import { api } from '../../lib/api';

type Turn = { question: string; answer: any };

const SUGGESTIONS = [
  'Which Pune purchase orders are still waiting for delivery?',
  'Which invoices have open exceptions, and why?',
  'How reliable is our top packaging supplier?',
  'I need 40 insulated delivery bags for Pune next week.',
];

export default function Concierge() {
  const me = useMe();
  const status = useLoad(() => api('/api/concierge/status'));
  const drafts = useLoad(() => api('/api/concierge/drafts'));
  const [question, setQuestion] = useState('');
  const [turns, setTurns] = useState<Turn[]>([]);
  const { busy, message, run } = useAction();

  async function send(text: string) {
    const answer = await run(() => api('/api/concierge/ask', { body: { question: text } }));
    if (answer) { setTurns((all) => [...all, { question: text, answer }]); setQuestion(''); drafts.reload(); }
  }
  function ask(event: FormEvent) { event.preventDefault(); send(question); }
  const s = status.data;

  return (
    <Page kicker="AI Procurement Concierge" title="Ask about your procurement" subtitle="Answers come only from your organization's records and cite them. The concierge can draft a request for you to review; it can't approve, pay or send anything."
      actions={can(me, 'ai.manage') && s && <button className="button secondary" disabled={busy || !s.configured} onClick={() => run(() => api('/api/concierge/consent', { body: { enabled: !s.enabled } })).then(status.reload)}>{s.enabled ? 'Turn AI off' : 'Turn AI on'}</button>}>
      <Message message={message} />
      {s && !s.available && <Notice>{s.configured ? 'AI is configured but switched off for this organization, so you get matching records instead of written answers.' : 'AI is not configured on this server. Add GEMINI_API_KEY or ANTHROPIC_API_KEY to .env to get written answers; until then you get matching records.'}</Notice>}
      <Card>
        <form className="ask" onSubmit={ask}>
          <input aria-label="Question" placeholder="e.g. Which Pune purchase orders are still waiting for delivery? Or: I need 40 insulated bags for Koramangala next week." value={question} onChange={(e) => setQuestion(e.target.value)} />
          <button className="button" disabled={busy || question.length < 2}>{busy ? 'Looking through your records…' : 'Ask'}</button>
        </form>
        {turns.length === 0 && <div className="suggest" aria-label="Example questions">
          {SUGGESTIONS.map((q) => <button key={q} type="button" disabled={busy} onClick={() => { setQuestion(q); send(q); }}>{q}</button>)}
        </div>}
        {s?.available && <p className="muted">Answered by {s.provider === 'gemini' ? 'Google Gemini' : s.provider === 'anthropic' ? 'Claude' : s.provider} ({s.model}). Answers can take up to a minute.</p>}
        {turns.map((t, i) => (
          <div key={i} className="turn">
            <p className="q">{t.question}</p>
            {t.answer.answer ? <div className="a"><p>{t.answer.answer}</p>{t.answer.citations?.length > 0 && <p className="muted">Sources: {t.answer.citations.map((c: any) => <Link key={c.ref} href={c.link}>{c.ref}</Link>)}</p>}</div>
              : <div className="a"><p className="muted">{t.answer.notice}</p><Table rows={t.answer.results} empty="No matching records." columns={[{ key: 'type', label: 'Type', render: (r: any) => r.type.replace('_', ' ') }, { key: 'ref', label: 'Record', render: (r: any) => <Link href={r.link}>{r.ref}</Link> }, { key: 'label', label: 'Name' }, { key: 'detail', label: 'Detail' }]} /></div>}
            {t.answer.notice && t.answer.answer && <p className="muted">{t.answer.notice}</p>}
          </div>
        ))}
      </Card>
      <Card title="Drafts waiting for you">
        <Table rows={drafts.data} empty="No drafts." columns={[
          { key: 'title', label: 'Draft request', render: (r: any) => r.payload.title },
          { key: 'lines', label: 'Lines', render: (r: any) => r.payload.lines.length },
          { key: 'open', label: '', render: (r: any) => <span className="inline-form"><Link className="button small" href={`/app/intake?draft=${r.id}`}>Review and submit</Link><button className="link" onClick={() => api(`/api/concierge/drafts/${r.id}/discard`, { method: 'POST' }).then(drafts.reload)}>Discard</button></span> },
        ]} />
      </Card>
    </Page>
  );
}
