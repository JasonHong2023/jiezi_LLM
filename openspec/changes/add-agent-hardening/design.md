## Context / 背景

芥子已有有限代理迴圈、唯讀 MCP 工具、grant、稽核、注入防護與本機軌跡，但上限常數重複定義於 `loop.py` 與 `contract.py`，紅隊案例散落在 `tests/test_agent.py`、`tests/test_injection.py` 與文件中。 / Jiezi already has a bounded agent loop, read-only MCP tools, grants, audit, injection guard, and local trajectories, but limit constants are duplicated in `loop.py` and `contract.py`, while red-team cases are scattered across `tests/test_agent.py`, `tests/test_injection.py`, and prose.

`docs/dev-plan.md` §15.5 把 A2 `add-agent-hardening` 排在 A1 之後，要求在既有 642 項基線與目前 711 項測試上不退化，維持唯讀代理 6/6、中止 ≤ 1 秒與紅隊案例全過。 / `docs/dev-plan.md` §15.5 places A2 `add-agent-hardening` after A1, requiring no regression from the original 642-test baseline and the current 711 tests, while preserving read-only agent 6/6, stop within 1 second, and all red-team cases passing.

本變更依 §15.2 歸類為核心／既有模組，不是 `SKILL` 或 `MCP`；現成方案搜尋沿用 §15.3 已查證的 MCP spec、Anthropic Skills／Building effective agents、OWASP LLM Top 10 2025 與 Agent Security Cheat Sheet；§15.4 的資安準則直接套用。 / Per §15.2 this change is classified as a core/existing module, not a `SKILL` or `MCP`; the existing-solution search reuses the official documents already checked in §15.3, and the §15.4 security guidance applies directly.

Constraints / 限制：R1 雙語、R4 核准後施工、R8 小任務、R15 高代價選項先問、R18 資源預算、R19.4 更正不刪除、R21 可攜性、R22 最小權限、R23 禁用高風險技術；無新相依、連接埠、模型或 GPU 負載。 / Constraints: R1 bilingual writing, R4 implementation only after approval, R8 small tasks, R15 ask on costly options, R18 resource budgets, R19.4 correct without deleting, R21 portability, R22 least privilege, R23 no high-risk technology; no new dependency, port, model, or GPU load.

## Goals / Non-Goals / 目標與非目標

**Goals / 目標：**

- 建立版本化合成紅隊語料與單一回歸關卡，讓安全不變量有固定證據。 / Establish a versioned synthetic red-team corpus and a single regression gate so safety invariants have fixed evidence.
- 把上限常數收斂到 `limits.py`，讓 loop、contract 與後續 dashboard 欄位可對齊。 / Consolidate limit constants into `limits.py` so loop, contract, and later dashboard fields can align.
- 補足重複呼叫、逾時、取消、撤銷、解析後路徑、稽核無內容與多來源注入的可重複測試。 / Add repeatable tests for repeated calls, timeout, cancel, revocation, resolved paths, content-free audit, and multi-source injection.
- 維持既有行為與數值，只增加可觀測性與回歸證據。 / Preserve existing behavior and values, adding only observability and regression evidence.

**Non-Goals / 非目標：**

- 不新增寫入、shell、網路工具，不做 per-action approve、preview、dry-run 或 rollback。 / No write, shell, or network tools, and no per-action approval, preview, dry-run, or rollback.
- 不新增 `SKILL`、`MCP` server、套件、服務、連接埠、模型或 GPU 工作。 / No new `SKILL`, `MCP` server, package, service, port, model, or GPU work.
- 不改核心 `qwen3.5-4b-q4_k_m`、P1–P8、D1–D12、G1–G5 或 Phase 0–8 主時程。 / No change to core `qwen3.5-4b-q4_k_m`, P1–P8, D1–D12, G1–G5, or the main Phase 0–8 schedule.
- 不改寫 dashboard UI；大量模糊測試留到夜間另行安排。 / No dashboard UI rewrite; large fuzz runs remain a separate nightly activity.

## Decisions / 決策

