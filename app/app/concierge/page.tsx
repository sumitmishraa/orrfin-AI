'use client';
import Link from 'next/link';
import { FormEvent, useState } from 'react';
import { Card, Message, Notice, Page, Table, useAction, useLoad } from '../../components/ui';
import { can, useMe } from '../../components/Shell';
import { api } from '../../lib/api';

type Turn = { question: string; answer: any };

export default function Concierge() {
  const me = useMe();
  const status = useLoad(() => api('/api/concierge/status'));
  const drafts = useLoad(() => api('/api/concierge/drafts'));
  const [question, setQuestion] = useState('');
  const [turns, setTurns] = useState<Turn[]>([]);
  const { busy, message, run } = useAction();

  async function ask(event: FormEvent) {
    event.preventDefault();
    const answer = await run(() => api('/api/concierge/ask', { body: { question } }));
    if (answer) { setTurns([...turns, { question, answer }]); setQuestion(''); drafts.reload(); }
  }
  const s = status.data;

  return (
    <Page kicker="AI Procurement Concierge" title="Ask about your procurement" subtitle="Answers come only from your organization's records and cite them. The concierge can draft a request for you to review; it can't approve, pay or send anything."
      actions={can(me, 'ai.manage') && s && <button className="button secondary" disabled={busy || !s.configured} onClick={() => run(() => api('/api/concierge/consent', { body: { enabled: !s.enabled } })).then(status.reload)}>{s.enabled ? 'Turn AI off' : 'Turn AI on'}</button>}>
      <Message message={message} />
      {s && !s.available && <Notice>{s.configured ? 'AI is configured but switched off for this organization, so you get matching records instead of written answers.' : `AI isn't configured on this server (provider ${s.provider}). Add ANTHROPIC_API_KEY to .env to enable written answers. Search still works.`}</Notice>}
      <Card>
        <form className="ask" onSubmit={ask}>
          <input aria-label="Question" placeholder="e.g. Which Pune purchase orders are still waiting for delivery? Or: I need 40 insulated bags for Koramangala next week." value={question} onChange={(e) => setQuestion(e.target.value)} />
          <button className="button" disabled={busy || question.length < 2}>{busy ? 'Thinking…' : 'Ask'}</button>
        </form>
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
