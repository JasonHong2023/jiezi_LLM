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

// 串流對話：每段文字呼叫 onDelta，最後的 jiezi 狀態呼叫 onMeta；signal 用來一鍵中止。
// Streaming chat: onDelta per chunk, onMeta for the final jiezi status; signal aborts at once.
export async function streamChat(messages, policy, { onDelta, onMeta, signal }) {
  const r = await fetch(BASE + "/v1/chat/completions", {
    method: "POST",
    headers: headers(),
    body: JSON.stringify({ model: policy, messages, stream: true }),
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
