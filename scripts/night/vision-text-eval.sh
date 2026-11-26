#!/usr/bin/env bash
# 圖中文字評測（add-image-ocr 3.2；使用者 2026-11-26「照原計畫進行」，夜間 00:00–07:00 跑）：自製 20 張繁中招牌等，
# JIEZI_IMAGE_OCR=off（只看圖）與 auto（問字時 OCR）各跑一次。用法同 vision-eval.sh：改 .env、重啟 gateway、結束時還原。
# OCR off vs auto on 20 synthetic Traditional Chinese images; resumable; stops by 06:45; restores .env and the gateway.
set -u
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"; cd "$ROOT"
log="var/eval/vision-text/night-$(date +%F).log"; mkdir -p var/eval/vision-text
exec >> "$log" 2>&1
[ -s var/eval/vision-text/set.jsonl ] || { echo "no set; run: python -m jiezi.eval.vision_text prepare"; exit 1; }
orig=$(grep '^JIEZI_IMAGE_OCR=' .env || true)
restart() { scripts/jiezi stop >/dev/null 2>&1; sleep 2; scripts/jiezi start >/dev/null 2>&1; sleep 8; }
seto() { sed -i '/^JIEZI_IMAGE_OCR=/d' .env; [ -n "$1" ] && printf '%s\n' "$1" >> .env; }
trap 'seto "$orig"; restart; echo "=== restored $(date -Iseconds)"' EXIT
for mode in off auto; do
  left=$(( $(date -d "$(date +%F) 06:45" +%s) - $(date +%s) ))
  [ "$left" -lt 300 ] && { echo "out of time before ocr-$mode"; break; }
  [ "$mode" = off ] && left=$(( left / 2 ))
  seto "JIEZI_IMAGE_OCR=$mode"; restart
  echo "=== ocr-$mode for ${left}s $(date -Iseconds)"
  PYTHONPATH=src timeout "$left" .venv/bin/python -m jiezi.eval.vision_text run "ocr-$mode" | tail -3
  echo "--- ocr-$mode rc=$? $(date -Iseconds)"
done
PYTHONPATH=src .venv/bin/python -m jiezi.eval.vision_text report ocr-off ocr-auto
cat var/eval/vision-text/report.md
