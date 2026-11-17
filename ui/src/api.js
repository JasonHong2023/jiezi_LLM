// gateway API：同源呼叫，金鑰只存在這個分頁的 sessionStorage。
// Gateway API: same-origin calls; the key lives only in this tab's sessionStorage.

const KEY = "jiezi.gatewayKey";

// 在 Tauri 外殼裡（tauri://localhost 或 Windows 的 tauri.localhost）要用完整的 gateway 網址；瀏覽器用同源。
// Inside the Tauri shell use the full gateway URL; in a browser use the same origin.
const IN_TAURI = location.protocol === "tauri:" || location.hostname === "tauri.localhost";
export const BASE = IN_TAURI ? "http://127.0.0.1:36100" : "";

export const getKey = () => sessionStorage.getItem(KEY) || "";
export const setKey = (k) => (k ? sessionStorage.setItem(KEY, k.trim()) : sessionStorage.removeItem(KEY));

function headers() {
  return { Authorization: `Bearer ${getKey()}`, "Content-Type": "application/json" };
}

export async function getJSON(path) {
  const r = await fetch(BASE + path, { headers: headers() });
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
export async function streamChat(messages, policy, { onDelta, onMeta, onStep, signal, agent = false }) {
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
        if (d.jiezi_agent) { onStep && onStep(d.jiezi_agent); continue; }  // 唯讀代理的一步 / an agent step
        if (d.jiezi) onMeta(d.jiezi);
        for (const ch of d.choices || []) {
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
