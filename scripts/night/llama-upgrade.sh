#!/usr/bin/env bash
# llama.cpp 升級到 b12556（使用者 2026-11-25 同意，夜間 00:00 後執行）：修 CVE-2026-133710（hrm 模型載入越界寫入，
# 50518b6）與 CVE-2026-134540（llama-server 取樣參數驗證，9f26fe1）。b12556 是同時含兩個修正的最小版本（領先原鎖定 233 commit）。
# 步驟：舊版自我測試當基準 → 卸下引擎 → 舊原始碼與建置移到備份 → 改 stack.md 鎖定 → 抓原始碼並建置（只跑 bootstrap 的
# 取得與建置兩步，不跑 uv sync，免得移除選用套件）→ 新版自我測試 → 掉超過 3 題或建置失敗就自動還原 → E0 同條件評測
# （白天主控比對 e0-qwen3.5-4b-r3）→ 資安稽核。紀錄 var/builds/upgrade-YYYY-MM-DD.log；不 commit，白天看完結果再提交。
# Upgrade llama.cpp to b12556 (both CVE fixes). Rolls back on a build failure or a selftest drop of more than 3.
set -u
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"; cd "$ROOT"
NEW=50518b64c6f2191a116d2760042f106c4b3387d7; NEW_DATE=2026-11-19; TAG=b12556
log="var/builds/upgrade-$(date +%F).log"; mkdir -p var/builds
exec >> "$log" 2>&1
pin() { .venv/bin/python -c "import sys; sys.path.insert(0, 'scripts'); from jiezi_bootstrap import source; print(source.read_pin().commit)"; }
OLD=$(pin)
echo "=== $(date -Iseconds) start: $OLD -> $NEW ($TAG)"
if [ "$OLD" = "$NEW" ]; then echo "already at $TAG"; exit 0; fi
key=$(grep '^JIEZI_GATEWAY_KEY=' .env | cut -d= -f2-)
hold() { curl -s -m 60 -X POST "http://127.0.0.1:36100/admin/unload" -H "Authorization: Bearer $key" \
  -H 'Content-Type: application/json' -d "$1"; echo; }
selftest() { scripts/jiezi selftest --policy jiezi-local | tail -1; }
correct() { sed -n 's/^\([0-9]*\)\/[0-9]* correct.*/\1/p' | tail -1; }
bk="var/builds/backup-${OLD:0:12}"

echo "--- baseline selftest (old engine) $(date -Iseconds)"
base_line=$(selftest); echo "$base_line"; base=$(echo "$base_line" | correct)

restore() {
  echo "!!! rollback: $1 $(date -Iseconds)"
  hold "{\"hold_until\": \"$(date +%F)T07:00\", \"reason\": \"llama.cpp rollback\"}"
  rm -rf vendor/llama.cpp build-cpu build-cuda
  mv "$bk/llama.cpp" vendor/llama.cpp; [ -d "$bk/build-cpu" ] && mv "$bk/build-cpu" build-cpu
  [ -d "$bk/build-cuda" ] && mv "$bk/build-cuda" build-cuda
  cp "$bk/stack.md" openspec/specs/stack.md; cp "$bk"/*.json var/builds/ 2>/dev/null
  hold '{"hold_until": null}'
  echo "rolled back to $(pin)"
}

hold "{\"hold_until\": \"$(date +%F)T07:00\", \"reason\": \"llama.cpp upgrade $TAG\"}"
mkdir -p "$bk"
mv vendor/llama.cpp "$bk/llama.cpp"; [ -d build-cpu ] && mv build-cpu "$bk/build-cpu"; [ -d build-cuda ] && mv build-cuda "$bk/build-cuda"
cp openspec/specs/stack.md "$bk/stack.md"; cp var/builds/*.json "$bk/" 2>/dev/null
sed -i "s/\`$OLD\`（2026-11-12）/\`$NEW\`（$NEW_DATE，$TAG）/" openspec/specs/stack.md
if [ "$(pin)" != "$NEW" ]; then restore "stack.md pin not updated"; exit 1; fi

echo "--- fetch and build $(date -Iseconds)"
if ! .venv/bin/python - <<'EOF'
import json, sys
from pathlib import Path
sys.path.insert(0, "scripts")
from jiezi_bootstrap import build, source
root = Path(".").resolve()
pin = source.read_pin(root / "openspec" / "specs" / "stack.md")
print("fetch:", source.fetch(root / "vendor" / "llama.cpp", pin))
facts = json.loads((root / "facts.json").read_text(encoding="utf-8"))
for s in build.build_all(facts, root / "vendor" / "llama.cpp", pin.commit, root):
    print("build:", s.get("backend"), s.get("result"), s.get("duration_s"))
EOF
then restore "fetch or build failed"; exit 1; fi
for b in build-cpu build-cuda; do
  [ -d "$bk/$b" ] && [ ! -x "$b/bin/llama-server" ] && { restore "$b/bin/llama-server missing"; exit 1; }
done
hold '{"hold_until": null}'

echo "--- selftest (new engine) $(date -Iseconds)"
new_line=$(selftest); echo "$new_line"; new=$(echo "$new_line" | correct)
if [ -n "$base" ] && { [ -z "$new" ] || [ "$new" -lt $(( base - 3 )) ]; }; then
  restore "selftest dropped: ${base:-?} -> ${new:-?}"; exit 1
fi

# E0 同條件（bank r0、ctx 4096、貪婪）重跑目前核心，和 e0-qwen3.5-4b-r3 比；評審在雲端，獨立單元
# Same E0 conditions as e0-qwen3.5-4b-r3 on the new engine; judges run in their own unit
rid="e0-qwen3.5-4b-r3-llama-$TAG"; gguf="var/train/qwen3.5-4b-r3/qwen3.5-4b-r3-Q4_K_M.gguf"
hold "{\"hold_until\": \"$(date +%F)T07:00\", \"reason\": \"E0 on llama.cpp $TAG\"}"
left=$(( $(date -d "$(date +%F) 06:45" +%s) - $(date +%s) ))
if [ -f "$gguf" ] && [ "$left" -gt 900 ]; then
  echo "=== eval $rid for ${left}s $(date -Iseconds)"
  timeout "$left" scripts/eval run --bank r0 --backend local --model "$gguf" --ngl 99 --ctx 4096 --run-id "$rid" --now
  echo "--- eval rc=$? $(date -Iseconds)"
  systemd-run --user --unit="jiezi-verify-$rid-$(date +%H%M)" --setenv=PATH="$PATH" --working-directory="$ROOT" \
    bash -c "scripts/eval verify $rid --judge-model nvidia-nemotron-3-ultra --judge-match nemotron --now >> var/builds/verify-$rid.log 2>&1"
fi
hold '{"hold_until": null}'
echo "--- audit $(date -Iseconds)"
scripts/jiezi audit | tail -1
echo "=== $(date -Iseconds) end: now at $(pin); backup kept in $bk"
