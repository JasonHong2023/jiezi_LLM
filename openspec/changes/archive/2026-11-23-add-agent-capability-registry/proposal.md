> **狀態 / Status**：使用者 2026-11-23 授權直接實作 / User authorized direct implementation on 2026-11-23.

## Why / 動機

依 `docs/dev-plan.md` §15.5 A4，每個新功能都必須在 proposal 中提供三項證據：分類（SKILL／MCP／核心）、現成方案連結與理由、資安掃描結論；若無現成方案須寫理由；發現重大問題先停下交使用者決策。目前專案缺少一個集中、機器可讀的登錄表來追蹤這些資訊，導致審查時需人工翻閱多個 proposal。

本變更建立一個小型、只用標準函式庫的能力登錄表，將所有已完成與進行中的 change 的關鍵決策資訊集中化，並提供驗證工具確保新 proposal 都含有必要三段。

## What Changes / 變更內容

- 新增 `docs/capabilities.toml`：每個能力一筆記錄，欄位包含 `id`、`name`、`kind`（skill／mcp／core）、`change`（openspec change 名稱）、`existing_solutions`（連結或「無，理由：…」）、`security_scan`（日期＋結論 ok／issues）、`version`、`owner`、`removal_condition`、`status`。先填入已完成且 tasks 全勾的 5 個 change：`add-agent-contract`、`add-agent-hardening`、`add-scrapling-web-read`、`add-client-tool-filter`、`add-holiday-tool`；取不到資料處標註 "unknown" 並在報告列出。
- 新增 `src/jiezi/capabilities.py`：提供 `load()`、`validate()`（缺欄位、kind 不合法、existing_solutions 空且無理由、security_scan 結論為 issues 但 status=enabled → 錯誤）、以及 `check_proposals(root)` 檢查 `openspec/changes/` 下每個 change 的 `proposal.md` 都含「分類」「現成方案」「資安掃描」三段（回傳缺項清單，不丟例外）。
- 在 `src/jiezi/cli/` 現有 CLI 加子命令 `jiezi capabilities check`，呼叫上述驗證並輸出結果。
- 新增 `tests/test_capabilities.py`（unittest）覆蓋載入、驗證、缺項偵測、CLI 輸出。

### Non-Goals / 不做的範圍

- 不新增任何外部相依套件（只用標準函式庫 `tomllib`／`json`、`pathlib`、`re`）。
- 不新增服務、連接埠、模型、GPU 負載、背景進程。
- 不改核心 `qwen3.5-4b-q4_k_m`、P1–P8、D1–D12、G1–G5、Phase 0–8 主時程。
- 不建立新檔案格式版本機制；TOML 結構若需擴充直接加欄位，舊欄位不刪。

## Capabilities / 能力

### New Capabilities / 新增能力

- `agent-capability-registry`：集中化能力決策登錄表、載入驗證模組、proposal 三段檢查器、CLI 子命令。

### Modified Capabilities / 修改能力

- 無正式 delta。既有 `cli` 註冊機制被擴充以支援 `capabilities` 子命令群組。

## Impact / 影響

- 程式碼 / Code：新增 `src/jiezi/capabilities.py`、`src/jiezi/cli/capabilities.py`、測試檔；修改 `src/jiezi/cli/__init__.py` 註冊子命令。
- 測試 / Tests：新增 `tests/test_capabilities.py`。
- 規格 / Specs：新增 delta `specs/agent-capability-registry/spec.md`。
- 驗證 / Validation：`openspec validate add-agent-capability-registry --strict`、`openspec validate --all --strict`、`PYTHONPATH=src:tests .venv/bin/python -m unittest discover -s tests`、`GIT_MASTER=1 git diff --check`。
- 分類 / Classification：**核心／既有模組（core module）**，不是 `SKILL`，也不是 `MCP`。理由：此變更是內部決策追蹤與驗證工具，不對外暴露工具、不啟動獨立服務、不引入新傳輸協定、不處理敏感資料。依 `docs/dev-plan.md` §15.2 判定流程：提供工具→否；獨立服務→否；新傳輸→否→歸類為核心模組。
- 現成方案搜尋 / Existing-solution search：
  1. **OpenSpec 內建 change 追蹤**：OpenSpec CLI 已有 `openspec list`、`openspec status`、`openspec show`，但不包含分類、現成方案、資安掃描三欄的結構化查詢；本變更補足此缺口。
  2. **依賴掃描工具**（`pip-audit`、`cargo audit`、`npm audit`）：針對套件相依，不涵蓋功能層級的分類與現成方案決策。
  3. **SBOM（Software Bill of Materials）格式**（SPDX、CycloneDX）：適用於供應鏈透明化，非為專案內部功能決策登錄設計。
  4. **結論**：無現成方案滿足「功能級分類＋現成方案連結＋資安掃描」三合一的輕量本機登錄需求，故自行實作。
