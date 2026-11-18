#!/usr/bin/env bash
# add-chunk-recall 2.1：依序以 JIEZI_DOC_RECALL=off／reserve／hyde 重啟 gateway 並量測；結束（或失敗）時還原 .env 原本的設定。
# Measure chunk recall modes one by one, restarting the gateway; the original .env line is restored on exit.
set -u
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"; cd "$ROOT"
dir=var/eval/recall-ab
orig=$(grep '^JIEZI_DOC_RECALL=' .env || true)
restart() { scripts/jiezi stop >/dev/null 2>&1; sleep 2; scripts/jiezi start >/dev/null 2>&1; sleep 5; }
setmode() { sed -i '/^JIEZI_DOC_RECALL=/d' .env; [ -n "$1" ] && printf '%s\n' "$1" >> .env; }
trap 'setmode "$orig"; restart' EXIT
for mode in off reserve hyde; do
  setmode "JIEZI_DOC_RECALL=$mode"; restart
  echo "=== recall $mode $(date -Iseconds)"
  .venv/bin/python scripts/night/recall-ab.py "$dir" "$mode" "$dir/$mode.json" | tail -3
done
