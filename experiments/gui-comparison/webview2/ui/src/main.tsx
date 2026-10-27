import React, { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { flushSync } from 'react-dom';
import { Bridge } from './bridge';
import { Profile, ValidProfile, type Page, type Probe, type Snapshot } from './contracts';
import { Tree, restoreAnchor } from './tree';
import './style.css';

const bridge = new Bridge(window.chrome.webview);
const initial: Profile = { source: 0, file: '', scenarios: [] };
const empty = new Tree([]);
let readProbe: () => Probe & { reference_ids: string[] };
let receiveSnapshot: (s: Snapshot) => void;
let receiveDraft: (p: Profile) => void;
function App() {
  const [snapshot, setSnapshot] = useState<Snapshot>();
  const [tree, setTree] = useState(empty);
  const [page, setPage] = useState<Page>('monitor');
  const [draft, setDraft] = useState<Profile>(initial);
  const [errors, setErrors] = useState<string[]>([]);
  const [expanded, setExpanded] = useState(new Set<string>());
  const [dark, setDark] = useState(false);
  const [scroll, setScroll] = useState(0);
  const [height, setHeight] = useState(320);
  const viewport = useRef<HTMLDivElement>(null);
  const image = useRef<HTMLImageElement>(null);
  const rows = useMemo(() => tree.flatten(expanded), [tree, expanded]);
  const previousRows = useRef(rows);
  const builds = useRef(0), updates = useRef(0), busy = useRef(0);
  const [status, setStatus] = useState('Connecting to native host…');
  const metrics = useMemo(() => new Map(snapshot?.metrics.map(m => [m[0], m]) ?? []), [snapshot?.metrics]);
  const dirty = !!snapshot && JSON.stringify(draft) !== JSON.stringify(snapshot.profile);
  const wanted = useMemo(() => page === 'diagnostics' ? rows.filter(r => r.node.kind === 3 && expanded.has(r.node.id)).slice(0, 16).map(r => r.node.id) : [], [page, rows, expanded]);
  const invoke = useCallback(async (command: string, args: unknown = {}) => {
    busy.current++;
    try { return await bridge.request(command, args); }
    catch (error) { setErrors([String(error)]); return undefined; }
    finally { busy.current--; }
  }, []);
  const edit = (p: Profile) => { setDraft(p); void invoke('draft', { profile: p }); };
  const cancelHold = useCallback(() => { void invoke('holdCancel'); }, [invoke]);
  const navigate = (next: Page) => { cancelHold(); setPage(next); void invoke('page', { page: next }); };
  useEffect(() => {
    const blur = () => cancelHold();
    const visibility = () => { if (document.hidden) cancelHold(); };
    window.addEventListener('blur', blur); document.addEventListener('visibilitychange', visibility);
    return () => { window.removeEventListener('blur', blur); document.removeEventListener('visibilitychange', visibility); };
  }, [cancelHold]);
  useLayoutEffect(() => {
    if (!viewport.current) return;
    const element = viewport.current;
    const observer = new ResizeObserver(() => setHeight(element.clientHeight));
    observer.observe(element); return () => observer.disconnect();
  }, [page]);
  useLayoutEffect(() => {
    if (viewport.current && previousRows.current !== rows) {
      viewport.current.scrollTop = restoreAnchor(previousRows.current, rows, scroll);
      setScroll(viewport.current.scrollTop);
    }
    previousRows.current = rows;
  }, [rows]);
  receiveDraft = p => { setDraft(p); setErrors([]); };
  receiveSnapshot = s => {
    if (s.nodes) { const next = new Tree(s.nodes); setTree(next); setExpanded(e => next.retain(e)); builds.current++; }
    if (page === 'diagnostics') updates.current++;
    setSnapshot(s); setStatus(`State ${s.sequence} · resets ${s.resets} · ${s.running ? 'Running' : 'Stopped'}`);
  };
  readProbe = () => ({ page, expanded: expanded.has(tree.nodes.find(n => n.kind === 3)?.id ?? ''), dirty,
    errors: errors.length > 0, references: wanted.filter(id => snapshot?.references[id]).length,
    reference_ids: wanted, draft_count: draft.scenarios.length, scroll: Math.round(viewport.current?.scrollTop ?? scroll),
    busy: busy.current > 0, rendered_rows: document.querySelectorAll('[role=treeitem]').length, tree_builds: builds.current, value_updates: updates.current });
  bridge.onTestAction = action => {
    // The native contract drives the same DOM handlers as interactive use.
    const click = (id: string) => document.getElementById(id)?.click();
    const input = (id: string, value: string) => {
      const element = document.getElementById(id) as HTMLInputElement;
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(element, value);
      element.dispatchEvent(new Event('input', { bubbles: true }));
    };
    const open = (id: string | undefined) => { if (id) setExpanded(e => new Set([...e, ...tree.path(id)])); };
    switch (action) {
      case 0: click('monitor'); break; case 1: click('diagnostics'); break; case 2: click('profile'); break;
      case 3: open(tree.nodes.find(n => n.kind === 3)?.id); break;
      case 4: setExpanded(e => { const next = new Set(e); next.delete(tree.nodes.find(n => n.kind === 3)?.id ?? ''); return next; }); break;
      case 5: click('mutate'); break;
      case 6: input('name-0', ''); break;
      case 7: input('name-0', 'Edited scenario'); queueMicrotask(() => { click('enabled-0'); queueMicrotask(() => input('note-0', 'Maintenance note')); }); break;
      case 8: click('apply'); break; case 9: click('add'); break;
      case 10: click(`remove-${draft.scenarios.length - 1}`); break;
      case 11: click('enabled-0'); queueMicrotask(() => click('fresh')); break;
      case 12: click('browse'); break; case 13: click('discard'); break;
      case 14: document.getElementById('reset')?.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true, pointerId: 1 })); break;
      case 15: document.getElementById('reset')?.dispatchEvent(new PointerEvent('pointerup', { bubbles: true, pointerId: 1 })); break;
      case 16: window.dispatchEvent(new Event('blur')); break;
      case 17: click('theme'); break; case 18: void invoke('resize'); break;
      case 19: click('start'); break; case 20: click('stop'); break;
      case 21:
        setExpanded(e => new Set([...e, ...tree.nodes.filter(n => n.kind === 0).map(n => n.id)]));
        requestAnimationFrame(() => { if (viewport.current) { viewport.current.scrollTop = 64; setScroll(64); } }); break;
      case 22: open(tree.nodes.at(-1)?.id); break;
    }
  };
  const from = Math.max(0, Math.floor(scroll / 32) - 4), to = Math.min(rows.length, Math.ceil((scroll + height) / 32) + 4);
  const apply = async () => {
    const parsed = ValidProfile.safeParse(draft);
    if (!parsed.success) { setErrors(parsed.error.issues.map(i => i.message)); return; }
    const result = await invoke('apply', { profile: parsed.data }) as { errors: string[] } | undefined;
    if (result) setErrors(result.errors);
  };
  return <main data-theme={dark ? 'dark' : 'light'}>
    <header><strong>DivergenceSplitter <small>WebView2 comparison</small></strong><span>{status}</span></header>
    <div className="toolbar">
      <button id="start" onClick={() => void invoke('running', { value: true })}>Start</button>
      <button id="stop" onClick={() => { cancelHold(); void invoke('running', { value: false }); }}>Stop</button>
      <button id="reset" onPointerDown={e => { if (e.isTrusted) e.currentTarget.setPointerCapture(e.pointerId); void invoke('holdPress'); }} onPointerUp={cancelHold} onPointerCancel={cancelHold} onLostPointerCapture={cancelHold} onBlur={cancelHold}>Hold 2s: Reset All</button>
      <button id="mutate" onClick={() => void invoke('mutate')}>Add/remove diagnostic branch</button>
      <button id="theme" onClick={() => setDark(d => !d)}>Light / dark</button>
      <button onClick={() => void invoke('reload')}>Reload UI</button>
    </div>
    <nav>{(['monitor', 'diagnostics', 'profile'] as Page[]).map(p => <button id={p} key={p} aria-pressed={page === p} onClick={() => navigate(p)}>{p === 'profile' ? 'Configuration' : p}</button>)}</nav>
    {page === 'monitor' && <section className="monitor"><div className="cards">{snapshot?.profile.scenarios.map(s => {
      const root = snapshot.roots.find(n => n.label === s.name), m = root && metrics.get(root.id);
      return <article key={s.id}><h2>{s.name}</h2><p>{s.enabled ? snapshot.running ? 'Running' : 'Stopped' : 'Disabled'} · :{s.port}</p><p>{s.note}</p><output>{m?.[1].toFixed(3) ?? '—'}</output></article>;
    })}</div><img ref={image} className="preview" alt="Latest mock preview, 15Hz intake cap" src={snapshot?.frame?.jpeg} /></section>}
    {page === 'diagnostics' && <section className="diagnostics"><p>{tree.nodes.length.toLocaleString()} nodes · {rows.length} expanded rows · {to - from} DOM rows</p>
      <div role="tree" className="tree" ref={viewport} onScroll={e => setScroll(e.currentTarget.scrollTop)}>
        <div style={{ height: rows.length * 32, position: 'relative' }}>
          {rows.slice(from, to).map(({ node, depth }, i) => <div key={node.id} role="treeitem" aria-level={depth + 1} aria-expanded={expanded.has(node.id)} className="tree-row" style={{ top: (from + i) * 32, paddingLeft: depth * 22 }}>
            <button onClick={() => setExpanded(e => { const next = new Set(e); if (!next.delete(node.id)) next.add(node.id); return next; })}>{expanded.has(node.id) ? '▾' : '▸'}</button>
            <span title={node.note}>{node.label}{node.note && ` · ${node.note}`}</span><output>{metrics.get(node.id)?.[1].toFixed(3)} {metrics.get(node.id)?.[4] ? metrics.get(node.id)?.[2] ? 'active' : 'waiting' : 'disabled'}</output>
          </div>)}
        </div>
      </div><div className="references">{wanted.map(id => <img key={id} alt={`Reference ${id}`} width="160" height="90" src={snapshot?.references[id]} />)}</div>
      {wanted.length === 16 && <p>Reference preview is limited to 16 expanded detectors.</p>}
    </section>}
    {page === 'profile' && <section className="configuration"><p>{dirty ? 'Unapplied changes' : 'Applied settings'}</p>
      <div className="toolbar"><label>Input <select value={draft.source} onChange={e => edit({ ...draft, source: Number(e.target.value) })}><option value="0">Synthetic camera</option><option value="1">Synthetic file</option></select></label>
        <input aria-label="Input file" value={draft.file} onInput={e => edit({ ...draft, file: e.currentTarget.value })} /><button id="browse" onClick={async () => { const p = await invoke('browse') as Profile | undefined; if (p) setDraft(p); }}>Browse…</button></div>
      <div className="form-rows">{draft.scenarios.map((s, index) => <fieldset key={s.id}><legend>Scenario {s.id}</legend>
        <label>Name<input id={`name-${index}`} value={s.name} onInput={e => edit({ ...draft, scenarios: draft.scenarios.map((v, i) => i === index ? { ...v, name: e.currentTarget.value } : v) })} /></label>
        <label>Port<input type="number" min="1" max="65535" value={s.port} onInput={e => edit({ ...draft, scenarios: draft.scenarios.map((v, i) => i === index ? { ...v, port: Number(e.currentTarget.value) } : v) })} /></label>
        <label><input id={`enabled-${index}`} type="checkbox" checked={s.enabled} onChange={e => edit({ ...draft, scenarios: draft.scenarios.map((v, i) => i === index ? { ...v, enabled: e.target.checked } : v) })} />Enabled</label>
        <label>Note<input id={`note-${index}`} value={s.note} onInput={e => edit({ ...draft, scenarios: draft.scenarios.map((v, i) => i === index ? { ...v, note: e.currentTarget.value } : v) })} /></label>
        <button id={`remove-${index}`} onClick={async () => { const p = await invoke('remove', { id: s.id }) as Profile | undefined; if (p) setDraft(p); }}>Remove</button>
      </fieldset>)}</div>
      <div className="toolbar"><button id="add" onClick={async () => { const p = await invoke('add') as Profile | undefined; if (p) setDraft(p); }}>Add Scenario</button>
        <button id="apply" onClick={() => void apply()}>Apply</button><button id="discard" onClick={async () => { const p = await invoke('discard') as Profile | undefined; if (p) { setDraft(p); setErrors([]); } }}>Discard</button>
        <button id="fresh" onClick={async () => { const p = await invoke('fresh') as Profile | undefined; if (p) setDraft(p); }}>New Profile</button></div>
    </section>}
    <div role="alert">{errors.join('; ')}</div>
  </main>;
}
createRoot(document.getElementById('root')!).render(<App />);
bridge.onSnapshot = async snapshot => {
  flushSync(() => receiveSnapshot(snapshot));
  await Promise.all([...document.images].filter(i => i.src).map(i => i.decode().catch(() => { throw new Error('JPEG decode failed'); })));
  await new Promise<void>(resolve => {
    // A minimized renderer can suspend animation frames. Never let visibility grow a queue.
    const fallback = setTimeout(resolve, 250);
    requestAnimationFrame(() => { clearTimeout(fallback); resolve(); });
  });
  return readProbe();
};
// React must commit before the native ready handshake sends the initial snapshot.
requestAnimationFrame(() => { void bridge.request('ready').then(p => flushSync(() => receiveDraft(Profile.parse(p)))).catch(error => { document.body.textContent = String(error); }); });
