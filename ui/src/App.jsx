// 芥子桌面 App 雛形：對話、稽核紀錄、狀態（唯讀；不操控作業系統）。
// Jiezi desktop prototype: chat, audit log, status (read-only; no OS control).
import { useEffect, useRef, useState } from "react";
import { BASE, THEME_LABEL, firstPhase, getJSON, getKey, loadInputs, loadTheme, nextTheme, phaseAfter, phaseLabel, readDocument, recallInput, rememberInput, setKey, stepText, streamChat, withDocuments } from "./api.js";

const MAX_DOC_CHARS = 1500000;  // 附著文件的總字數上限（和 jiezi chat 相同）/ same cap as jiezi chat
const MAX_IMAGE_BYTES = 5 * 1024 * 1024;  // 和 jiezi chat 的 /image 相同 / same cap as /image in chat

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
  const who = m.tier === "memory" ? "記憶" : m.tier === 2 ? `本機＋${m.feedback_from === "claude" ? "Claude" : "雲端"}回饋`
    : m.provider === "claude" ? "Claude" : m.tier === 3 ? "雲端" : "本機";
  const parts = [`第 ${m.tier} 層（${who}）`, m.model];
  if (m.tps) parts.push(`${m.tps} t/s`);
  if (m.latency_s != null) parts.push(`${m.latency_s} 秒`);
  if (m.confidence != null) parts.push(`信心 ${m.confidence}`);
  if (m.verification && m.verification !== "not_applicable") parts.push(`驗證 ${m.verification}`);
  if (m.escalation && m.escalation !== "policy") parts.push(`轉交原因 ${m.escalation}`);
  return parts.filter(Boolean).join(" · ");
}

// 開場動畫「芥子納須彌」（和終端機版同一個意境）/ Opening animation, same idea as the terminal
const SEED_FRAMES = [
  ["", "", "·", "", ""],
  ["", "", "( · )", "", ""],
  ["", "˙   ˙   ˙", "(  ●  )", "˙   ˙   ˙", ""],
  ["          ✦", "      ▲", "    ▲▲▲", "～～( ● )～～", ""],
  ["   ✧          ✦", "      ▲    ▲▲", "    ▲▲▲▲  ▲▲▲▲", "～～～～( ● )～～～～", ""],
  ["✦      ✧    ☾     ✦", "    ▲     ▲▲▲", "  ▲▲▲▲  ▲▲▲▲▲▲  ▲▲", "～～～～～～( ● )～～～～～～", ""],
];
const WORLD = SEED_FRAMES[SEED_FRAMES.length - 1].slice(0, 4);
const TITLE = "芥子納須彌";
for (let n = 1; n <= TITLE.length; n++) SEED_FRAMES.push([...WORLD, TITLE.slice(0, n)]);
SEED_FRAMES.push([...WORLD, "芥子納須彌 —— 一粒芥子，裝下一整個世界"]);

function SeedBanner() {
  const [f, setF] = useState(0);
  useEffect(() => {
    const t = setInterval(() => setF((x) => { if (x >= SEED_FRAMES.length - 1) { clearInterval(t); return x; } return x + 1; }), 200);
    return () => clearInterval(t);
  }, []);
  return <pre className="seed" aria-label="芥子納須彌">{SEED_FRAMES[f].join("\n")}</pre>;
}

const SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏";

function Progress({ phase, t0, events }) {
  const [now, setNow] = useState(performance.now());
  useEffect(() => { const t = setInterval(() => setNow(performance.now()), 100); return () => clearInterval(t); }, []);
  const s = (now - t0) / 1000;
  return <div className="progress"><span className="spin">{SPINNER[Math.floor(s * 10) % SPINNER.length]}</span>
    {phaseLabel(phase, s, events)}… {Math.floor(s)} 秒</div>;
}

