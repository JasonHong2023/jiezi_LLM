> **狀態 / Status**：提案草稿，待使用者審閱（R4）。初稿由 OpenCode worker（nvidia-kimi-k3，兩輪）撰寫，主控（Claude Code）2026-11-23 審查更正：spec 改為正確 delta 格式；MODIFIED 需求名稱對齊主規格、刪除未變更的需求、新需求移到 ADDED（歸檔時才能正確合併）；更正 training_use 寫入點與原因。/ Draft awaiting review.

> **主控更正（2026-11-23，歸檔前）**：spec delta 最終只有 trust-gate、skills（ADDED）與 injection-guard、memory、training-data、trajectory（MODIFIED）；原列的 escalation delta 不需要（雲端標記由 trajectory 的 `trust` 欄位描述）。

> **主控更正（2026-11-23，實作時）**：依 OQ1 決定，雲端不是信任等級。原草稿的 `gateway_enforce_training_use_false()`／`trust_level="cloud"` 一律改為 `TrustGate.mark_untrainable(rec, reason, model)`：寫 `rec["training_use"]=False` 與 `rec["trust"]={level, reason, provenance}`；雲端原因（cloud／cloud_hint／helper／consultation／escalation）的 provenance.source_channel="cloud"、level=unverified；injection→tainted；其餘原因（license／private／unverifiable…）source_channel="local"。`get_gate(root)` 以絕對路徑 `<root>/var/trust/taint_index.jsonl` 持久化；`injection.guard()` 回傳 `taints`（每段可疑內容各一個 sha256）。

## Why / 動機

芥子已有 `training_use` 旗標（memory.py、trajectory.py、training_data.py、gateway.py）、防提示注入（injection.py）、技能庫僅收驗證成功呼叫（skills.py），但 **缺少統一的信任閘門**：

1. **來源信任等級缺失**：外部內容（網頁、文件、雲端回答、MCP 工具輸出）進入記憶、技能庫、訓練資料前，沒有標準化的 `trust_level` 欄位（如 `trusted` / `verified` / `unverified` / `tainted`）。現況僅靠 `training_use: false` 與注入偵測雙重防線，無法表達「可信但不可訓練」（如 MIT 授權文件）或「待人工覆核」等中間態。/ Jiezi has `training_use` flags, injection guard, and skill verification, but lacks a unified trust gate: no standardized `trust_level` for external content entering memory, skills, or training data.

2. **Provenance 不完整**：memory.py 的頁面前言僅有 `created`、`updated`、`tags`、`confidence`、`training_use`；skills.jsonl 僅有 `question`、`call`、`functions`、`used`、`at`、`trajectory_id`；training_data.py 的範例有 `source`、`license`、`sha256`、`origin`，但**缺少版本、擷取時間、原始 URL、checksum 或等價驗證**。無法事後追溯「這筆技能來自哪次軌跡、哪個版本的文件、何時被加入」。/ Provenance is incomplete: memory pages lack version, fetch time, source URL, checksum; skills lack origin trajectory version, document version; training data has hash but no fetch metadata.

3. **污染隔離不足**：injection.py 偵測到注入會設 `training_use=false` 並阻擋技能/記憶寫入，但 **同一筆受污染內容可能透過不同管道再次進入**（如：文件先被注入標記，後來同內容以 MCP tool result 形式回傳，繞過記憶寫入檢查）。缺少跨管道的 `taint_id` 或 `content_hash` 去重與隔離。/ Contamination isolation is insufficient: injection detection blocks skill/memory writes, but the same tainted content can re-enter via another channel (e.g., document flagged, later returns as MCP tool result, bypassing memory checks). No cross-channel `taint_id` or `content_hash` deduplication.

