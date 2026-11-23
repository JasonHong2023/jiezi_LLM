// 芥子桌面 App 雛形：對話、稽核紀錄、狀態（唯讀；不操控作業系統）。
// Jiezi desktop prototype: chat, audit log, status (read-only; no OS control).
import { useEffect, useRef, useState } from "react";
import { BASE, THEME_LABEL, firstPhase, processSummary, refParts, splitAppendix, getJSON, postJSON, getKey, loadInputs, loadTheme, nextTheme, phaseAfter, phaseLabel, readDocument, recallInput, rememberInput, setKey, stepText, streamChat, withDocuments } from "./api.js";

const MAX_DOC_CHARS = 1500000;  // 附著文件的總字數上限（和 jiezi chat 相同）/ same cap as jiezi chat
const MAX_IMAGE_BYTES = 5 * 1024 * 1024;  // 和 jiezi chat 的 /image 相同 / same cap as /image in chat

// 選單不列「直接請教 Claude」（使用者 2026-11-18：拿掉）；預設的「芥子」答不出來時仍會自動請教
// The menu omits ask-Claude (user request); the default policy still consults Claude when needed
const POLICIES = [
  ["jiezi", "芥子（本機優先，答不出來請教 Claude）"],
  ["jiezi-local", "只用本機"],
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

// 一則訊息：回答本文、參考資料（一直顯示）、過程（預設收合）（add-answer-process，使用者 2026-11-18）
// One message: the answer, its references (always shown) and the process (folded)
function Message({ m, live }) {
  if (m.role !== "assistant") return <div className={`msg ${m.role}`}><div className="body">{m.content}</div></div>;
  const { body, refs, checks } = splitAppendix(m.content);
  const steps = m.steps?.length > 0 && <ul className="steps">{m.steps.map((s, j) =>
    <li key={j} className={s.status}>{stepText(s)}</li>)}</ul>;
  const proc = m.meta?.process || [];
  return (
    <div className="msg assistant">
      {!m.meta && steps}
      {m.meta && (proc.length > 0 || steps) && (
        <details className="process">
          <summary>{processSummary(proc, m.meta.latency_s)}</summary>
          <ol>{proc.map((st, j) => (
            <li key={j}>
              <b>{st.label}</b>{st.model && <span className="muted"> · {st.model}</span>}
              {st.t_s != null && <span className="muted"> · {st.t_s} 秒</span>}
              {st.items?.length > 0 && <div className="muted">{st.items.join("；")}</div>}
              {st.check && <div className={st.check.startsWith("沒通過") ? "warn" : "muted"}>檢查：{st.check}</div>}
              {st.error && <div className="warn">錯誤：{st.error}</div>}
              {st.draft && <details className="draft"><summary>這一步的草稿（沒有採用）</summary><div>{st.draft}</div></details>}
            </li>
          ))}</ol>
          {steps}
        </details>
      )}
      <div className="body">{body}</div>
      {live && <Progress {...live} />}
      {checks.map((c, j) => <div key={j} className="warn check">查核：{c}</div>)}
      {refs.length > 0 && (
        <div className="refs">
          <div className="refs-title">參考資料</div>
          {refs.map((r, j) => (
            <div key={j} className="ref">
              {r.title !== "參考資料" && <span className="muted">{r.title}</span>}
              {r.text.split("\n").map((line, k) => (
                <div key={k}>{refParts(line).map((p, n) => p.link
                  ? <a key={n} href={p.link} target="_blank" rel="noopener noreferrer" title={p.link}>{p.text}</a>
                  : <span key={n}>{p.text}</span>)}</div>
              ))}
            </div>
          ))}
        </div>
      )}
      {m.meta && <div className="meta">{statusLine(m.meta)}</div>}
      {m.meta?.injection?.suspected?.length > 0 &&
        <div className="warn">注意：{m.meta.injection.warning}（{m.meta.injection.suspected.join("、")}）</div>}
    </div>
  );
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

  // 一定要用大括號：新版 Chrome（158）的 scrollIntoView 會回傳 Promise，箭頭函式直接回傳它，React 會當成清理函式呼叫，
  // 出現「l is not a function」整個畫面消失（使用者 2026-11-18：送出後、切換分頁後空白）
  // Braces matter: in Chrome 158 scrollIntoView returns a Promise, which React then calls as the cleanup and crashes
  useEffect(() => { end.current?.scrollIntoView({ block: "end" }); }, [msgs]);
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
    // 畫面上的舊訊息保留 meta（過程、狀態列），送出的歷史才只留 role、content
    // Earlier messages keep their meta on screen; only the outgoing history is reduced to role and content
    setMsgs([...msgs, history[history.length - 1], { role: "assistant", content: "", meta: null, steps: [] }]);
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
          <Message key={i} m={m} live={busy && i === msgs.length - 1 ? progress : null} />
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

// 轉交原因的中文說明 / escalation reasons in words
const REASONS = { context_too_large: "請求太大", engine_unavailable: "本機被保留", unsupported_claims: "查核沒過",
  self_reported_unsure: "本機不確定", needs_web: "要上網", truncated: "回答被截斷", empty_answer: "沒有回答",
  verification_failed: "驗證沒過", policy: "使用者指定", consult_failed: "請教失敗", unknown: "其他" };
function reasonText(k) {
  const [who, why] = k.split(":");
  return `${who === "claude" ? "Claude" : "雲端"}・${REASONS[why] || why}`;
}

// add-agent-approval：寫入請求要看過完整內容才能核准；核准時把畫面上這份內容的 sha256 一起送出
function Approvals() {
  const [list, setList] = useState([]);
  const [open, setOpen] = useState(null);
  const [msg, setMsg] = useState("");
  const load = () => getJSON("/v1/agent/approvals").then((d) => setList(d.approvals)).catch((e) => setMsg(String(e.message)));
  useEffect(() => { load(); }, []);
  const show = (id) => getJSON(`/v1/agent/approvals/${id}`).then(setOpen).catch((e) => setMsg(String(e.message)));
  const decide = (action) => {
    const reason = action === "allow" ? "桌面網頁核准" : action === "deny" ? "桌面網頁拒絕" : "桌面網頁撤回";
    postJSON(`/v1/agent/approvals/${open.id}`, { action, sha256: open.sha256, reason })
      .then((r) => { setMsg(`${r.status}：${r.path}`); setOpen(null); load(); })
      .catch((e) => setMsg(String(e.message)));
  };
  if (!list.length && !msg) return null;
  return (
    <div className="esc">
      <h3>寫入請求（代理要建立的新檔，看過內容才核准）</h3>
      {msg && <p className="muted">{msg}</p>}
      <table>
        <thead><tr><th>狀態</th><th>路徑</th><th>大小</th><th></th></tr></thead>
        <tbody>{list.map((r) => (
          <tr key={r.id}><td>{r.status}</td><td className="q">{r.path}</td><td>{r.bytes} B</td>
            <td><button onClick={() => show(r.id)}>看內容</button></td></tr>
        ))}</tbody>
      </table>
      {open && (
        <div>
          <p className="muted">{open.path}・sha256 {open.sha256}・{open.status}</p>
          <pre className="q">{open.content}</pre>
          {open.status === "proposed" && <><button onClick={() => decide("allow")}>核准寫入</button> <button onClick={() => decide("deny")}>拒絕</button></>}
          {open.status === "applied" && <button onClick={() => decide("rollback")}>撤回（刪掉這個新檔）</button>}
          {" "}<button onClick={() => setOpen(null)}>關閉</button>
        </div>
      )}
    </div>
  );
}

function Status() {
  const [health, setHealth] = useState(null);
  const [doctor, setDoctor] = useState(null);
  const [esc, setEsc] = useState(null);
  const [mem, setMem] = useState(null);
  const [obs, setObs] = useState(null);
  const [error, setError] = useState("");
  useEffect(() => {
    fetch(BASE + "/health").then((r) => r.json()).then(setHealth).catch((e) => setError(String(e)));
    getJSON("/admin/doctor").then(setDoctor).catch((e) => setError(String(e.message)));
    getJSON("/admin/escalations").then(setEsc).catch(() => setEsc(null));
    getJSON("/admin/memory").then(setMem).catch(() => setMem(null));
    getJSON("/admin/observability?days=7").then(setObs).catch(() => setObs(null));
  }, []);
  return (
    <div>
      {error && <div className="error">{error}</div>}
      {!doctor && !error && <p className="muted">讀取中…</p>}
      {esc && (
        <div className="esc">
          <h3>轉交次數（最近 7 天）</h3>
          <p className="muted">共 {esc.total.requests} 題，請教 Claude {esc.total.claude} 次、雲端模型 {esc.total.cloud} 次</p>
          <table>
            <thead><tr><th>日期</th><th>題數</th><th>Claude</th><th>雲端</th><th>原因</th></tr></thead>
            <tbody>{esc.days.map((d) => (
              <tr key={d.day}><td>{d.day}</td><td>{d.requests}</td><td>{d.claude}</td><td>{d.cloud}</td>
                <td className="q">{Object.entries(d.reasons).map(([k, n]) => `${reasonText(k)} ${n}`).join("、")}</td></tr>
            ))}</tbody>
          </table>
        </div>
      )}
      {obs && (
        <div className="esc">
          <h3>代理與工具（最近 {obs.days} 天，{obs.requests} 題）</h3>
          <p className="muted">代理 {obs.agent_enabled ? "開" : "關"}・寫入工具 {obs.agent_write_enabled ? "開" : "關"}・工具篩選 {obs.tool_filter_enabled ? "開" : "關"}</p>
          <table><tbody>
            <tr><td>結果</td><td className="q">{Object.entries(obs.terminal_states).map(([k, n]) => `${k} ${n}`).join("、")}</td></tr>
            <tr><td>轉交原因</td><td className="q">{Object.entries(obs.escalation_reasons).map(([k, n]) => `${k} ${n}`).join("、") || "—"}</td></tr>
            <tr><td>停止動作（fail-closed）</td><td className="q">{Object.entries(obs.fail_closed).map(([k, n]) => `${k} ${n}`).join("、") || "—"}</td></tr>
            <tr><td>工具篩選</td><td className="q">{obs.tool_filter.requests ? `${obs.tool_filter.requests} 次，平均 ${obs.tool_filter.avg_original} → ${obs.tool_filter.avg_kept} 個工具` : "—"}</td></tr>
            <tr><td>不可訓練原因</td><td className="q">{Object.entries(obs.untrainable_reasons).map(([k, n]) => `${k} ${n}`).join("、") || "—"}</td></tr>
          </tbody></table>
        </div>
      )}
      <Approvals />
      {mem && (
        <div className="esc">
          <h3>記憶 wiki（{mem.topics.length} 個主題）</h3>
          <p className="muted">要修改請直接編輯 var/memory/wiki 裡的頁面；刪除一個主題用 <code>scripts/jiezi memory forget 主題</code>。</p>
          {mem.topics.length > 0 && (
            <table>
              <thead><tr><th>主題</th><th>答案</th><th>更正</th><th>記住的事</th><th>更新</th></tr></thead>
              <tbody>{mem.topics.map((t) => (
                <tr key={t.page}><td className="q">{t.title}</td><td>{t.qa}</td><td>{t.correction}</td><td>{t.note}</td><td>{t.updated}</td></tr>
              ))}</tbody>
            </table>
          )}
          <h3>經驗（{mem.lessons.length} 筆，無效 3 次自動停用）</h3>
          {mem.lessons.length > 0 && (
            <table>
              <thead><tr><th>題目</th><th>下次要注意</th><th>用上</th><th>有效</th><th>無效</th><th>狀態</th></tr></thead>
              <tbody>{mem.lessons.map((x) => (
                <tr key={x.id}><td className="q">{x.question}</td><td className="q">{x.lesson}</td><td>{x.uses}</td><td>{x.wins}</td><td>{x.fails}</td><td>{x.active ? "啟用" : "停用"}</td></tr>
              ))}</tbody>
            </table>
          )}
        </div>
      )}
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
