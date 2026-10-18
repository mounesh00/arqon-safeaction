'use client';
import { useEffect, useState, type FormEvent } from 'react';
import SafeActionPanel from './safe-action-panel';
type Run = { run_id: string; status: string; response?: string; task_name?: string; created_at?: string; updated_at?: string; error_code?: string; task?: string };
export default function Dashboard() {
  const [health, setHealth] = useState('Checking'); const [task, setTask] = useState('');
  const [busy, setBusy] = useState(false); const [error, setError] = useState('');
  const [runs, setRuns] = useState<Run[]>([]); const [selected, setSelected] = useState<Run | null>(null);
  const [lookup, setLookup] = useState(''); const [menu, setMenu] = useState(false);
  async function checkHealth() { try { const r = await fetch('/api/v1/health'); setHealth(r.ok ? 'Connected' : 'Offline'); } catch { setHealth('Offline'); } }
  useEffect(() => { void checkHealth(); }, []);
  async function submit(e: FormEvent) {
    e.preventDefault(); if (busy || !task.trim()) return; setBusy(true); setError('');
    try {
      const r = await fetch('/api/v1/agent/run', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ task }) });
      const data = await r.json();
      if (data.run_id) { const run = { ...data, task }; setRuns(previous => [run, ...previous].slice(0, 20)); setSelected(run); setLookup(data.run_id); }
      if (!r.ok) throw new Error(data.error || data.error_code || 'Request failed');
      setTask(''); setHealth('Connected');
    } catch (e) { setError(e instanceof Error ? e.message : 'Unable to connect'); }
    finally { setBusy(false); }
  }
  async function retrieve(e: FormEvent) {
    e.preventDefault(); setError('');
    if (!/^[0-9a-f-]{36}$/i.test(lookup)) { setError('Enter a valid run ID.'); return; }
    try { const r = await fetch('/api/v1/agent/runs/' + encodeURIComponent(lookup)); const data = await r.json(); if (!r.ok) throw new Error(data.error); setSelected(previous => ({ ...(previous?.run_id === data.run_id ? previous : {}), ...data })); }
    catch (e) { setError(e instanceof Error ? e.message : 'Could not retrieve run'); }
  }
  return <div className="shell">
    <aside className={menu ? 'sidebar open' : 'sidebar'}>
      <a className="brand" href="/"><span className="logo">A</span><span>arqon<span className="muted"> / OS</span></span></a>
      <div className="workspace"><span className="avatar">L</span><div>Local workspace<small>Personal environment</small></div><span className="dot" /></div>
      <p className="eyebrow">WORKSPACE</p><button className="nav active" onClick={() => { setSelected(null); setMenu(false); }}>◈ <span>Agent workspace</span><span className="key">01</span></button>
      <div className="sidebar-history"><p className="eyebrow">THIS SESSION <span>{runs.length.toString().padStart(2, '0')}</span></p>
        {runs.length === 0 ? <p className="muted text-sm">Your runs will appear here.</p> : runs.map(run => <button className="history" key={run.run_id} onClick={() => { setSelected(run); setLookup(run.run_id); setMenu(false); }}><span>{run.task?.slice(0, 32)}</span><small>{run.status} · {run.run_id.slice(0, 8)}</small></button>)}
      </div><div className="sidebar-bottom"><span className="dot" /> Local-only prototype<small>Arqon OS v0.1.0</small></div>
    </aside>
    <div className="main">
      <header><button className="mobile-menu" onClick={() => setMenu(!menu)} aria-expanded={menu} aria-label="Toggle sidebar">☰</button><span className="muted">Workspace <span className="mx-3">/</span></span><span>Agent console</span><button className="connection" onClick={checkHealth}><span className={health === 'Connected' ? 'dot' : 'dot offline'} />{health}</button></header>
      <main><div className="heading"><div><p className="eyebrow">BUILD WITH INTENT</p><h1>Your agent workspace.</h1><p className="muted">A clear view of every task, response, and run.</p></div><span className="badge">MOCK PROVIDER</span></div>
      <div className="dashboard"><section className="console" aria-label="Agent task console">
        <div className="panel-title"><span>◈ &nbsp; Assistant</span><span className="muted text-xs">Single-step agent</span></div>
        <div className="conversation" aria-live="polite">
        {selected ? <><div className="message-label">YOU</div><p className="user-message">{selected.task || 'Retrieved run metadata'}</p><div className="message-label accent">ARQON <span className="badge small">PROTOTYPE</span></div><p className="response">{selected.response || 'Response history is not stored. Only lifecycle metadata is available for this run.'}</p><div className="run-state">{selected.status} <span>↗ {selected.run_id.slice(0, 8)}</span></div></> : <div className="empty"><div className="orb">✳</div><h2>Start with a task.</h2><p>Explore the agent flow in a safe, local workspace.<br />This prototype returns deterministic mock output.</p><button className="suggestion" onClick={() => setTask('Explain what Arqon OS does')}>Explain what Arqon OS does <span>↗</span></button></div>}
        {busy && <p className="accent" role="status">◌ Running your task…</p>}</div>
        <form onSubmit={submit} className="composer"><label htmlFor="task" className="sr-only">Task for the agent</label><textarea id="task" placeholder="What would you like to work on?" value={task} onChange={e => setTask(e.target.value)} maxLength={4000} rows={3} disabled={busy} /><div className="composer-footer"><span>{task.length} / 4,000 <span className="desktop-hint"> · No tools enabled</span></span><button className="primary" disabled={busy || !task.trim()}>{busy ? 'Running…' : 'Run task'} <span>↑</span></button></div></form>
        <p className="footnote">Mock output · No live inference · Conversations are not persisted</p>
      </section><aside className="details"><div className="panel-title">Run inspector <span className="muted">↗</span></div><div className="details-body"><p className="eyebrow">EXECUTION DETAILS</p><dl><dt>Status</dt><dd><span className="badge">{selected?.status || 'Idle'}</span></dd><dt>Provider</dt><dd>MockModelProvider</dd><dt>Environment</dt><dd>Local / SQLite</dd><dt>Run ID</dt><dd className="mono">{selected?.run_id || 'Waiting for a run'}</dd><dt>Created</dt><dd>{selected?.created_at ? new Date(selected.created_at).toLocaleString() : 'Retrieve metadata to view'}</dd><dt>Updated</dt><dd>{selected?.updated_at ? new Date(selected.updated_at).toLocaleString() : '—'}</dd></dl><hr /><form onSubmit={retrieve}><label htmlFor="run-id">Retrieve a persisted run</label><input id="run-id" value={lookup} onChange={e => setLookup(e.target.value)} placeholder="Paste a run ID" /><button className="secondary" type="submit">Load run metadata <span>→</span></button></form><p className="note">Lifecycle metadata survives a restart. Responses and this session’s run list do not.</p></div></aside></div>
      <SafeActionPanel />
      {error && <div className="error" role="alert"><span>Unable to complete request: {error.replaceAll('_', ' ').toLowerCase()}</span><button aria-label="Dismiss error" onClick={() => setError('')}>×</button></div>}
      <footer><span><span className="dot" /> Permission-first by design</span><span>LOCAL DEVELOPMENT / V0.1</span></footer></main>
    </div></div>;
}
