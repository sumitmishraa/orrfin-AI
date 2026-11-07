'use client';
import Link from 'next/link';
import { useState } from 'react';
import { Card, Message, Page, Status, Table, useAction, useLoad } from '../../components/ui';
import { api, day, inr } from '../../lib/api';

export default function Approvals() {
  const queue = useLoad(() => api('/api/approvals/queue'));
  const { busy, message, run } = useAction();
  const [comments, setComments] = useState<Record<string, string>>({});
  async function decide(task: any, approve: boolean) {
    await run(() => api(`/api/approvals/tasks/${task.id}/${approve ? 'approve' : 'reject'}`, { body: { comment: comments[task.id] || '' } }), approve ? 'Approved.' : 'Rejected.');
    queue.reload();
  }
  return (
    <Page kicker="Approvals" title="Waiting for your decision" subtitle="Steps are assigned by role and branch. You can't approve a request you raised; the database enforces this.">
      <Message message={message} />
      <Card>
        <Table rows={queue.data} empty="Nothing is waiting for you." columns={[
          { key: 'subject', label: 'Request', render: (r: any) => r.subject_type === 'intake' ? <Link href={`/app/intake/${r.subject_id}`}>{r.subject}</Link> : <Link href={`/app/orders/${r.subject_id}`}>{r.subject}</Link> },
          { key: 'step', label: 'Step', render: (r: any) => `${r.step} of ${r.steps} · ${r.approver_role.replace('_', ' ')}` },
          { key: 'amount', label: 'Amount', align: 'right', render: (r: any) => inr(r.amount) },
          { key: 'due_at', label: 'Due', render: (r: any) => <span className={r.due_at && new Date(r.due_at) < new Date() ? 'overdue' : ''}>{day(r.due_at)}</span> },
          { key: 'decision', label: 'Decision', render: (r: any) => r.own_request ? <Status value="waiting" /> : (
            <div className="inline-form">
              <input placeholder="Comment (required to reject)" value={comments[r.id] || ''} onChange={(e) => setComments({ ...comments, [r.id]: e.target.value })} />
              <button className="button small" disabled={busy} onClick={() => decide(r, true)}>Approve</button>
              <button className="button small danger" disabled={busy} onClick={() => decide(r, false)}>Reject</button>
            </div>
          ) },
        ]} />
      </Card>
    </Page>
  );
}