function Chat() {
  const [policy, setPolicy] = useState("jiezi");
  const [msgs, setMsgs] = useState([]);
  const [input, setInput] = useState("");
  const inputs = useRef(loadInputs());   // ↑／↓ 輸入紀錄 / input history
  const recall = useRef({ pos: null, draft: "" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [docs, setDocs] = useState([]);       // 附著的文件，每一題都帶 / attached documents, sent with every question
  const [reading, setReading] = useState("");
  const [agent, setAgent] = useState(false);  // 唯讀檔案代理（add-agent-readonly）/ read-only file agent
  const [progress, setProgress] = useState(null);
  const [image, setImage] = useState(null);   // 下一題附的圖 {name, url}（使用者 2026-11-18）/ image for the next question  // 送出後的狀態 / live status {phase, t0, events}
  const abort = useRef(null);
  const end = useRef(null);
  const picker = useRef(null);

  async function attach(files) {
    setError("");
    for (const f of files) {
      if (f.type?.startsWith("image/")) {     // 圖片附在下一題 / images go with the next question
        if (f.size > MAX_IMAGE_BYTES) { setError(`${f.name}：圖片超過 5 MB`); continue; }
        const url = await new Promise((res, rej) => { const r = new FileReader(); r.onload = () => res(r.result); r.onerror = rej; r.readAsDataURL(f); });
        setImage({ name: f.name || "貼上的圖片", url });
        continue;
      }
      setReading(f.name);
      try {
        const d = await readDocument(f);
        setDocs((cur) => {
          const rest = cur.filter((x) => x.name !== d.name);  // 同名視為更新 / same name replaces
          if (rest.reduce((n, x) => n + x.chars, 0) + d.chars > MAX_DOC_CHARS) {
            setError(`附著的文件合計超過 ${MAX_DOC_CHARS} 字，請先移除一些`);
            return cur;
          }
          return [...rest, d];
        });
        if (d.warnings?.length) setError(`${d.name}：${d.warnings.join("；")}`);
      } catch (e) {
        setError(`${f.name}：${e.message || e}`);
      }
    }
    setReading("");
  }

  useEffect(() => end.current?.scrollIntoView({ block: "end" }), [msgs]);
  useEffect(() => {
    const onKey = (e) => e.key === "Escape" && abort.current?.abort();  // 一鍵中止 / one-key stop
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  async function send() {
    const text = input.trim();
    if (!text || busy) return;
    inputs.current = rememberInput(inputs.current, text);
    recall.current = { pos: null, draft: "" };
    const history = [...msgs.map(({ role, content }) => ({ role, content })), { role: "user", content: text }];
    // 畫面與歷史只留問題；文件在送出時包進最新的問題，gateway 才能依這一題重新挑段落
    // The log keeps the bare question; documents are wrapped around the latest question when sending
    const outgoing = [...history.slice(-12)];
    const asked = withDocuments(text, docs);
    outgoing[outgoing.length - 1] = { role: "user", content: image
      ? [{ type: "text", text: asked }, { type: "image_url", image_url: { url: image.url } }] : asked };
    if (image) history[history.length - 1] = { role: "user", content: `${text}  [圖片：${image.name}]` };
    setImage(null);
    setMsgs([...history, { role: "assistant", content: "", meta: null, steps: [] }]);
    setInput("");
    setBusy(true);
    setError("");
    abort.current = new AbortController();
    const t0 = performance.now();
    setProgress({ phase: image ? "看圖中" : firstPhase(policy, { docs: docs.length > 0, agent }), t0, events: 0 });
    const bump = (kind, value) => setProgress((p) => p && { ...p, phase: phaseAfter(kind, value, p.phase), events: p.events + 1 });
    try {
      await streamChat(outgoing, policy, {
        signal: abort.current.signal,
        agent,
        onThinking: () => bump("thinking"),
        onProgress: (stage) => bump("progress", stage),
        onStep: (ev) => bump("agent", ev) || setMsgs((m) => {
          const c = [...m]; const last = c[c.length - 1];
          // 同一步「進行中」換成結果 / a running step is replaced by its outcome
          const steps = (last.steps || []).filter((s) => !(s.step === ev.step && s.status === "running" && ev.status !== "running"));
          c[c.length - 1] = { ...last, steps: [...steps, ev] }; return c;
        }),
        onDelta: (t) => bump("delta", t) || setMsgs((m) => { const c = [...m]; c[c.length - 1] = { ...c[c.length - 1], content: c[c.length - 1].content + t }; return c; }),
        onMeta: (meta) => setMsgs((m) => { const c = [...m]; c[c.length - 1] = { ...c[c.length - 1], meta }; return c; }),
      });
    } catch (e) {
      if (e.name === "AbortError") {
        setError(`已中止（${Math.round(performance.now() - t0)} ms）`);
      } else {
        setError(String(e.message || e));
      }
    } finally {
      setProgress(null);
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
        <button onClick={() => { setMsgs([]); setDocs([]); }} disabled={busy}>清除對話</button>
        <input ref={picker} type="file" multiple hidden
          accept="image/png,image/jpeg,image/webp,image/gif,.pdf,.docx,.pptx,.xlsx,.doc,.ppt,.xls,.rtf,.odt,.odp,.ods,.html,.htm,.txt,.md,.csv,.json,.log"
          onChange={(e) => { attach([...e.target.files]); e.target.value = ""; }} />
        <button onClick={() => picker.current?.click()} disabled={busy || !!reading}>附加檔案／圖片</button>
        <label title="讓芥子列出、尋找、讀取你授權的資料夾（scripts/jiezi agent grant 資料夾）；只能讀，不能改">
          <input type="checkbox" checked={agent} onChange={(e) => setAgent(e.target.checked)} disabled={busy} /> 讀我的檔案（唯讀）
        </label>
      </div>
      {(docs.length > 0 || reading || image) && (
        <div className="docs">
          {image && <span className="doc">🖼 {image.name}（下一題）
            <button aria-label={`移除 ${image.name}`} onClick={() => setImage(null)} disabled={busy}>×</button></span>}
          {docs.map((d) => (
            <span key={d.name} className="doc" title={d.ocr_pages ? `OCR ${d.ocr_pages} 頁` : ""}>
              {d.name}（{d.chars} 字）
              <button aria-label={`移除 ${d.name}`} onClick={() => setDocs((c) => c.filter((x) => x !== d))} disabled={busy}>×</button>
            </span>
          ))}
          {reading && <span className="muted">讀取中：{reading}…</span>}
          {docs.length > 0 && <span className="muted">文件會跟著每一題送出，可以一直追問</span>}
        </div>
      )}
      <div className="log">
        {msgs.length === 0 && <SeedBanner />}
        {msgs.map((m, i) => (
          <div key={i} className={`msg ${m.role}`}>
            {m.steps?.length > 0 && <ul className="steps">{m.steps.map((s, j) =>
              <li key={j} className={s.status}>{stepText(s)}</li>)}</ul>}
            <div className="body">{m.content}</div>
            {busy && progress && i === msgs.length - 1 && <Progress {...progress} />}
            {m.meta && <div className="meta">{statusLine(m.meta)}</div>}
            {m.meta?.injection?.suspected?.length > 0 &&
              <div className="warn">注意：{m.meta.injection.warning}（{m.meta.injection.suspected.join("、")}）</div>}
          </div>
        ))}
        <div ref={end} />
      </div>
      {error && <div className="error">{error}</div>}
      <div className="composer">
        <textarea value={input} onChange={(e) => setInput(e.target.value)} rows={3}
          onPaste={(e) => { const imgs = [...(e.clipboardData?.files || [])].filter((f) => f.type.startsWith("image/")); if (imgs.length) { e.preventDefault(); attach(imgs); } }}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); return; }
            const t = e.currentTarget, up = e.key === "ArrowUp", down = e.key === "ArrowDown";
            // 游標在第一行按 ↑、在最後一行按 ↓ 才切換，多行輸入仍可上下移動 / only on the first / last line
            if ((up && !t.value.slice(0, t.selectionStart).includes("\n")) ||
                (down && !t.value.slice(t.selectionEnd).includes("\n"))) {
              const r = recall.current;
              const got = recallInput(inputs.current, r.pos, r.draft, up ? -1 : 1);
              if (!got) return;
              e.preventDefault();
              recall.current = { pos: got[0], draft: r.pos === null ? input : r.draft };
              setInput(got[1]);
            }
          }}
          placeholder="問芥子…（Enter 送出、Shift+Enter 換行、↑↓ 叫回輸入過的句子、Esc 中止；圖片可以直接貼上）" />
        {busy ? <button className="stop" onClick={() => abort.current?.abort()}>中止</button>
          : <button onClick={send} disabled={!input.trim()}>送出</button>}
      </div>
    </div>
  );
}

function AgentAudit() {
  const [d, setD] = useState(null);
  const [error, setError] = useState("");
  const load = () => getJSON("/v1/agent/audit?days=7").then(setD).catch((e) => setError(String(e.message)));
  useEffect(() => { load(); }, []);
  if (error) return <div className="error">{error}</div>;
  if (!d) return null;
  return (
    <div>
      <h3>唯讀代理的動作（最近 7 天）</h3>
      <p className="muted">代理：{d.enabled ? "開" : "關（JIEZI_AGENT=on 才會啟用）"}；授權資料夾：{d.folders.length ? d.folders.join("、") : "沒有"}。只記錄動作與大小，不存檔案內容。</p>
      {d.entries.length > 0 && (
        <table>
          <thead><tr><th>時間</th><th>結果</th><th>工具</th><th>路徑</th><th>說明</th></tr></thead>
          <tbody>
            {[...d.entries].reverse().map((r, i) => (
              <tr key={i}>
                <td>{r.at?.slice(5, 16).replace("T", " ")}</td><td>{r.allowed ? "允許" : "拒絕"}</td><td>{r.tool}</td>
                <td className="q">{r.path || (r.arguments && (r.arguments.path || r.arguments.root)) || ""}</td>
                <td>{r.error || (r.chars != null ? `${r.chars} 字` : r.entries != null ? `${r.entries} 項` : r.matches != null ? `${r.matches} 個符合` : "")}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
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
              <td>{r.at?.slice(5, 16).replace("T", " ")}</td><td>{r.policy}</td><td>{r.final_tier != null ? r.final_tier : (r.status === "cancelled" ? "已中止" : r.status || "—")}</td>
              <td className="q">{r.question}</td><td>{(r.sources || []).join("、")}</td>
              <td>{r.training_use === false ? "否" : r.training_use === true ? "是" : "待確認"}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <AgentAudit />
    </div>
  );
}

function Status() {
  const [health, setHealth] = useState(null);
  const [doctor, setDoctor] = useState(null);
  const [error, setError] = useState("");
  useEffect(() => {
    fetch(BASE + "/health").then((r) => r.json()).then(setHealth).catch((e) => setError(String(e)));
    getJSON("/admin/doctor").then(setDoctor).catch((e) => setError(String(e.message)));
  }, []);
  return (
    <div>
      {error && <div className="error">{error}</div>}
      {!doctor && !error && <p className="muted">讀取中…</p>}
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
  const [theme, setTheme] = useState(loadTheme);
  useEffect(() => { document.documentElement.dataset.theme = theme; }, [theme]);
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
        <button className="theme" title="切換主題：自動（跟隨系統）／淺色／深色" aria-label="切換主題"
          onClick={() => setTheme((t) => nextTheme(t))}>{THEME_LABEL[theme]}</button>
      </header>
      <main>
        {!ready ? <KeyGate onDone={() => setReady(true)} /> : tab === "chat" ? <Chat /> : tab === "audit" ? <Audit /> : <Status />}
      </main>
      <footer className="muted">不會操控你的電腦：「讀我的檔案」只能讀你授權的資料夾，不能修改。所有對話只經過本機 gateway（127.0.0.1）。</footer>
    </div>
  );
}
