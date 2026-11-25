#!/usr/bin/env bash
# 看圖評測（add-vision-tools 1.2、3.1；使用者 2026-11-25 同意夜間 00:00–07:00 跑）：Open Images V7 子集 100 張，
# 看圖工具關（只用核心）與開各跑一次，比精確率與召回率。用法同 relevance-e2e.sh：改 .env、重啟 gateway、結束時還原。
# 可接續：已有的圖不重問；06:45 前停。紀錄 var/eval/vision/night-YYYY-MM-DD.log。
# Vision tools off vs on over 100 Open Images photos; resumable; stops by 06:45; restores .env and the gateway.
set -u
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"; cd "$ROOT"
log="var/eval/vision/night-$(date +%F).log"; mkdir -p var/eval/vision
exec >> "$log" 2>&1
[ -s var/eval/vision/set.jsonl ] || { echo "no var/eval/vision/set.jsonl; run: python -m jiezi.eval.vision prepare"; exit 1; }
orig=$(grep '^JIEZI_VISION_TOOLS=' .env || true)
restart() { scripts/jiezi stop >/dev/null 2>&1; sleep 2; scripts/jiezi start >/dev/null 2>&1; sleep 8; }
setv() { sed -i '/^JIEZI_VISION_TOOLS=/d' .env; [ -n "$1" ] && printf '%s\n' "$1" >> .env; }
trap 'setv "$orig"; restart; echo "=== restored $(date -Iseconds)"' EXIT
for mode in off on; do
  left=$(( $(date -d "$(date +%F) 06:45" +%s) - $(date +%s) ))
  [ "$left" -lt 600 ] && { echo "out of time before tools-$mode"; break; }
  [ "$mode" = off ] && left=$(( left / 2 ))          # 先跑的最多用一半，留時間給另一組 / leave half for the other
  setv "JIEZI_VISION_TOOLS=$mode"; restart
  echo "=== tools-$mode for ${left}s $(date -Iseconds)"
  PYTHONPATH=src timeout "$left" .venv/bin/python -m jiezi.eval.vision run "tools-$mode" | tail -3
  echo "--- tools-$mode rc=$? $(date -Iseconds)"
done
PYTHONPATH=src .venv/bin/python -m jiezi.eval.vision report tools-off tools-on
cat var/eval/vision/report.md