- 資安掃描 / Security scan：
  - 無新增相依套件、連接埠、權限、模型或服務。
  - 唯一讀取路徑為 `openspec/changes/` 與 `docs/capabilities.toml`，皆為本機唯讀文件，無注入風險。
  - 主要殘留風險：TOML 檔被惡意修改導致驗證誤判；緩解：`validate()` 嚴格檢查欄位與邏輯、CLI 僅輸出不寫入、建議配合 git 變更追蹤。

## 已完成 Change 資料摘錄 / Completed Changes Data Extraction

以下 5 個 change 的關鍵欄位將填入 `docs/capabilities.toml`：

| change | kind | existing_solutions | security_scan | version | owner | removal_condition | status |
|---|---|---|---|---|---|---|---|
| add-agent-contract | core | MCP spec、Anthropic Skills、OWASP LLM Top 10 2025、OWASP Agent Security Cheat Sheet（dev-plan §15.3 已查）；本變更沿用 bounded loop 與 least privilege，不引入新套件 | 2026-11-19 ok（無新相依、連接埠、權限、機密處理；殘留風險：contract 文字被當成可信指令，以 metadata-only 處理與 injection guard 緩解） | 1.0.0 | JasonHong | 若核心循環改為非 contract 架構，移除 contract.py 與相關測試 | enabled |
| add-agent-hardening | core | MCP spec、Anthropic Skills、OWASP LLM Top 10 2025、OWASP Agent Security Cheat Sheet（dev-plan §15.3 已查）；不引入新套件 | 2026-11-20 ok（無新相依、連接埠、權限、模型；殘留風險：語料誤放真實機密或過擬合，以合成資料、掃描檢查、正常對照緩解） | 1.0.0 | JasonHong | 若 agent 循環架構重寫且不再需要回歸關卡，移除 limits.py、紅隊語料與測試 | enabled |
| add-scrapling-web-read | mcp | Scrapling 官方 MCP server 與 Agent Skill（PyPI 0.5.1、BSD-3-Clause）；OSV 查詢 scrapling 本體空、相依 lxml/orjson/curl_cffi/protego/markdownify 無命中；anyio 4.14.0 High（修復 4.14.2）、mcp 2.0.0 High（修復 2.2.0）→ 最低版本已提升 | 2026-11-19 ok（已鎖定修復版、pip-audit 0 findings、OSV 74 套件 0 hits、CISA KEV 0 命中；第三方稽核 17 項未全查證，故後端維持預設關閉、不建議正式啟用） | 0.5.1 | JasonHong | 關閉開關後移除 adapter、可選相依群組與文件章節即可；無資料遷移、port 或 model 狀態需清理 | disabled (opt-in) |
| add-client-tool-filter | core | RAG-MCP (arXiv 2505.03275)、Semantic Tool Discovery (arXiv 2603.20313)、ScaleMCP (arXiv 2505.06416)、Dynamic ReAct (arXiv 2509.20386)；共同模式「工具名稱＋描述建索引→取 top-k→只注入選中工具」；查無授權清楚可直接套用套件；芥子已有 embedding 引擎，故核心內建、不新增相依 | 2026-11-23 ok（工具描述注入風險經 injection.clean() 緩解；過濾掉必要工具以契約工具永不被過濾、白名單核心工具永不被過濾緩解；fallback 保留 parameters、只截短描述，命中注入句型的描述不給分；無新相依、連接埠、權限、模型） | 1.0.0 | JasonHong | 移除 tool_filter.py 與相關測試、gateway 整合點還原 | enabled |
| add-holiday-tool | core | lunar-python（已安裝、BSD-3-Clause）；本機法規資料庫《紀念日及節日實施條例》第 4、6、8 條；無其他外部套件 | 2026-11-19 ok（無新相依、連接埠、權限、模型；lunar-python 既有相依、OSV 無命中） | 1.0.0 | JasonHong | 移除 holidays 函式與測試、tools grounding 還原 | enabled |

> 註：上表中標註 "unknown" 的欄位（如確切 security_scan 日期若 proposal 未明確寫出），將在 `docs/capabilities.toml` 中以 `"unknown"` 填入，並在驗證報告列出。