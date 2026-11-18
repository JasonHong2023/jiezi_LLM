#!/usr/bin/env bash
# 夜間工作（使用者 2026-11-17 選「拆成多晚、小批訓練」）：
#   1. Phase 6 第一輪訓練（add-sft-training 2.3），06:30 存檢查點暫停、下一晚接續；
#   2. 訓練完成就合併並匯出 Q4_K_M GGUF（CPU，約 3 分鐘、9 GB 系統記憶體）；
#   3. 用 E0 條件評測訓練後的模型（回歸關卡用）；
#   4. 剩下的時間跑 E0 取樣設定（add-e0-benchmark 5.5，可接續），06:45 前停。
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
# add-chunk-recall 2.1：有 todo 標記就先量段落召回（約 30 分鐘，要用 GPU，所以在保留 GPU 之前）
# Chunk-recall measurement first when flagged (needs the engine, so before the GPU hold)
if [ -f var/eval/recall-ab/todo ]; then
  scripts/night/recall-ab.sh >> "$log" 2>&1 && rm -f var/eval/recall-ab/todo
  echo "--- recall-ab done $(date -Iseconds)" >> "$log"
fi
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
# 3. 訓練後的模型用和 E0 相同的條件評測（bank r0、ctx 4096、貪婪解碼），給回歸關卡（R20）用；可接續
#    Evaluate the trained model under E0 conditions for the regression gate; resumable
gguf="var/train/$run/$run-Q4_K_M.gguf"; rid="e0-$run"
if [ -f "$gguf" ] && ! grep -q '"complete"' "var/eval/runs/$rid/report.json" 2>/dev/null; then
  left=$(( $(date -d "$(date +%F) 06:45" +%s) - $(date +%s) ))
  if [ -f "var/eval/runs/$rid/conditions.json" ]; then idarg="--resume $rid --retry-errors"; else idarg="--run-id $rid"; fi
  echo "=== eval $rid for ${left}s $(date -Iseconds)" >> "$log"
  timeout "$left" scripts/eval run --bank r0 --backend local --model "$gguf" --ngl 99 --ctx 4096 $idarg --now >> "$log" 2>&1
  echo "--- eval rc=$? $(date -Iseconds)" >> "$log"
  # 評審在雲端，不佔本機 GPU；沒跑完白天可以再跑 / judges are in the cloud; rerun in the daytime if unfinished
  # 獨立的 systemd 單元，這個腳本結束也不會被一起停掉 / its own unit so it outlives this script
  systemd-run --user --unit="jiezi-verify-$rid-$(date +%H%M)" --setenv=PATH="$PATH" --working-directory="$ROOT" \
    bash -c "scripts/eval verify $rid --judge-model nvidia-nemotron-3-ultra --judge-match nemotron --now >> var/train/verify-$rid.log 2>&1" >> "$log" 2>&1
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
