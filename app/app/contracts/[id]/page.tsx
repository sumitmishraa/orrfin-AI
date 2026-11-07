'use client';
import { useParams } from 'next/navigation';
import { useState } from 'react';
import { Card, DownloadLink, Loading, Message, Notice, Page, Status, Table, useAction, useLoad } from '../../../components/ui';
import { can, useMe } from '../../../components/Shell';
import { api, day } from '../../../lib/api';

export default function ContractDetail() {
  const { id } = useParams<{ id: string }>();
  const me = useMe();
  const contract = useLoad(() => api(`/api/contracts/${id}`), [id]);
  const { busy, message, run } = useAction();
  const [editing, setEditing] = useState<string | null>(null);
  const [redline, setRedline] = useState<any>(null);
  const d = contract.data;
  if (!d) return <Page title="Contract"><Loading error={contract.error} /></Page>;
  const current = d.versions[0];
  const review = current?.review || {};

  async function upload(event: any) {
    const file = event.target.files?.[0];
    if (!file) return;
    const form = new FormData(); form.append('file', file);
    await run(() => api(`/api/contracts/${id}/upload`, { form }), 'Uploaded and reviewed.');
    contract.reload();
  }

  return (
    <Page kicker={d.number} title={d.title} subtitle={`${d.supplier} · ${day(d.start_on)} to ${day(d.end_on)} · signature ${d.signature_status.replace(/_/g, ' ')}`}
      actions={<><Status value={d.status} />
        <DownloadLink href={`/api/contracts/${id}/versions/${current.version}/docx`}>Word</DownloadLink>
        <DownloadLink href={`/api/contracts/${id}/versions/${current.version}/pdf`}>PDF</DownloadLink>
        {can(me, 'contracts.write') && <label className="button secondary">Upload their version<input type="file" accept="application/pdf" hidden onChange={upload} /></label>}
        {['legal', 'admin'].includes(me.role) && d.status !== 'approved' && d.status !== 'signed' && <button className="button" disabled={busy} onClick={() => run(() => api(`/api/contracts/${id}/status`, { body: { status: 'approved' } }), 'Approved by legal.').then(contract.reload)}>Approve</button>}
        {['legal', 'admin'].includes(me.role) && d.status === 'approved' && <button className="button" disabled={busy} onClick={() => run(() => api(`/api/contracts/${id}/status`, { body: { status: 'signed', signature_status: 'fully_signed' } }), 'Marked signed.').then(contract.reload)}>Mark signed</button>}
      </>}>
      <Message message={message} />
      <Card title={`Review of version ${current.version} (${current.source})`}>
        <Notice tone="warn">{review.notice}</Notice>
        {review.ai_summary ? <Notice tone="info"><strong>AI summary:</strong> {review.ai_summary.summary}<ul>{review.ai_summary.key_risks.map((r: string) => <li key={r}>{r}</li>)}</ul></Notice>
          : <p className="muted">AI summary: {d.ai.available ? 'not available for this version.' : 'AI is off for this organization, so this review uses your clause library and rules only.'}</p>}
        <Table rows={review.findings} columns={[
          { key: 'severity', label: '', render: (r: any) => <Status value={r.severity === 'none' ? 'standard' : r.severity} /> },
          { key: 'clause', label: 'Clause' }, { key: 'status', label: 'Result', render: (r: any) => <Status value={r.status} /> }, { key: 'note', label: 'Note' },
          { key: 'excerpt', label: 'Excerpt', render: (r: any) => r.excerpt ? <span className="excerpt">{r.excerpt}</span> : '-' },
        ]} />
      </Card>
      <div className="grid-2">
        <Card title="Versions" actions={d.versions.length > 1 && <button className="link" onClick={() => api(`/api/contracts/${id}/redline?from_version=${d.versions[1].version}&to_version=${current.version}`).then(setRedline)}>Compare latest two</button>}>
          <Table rows={d.versions} columns={[{ key: 'version', label: 'Version' }, { key: 'source', label: 'Source' }, { key: 'created_by', label: 'By' }, { key: 'created_at', label: 'When', render: (r: any) => day(r.created_at) }]} />
          {redline && <div className="redline">{redline.changes.map((c: any, i: number) => <pre key={i} className={c.op}>{c.text}</pre>)}</div>}
        </Card>
        <Card title="Obligations and renewal">
          <Table rows={d.obligations} columns={[{ key: 'title', label: 'Obligation' }, { key: 'due_on', label: 'Due', render: (r: any) => day(r.due_on) }, { key: 'status', label: 'Status', render: (r: any) => <Status value={r.status} /> }]} />
        </Card>
      </div>
      <Card title="Contract text" actions={can(me, 'contracts.write') && (editing === null ? <button className="link" onClick={() => setEditing(current.body)}>Edit as new version</button> : <span className="inline-form"><button className="button small" disabled={busy} onClick={() => run(() => api(`/api/contracts/${id}/versions`, { body: { body: editing } }), 'Saved as a new version.').then(() => { setEditing(null); contract.reload(); })}>Save version</button><button className="link" onClick={() => setEditing(null)}>Cancel</button></span>)}>
        {editing === null ? <pre className="contract-text">{current.body}</pre> : <textarea className="contract-text" value={editing} onChange={(e) => setEditing(e.target.value)} rows={30} />}
      </Card>
    </Page>
  );
}
