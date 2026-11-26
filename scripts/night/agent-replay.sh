#!/usr/bin/env bash
# 代理程式長上下文評測（add-long-context 3.2；使用者 2026-11-26「照擬計畫的進行」，夜間 00:00–07:00 跑）：
# 等圖中文字評測（jiezi-night-YYYYMMDD）跑完，先記舊設定的自我測試當基準，再開 JIEZI_AGENT_CTX=30000（引擎 36864 共用池、
# q8_0 KV）重啟，記自我測試與 VRAM，重放 Hermes 請求（只生成、不執行工具）。引擎起不來或自我測試掉超過 3 題就退到 24576 再試。
# 用法同 vision-eval.sh：改 .env、重啟 gateway、結束時還原。紀錄 var/eval/agent-replay/night-YYYY-MM-DD.log。
# Long-context agent replay: baseline selftest, then JIEZI_AGENT_CTX=30000, selftest + VRAM, replay Hermes requests
# without running tools; falls back to 24576 if the engine fails or the selftest drops; restores .env and the gateway.
set -u
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"; cd "$ROOT"
D=var/eval/agent-replay; log="$D/night-$(date +%F).log"; mkdir -p "$D"
exec >> "$log" 2>&1
[ -s "$D/set.jsonl" ] || { echo "no set; run: python -m jiezi.eval.agent_replay prepare <days>"; exit 1; }
deadline=$(date -d "$(date +%F) 06:45" +%s)
# 等前一個夜間評測結束（最多到 02:30）/ wait for the earlier night job, at most until 02:30
while systemctl --user is-active --quiet "jiezi-night-$(date +%Y%m%d)" && [ "$(date +%s)" -lt "$(date -d "$(date +%F) 02:30" +%s)" ]; do sleep 30; done
echo "=== start $(date -Iseconds)"
orig=$(grep '^JIEZI_AGENT_CTX=' .env || true)
restart() { scripts/jiezi stop >/dev/null 2>&1; sleep 2; scripts/jiezi start >/dev/null 2>&1; sleep 8; }
setc() { sed -i '/^JIEZI_AGENT_CTX=/d' .env; [ -n "$1" ] && printf '%s\n' "$1" >> .env; }
selftest() { scripts/jiezi selftest --policy jiezi-local | tail -1; }
correct() { sed -n 's/^\([0-9]*\)\/[0-9]* correct.*/\1/p' | tail -1; }
vram_pid=""
trap '[ -n "$vram_pid" ] && kill "$vram_pid" 2>/dev/null; setc "$orig"; restart; echo "=== restored $(date -Iseconds)"' EXIT

echo "--- baseline selftest (agent ctx off) $(date -Iseconds)"
setc ""; restart
b_line=$(selftest); echo "$b_line"; base=$(echo "$b_line" | correct)

ok=""
for ctx in 30000 24576; do
  setc "JIEZI_AGENT_CTX=$ctx"; restart
  echo "--- selftest agent ctx $ctx $(date -Iseconds)"
  n_line=$(selftest); echo "$n_line"; new=$(echo "$n_line" | correct)
  PYTHONPATH=src .venv/bin/python -m jiezi.runtime doctor 2>&1 | grep -E "代理程式上下文|核心" | head -3
  nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits
  if [ -n "$new" ] && { [ -z "$base" ] || [ "$new" -ge $(( base - 3 )) ]; }; then ok=$ctx; break; fi
  echo "!!! agent ctx $ctx: selftest ${base:-?} -> ${new:-?}; trying smaller"
done
[ -z "$ok" ] && { echo "no working agent ctx; stop"; exit 1; }

( while true; do nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits; sleep 2; done ) > "$D/vram.log" 2>/dev/null &
vram_pid=$!
left=$(( deadline - $(date +%s) ))
echo "=== replay ctx$ok for ${left}s $(date -Iseconds)"
PYTHONPATH=src timeout "$left" .venv/bin/python -m jiezi.eval.agent_replay run "ctx$ok" | tail -3
echo "--- replay rc=$? $(date -Iseconds)"
kill "$vram_pid" 2>/dev/null; vram_pid=""
PYTHONPATH=src .venv/bin/python -m jiezi.eval.agent_replay report "ctx$ok"
cat "$D/report.md"
