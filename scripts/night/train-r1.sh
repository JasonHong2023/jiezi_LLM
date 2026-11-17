#!/usr/bin/env bash
# 夜間接續訓練（add-sft-training 2.3；使用者 2026-11-17 選「拆成多晚、小批訓練」）。
# Nightly resumable training. Holds the gateway's GPU until 07:00, trains until 06:30, then releases the GPU.
# 訓練完成後改跑 E0 的取樣設定（可接續）。/ After training finishes, the E0 sampled setting runs instead.
set -u
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
log="var/train/night-$(date +%F).log"; mkdir -p var/train
key=$(grep '^JIEZI_GATEWAY_KEY=' .env | cut -d= -f2-)
hold() { curl -s -m 30 -X POST "http://127.0.0.1:36100/admin/unload" -H "Authorization: Bearer $key" \
  -H 'Content-Type: application/json' -d "$1" >> "$log" 2>&1; echo >> "$log"; }
echo "=== $(date -Iseconds) start" >> "$log"
if [ -f var/train/qwen3.5-4b-r1/adapter/adapter_config.json ]; then
  echo "training already done; running the E0 sampled setting instead" >> "$log"
  scripts/eval e0 sample --now --judge-model nvidia-nemotron-3-ultra --judge-match nemotron >> "$log" 2>&1
  scripts/eval e0 report >> "$log" 2>&1
  exit 0
fi
hold "{\"hold_until\": \"$(date +%F)T07:00\", \"reason\": \"nightly training (add-sft-training)\"}"
HF_HUB_OFFLINE=1 scripts/jiezi train sft --config src/jiezi/train/configs/qwen3.5-4b-r1.json >> "$log" 2>&1
rc=$?
echo "--- rc=$rc (0 done, 3 paused) $(date -Iseconds)" >> "$log"
hold '{"hold_until": null}'
if [ "$rc" = 0 ] && [ ! -f var/train/qwen3.5-4b-r1/model-Q4_K_M.gguf ]; then
  # 訓練完成：合併並轉成 GGUF（CPU，約 9 GB 系統記憶體）；評測與換核心交給白天與使用者決定
  # Done: merge and convert to GGUF on the CPU; evaluation and any core switch are decided in the daytime
  echo "=== export $(date -Iseconds)" >> "$log"
  HF_HUB_OFFLINE=1 scripts/jiezi train export --run qwen3.5-4b-r1 --quant Q4_K_M >> "$log" 2>&1
  echo "--- export rc=$? $(date -Iseconds)" >> "$log"
fi
