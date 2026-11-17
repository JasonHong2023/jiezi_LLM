// 桌面網頁的無頭瀏覽器實測（不碰使用者的螢幕）/ headless check of the desktop page (never touches the user's screen)
// 用法 / usage: node scripts/ui_check.mjs <headless-chromium 執行檔> <gateway 金鑰> <要附的文件> <截圖輸出資料夾>
// 流程：開頁 → 附檔 → 問一題 → 長回答時按 Esc 中止 → 稽核頁；印出 JSON 結果並存 5 張截圖。gateway 要在跑。
// Flow: open, attach, ask, Esc-stop a long answer, audit tab; prints JSON and saves five screenshots.
import { spawn } from "node:child_process";
import { writeFileSync } from "node:fs";
const [BIN, KEY, DOC, OUT] = process.argv.slice(2);
const port = 36117;
const proc = spawn(BIN, ["--headless", `--remote-debugging-port=${port}`, "--remote-debugging-address=127.0.0.1",
  "--window-size=1200,900", "--lang=zh-TW", "about:blank"], { stdio: "ignore" });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let ws, id = 0; const pending = new Map(); const events = [];
async function connect() {
  for (let i = 0; i < 50; i++) {
    try {
      const list = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
      const page = list.find((t) => t.type === "page");
      if (page) { ws = new WebSocket(page.webSocketDebuggerUrl); break; }
    } catch {}
    await sleep(200);
  }
  await new Promise((r) => ws.addEventListener("open", r));
  ws.addEventListener("message", (m) => { const d = JSON.parse(m.data); if (d.id && pending.has(d.id)) { pending.get(d.id)(d); pending.delete(d.id); } else events.push(d); });
}
const send = (method, params = {}) => new Promise((r) => { const i = ++id; pending.set(i, r); ws.send(JSON.stringify({ id: i, method, params })); });
const ev = async (expr) => (await send("Runtime.evaluate", { expression: expr, awaitPromise: true, returnByValue: true })).result?.result?.value;
const shot = async (name) => { const r = await send("Page.captureScreenshot", { format: "png" }); writeFileSync(`${OUT}/${name}.png`, Buffer.from(r.result.data, "base64")); };
const waitFor = async (expr, ms = 60000) => { const t = Date.now(); while (Date.now() - t < ms) { if (await ev(expr)) return true; await sleep(250); } return false; };
const results = {};
try {
  await connect();
  await send("Page.enable"); await send("DOM.enable"); await send("Runtime.enable");
  await send("Page.navigate", { url: "http://127.0.0.1:36100/ui/" }); await sleep(1500);
  await ev(`sessionStorage.setItem("jiezi.gatewayKey", ${JSON.stringify(KEY)}); Object.keys(sessionStorage).join(",")`);
  await send("Page.reload"); await sleep(1500);
  results.gate = await ev(`!!document.querySelector("input[type=password]")`);
  if (results.gate) {
    await ev(`(()=>{const i=document.querySelector("input[type=password]"); const s=Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,"value").set; s.call(i, ${JSON.stringify(KEY)}); i.dispatchEvent(new Event("input",{bubbles:true})); const f=i.closest("form"); if(f){f.requestSubmit()} else {[...document.querySelectorAll("button")].find(b=>/登入|確定|連線|save|ok/i.test(b.textContent))?.click()} })()`);
    await sleep(1000);
  }
  await shot("1-chat");
  results.title = await ev(`document.querySelector("h1")?.textContent`);
  // 附文件 / attach a document
  const doc = await send("DOM.getDocument", { depth: -1 });
  const q = await send("DOM.querySelector", { nodeId: doc.result.root.nodeId, selector: "input[type=file]" });
  await send("DOM.setFileInputFiles", { nodeId: q.result.nodeId, files: [DOC] });
  results.attached = await waitFor(`!!document.querySelector(".docs .doc")`, 30000);
  results.docChip = await ev(`document.querySelector(".docs .doc")?.textContent`);
  await shot("2-attached");
  // 問一題並等回答 / ask and wait for the answer
  await ev(`(()=>{const t=document.querySelector(".composer textarea"); const s=Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,"value").set; s.call(t,"這份文件的待辦事項有哪些？"); t.dispatchEvent(new Event("input",{bubbles:true}));})()`);
  await sleep(300);
  await ev(`[...document.querySelectorAll(".composer button")].find(b=>b.textContent.includes("送出"))?.click()`);
  results.answered = await waitFor(`!!document.querySelector(".msg.assistant .meta")`, 240000);
  results.answer = await ev(`document.querySelector(".msg.assistant .body")?.textContent?.slice(0,200)`);
  results.meta = await ev(`document.querySelector(".msg.assistant .meta")?.textContent`);
  await shot("3-answer");
  // 一鍵中止：送出長問題後按 Esc / one-key stop with Esc
  await ev(`(()=>{const t=document.querySelector(".composer textarea"); const s=Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,"value").set; s.call(t,"請寫一篇一千字的文章介紹台灣夜市。"); t.dispatchEvent(new Event("input",{bubbles:true}));})()`);
  await sleep(300);
  await ev(`[...document.querySelectorAll(".composer button")].find(b=>b.textContent.includes("送出"))?.click()`);
  await waitFor(`(document.querySelectorAll(".msg.assistant .body")[1]?.textContent||"").length > 20`, 120000);
  await ev(`window.dispatchEvent(new KeyboardEvent("keydown",{key:"Escape"}))`);
  results.stopped = await waitFor(`!!document.querySelector(".error") && document.querySelector(".error").textContent.includes("已中止")`, 5000);
  results.stopText = await ev(`document.querySelector(".error")?.textContent`);
  await shot("4-stopped");
  // 稽核頁 / audit tab
  await ev(`[...document.querySelectorAll("nav button")].find(b=>b.textContent.includes("稽核"))?.click()`);
  await sleep(2000);
  results.audit = await ev(`document.querySelector("main")?.textContent?.slice(0,160)`);
  await shot("5-audit");
} catch (e) { results.error = String(e); }
console.log(JSON.stringify(results, null, 1));
proc.kill();
process.exit(0);
