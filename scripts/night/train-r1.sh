#!/usr/bin/env bash
# 夜間工作（使用者 2026-11-17 選「拆成多晚、小批訓練」）：
#   1. Phase 6 第一輪訓練（add-sft-training 2.3），06:30 存檢查點暫停、下一晚接續；
#   2. 訓練完成就合併並匯出 Q4_K_M GGUF（CPU，約 3 分鐘、9 GB 系統記憶體）；
#   3. 剩下的時間跑 E0 取樣設定（add-e0-benchmark 5.5，可接續），06:45 前停。
# 整段期間把 gateway 的 GPU 保留到 07:00。紀錄 var/train/night-YYYY-MM-DD.log。
# Nightly: resumable training, GGUF export when done, then the resumable E0 sampled setting until 06:45.
set -u
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
log="var/train/night-$(date +%F).log"; mkdir -p var/train
key=$(grep '^JIEZI_GATEWAY_KEY=' .env | cut -d= -f2-)
run="qwen3.5-4b-r1"
hold() { curl -s -m 30 -X POST "http://127.0.0.1:36100/admin/unload" -H "Authorization: Bearer $key" \
  -H 'Content-Type: application/json' -d "$1" >> "$log" 2>&1; echo >> "$log"; }
echo "=== $(date -Iseconds) start" >> "$log"
hold "{\"hold_until\": \"$(date +%F)T07:00\", \"reason\": \"nightly training and evaluation\"}"
if [ ! -f "var/train/$run/adapter/adapter_config.json" ]; then
  HF_HUB_OFFLINE=1 scripts/jiezi train sft --config "src/jiezi/train/configs/$run.json" >> "$log" 2>&1
  echo "--- train rc=$? (0 done, 3 paused) $(date -Iseconds)" >> "$log"
fi
if [ -f "var/train/$run/adapter/adapter_config.json" ] && [ ! -f "var/train/$run/$run-Q4_K_M.gguf" ]; then
  echo "=== export $(date -Iseconds)" >> "$log"
  HF_HUB_OFFLINE=1 scripts/jiezi train export --run "$run" --quant Q4_K_M >> "$log" 2>&1
  echo "--- export rc=$? $(date -Iseconds)" >> "$log"
fi
left=$(( $(date -d "$(date +%F) 06:45" +%s) - $(date +%s) ))
if [ -f "var/train/$run/adapter/adapter_config.json" ] && [ "$left" -gt 1800 ]; then
  echo "=== e0 sample for ${left}s $(date -Iseconds)" >> "$log"
  timeout "$left" scripts/eval e0 sample --now --judge-model nvidia-nemotron-3-ultra --judge-match nemotron >> "$log" 2>&1
  echo "--- e0 sample rc=$? (124 = stopped at 06:45, resumes next night) $(date -Iseconds)" >> "$log"
  scripts/eval e0 report >> "$log" 2>&1
fi
hold '{"hold_until": null}'
echo "=== $(date -Iseconds) end" >> "$log"
