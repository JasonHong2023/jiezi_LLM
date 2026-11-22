## Why / 動機

芥子已有有限代理迴圈、唯讀工具、grant、稽核、注入防護與本機軌跡，但 A2／A4／A12／A13 的極限與紅隊行為仍散落在常數、既有測試與文件說明中，缺少固定語料與可重建的 regression gate；日後修改容易讓安全不變量在表面上全量測試通過時悄悄退化。 / Jiezi already has a bounded agent loop, read-only tools, grants, audit, injection guard, and local trajectories, but the A2/A4/A12/A13 limits and red-team behaviors remain scattered across constants, existing tests, and prose; there is no fixed corpus or reproducible regression gate, so a later edit could erode a safety invariant while the suite still looks green.

依 `docs/dev-plan.md` §15.5，A2 是 A1 之後的下一個變更；本提案先把回歸關卡與語料制度化，核准後才施工，不改核心模型、不新增外部能力、不占滿硬體。 / Under `docs/dev-plan.md` §15.5, A2 is the next change after A1; this proposal first institutionalizes the regression gate and corpus, and implementation begins only after approval, without changing the core model, adding external capabilities, or saturating hardware.

## What Changes / 變更內容

- 建立版本化、唯讀的 agent hardening 回歸語料，覆蓋步數／呼叫數／輸出字數／超時／取消、path traversal／symlink／secret deny／revoke-after-grant、注入語料，以及 token／tool／time budget 對齊。 / Add a versioned, read-only agent hardening regression corpus covering step/call/output/timeout/cancel limits, path traversal/symlink/secret deny/revoke-after-grant, injection cases, and token/tool/time budget alignment.
- 新增 `src/jiezi/agent/limits.py` 作為唯一常數來源，提供唯讀有效上限視圖；`loop.py` 與 `contract.py` 改為讀取它，常數值與 fail-closed 語意不變。 / Add `src/jiezi/agent/limits.py` as the single constant source with a read-only effective-limit view; `loop.py` and `contract.py` consume it, with values and fail-closed semantics unchanged.
- 補上重複呼叫、慢工具 timeout、取消後 process group 終止、grant 撤銷後下一次呼叫即失效等確定性測試。 / Add deterministic tests for repeated calls, slow-tool timeout, process-group termination on cancel, and grant revocation taking effect on the next call.
- 建立固定注入語料，覆蓋網頁／文件／記憶／技能四種外部來源，並包含正常對照案例，避免只靠啟發式句型造成過度標記。 / Create a fixed injection corpus covering web page, document, memory, and skill sources, with benign controls so heuristic patterns do not become over-flagging.
- 加入回歸關卡：既有測試不得低於目前 711 項（`docs/dev-plan.md` 原基線 642 項亦不得退化），紅隊案例全過，唯讀代理 6/6 與中止 ≤ 1 秒維持既有基線。 / Add a regression gate: the suite SHALL remain at or above the current 711 tests (and the original 642-test baseline in `docs/dev-plan.md`), all red-team cases SHALL pass, and the read-only agent 6/6 plus stop-within-1-second baselines SHALL hold.

### Non-Goals / 不做的範圍

- 不新增寫入、shell、網路工具，也不新增 per-action approve、dry-run 或 rollback；那些屬於 `add-agent-approval`。 / No write, shell, or network tools, and no per-action approval, dry-run, or rollback; those belong to `add-agent-approval`.
- 不新增 SKILL、MCP server、相依套件、服務、連接埠、模型或 GPU 負載。 / No new SKILL, MCP server, dependency, service, port, model, or GPU load.
- 不改核心 `qwen3.5-4b-q4_k_m`、P1–P8、D1–D12、G1–G5 或 Phase 0–8 主時程。 / No change to core `qwen3.5-4b-q4_k_m`, P1–P8, D1–D12, G1–G5, or the main Phase 0–8 schedule.
- 不把真實金鑰、`.env`、`facts.json`、模型權重或使用者機密放進語料；所有 fixture 都是合成資料。 / No real key, `.env`, `facts.json`, model weight, or user secret in the corpus; every fixture is synthetic.
- 不在本 change 改寫 dashboard UI；只提供可向後對齊的欄位與測試。 / No dashboard UI rewrite in this change; only later-alignable fields and tests.

## Capabilities / 能力

### New Capabilities / 新增能力

- `agent-hardening`: 定義版本化回歸語料、合成紅隊案例、不退化關卡與有效上限的單一來源。 / Defines the versioned regression corpus, synthetic red-team cases, non-regression gate, and single source of effective limits.

### Modified Capabilities / 修改能力

- `agent`: 新增有限迴圈上限、撤銷後即時失效、取消時限與稽核不記內容的可測試要求。 / Adds testable requirements for bounded-loop limits, immediate effect after revocation, cancellation timing, and content-free audit records.
- `injection-guard`: 新增固定多來源注入語料與正常對照案例的回歸要求。 / Adds regression requirements for a fixed multi-source injection corpus and benign controls.

## Impact / 影響

- 程式碼 / Code：新增 `src/jiezi/agent/limits.py` 唯讀上限來源；`loop.py` 與 `contract.py` 改為讀取它；必要時微調 `grants.py` 測試可觀測性，不改授權語意。 / Add `src/jiezi/agent/limits.py` as the read-only limit source; `loop.py` and `contract.py` consume it; `grants.py` may gain test observability only, with no authorization-semantics change.
- 測試 / Tests：新增 `tests/test_agent_hardening.py`、`tests/fixtures/agent_redteam/**`，並補強既有 `tests/test_agent.py` 與 `tests/test_injection.py`。 / Add `tests/test_agent_hardening.py`, `tests/fixtures/agent_redteam/**`, and strengthen `tests/test_agent.py` plus `tests/test_injection.py`.
- 規格 / Specs：新增 delta `specs/agent-hardening/spec.md`；修改 delta `specs/agent/spec.md` 與 `specs/injection-guard/spec.md`。 / Add delta `specs/agent-hardening/spec.md`; update deltas `specs/agent/spec.md` and `specs/injection-guard/spec.md`.
- 驗證 / Validation：`openspec validate --all --strict`、`PYTHONPATH=src:tests .venv/bin/python -m unittest discover -s tests`、`GIT_MASTER=1 git diff --check`；大量模糊測試僅夜間另排。 / Run strict validation, the full unit suite, and diff check; large fuzz runs are scheduled only at night.
- 分類 / Classification：核心／既有模組（core module），不是 `SKILL`，也不是 `MCP`；此變更是安全不變量與回歸關卡，不對外提供工具。 / Core module, not SKILL or MCP; this is a safety invariant and regression gate, not an external tool.
- 現成方案搜尋 / Existing-solution search：沿用 `docs/dev-plan.md` §15.3 已查證的 MCP spec、Anthropic Skills／Building effective agents、OWASP LLM Top 10 2025 與 Agent Security Cheat Sheet；本變更不引入新套件。 / Reuse the official documents already checked in `docs/dev-plan.md` §15.3; no new dependency is introduced.
- 資安掃描 / Security scan：無新相依、連接埠、權限或模型；主要殘留風險是語料誤放真實機密或語料過擬合，以合成資料、掃描檢查與正常對照案例緩解。 / No new dependency, port, permission, or model; the main residual risks are real secrets entering fixtures and corpus overfitting, mitigated by synthetic data, scanning checks, and benign controls.
