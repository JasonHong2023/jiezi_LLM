// 筆記本分頁（add-notebooks）：來源管理、引用問答、原文檢視、查證後存記憶
// Notebooks tab: sources, cited Q&A, source viewer with highlighted passages, verified saving to memory
import { useEffect, useRef, useState } from "react";
import { BASE, getKey } from "./api.js";

const auth = () => ({ Authorization: `Bearer ${getKey()}` });

async function call(path, { method = "GET", json, form, timeout = 60000 } = {}) {
  const headers = auth();
  let body;
  if (json !== undefined) { headers["Content-Type"] = "application/json"; body = JSON.stringify(json); }
  if (form) body = form;
  const r = await fetch(BASE + path, { method, headers, body, signal: AbortSignal.timeout(timeout) });
  const text = await r.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch { data = null; }
  if (!r.ok) throw new Error(data?.error?.message || `${r.status} ${text.slice(0, 200)}`);
  return data;
}

// 回答裡的 [n] 變成可點的按鈕 / turn [n] markers into buttons
function Cited({ text, citations, onCite }) {
  const byN = Object.fromEntries((citations || []).map((c) => [c.n, c]));
  const parts = String(text || "").split(/(\[\d{1,2}\])/g);
  return <div className="body">{parts.map((p, i) => {
    const m = p.match(/^\[(\d{1,2})\]$/);
    if (m && byN[m[1]]) {
      const c = byN[m[1]];
      return <button key={i} className="cite" title={`《${c.title}》${c.quote}`} onClick={() => onCite(c)}>{m[1]}</button>;
    }
    return <span key={i}>{p}</span>;
  })}</div>;
}

function MemoryState({ nb, item, onFix, onSaved }) {
  const mem = item.meta?.memory;
  const [busy, setBusy] = useState(false);
  if (!mem) return null;
  if (mem.saved) return <div className="muted mem ok">✓ 已查證並存進記憶</div>;
  if (mem.skipped === "not_found") return <div className="muted mem">來源裡找不到，沒有存進記憶</div>;
  if (!mem.findings?.length) return null;
  return <div className="mem warn">
    <div>查證發現（沒有存進記憶）：</div>
    <ul>{mem.findings.map((f, i) => <li key={i}>{f.message}</li>)}</ul>
    <button disabled={busy} onClick={async () => {
      setBusy(true);
      try { const r = await call(`/v1/notebooks/${nb.id}/remember`, { method: "POST", json: { trajectory_id: item.tid } });
        if (r.saved) onSaved(); } finally { setBusy(false); }
    }}>仍要存</button> <button onClick={onFix}>我來更正</button>
  </div>;
}