1. **單一上限來源 / Single limit source**：新增 `src/jiezi/agent/limits.py`，以不可變 `EFFECTIVE_LIMITS` 保存六個上限；`loop.py` 與 `contract.py` 都改為讀取。 / Add `src/jiezi/agent/limits.py` with an immutable `EFFECTIVE_LIMITS` for six ceilings; both `loop.py` and `contract.py` consume it. 替代方案是保留重複常數並用測試比對，或缺省改環境變數；前者仍會漂移，後者新增設定表面並違反 R21。 / Alternatives were duplicated constants with equality tests, or environment overrides; the former still drifts, and the latter adds configuration surface against R21.
2. **單一語料清單 / One corpus manifest**：`tests/fixtures/agent_redteam/manifest.json` 以 `schema_version`、`categories`、`cases` 描述合成案例；案例文字直接放在 `input`，不新增大量小檔。 / Use `tests/fixtures/agent_redteam/manifest.json` with `schema_version`, `categories`, and `cases`; case text lives in `input` instead of many tiny files. 替代方案是每個案例一個檔或下載外部語料；前者增加檔案嘈雜，後者引入外部信任與機密風險。 / Alternatives were one file per case or downloading external corpora; the former adds file noise, and the latter introduces external trust and secret risk.
3. **沿用 unittest / Keep unittest**：使用現有 `PYTHONPATH=src:tests .venv/bin/python -m unittest discover -s tests`，不引入 pytest。 / Reuse the existing unittest command and introduce no pytest dependency. 替代方案是 pytest parametrize；可讀性較好但需新相依，不符合最小變更。 / Alternative was pytest parametrization; more readable but requires a new dependency and violates minimal change.
4. **確定測試與真實子行程分層 / Deterministic tests plus one real child**：大多數案例用 `FakeMcp` 與 temp dir；只保留一個真實子行程取消測試驗證 ≤ 1 秒。 / Most cases use `FakeMcp` and temp dirs; only one real child cancellation test verifies ≤ 1 second. 替代方案是每個案例走完整 gateway；會變慢且容易受排程影響。 / Alternative was full gateway for every case; slower and more scheduler-sensitive.
5. **注入語料映射既有通道 / Corpus maps to existing channels**：`web` 映射工具結果，`document` 映射附件文件，`memory` 映射 gateway 附加資料，`skill` 映射技能工具結果；不新增掃描 API。 / Map `web` to tool results, `document` to attachments, `memory` to gateway-attached data, and `skill` to skill tool results; add no scanner API. 替代方案是新增通用 source 參數；會擴大信任模型與程式碼表面。 / Alternative was a generic source parameter; that would expand the trust model and code surface.
6. **回歸閘門在一般測試執行 / Gate runs in the normal suite**：快速合成案例進 `tests/test_agent_hardening.py`，大量 fuzz 不進白天 gate。 / Fast synthetic cases go into `tests/test_agent_hardening.py`; large fuzz stays out of the daytime gate. 替代方案是把全部語料改成夜間工作；會降低每次提交的防護。 / Alternative was moving all corpus runs to nightly; that would weaken every-commit protection.

## Risks / Trade-offs / 風險與取捨

- [語料誤放真實機密 / Real secret in fixtures] → 全部案例標 `synthetic: true`、使用保留範例網域，測試拒絕未標記的 `sk-` 或憑證字串。 / Mark every case `synthetic: true`, use reserved example domains, and reject unmarked `sk-` or credential strings.
- [語料過擬合 / Corpus overfitting] → 每種來源都有正常對照，並保留零寬字元、雙語句型與使用者本人文字不變案例。 / Every source has benign controls, plus zero-width, bilingual patterns, and unchanged user-text cases.
- [取消測試不穩定 / Flaky cancellation test] → 只保留一個真實子行程測試，門檻沿用既有 ≤ 1 秒；其餘用 `FakeMcp`。 / Keep only one real child test with the existing ≤ 1 second bound; use `FakeMcp` elsewhere.
- [上限再次漂移 / Limit drift] → `EFFECTIVE_LIMITS` 為唯一來源，測試同時比對 loop、contract 與映射值。 / Make `EFFECTIVE_LIMITS` the only source and test loop, contract, and mapping values together.
- [稽核外洩內容 / Audit content leak] → 紅隊案例直接搜尋稽核檔，確認沒有注入句、檔案內容或金鑰。 / Red-team cases search audit files for injection text, file content, or keys.
- [契約與迴圈Budget不一致 / Contract-loop budget mismatch] → 測試 `effective_budget` 等於 `EFFECTIVE_LIMITS` 且超額值被 cap。 / Test that `effective_budget` equals `EFFECTIVE_LIMITS` and above-ceiling values are capped.

## Migration Plan / 遷移計畫

1. R4 核准後才 `/opsx-apply`；依 tasks.md 順序先做上限來源，再做語料、代理回歸、注入回歸、稽核與驗證。 / After R4 approval, run `/opsx-apply` and follow tasks.md: limits, corpus, agent regressions, injection regressions, audit, then validation.
2. 無執行期資料遷移、設定檔或連接埠變更；既有 trajectory 格式保持可讀。 / No runtime data migration, config, or port change; existing trajectories stay readable.
3. 完成後跑 strict validate、完整 unittest 與 `git diff --check`，再依 R19.4 在 `docs/dev-plan.md` §15.7 補完成紀錄，並更新 HANDOFF 與當日記錄。 / After implementation, run strict validation, full unittest, and `git diff --check`, then add a §15.7 completion note per R19.4 and update HANDOFF plus the daily record.
4. 回滾策略：回到本 change 前的檔案狀態；不刪既有測試與語料，必要時以新更正取代。 / Rollback: return files to the pre-change state; do not delete existing tests or corpus, and use a new correction instead when needed.

## Open Questions / 未決問題

無阻斷問題。 / No blocking questions. 可選的夜間大量 fuzz 範疇已依 `docs/dev-plan.md` §15.5 排除在本 change 之外；若核准時要調整，再提出新決策。 / The optional nightly large-fuzz scope is already excluded from this change per `docs/dev-plan.md` §15.5; if approval changes that, raise a new decision first.
