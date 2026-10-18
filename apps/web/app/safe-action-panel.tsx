'use client';
import { useEffect, useState, useSyncExternalStore, type FormEvent } from 'react';
import { SafeActionClient, type SafeActionProposal } from '../lib/safe-action-client';
export type { SafeActionProposal } from '../lib/safe-action-client';

export function SafeActionDetails({ proposal }: { proposal?: SafeActionProposal | null }) {
  return <dl>
    <dt>Checklist title</dt><dd>{proposal?.title ?? 'No proposal loaded'}</dd>
    <dt>Checklist items</dt><dd>{proposal ? <ul className="list-disc pl-5 space-y-2">
      {proposal.items.map((item, index) => <li key={index}>{item}</li>)}
    </ul> : 'Items will appear after authenticated retrieval.'}</dd>
    <dt>Proposal ID</dt><dd className="mono">{proposal?.proposal_id ?? '—'}</dd>
    <dt>Canonical fingerprint</dt><dd className="mono">{proposal?.fingerprint ?? '—'}</dd>
    <dt>Expires at (UTC)</dt><dd className="mono">{proposal?.expires_at ?? '—'}</dd>
    <dt>Decision status</dt><dd>{proposal?.status ?? 'Unavailable'}</dd>
  </dl>;
}

export default function SafeActionPanel() {
  const [client] = useState(() => new SafeActionClient());
  const state = useSyncExternalStore(client.subscribe, client.snapshot, client.snapshot);
  const [password, setPassword] = useState(''); const [id, setId] = useState('');
  useEffect(() => { void client.restore(); const timer = setInterval(client.expire, 1000);
    return () => clearInterval(timer); }, [client]);
  useEffect(() => { if (!state.expires) { setId(''); setPassword(''); } }, [state.expires]);
  function login(event: FormEvent) { event.preventDefault(); const value = password; setPassword(''); void client.login(value); }
  const pending = state.proposal?.status === 'pending' && !state.needsRefresh;
  return <section className="details mt-6" aria-labelledby="safe-action-heading">
    <div className="panel-title"><h2 id="safe-action-heading" className="!m-0 !text-sm">SafeAction review</h2>
      <span className="badge">{state.expires ? 'OPERATOR SESSION' : 'SIGN IN REQUIRED'}</span></div>
    <div className="details-body">
      <p className="note !mt-0" role={state.error ? 'alert' : 'status'}>{state.message}</p>
      {state.expires ? <div className="flex flex-wrap items-center gap-4 mb-5">
        <p className="note !m-0">Session expires: {state.expires}</p>
        <button className="secondary !w-auto" type="button" disabled={state.busy}
          onClick={() => { setPassword(''); setId(''); void client.logout(); }}>Log out</button>
      </div> : <form onSubmit={login} className="mb-5">
        <label htmlFor="operator-password">Local operator password</label>
        <input id="operator-password" type="password" autoComplete="off" value={password}
          maxLength={1024} disabled={state.busy} onChange={event => setPassword(event.target.value)} />
        <button className="primary" disabled={state.busy || !password}>Log in</button>
      </form>}
      <form onSubmit={event => { event.preventDefault(); void client.retrieve(id.trim()); }}>
        <label htmlFor="proposal-id">Known proposal ID</label>
        <input id="proposal-id" placeholder="Paste a proposal UUID" value={id} maxLength={36}
          disabled={!state.expires || state.busy} onChange={event => setId(event.target.value)} />
        <button className="secondary" disabled={!state.expires || state.busy || !id.trim()}>Fetch proposal</button>
      </form>
      <SafeActionDetails proposal={state.proposal} />
      <label className="flex items-start gap-3 mt-6">
        <input type="checkbox" className="!w-auto !m-0" checked={state.reviewed}
          disabled={!state.expires || !pending || state.busy}
          onChange={event => client.review(event.target.checked)} />
        I have reviewed every checklist item, the proposal ID, fingerprint and expiration.
      </label>
      <div className="flex flex-wrap gap-3 mt-6">
        <button className="primary" type="button" disabled={!client.canDecide()}
          onClick={() => client.beginDecision('approve')}>Approve</button>
        <button className="secondary !w-auto" type="button" disabled={!client.canDecide()}
          onClick={() => client.beginDecision('reject')}>Reject</button>
      </div>
      {state.confirmation && <div className="mt-5 p-4 border border-gray-600 rounded" role="group" aria-label="Confirm decision">
        <p>Confirm {state.confirmation === 'approve' ? 'approval and saving this exact checklist' : 'rejection without saving'}?</p>
        <p className="mono">{state.proposal?.fingerprint}</p>
        <div className="flex flex-wrap gap-3 mt-3"><button className="primary" type="button"
          disabled={state.busy || !client.canDecide()} onClick={() => { void client.confirmDecision(); }}>
          Confirm {state.confirmation}</button>
          <button className="secondary !w-auto" type="button" disabled={state.busy}
            onClick={() => client.cancelDecision()}>Cancel</button></div>
      </div>}
      {state.busy && <p role="status" className="note">Request in progress…</p>}
      <p className="note">Local operator actions only. Decisions are verified by the backend.
        Credentials and session tokens are never stored in browser storage.</p>
    </div>
  </section>;
}
