#!/usr/bin/env bash
# tune-knowledge-relevance 2.4：知識庫門檻 0.5（舊）與 0.6（新）各跑一次真實問題（jiezi-local），由 train-r1.sh 在夜間呼叫；
# 只在 var/eval/relevance-e2e/todo 存在時跑一次。用法同 recall-ab.sh：改 .env、重啟 gateway、結束時還原。
# Old (0.5) vs new (0.6) knowledge threshold on the real questions; runs once when the todo marker exists.
set -u
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"; cd "$ROOT"
dir=var/eval/relevance-e2e
orig=$(grep '^JIEZI_RAG_MIN=' .env || true)
restart() { scripts/jiezi stop >/dev/null 2>&1; sleep 2; scripts/jiezi start >/dev/null 2>&1; sleep 5; }
setmin() { sed -i '/^JIEZI_RAG_MIN=/d' .env; [ -n "$1" ] && printf '%s\n' "$1" >> .env; }
trap 'setmin "$orig"; restart' EXIT
for t in 0.5 0.6; do
  setmin "JIEZI_RAG_MIN=$t"; restart
  echo "=== relevance-e2e $t $(date -Iseconds)"
  .venv/bin/python scripts/night/relevance-e2e.py "$t" "$dir/t$t.json" | tail -2
done
