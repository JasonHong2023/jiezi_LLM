// 芥子桌面 App 雛形：對話、稽核紀錄、狀態（唯讀；不操控作業系統）。
// Jiezi desktop prototype: chat, audit log, status (read-only; no OS control).
import { useEffect, useRef, useState } from "react";
import { getJSON, getKey, setKey, streamChat } from "./api.js";

const POLICIES = [
  ["jiezi", "芥子（本機優先，答不出來請教 Claude）"],
  ["jiezi-local", "只用本機"],
  ["jiezi-ask-claude", "直接請教 Claude"],
  ["jiezi-cloud", "雲端模型"],
];

function KeyGate({ onDone }) {
  const [k, setK] = useState("");
  return (
    <div className="card">
      <h2>連線到芥子 gateway</h2>
      <p>請貼上專案 <code>.env</code> 裡的 <code>JIEZI_GATEWAY_KEY</code>。金鑰只存在這個分頁，關掉就清除。</p>
      <input type="password" value={k} onChange={(e) => setK(e.target.value)} placeholder="JIEZI_GATEWAY_KEY" />
      <button onClick={() => { setKey(k); onDone(); }} disabled={!k.trim()}>連線</button>
    </div>
  );
}

function statusLine(m) {
  if (!m) return "";
  const who = m.tier === "memory" ? "記憶" : m.provider === "claude" ? "Claude" : m.tier === 3 ? "雲端" : "本機";
  const parts = [`第 ${m.tier} 層（${who}）`, m.model];
  if (m.tps) parts.push(`${m.tps} t/s`);
  if (m.latency_s != null) parts.push(`${m.latency_s} 秒`);
  if (m.confidence != null) parts.push(`信心 ${m.confidence}`);
  if (m.verification && m.verification !== "not_applicable") parts.push(`驗證 ${m.verification}`);
  if (m.escalation && m.escalation !== "policy") parts.push(`轉交原因 ${m.escalation}`);
  return parts.filter(Boolean).join(" · ");
}

