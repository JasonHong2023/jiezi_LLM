// gateway API：同源呼叫，金鑰只存在這個分頁的 sessionStorage。
// Gateway API: same-origin calls; the key lives only in this tab's sessionStorage.

const KEY = "jiezi.gatewayKey";

// 在 Tauri 外殼裡（tauri://localhost 或 Windows 的 tauri.localhost）要用完整的 gateway 網址；瀏覽器用同源。
// Inside the Tauri shell use the full gateway URL; in a browser use the same origin.
const IN_TAURI = location.protocol === "tauri:" || location.hostname === "tauri.localhost";
export const BASE = IN_TAURI ? "http://127.0.0.1:36100" : "";

export const getKey = () => cleanKey(sessionStorage.getItem(KEY));
// 從 .env 或終端機複製時常連「JIEZI_GATEWAY_KEY=」、引號、空白一起貼上（使用者 2026-11-18 得到 401），這裡去掉
// Pasting from .env or a terminal often brings the variable name, quotes or spaces along; strip them
export const cleanKey = (k) => String(k || "").trim().replace(/^(export\s+)?JIEZI_GATEWAY_KEY\s*=\s*/, "").trim()
  .replace(/^(["'])(.*)\1$/, "$2").trim();
export const setKey = (k) => (cleanKey(k) ? sessionStorage.setItem(KEY, cleanKey(k)) : sessionStorage.removeItem(KEY));

function headers() {
  return { Authorization: `Bearer ${getKey()}`, "Content-Type": "application/json" };
}

export async function getJSON(path) {
  // 30 秒沒回應就顯示錯誤，不讓頁面一直空著 / show an error instead of a blank page after 30 s
  const r = await fetch(BASE + path, { headers: headers(), signal: AbortSignal.timeout(30000) })
    .catch((e) => { throw new Error(`連不到 gateway（${BASE || location.origin}）：${e.name === "TimeoutError" ? "30 秒沒有回應" : e.message}`); });
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
  return r.json();
}

export async function postJSON(path, body) {
  const r = await fetch(BASE + path, { method: "POST", headers: headers(), body: JSON.stringify(body),
    signal: AbortSignal.timeout(30000) });
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
  return r.json();
}

// 上傳文件給 gateway 讀成文字（PDF、Word、網頁、純文字）；檔案讀完就刪，不留在 gateway。
// Upload a document for the gateway to read; the file is deleted once read.
export async function readDocument(file) {
  const r = await fetch(`${BASE}/v1/documents?name=${encodeURIComponent(file.name)}`, {
    method: "POST",
    headers: { Authorization: `Bearer ${getKey()}`, "Content-Type": "application/octet-stream" },
    body: file,
  });
  if (!r.ok) {
    let msg = `${r.status}`;
    try { msg = (await r.json()).error.message; } catch { /* 不是 JSON / not JSON */ }
    throw new Error(msg);
  }
  return r.json();
}

// 把附著的文件包進問題（和 jiezi chat 相同的標記；文字已由 gateway 清理過）。
// Wrap the attached documents around a question (same markers as jiezi chat; text already cleaned).
export function withDocuments(question, docs) {
  let out = question;
  for (const d of [...docs].reverse()) {
    const name = d.name.replace(/[】\n]/g, "").slice(0, 200) || "文件";
    out = `【文件：${name}】\n${d.text}\n【文件結束】\n\n${out}`;
  }
  return out;
}

// 串流對話：每段文字呼叫 onDelta，最後的 jiezi 狀態呼叫 onMeta；signal 用來一鍵中止。
// Streaming chat: onDelta per chunk, onMeta for the final jiezi status; signal aborts at once.
export async function streamChat(messages, policy, { onDelta, onMeta, onStep, onThinking, onProgress, signal, agent = false }) {
  const r = await fetch(BASE + "/v1/chat/completions", {
    method: "POST",
    headers: headers(),
    body: JSON.stringify({ model: policy, messages, stream: true, ...(agent ? { jiezi_agent: true } : {}) }),
    signal,
  });
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
  const reader = r.body.getReader();
  const dec = new TextDecoder();
  let buf = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    let i;
    while ((i = buf.indexOf("\n\n")) >= 0) {
      const line = buf.slice(0, i).trim();
      buf = buf.slice(i + 2);
      if (!line.startsWith("data: ")) continue;
      const payload = line.slice(6);
      if (payload === "[DONE]") return;
      try {
        const d = JSON.parse(payload);
        if (d.error) throw new Error(d.error.message || "error");
        if (d.jiezi_progress) { onProgress && onProgress(d.jiezi_progress.stage); continue; }  // gateway 回報的階段
        if (d.jiezi_agent) { onStep && onStep(d.jiezi_agent); continue; }  // 唯讀代理的一步 / an agent step
        if (d.jiezi) onMeta(d.jiezi);
        for (const ch of d.choices || []) {
          if (ch.delta && ch.delta.reasoning_content) onThinking && onThinking();  // 只標示「思考中」/ status only
          const t = ch.delta && ch.delta.content;
          if (t) onDelta(t);
        }
      } catch (e) {
        if (e instanceof SyntaxError) continue;
        throw e;
      }
    }
  }
}

// 代理一步的說明（和 chat 的文字一致）/ One agent step as text (same wording as the TUI)
export function stepText(ev) {
  const what = { list_dir: "列出資料夾", find_files: "尋找檔案", read_file: "讀取", file_info: "查看" }[ev.tool] || ev.tool || "?";
  const a = ev.arguments || {};
  const target = ev.path || a.path || a.root || "";
  if (ev.status === "running") return `第 ${ev.step} 步：正在${what} ${target} …`;
  const mark = { ok: "完成", refused: "被拒絕（未授權）", error: "失敗" }[ev.status] || ev.status;
  return `第 ${ev.step} 步：${what} ${target} ${mark}${ev.error && ev.status !== "ok" ? "：" + ev.error : ""}`;
}

// 送出後的狀態（和 chat 的文字一致，使用者 2026-11-18）/ Live status after sending (same wording as the TUI)
export const SLOW_S = 8;
export function firstPhase(policy, { docs = false, agent = false } = {}) {
  if (policy === "jiezi-ask-claude") return "請教 Claude 中";
  if (policy === "jiezi-cloud") return "詢問雲端模型中";
  if (agent) return "準備查看你的檔案";
  if (docs) return "閱讀文件中";
  return "思考中";
}
export const STAGE_TEXT = {  // gateway 回報的階段（add-progress-events）/ stages reported by the gateway
  loading_model: "載入模型中", reading_documents: "閱讀文件中", looking: "辨識圖中物體", thinking: "思考中",
  retrying: "本機重新作答", thinking_hard: "本機深入思考中", asking_claude: "請教 Claude 中", asking_cloud: "詢問雲端模型中",
  asking_feedback: "向雲端要提示後重答",
};
export function phaseAfter(kind, value, current) {
  if (kind === "progress") return STAGE_TEXT[value] || current;
  if (kind === "thinking") return "思考中";
  if (kind === "agent") return `查看檔案中：${stepText(value)}`;
  if (kind === "delta") {
    if (value.includes("本機答不出來")) return value.includes("Claude") ? "請教 Claude 中" : "詢問雲端模型中";
    if (current.startsWith("請教") || current.startsWith("詢問")) return current;
    return "回答中";
  }
  return current;
}
export function phaseLabel(phase, seconds, events) {
  if (!events && seconds > SLOW_S && /^(思考|閱讀)/.test(phase)) return "處理中（準備模型或整理資料，第一次會久一點）";
  return phase;
}

// 輸入紀錄：↑／↓ 切換輸入過的句子（使用者 2026-11-18；和 jiezi chat 相同），存在這台電腦的 localStorage。
// Input history for Up / Down (same as jiezi chat), kept in localStorage on this machine.
export const MAX_INPUTS = 500;
export function loadInputs(store = globalThis.localStorage) {
  try { const v = JSON.parse(store?.getItem("jiezi.inputs") || "[]"); return Array.isArray(v) ? v.filter((x) => typeof x === "string") : []; }
  catch { return []; }
}
export function rememberInput(inputs, text, store = globalThis.localStorage) {
  const next = inputs[inputs.length - 1] === text ? inputs : [...inputs, text].slice(-MAX_INPUTS);
  try { store?.setItem("jiezi.inputs", JSON.stringify(next)); } catch { /* 存不下就只留在記憶體 / memory only */ }
  return next;
}
// pos = null 表示正在打的新句子；回傳 [新 pos, 要顯示的文字]，不能再移動時回傳 null。
// pos = null is the draft; returns [new pos, text to show], or null when there is nowhere to go.
export function recallInput(inputs, pos, draft, dir) {
  if (dir < 0) {
    if (!inputs.length || pos === 0) return null;
    const p = pos === null ? inputs.length - 1 : pos - 1;
    return [p, inputs[p]];
  }
  if (pos === null) return null;
  return pos === inputs.length - 1 ? [null, draft] : [pos + 1, inputs[pos + 1]];
}

// 夜間模式（使用者 2026-11-18）：auto 跟隨系統，light／dark 固定；選擇存在 localStorage。
// Dark mode: auto follows the system, light / dark are fixed; the choice is kept in localStorage.
export const THEMES = ["auto", "light", "dark"];
export const THEME_LABEL = { auto: "🌓 自動", light: "☀ 淺色", dark: "🌙 深色" };
export function loadTheme(store = globalThis.localStorage) {
  try { const t = store?.getItem("jiezi.theme"); return THEMES.includes(t) ? t : "auto"; } catch { return "auto"; }
}
export function nextTheme(theme, store = globalThis.localStorage) {
  const t = THEMES[(THEMES.indexOf(theme) + 1) % THEMES.length];
  try { store?.setItem("jiezi.theme", t); } catch { /* 存不下就只用這次 / this session only */ }
  return t;
}

// 回答與附錄分開、過程摘要（add-answer-process，使用者 2026-11-18）。附錄格式見 gateway 的 APPENDIX。
// Split the gateway appendix from the answer and summarise the process (add-answer-process).
const APPENDIX_HEAD = /\n*-{3,}[ \t]*\n【(字詞轉換|辭典原文|法規原文|參考資料|計算|記憶|課綱資料原文|延伸閱讀)】\n?/g;
// 串流回答時 gateway 插在本文後的查核提醒「［查核：…］」，拆出來另外顯示 / the inline grounding warning, shown apart
const CHECK_NOTE = /\n*［查核：([^］]*)］/g;
// 串流時本機答不出來，gateway 在同一個串流接著送「—— 本機答不出來，以下由 X 回答 ——」與 X 的回答：
// 畫面只顯示 X 的回答，本機草稿在「過程」裡；本機查到的參考資料保留（使用者 2026-11-18：Claude 的回答跑進參考資料框）
// When a streamed local answer is handed over, show only the helper's answer; the local draft lives in the process
// 本機重想成功時是「—— 本機重新想過，以下是新的回答 ——」；有好幾段時以最後一段為準
// A local retry uses "本機重新想過"; with several separators the last one wins
const HANDOFF = /\n*—— (?:本機答不出來，以下由 .+? 回答|本機重新想過，以下是新的回答)[^\n]*——\n*/g;
export function splitAppendix(text) {
  const s = String(text || "");
  const all = [...s.matchAll(HANDOFF)];
  if (!all.length) return splitOne(s);
  const h = all[all.length - 1];
  const before = splitOne(s.slice(0, h.index)), after = splitOne(s.slice(h.index + h[0].length));
  return { ...after, refs: [...before.refs, ...after.refs], handedOver: true };
}
function splitOne(text) {
  let s = text;
  const checks = [...s.matchAll(CHECK_NOTE)].map((m) => m[1].trim());
  s = s.replace(CHECK_NOTE, "");
  const heads = [...s.matchAll(APPENDIX_HEAD)];
  if (!heads.length) return { body: s.trim(), refs: [], checks };
  const refs = heads.map((m, i) => ({
    title: m[1],
    text: s.slice(m.index + m[0].length, i + 1 < heads.length ? heads[i + 1].index : s.length).trim(),
  }));
  return { body: s.slice(0, heads[0].index).trimEnd(), refs, checks };
}

// 參考資料的一行切成文字與連結：「- 標題（備註）：網址」只顯示標題當連結，其他網址縮短顯示
// A reference line as text and links: "- title: URL" shows the title as the link; other URLs are shortened
const URL_RE = /https?:\/\/[^\s，、）)」]+/g;
export function shortUrl(u) {
  try {
    const x = new URL(u);
    const last = decodeURIComponent(x.pathname.split("/").filter(Boolean).pop() || "");
    return last ? `${x.hostname}/…/${last}` : x.hostname;
  } catch { return u; }
}
export function refParts(line) {
  const m = line.match(/^\s*[-•·]?\s*(.+?)[：:]\s*(https?:\/\/\S+)\s*$/);
  if (m) return [{ link: m[2], text: m[1] }];
  const out = []; let last = 0;
  for (const u of line.matchAll(URL_RE)) {
    if (u.index > last) out.push({ text: line.slice(last, u.index) });
    out.push({ link: u[0], text: shortUrl(u[0]) });
    last = u.index + u[0].length;
  }
  if (last < line.length) out.push({ text: line.slice(last) });
  return out;
}
const STEP_SHORT = { files: "讀檔", lookup: "查資料", look: "看圖工具", experience: "參考經驗", web: "讀網頁" };
export function processSummary(process, latency) {
  const parts = [];
  for (const st of process || []) {
    parts.push(STEP_SHORT[st.kind] || st.label);
    if (st.kind === "answer" && st.check?.startsWith("沒通過")) parts.push("檢查沒過");
    else if (st.kind === "answer" && st.check && st.check !== "通過") parts.push(st.check);
    if (st.kind === "answer" && st.error) parts.push("失敗");
  }
  const total = latency != null ? `，共 ${Math.round(latency * 10) / 10} 秒` : "";
  return `過程：${parts.join(" → ") || "直接回答"}${total}`;
}