4. **雲端輸出禁止進訓練的強制標記分散且理由各異**：gateway.py 至少 12 處分別設 `rec["training_use"] = False`，理由各不相同：
   - 581：禁止改作的辭典 / no-derivatives dictionary
   - 606：注入偵測 / injection detected
   - 737：網頁授權不明 / page licence unknown
   - 850：記憶回覆 `training=False` / memory reply training=False
   - 1324：使用者私人檔案 / user's private files
   - 1483：翻譯不可驗證、原文多為私人文件 / unverifiable, usually private
   - 1833：受雲端提示影響 / shaped by cloud hint
   - 2076：受協助者影響（Claude 內容不當訓練資料；其他雲端待查條款） / shaped by helper
   - 2134/2149/2363：Claude 諮詢（consult_mod.TRAINING_USE = False） / Claude consultation
   **缺少單一強制點**與審計線索。/ Cloud output training prohibition scattered across 12+ sites in gateway.py with distinct reasons (license, injection, private, unverifiable, cloud hint, helper, consultation), no single enforcement point or audit trail.

依 `docs/dev-plan.md` §15.5，A5 `add-agent-trust-gate` 排在 A4 之後，要求：**外部內容不可直接變成技能／訓練；來源可查；注入語料回歸通過**。本提案建立統一的 Trust Gate 機制，作為記憶、技能、訓練資料三條管道的共同前置關卡。/ Per §15.5, A5 requires: external content cannot directly become skills/training; sources traceable; injection corpus regression passes. This proposal establishes a unified Trust Gate as the common pre-gate for memory, skills, and training data pipelines.

**現況證據與檔案位置 / Current Evidence & File Locations**：

| 領域 | 檔案 | 關鍵發現 |
|------|------|----------|
| 記憶 | `src/jiezi/memory.py:144` | 頁面前言有 `training_use: false`，無 `trust_level`、`version`、`source_url`、`checksum` |
| 技能 | `src/jiezi/skills.py:69` | 技能項目只有 `at`、`trajectory_id`，無來源信任等級、文件版本、內容雜湊 |
| 訓練資料 | `src/jiezi/training_data.py:74` | 有 `source`、`license`、`sha256`、`origin`，但無 `fetched_at`、`source_version`、`trust_level` |
| 注入防護 | `src/jiezi/injection.py:92` | 偵測到注入設 `training_use=false`、阻擋技能/記憶，但無跨管道 `taint_id` |
| 軌跡 | `src/jiezi/runtime/trajectory.py` | `training_use` 欄位：Claude 為 `false`，其他為 `null`（需授權表判斷） |
| 雲端轉交 | `src/jiezi/runtime/gateway.py:581,606,737,850,1324,1483,1833,2076,2134,2149,2363` | 12+ 處分別寫 `rec["training_use"] = False`，理由各異（license、injection、private、unverifiable、cloud_hint、helper、consultation），無統一強制點 |

## What Changes / 變更內容

1. **新增 `src/jiezi/trust.py`**：Trust Gate 核心模組，定義 `TrustLevel`、`Provenance`、`TaintRecord` 資料結構；提供 `evaluate_trust(content, source_channel, metadata)` 統一判斷函式。
2. **擴充記憶頁面前言**：新增 `trust_level`、`source_url`、`source_version`、`content_hash`、`fetched_at` 欄位；`render_page` 自動填入。
3. **擴充技能項目**：`skills.jsonl` 每筆新增 `trust_level`、`provenance`（含 `source_channel`、`source_id`、`content_hash`、`fetched_at`）；`collect()`、`build()`、`add()` 同步寫入。
4. **擴充訓練資料範例**：`_ex()` 產出的範例新增 `trust_level`、`provenance`、`fetched_at`；`export()` 只匯出 `trust_level in (Trusted, Verified)` 且 `training_use=True` 的範例。
5. **注入防護整合**：`injection.guard()` 偵測到注入時，回傳 `taint_id`（內容 SHA-256 前 16 碼）；Trust Gate 維護 `taint_index`，跨管道攔截相同雜湊內容。
6. **雲端輸出統一強制點**：新增 `mark_untrainable(rec, reason, model)` 單一函式，取代 12+ 處分散寫法；`reason` 欄位保留具體原因（`license`、`injection`、`private`、`unverifiable`、`cloud_hint`、`helper`、`consultation` 等），不是全部標 `cloud`；寫入軌跡時自動附加 `trust.level: unverified`＋`provenance.source_channel: cloud`、`provenance: {source: "cloud", model: ..., at: ..., extra: {reason: ...}}`。
7. **MCP 工具輸出納入 Trust Gate**：`agent/server.py` 的 `tools/call` 回傳前，經 Trust Gate 評估 `trust_level`（預設 `unverified`，受信任 server 可標 `verified`），並記錄 `provenance`。