function Chat() {
  const [policy, setPolicy] = useState("jiezi");
  const [msgs, setMsgs] = useState([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const abort = useRef(null);
  const end = useRef(null);

  useEffect(() => end.current?.scrollIntoView({ block: "end" }), [msgs]);
  useEffect(() => {
    const onKey = (e) => e.key === "Escape" && abort.current?.abort();  // 一鍵中止 / one-key stop
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  async function send() {
    const text = input.trim();
    if (!text || busy) return;
    const history = [...msgs.map(({ role, content }) => ({ role, content })), { role: "user", content: text }];
    setMsgs([...history, { role: "assistant", content: "", meta: null }]);
    setInput("");
    setBusy(true);
    setError("");
    abort.current = new AbortController();
    const t0 = performance.now();
    try {
      await streamChat(history.slice(-12), policy, {
        signal: abort.current.signal,
        onDelta: (t) => setMsgs((m) => { const c = [...m]; c[c.length - 1] = { ...c[c.length - 1], content: c[c.length - 1].content + t }; return c; }),
        onMeta: (meta) => setMsgs((m) => { const c = [...m]; c[c.length - 1] = { ...c[c.length - 1], meta }; return c; }),
      });
    } catch (e) {
      if (e.name === "AbortError") {
        setError(`已中止（${Math.round(performance.now() - t0)} ms）`);
      } else {
        setError(String(e.message || e));
      }
    } finally {
      setBusy(false);
      abort.current = null;
    }
  }

  return (
    <div className="chat">
      <div className="toolbar">
        <label>策略 <select value={policy} onChange={(e) => setPolicy(e.target.value)}>
          {POLICIES.map(([v, t]) => <option key={v} value={v}>{t}</option>)}
        </select></label>
        <button onClick={() => setMsgs([])} disabled={busy}>清除對話</button>
      </div>
      <div className="log">
        {msgs.length === 0 && <p className="muted">輸入問題後按 Enter；Shift+Enter 換行；Esc 或「中止」立刻停止。</p>}
        {msgs.map((m, i) => (
          <div key={i} className={`msg ${m.role}`}>
            <div className="body">{m.content || (busy && i === msgs.length - 1 ? "…" : "")}</div>
            {m.meta && <div className="meta">{statusLine(m.meta)}</div>}
          </div>
        ))}
        <div ref={end} />
      </div>
      {error && <div className="error">{error}</div>}
      <div className="composer">
        <textarea value={input} onChange={(e) => setInput(e.target.value)} rows={3}
          onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } }}
          placeholder="問芥子…" />
        {busy ? <button className="stop" onClick={() => abort.current?.abort()}>中止</button>
          : <button onClick={send} disabled={!input.trim()}>送出</button>}
      </div>
    </div>
  );
}

function Audit() {
  const [rows, setRows] = useState(null);
  const [error, setError] = useState("");
  const load = () => getJSON("/admin/trajectories?limit=100").then((d) => setRows(d.records)).catch((e) => setError(String(e.message)));
  useEffect(() => { load(); }, []);
  if (error) return <div className="error">{error}</div>;
  if (!rows) return <p className="muted">讀取中…</p>;
  return (
    <div>
      <div className="toolbar"><button onClick={load}>重新整理</button><span className="muted">最近 {rows.length} 筆（只存在本機）</span></div>
      <table>
        <thead><tr><th>時間</th><th>策略</th><th>由誰回答</th><th>問題</th><th>引用資料</th><th>可訓練</th></tr></thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.id}>
              <td>{r.at?.slice(5, 16).replace("T", " ")}</td><td>{r.policy}</td><td>{String(r.final_tier)}</td>
              <td className="q">{r.question}</td><td>{(r.sources || []).join("、")}</td>
              <td>{r.training_use === false ? "否" : r.training_use === true ? "是" : "待確認"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Status() {
  const [health, setHealth] = useState(null);
  const [doctor, setDoctor] = useState(null);
  const [error, setError] = useState("");
  useEffect(() => {
    fetch("/health").then((r) => r.json()).then(setHealth).catch((e) => setError(String(e)));
    getJSON("/admin/doctor").then(setDoctor).catch((e) => setError(String(e.message)));
  }, []);
  return (
    <div>
      {error && <div className="error">{error}</div>}
      {doctor && (
        <table>
          <thead><tr><th></th><th>項目</th><th>狀態</th><th>修復方法</th></tr></thead>
          <tbody>{doctor.checks.map(([item, state, detail, fix]) => (
            <tr key={item} className={state}><td>{state === "ok" ? "✓" : state === "warn" ? "!" : "✗"}</td><td>{item}</td><td>{detail}</td><td><code>{state !== "ok" ? fix : ""}</code></td></tr>
          ))}</tbody>
        </table>
      )}
      {health && <details><summary>gateway /health 原始資料</summary><pre>{JSON.stringify(health, null, 2)}</pre></details>}
    </div>
  );
}

export default function App() {
  const [tab, setTab] = useState("chat");
  const [ready, setReady] = useState(!!getKey());
  return (
    <div className="app">
      <header>
        <h1>芥子 Jiezi</h1>
        <nav>
          {[["chat", "對話"], ["audit", "稽核紀錄"], ["status", "狀態"]].map(([k, t]) => (
            <button key={k} className={tab === k ? "on" : ""} onClick={() => setTab(k)}>{t}</button>
          ))}
          {ready && <button onClick={() => { setKey(""); setReady(false); }}>登出</button>}
        </nav>
      </header>
      <main>
        {!ready ? <KeyGate onDone={() => setReady(true)} /> : tab === "chat" ? <Chat /> : tab === "audit" ? <Audit /> : <Status />}
      </main>
      <footer className="muted">唯讀雛形：不會操控你的電腦。所有對話只經過本機 gateway（127.0.0.1）。</footer>
    </div>
  );
}
