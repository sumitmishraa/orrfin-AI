'use client';
import { useState } from 'react';
import { Card, Field, Message, Page, Table, Tabs, useAction, useLoad } from '../../components/ui';
import { can, useMe } from '../../components/Shell';
import { api, day, inr } from '../../lib/api';

const ROLES = ['requester', 'branch_manager', 'procurement', 'finance_ap', 'legal', 'risk', 'admin'];

export default function Admin() {
  const me = useMe();
  const [tab, setTab] = useState('structure');
  const overview = useLoad(() => api('/api/org/overview'));
  const users = useLoad(() => (can(me, 'users.manage') ? api('/api/auth/users') : Promise.resolve([])));
  const rules = useLoad(() => api('/api/org/approval-rules'));
  const audit = useLoad(() => (can(me, 'audit.read') ? api('/api/org/audit?limit=100') : Promise.resolve([])));
  const { busy, message, run } = useAction();
  const [entity, setEntity] = useState({ name: '', gstin: '', address: '' });
  const [branch, setBranch] = useState({ code: '', name: '', city: '', legal_entity_id: '' });
  const [user, setUser] = useState({ name: '', email: '', password: '', role: 'requester', branch_ids: [] as string[] });
  const [rule, setRule] = useState({ name: '', step: '1', min_amount: '0', approver_role: 'procurement' });
  const write = can(me, 'org.write');
  const o = overview.data;

  return (
    <Page kicker="Organization" title={me.tenant.name} subtitle="GST registrations, branches and sites, people and roles, approval rules and the audit trail.">
      <Message message={message} />
      <Tabs value={tab} onChange={setTab} tabs={[['structure', 'Entities and branches'], ['people', 'People'], ['rules', 'Approval rules'], ['audit', 'Audit trail']]} />
      {tab === 'structure' && o && <>
        <Card title="Legal entities (one per GST registration)">
          <Table rows={o.legal_entities} columns={[{ key: 'name', label: 'Name' }, { key: 'gstin', label: 'GSTIN' }, { key: 'state_name', label: 'State' }]} />
          {write && <div className="row"><Field label="Name"><input value={entity.name} onChange={(e) => setEntity({ ...entity, name: e.target.value })} /></Field><Field label="GSTIN"><input value={entity.gstin} onChange={(e) => setEntity({ ...entity, gstin: e.target.value.toUpperCase() })} /></Field><Field label="Address"><input value={entity.address} onChange={(e) => setEntity({ ...entity, address: e.target.value })} /></Field><button className="button" disabled={busy} onClick={() => run(() => api('/api/org/legal-entities', { body: entity }), 'Added.').then(overview.reload)}>Add entity</button></div>}
        </Card>
        <Card title="Branches">
          <Table rows={o.branches} columns={[{ key: 'code', label: 'Code' }, { key: 'name', label: 'Branch' }, { key: 'city', label: 'City' }, { key: 'gstin', label: 'Bills under GSTIN' }, { key: 'locations', label: 'Sites', align: 'right' }]} />
          {write && <div className="row">{(['code', 'name', 'city'] as const).map((k) => <Field key={k} label={{ code: 'Branch code', name: 'Branch name', city: 'City' }[k]}><input value={branch[k]} onChange={(e) => setBranch({ ...branch, [k]: e.target.value })} /></Field>)}<Field label="Entity"><select value={branch.legal_entity_id} onChange={(e) => setBranch({ ...branch, legal_entity_id: e.target.value })}><option value="">Choose…</option>{o.legal_entities.map((x: any) => <option key={x.id} value={x.id}>{x.state_name}</option>)}</select></Field><button className="button" disabled={busy} onClick={() => run(() => api('/api/org/branches', { body: branch }), 'Added.').then(overview.reload)}>Add branch</button></div>}
        </Card>
      </>}
      {tab === 'people' && <Card title="People">
        <Table rows={users.data} columns={[{ key: 'name', label: 'Name' }, { key: 'email', label: 'Email' }, { key: 'role', label: 'Role', render: (r: any) => r.role.replace('_', ' ') }, { key: 'branch_ids', label: 'Branches', render: (r: any) => r.branch_ids.length ? r.branch_ids.map((b: string) => o?.branches.find((x: any) => x.id === b)?.code).join(', ') : 'All' }]} />
        {can(me, 'users.manage') && <div className="row">
          {(['name', 'email', 'password'] as const).map((k) => <Field key={k} label={{ name: 'Name', email: 'Work email', password: 'Temporary password' }[k]}><input type={k === 'password' ? 'password' : 'text'} value={user[k]} onChange={(e) => setUser({ ...user, [k]: e.target.value })} /></Field>)}
          <Field label="Role"><select value={user.role} onChange={(e) => setUser({ ...user, role: e.target.value })}>{ROLES.map((r) => <option key={r} value={r}>{r.replace('_', ' ')}</option>)}</select></Field>
          <Field label="Branch"><select value={user.branch_ids[0] || ''} onChange={(e) => setUser({ ...user, branch_ids: e.target.value ? [e.target.value] : [] })}><option value="">All (central roles)</option>{o?.branches.map((b: any) => <option key={b.id} value={b.id}>{b.code}</option>)}</select></Field>
          <button className="button" disabled={busy} onClick={() => run(() => api('/api/auth/users', { body: user }), 'Added.').then(users.reload)}>Add person</button>
        </div>}
      </Card>}
      {tab === 'rules' && <Card title="Approval rules">
        <Table rows={rules.data} columns={[{ key: 'step', label: 'Step' }, { key: 'name', label: 'Rule' }, { key: 'min_amount', label: 'From', align: 'right', render: (r: any) => inr(r.min_amount) }, { key: 'approver_role', label: 'Approver', render: (r: any) => r.approver_role.replace('_', ' ') }, { key: 'sla_hours', label: 'SLA (h)', align: 'right' }]} />
        {write && <div className="row"><Field label="Name"><input value={rule.name} onChange={(e) => setRule({ ...rule, name: e.target.value })} /></Field><Field label="Step"><input value={rule.step} onChange={(e) => setRule({ ...rule, step: e.target.value })} /></Field><Field label="From amount (₹)"><input value={rule.min_amount} onChange={(e) => setRule({ ...rule, min_amount: e.target.value })} /></Field><Field label="Approver"><select value={rule.approver_role} onChange={(e) => setRule({ ...rule, approver_role: e.target.value })}>{ROLES.map((r) => <option key={r} value={r}>{r.replace('_', ' ')}</option>)}</select></Field><button className="button" disabled={busy} onClick={() => run(() => api('/api/org/approval-rules', { body: { ...rule, step: Number(rule.step) } }), 'Rule added. It applies to new submissions only.').then(rules.reload)}>Add rule</button></div>}
      </Card>}
      {tab === 'audit' && <Card title="Audit trail (append-only)"><Table rows={audit.data} columns={[{ key: 'created_at', label: 'When', render: (r: any) => day(r.created_at) }, { key: 'actor_label', label: 'Who' }, { key: 'action', label: 'Action', render: (r: any) => r.action.replace(/_/g, ' ') }, { key: 'subject_type', label: 'Record' }]} /></Card>}
    </Page>
  );
}