## Non-Goals / 不做的範圍

- 不新增外部服務、資料庫、連接埠、模型或 GPU 負載。/ No new external service, database, port, model, or GPU load.
- 不改核心 `qwen3.5-4b-q4_k_m`、P1–P8、D1–D12、G1–G5 或 Phase 0–8 主時程。/ No change to core model, principles, decisions, gates, or main schedule.
- 不實作人工覆核 UI（屬於後續 `add-agent-approval` 或 dashboard 擴充）。/ No manual review UI (belongs to later `add-agent-approval` or dashboard).
- 不變更既有 `training_use` 語意，只在其之上疊加 `trust_level` 與 `provenance`。/ Existing `training_use` semantics unchanged; only layered with `trust_level` and `provenance`.
- 不處理第三方 MCP server 的完整 OAuth/HTTP 授權流（Phase 8 再做）。/ No full OAuth/HTTP auth for third-party MCP servers (Phase 8).

## Capabilities / 能力

### New Capabilities / 新增能力

- `trust-gate`：統一的外部內容信任評估、provenance 記錄、污染隔離與雲端輸出強制標記。/ Unified external content trust evaluation, provenance recording, contamination isolation, and cloud output mandatory labeling.

### Modified Capabilities / 修改能力

- `memory`：頁面前言新增 trust/provenance 欄位；`save_answer()`、`save_correction()` 經 Trust Gate 寫入。/ Page frontmatter gains trust/provenance fields; writes go through Trust Gate.
- `skills`：技能項目新增 trust/provenance；收集與即時學習經 Trust Gate 過濾。/ Skill items gain trust/provenance; collection and online learning filtered by Trust Gate.
- `training-data`：範例新增 trust/provenance/fetched_at；匯出門檻加入 `trust_level` 條件。/ Examples gain trust/provenance/fetched_at; export gate adds trust_level condition.
- `injection-guard`：偵測結果回傳 `taint_id`、`content_hash`；Trust Gate 維護跨管道污染索引。/ Detection returns `taint_id`, `content_hash`; Trust Gate maintains cross-channel taint index.
- `trajectory`：記錄新增 `trust_level`、`provenance` 欄位。/ Records gain trust_level and provenance fields.
- `escalation` / `gateway`：雲端輸出統一經 `mark_untrainable()`，自動附加 trust/provenance。/ Cloud outputs go through single enforcement function with auto trust/provenance.

## Impact / 影響

- **程式碼 / Code**：新增 `src/jiezi/trust.py`；修改 `memory.py`、`skills.py`、`training_data.py`、`injection.py`、`runtime/trajectory.py`、`runtime/gateway.py`、`agent/server.py`。
- **測試 / Tests**：新增 `tests/test_trust_gate.py`、擴充 `tests/test_memory.py`、`tests/test_skills.py`、`tests/test_training_data.py`、`tests/test_injection.py`。
- **規格 / Specs**：新增 delta `specs/trust-gate/spec.md`（ADDED）；修改 delta `specs/memory/spec.md`、`specs/training-data/spec.md`、`specs/injection-guard/spec.md`、`specs/trajectory/spec.md`、`specs/escalation/spec.md`（MODIFIED）；新增 delta `specs/skills/spec.md`（ADDED，因 openspec/specs/ 無 skills）。
- **驗證 / Validation**：`openspec validate add-agent-trust-gate --strict`、`openspec validate --all --strict`、`PYTHONPATH=src:tests .venv/bin/python -m unittest discover -s tests`、`GIT_MASTER=1 git diff --check`。
- **分類 / Classification**：核心／既有模組（core module），不是 `SKILL` 也不是 `MCP`；此變更是安全不變量與資料管道前置關卡，不對外提供工具。/ Core module, not SKILL or MCP; this is a safety invariant and data pipeline pre-gate, not an external tool.
- **現成方案搜尋 / Existing-solution search**：沿用 `docs/dev-plan.md` §15.3 已查證的 MCP spec（authorization、access control）、Anthropic Skills（metadata、versioning）、OWASP LLM Top 10 2025（Prompt Injection、Tool Poisoning）、OWASP AI Agent Security Cheat Sheet（Memory & Context Security、Scoped Allowlist）；**併入 `web-research.md` A5 段**：
  - OWASP Agent Memory Guard（ASI06 記憶污染參考實作；detectors＋宣告式政策）https://owasp.org/projects/agent-memory-guard
  - memward（PyPI）：每筆記憶標來源與信任層級；網頁來源一律不可信，不可主導工具選擇 https://pypi.org/project/memward/
  - Flynn memory guard（Go）：信任＝寫入來源的純函式（TrustOf）https://pkg.go.dev/github.com/ionalpha/flynn/memory/guard
  - memgar（PyPI，MIT）：快照、hash、provenance、簽章、diff、rollback；自報偵測 94.6%／誤報 6.0%（未獨立驗證）https://pypi.org/project/memgar/
  - memshield、agent-memory-guard（PyPI）：包裝向量庫、檢查取回片段 https://pypi.org/project/memshield/、https://pypi.org/project/agent-memory-guard/
  - SMSR（arXiv 2606.12703）：HMAC provenance＋隨機消融多數決，研究論文非套件 https://arxiv.org/html/2606.12703
  - **結論**：多為年輕專案、自述數字。「來源決定信任」的模式可直接採用；**核心內建、不新增相依**；若要引入套件須另做 OSV／授權掃描交使用者決定。/ Reuse verified docs from §15.3; incorporate A5 from web-research.md: OWASP Agent Memory Guard, memward, Flynn, memgar, memshield, SMSR. Core built-in, no new deps; if any package is to be adopted, separate OSV/license scan required for user decision.