export default function Notebooks() {
  const [list, setList] = useState([]);
  const [nb, setNb] = useState(null);          // 目前的筆記本（含 sources）/ current notebook
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [paste, setPaste] = useState("");
  const [qa, setQa] = useState([]);            // [{q, a, meta, tid}]
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [view, setView] = useState(null);      // {source, start, end}
  const picker = useRef(null);
  const mark = useRef(null);

  const load = () => call("/v1/notebooks").then((d) => setList(d.data)).catch((e) => setError(e.message));
  const open = (id) => call(`/v1/notebooks/${id}`).then((d) => { setNb(d); setQa([]); setView(null); })
    .catch((e) => setError(e.message));
  useEffect(() => { load(); }, []);
  useEffect(() => { mark.current?.scrollIntoView({ block: "center" }); }, [view]);

  const run = async (label, fn) => {
    setBusy(label); setError("");
    try { await fn(); } catch (e) { setError(e.message); } finally { setBusy(""); }
  };
  const refresh = () => open(nb.id).then(load);

  const create = () => run("建立中", async () => {
    const d = await call("/v1/notebooks", { method: "POST", json: { name } });
    setName(""); await load(); await open(d.id);
  });
  const addFiles = (files) => run("加入來源中（大檔或音檔要一些時間）", async () => {
    for (const f of files) {
      const form = new FormData(); form.append("file", f, f.name);
      await call(`/v1/notebooks/${nb.id}/sources`, { method: "POST", form, timeout: 30 * 60000 });
    }
    await refresh();
  });
  const addUrl = () => run("讀取網頁中", async () => {
    await call(`/v1/notebooks/${nb.id}/sources`, { method: "POST", json: { url } }); setUrl(""); await refresh();
  });
  const addText = () => run("加入中", async () => {
    await call(`/v1/notebooks/${nb.id}/sources`, { method: "POST", json: { text: paste, title: paste.slice(0, 20) } });
    setPaste(""); await refresh();
  });
  const removeSource = (s) => run("刪除中", async () => {
    if (!confirm(`刪除來源「${s.title}」？`)) return;
    await call(`/v1/notebooks/${nb.id}/sources/${s.id}`, { method: "DELETE" }); await refresh();
  });
  const removeNotebook = () => run("刪除中", async () => {
    if (!confirm(`刪除筆記本「${nb.name}」和它的所有來源？`)) return;
    await call(`/v1/notebooks/${nb.id}`, { method: "DELETE" }); setNb(null); await load();
  });
  const cite = (c) => run("", async () => {
    const s = await call(`/v1/notebooks/${nb.id}/sources/${c.source_id}`);
    setView({ source: s, start: c.start, end: c.end });
  });
  const makeNote = (kind, label) => run(`產生${label}中（每段先整理重點再彙整，段落多時要幾分鐘）`, async () => {
    const r = await call(`/v1/notebooks/${nb.id}/notes`, { method: "POST", json: { kind }, timeout: 60 * 60000 });
    setQa((cur) => [...cur, { q: `【${r.label}】${r.sampled ? `（依 ${r.chunks} 段中的 ${r.used} 段取樣）` : ""}`, a: r.answer,
      meta: { citations: r.citations } }]);
    await refresh();
  });
  const ask = () => run("思考中", async () => {
    const q = input.trim();
    if (!q) return;
    setInput("");
    const history = qa.slice(-3).flatMap((x) => [{ role: "user", content: x.q }, { role: "assistant", content: x.a }]);
    const r = await call("/v1/chat/completions", { method: "POST", timeout: 15 * 60000, json: {
      model: "jiezi", jiezi_notebook: nb.id, messages: [...history, { role: "user", content: q }] } });
    const m = r.jiezi?.notebook || {};
    setQa((cur) => [...cur, { q, a: m.answer ?? r.choices?.[0]?.message?.content ?? "", meta: m,
      tid: r.jiezi?.trajectory_id }]);
  });

  return <div className="notebooks">
    <aside className="nb-list">
      <div className="nb-new"><input value={name} placeholder="新筆記本名稱" onChange={(e) => setName(e.target.value)} />
        <button disabled={!name.trim() || !!busy} onClick={create}>建立</button></div>
      <ul>{list.map((n) => <li key={n.id}><button className={nb?.id === n.id ? "on" : ""} onClick={() => open(n.id)}>
        {n.name} <span className="muted">（{n.sources}）</span></button></li>)}</ul>
      {nb && <>
        <h3>來源</h3>
        <ul className="sources">{nb.sources.map((s) => <li key={s.id} title={s.origin}>
          <span>{{ file: "📄", url: "🌐", text: "📝", audio: "🎙", note: "🗒" }[s.kind] || "📄"} {s.title}</span>
          {s.trust?.injection && <span className="warn" title={s.trust.injection.join(", ")}> ⚠</span>}
          <span className="muted"> {s.chars} 字</span>
          <button aria-label={`刪除 ${s.title}`} onClick={() => removeSource(s)}>×</button></li>)}</ul>
        <input ref={picker} type="file" multiple hidden onChange={(e) => { addFiles([...e.target.files]); e.target.value = ""; }} />
        <button disabled={!!busy} onClick={() => picker.current?.click()}>加入檔案／音檔</button>
        <div className="nb-new"><input value={url} placeholder="https://…" onChange={(e) => setUrl(e.target.value)} />
          <button disabled={!url.trim() || !!busy} onClick={addUrl}>加入網頁</button></div>
        <textarea rows={3} value={paste} placeholder="貼上文字當來源" onChange={(e) => setPaste(e.target.value)} />
        <button disabled={!paste.trim() || !!busy} onClick={addText}>加入文字</button>
        <p><button className="danger" onClick={removeNotebook}>刪除這本筆記本</button></p>
      </>}
    </aside>
    <section className="nb-chat">
      {!nb ? <p className="muted">建立或選一本筆記本，加入來源後就能提問。回答只根據來源，每句都附出處；查證沒問題的問答會自動存進記憶。</p> : <>
        <h2>{nb.name}</h2>
        <div className="toolbar">
          {[["summary", "摘要"], ["faq", "常見問答"], ["study_guide", "學習指南"]].map(([k, t]) =>
            <button key={k} disabled={!!busy || !nb.sources.length} onClick={() => makeNote(k, t)}>產生{t}</button>)}
          <span className="muted">產生的筆記會加進來源，之後也能被引用</span>
        </div>
        <div className="log">{qa.map((x, i) => <div key={i}>
          <div className="msg user"><div className="body">{x.q}</div></div>
          <div className="msg assistant">
            <Cited text={x.a} citations={x.meta.citations} onCite={cite} />
            {x.meta.citations?.length > 0 && <div className="refs"><div className="refs-title">出處</div>
              {x.meta.citations.map((c) => <div key={c.n} className="ref"><button className="cite" onClick={() => cite(c)}>{c.n}</button>
                《{c.title}》<span className="muted">{c.quote.slice(0, 60)}…</span></div>)}</div>}
            <MemoryState nb={nb} item={x} onFix={() => setInput("不對，")}
              onSaved={() => setQa((cur) => cur.map((y) => y === x ? { ...y, meta: { ...y.meta, memory: { saved: true } } } : y))} />
          </div></div>)}</div>
        {error && <div className="error">{error}</div>}
        {busy && <div className="muted">{busy}…</div>}
        <div className="composer">
          <textarea rows={2} value={input} onChange={(e) => setInput(e.target.value)} placeholder="問這本筆記本…（Enter 送出）"
            onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); ask(); } }} />
          <button disabled={!input.trim() || !!busy || !nb.sources.length} onClick={ask}>送出</button>
        </div>
      </>}
      {!nb && error && <div className="error">{error}</div>}
    </section>
    <aside className="nb-view">
      {view ? <>
        <h3>《{view.source.title}》</h3>
        <div className="source-text">{view.source.text.slice(0, view.start)}
          <mark ref={mark}>{view.source.text.slice(view.start, view.end)}</mark>
          {view.source.text.slice(view.end)}</div>
      </> : <p className="muted">點回答裡的編號，這裡會顯示原文並標出那一段。</p>}
    </aside>
  </div>;
}