- **資安掃描 / Security scan**：無新相依、連接埠、權限或模型；主要殘留風險是 `taint_index` 記憶體無限成長（以 LRU + TTL 緩解）、provenance 欄位洩漏內部路徑（僅記錄邏輯 source_id，不記實體路徑）、hash 碰撞極低機率可忽略。/ No new dependency, port, permission, or model; residual risks: `taint_index` unbounded growth (mitigated by LRU+TTL), provenance leaking internal paths (only logical source_id recorded), hash collision negligible.

## Open Questions / 交使用者決定的選項

1. **TrustLevel 等級數與命名**：
   - 方案 A（四級）：`trusted`（可訓練、可技能、可記憶）> `verified`（可技能、可記憶、不可訓練）> `unverified`（僅可記憶、不可技能、不可訓練）> `tainted`（完全隔離） — `cloud` 作為 Provenance `source_type` 特殊標記，不納入排序
   - 方案 B（五級，分離 cloud）：在 A 基礎上把 `cloud` 獨立為第 5 級，不納入信任排序
   - **建議**：方案 A，`cloud` 作為特殊標記而非排序等級；`trust_level` 用排序值，`source_type` 區分 cloud
   - **請使用者確認**

2. **Provenance 結構是否對齊 W3C PROV-O / in-toto / SLSA**：
   - 完整對齊會增加欄位（`agent`、`activity`、`entity`、`generation`、`derivation`）；目前只需 `source_channel`、`source_id`、`content_hash`、`fetched_at`、`version`、`retrieval_method`
   - **建議**：最小集優先，預留 `prov:` 前綴欄位供未來擴充
   - **請使用者確認**

3. **Taint Index 保存策略**：
   - 僅記憶體（重啟失效，簡單但注入語料回歸需重跑）
   - 持久化到 `var/trust/taint_index.jsonl`（重啟保留，需定期清理）
   - **建議**：持久化 + 每日清理超過 30 天記錄
   - **請使用者確認**

4. **MCP Tool 信任預設值**：
   - 預設 `unverified`（保守，需人工標記 trusted server）
   - 預設 `verified`（寬鬆，本機 stdio server 視為可信）
   - **建議**：預設 `unverified`，`scripts/jiezi agent trust-mcp <name>` 手動升級
   - **請使用者確認**

5. **現有資料遷移**：
   - 現有 memory pages、skills、training data 缺少 trust/provenance 欄位，是否需一次性回填腳本
   - **建議**：不強制回填，讀取時缺失視為 `unverified`/`unknown`，新寫入自動補全
   - **請使用者確認**