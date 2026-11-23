## Implementation Tasks / 實作任務

> **主控更正（2026-11-23，實作時）**：依 OQ1 決定，雲端不是信任等級。原草稿的 `gateway_enforce_training_use_false()`／`trust_level="cloud"` 一律改為 `TrustGate.mark_untrainable(rec, reason, model)`：寫 `rec["training_use"]=False` 與 `rec["trust"]={level, reason, provenance}`；雲端原因（cloud／cloud_hint／helper／consultation／escalation）的 provenance.source_channel="cloud"、level=unverified；injection→tainted；其餘原因（license／private／unverifiable…）source_channel="local"。`get_gate(root)` 以絕對路徑 `<root>/var/trust/taint_index.jsonl` 持久化；`injection.guard()` 回傳 `taints`（每段可疑內容各一個 sha256）。

### Phase 1: Core Trust Gate Module / 核心信任閘門模組

- [x] **T1.1** Create `src/jiezi/trust.py` with `TrustLevel`, `Provenance`, `TaintRecord`, `TrustGate` classes
  - TrustLevel IntEnum (TAINTED=0, UNVERIFIED=1, VERIFIED=2, TRUSTED=3) with property methods
  - Provenance dataclass with to_dict/from_dict, content_hash, fetched_at, version, retrieval_method
  - TaintRecord dataclass with taint_id, content_hash, detected_at, injection_type, snippet
  - TrustGate with evaluate_trust(), mark_untrainable(), taint_index LRU+TTL
  - Global `get_gate()` singleton accessor

- [x] **T1.2** Add `tests/test_trust_gate.py` unit tests
  - TrustLevel ordering and property methods (can_memory, can_skill, can_train)
  - Provenance serialization round-trip
  - TaintRecord creation and taint_id extraction (SHA-256[:16])
  - TrustGate.evaluate_trust() returns correct TrustLevel for each source_channel
  - TrustGate.taint_index deduplication across channels (same content_hash blocked)
  - TrustGate.mark_untrainable() sets training_use=false, trust.level=unverified＋provenance.source_channel=cloud, provenance
  - LRU+TTL cleanup triggers at max_records and ttl_days

### Phase 2: Memory Integration / 記憶整合

- [x] **T2.1**（W8 實作、主控修正：Memory(wiki, root) 共用 gateway 的 taint index；頁面前言記 trust_level／provenance_*；被污染的內容不寫入） Modify `src/jiezi/memory.py`
  - `render_page()` adds `trust_level`, `source_url`, `source_version`, `content_hash`, `fetched_at` to frontmatter
  - `save_answer()` calls `get_gate().evaluate_trust(content, "cloud", model, {...})` before writing
  - `save_correction()` calls `get_gate().evaluate_trust(content, "correction", "user", {...})` before writing
  - Page reading: missing trust/provenance fields default to UNVERIFIED/unknown

- [x] **T2.2**（含 TestTaintAcrossChannels：gateway 登記的污染內容擋下記憶寫入） Extend `tests/test_memory.py`
  - save_answer() frontmatter includes trust.level=unverified＋provenance.source_channel=cloud, provenance with source_channel=cloud
  - save_correction() frontmatter includes trust_level, provenance with source_channel=correction
  - Reading old pages without trust fields defaults correctly
  - Injection-detected content blocked from memory write

### Phase 3: Skills Integration / 技能整合

- [x] **T3.1**（W8 實作、主控修正：Skills(path, root)；既有技能缺欄位視為 verified——它們都由 schema 驗證成功的呼叫產生，否則現有技能會全部失效；examples 只用 verified 以上） Modify `src/jiezi/skills.py`
  - SkillItem dataclass adds `trust_level: str`, `provenance: Dict`
  - `collect()` filters: only include items with `trust_level in ("verified", "trusted")`
  - `build()` writes trust_level and provenance to skills.jsonl
  - `add()` (online learning) calls `get_gate().evaluate_trust()` before appending
  - `load_skills()` reads trust_level/provenance, defaults to UNVERIFIED

- [x] **T3.2** Create `tests/test_skills.py` (or extend existing)
  - collect() excludes UNVERIFIED and TAINTED items
  - build() output JSONL includes trust_level and provenance fields
  - add() with cloud content gets trust.level=unverified＋provenance.source_channel=cloud, not added to skills
  - add() with trusted MCP content gets trust_level=verified, added to skills

### Phase 4: Training Data Integration / 訓練資料整合

- [x] **T4.1**（2026-11-23 主控：不改既有篩選規則〔已只收本機、強驗證、授權允許〕，通過者標 trust_level=trusted＋provenance；另排除 taint index 內的答案〔why: tainted_content〕。原草稿「只收 TRUSTED」若照字面套在舊資料上會讓匯出變空，故採此解讀） Modify `src/jiezi/training_data.py`
  - `_ex()` adds `trust_level`, `provenance`, `fetched_at` to each example dict
  - `export()` filters: only `trust_level == "trusted" and training_use == True`
  - Reading: missing fields default to UNVERIFIED/unknown/fetched_at=created_at

- [x] **T4.2**（test_trust_fields_and_tainted_content） Extend `tests/test_training_data.py`
  - export() excludes UNVERIFIED, VERIFIED, CLOUD, TAINTED examples
  - export() includes only TRUSTED + training_use=True examples
  - Example dict has all new fields populated

### Phase 5: Injection Guard Integration / 注入防護整合

- [x] **T5.1** Modify `src/jiezi/injection.py`
  - `guard()` computes SHA-256 of content, sets taint_id=hash[:16], content_hash=hash
  - Returns enriched result to TrustGate for taint_index registration

- [x] **T5.2** Extend tests (in `tests/test_trust_gate.py` as `TestInjectionIntegration`)
  - guard() returns taint_id and content_hash
  - Same injected content blocked across memory/skills/training channels via taint_index

### Phase 6: Trajectory Integration / 軌跡整合

- [x] **T6.1**（2026-11-23 主控：不另加 TrajectoryRecord 欄位；`mark_untrainable` 直接把 `trust={level, reason, provenance}` 寫進軌跡紀錄 rec，JSON 照常序列化） Modify `src/jiezi/runtime/trajectory.py`
  - `TrajectoryRecord` dataclass adds `trust_level: Optional[str]`, `provenance: Optional[Dict]`
  - `record_step()` includes trust_level and provenance from gateway enforcement
  - JSON serialization includes new fields

- [x] **T6.2**（test_injection_marks_untrainable_and_registers_taint、test_cloud_answer_marked_untrainable_with_reason 檢查軌跡的 trust 欄位） Test trajectory records have trust_level/provenance

### Phase 7: Gateway / Escalation Integration / 閘道與轉交整合

- [x] **T7.1**（2026-11-23 主控：gateway 新增 `_untrainable(rec, reason, model)`→`get_gate(root).mark_untrainable`；12 處改為 license／injection／memory／private／unverifiable／cloud_hint／helper／consultation，另補雲端回答 reason=cloud；注入時把 `guard()` 的 taints 以 `register_hash` 登記進 taint index；injection 標記不被後來的原因覆蓋） Modify `src/jiezi/runtime/gateway.py`
  - Replace 7 locations setting `rec["training_use"] = False` with `get_gate(root).mark_untrainable(rec, reason, model)`
  - Reasons: "web_content", "translation", "cloud_consultation", "cloud_hint", "cloud_helper", "escalation_feedback", "mcp_tool_result"
  - Ensure trajectory records get trust.level="unverified"＋provenance.source_channel="cloud" and provenance

- [x] **T7.2**（test_injection_marks_untrainable_and_registers_taint、test_cloud_answer_marked_untrainable_with_reason） Test gateway enforcement replaces all 7 scattered writes

### Phase 8: MCP Server Integration / MCP 伺服器整合

- [x] **T8.1**（2026-11-23 主控：`agent/server.py::_trust()`，結果放 `result._meta["jiezi/trust"]`，不改 structuredContent；本 server 只讀使用者授權的檔案，一律 source_channel=mcp、預設 unverified） Modify `src/jiezi/agent/server.py`
  - In `tools/call` handler, before returning result, call `get_gate().evaluate_trust()` on tool output
  - Source channel: "mcp", source_id: server name from grants
  - Metadata: trusted=grants.is_trusted(server_name), retrieval_method="mcp_call"
  - Attach trust_level and provenance to structuredContent return

- [x] **T8.2**（2026-11-23 主控：原決定不做，後改為實作以符合規格：`Grants.trust_mcp()／is_trusted()／trusted_servers()`，存 `var/agent/trusted_mcp.json`〔不放 grants.json，因 `_write` 會整檔覆寫〕；`scripts/jiezi agent trust-mcp <name> [--remove]`，不帶名稱時列出；server 每次呼叫重讀） Add `scripts/jiezi agent trust-mcp <name>` command to mark MCP server as trusted
  - Updates grants/trust config (new file or extend Grants class)

### Phase 9: Specs / 規格文件

- [x] **T9.1**（9.x 的 delta 在提案階段已建立〔W3〕；2026-11-23 實作後由主控依實作更正：cloud 改為 provenance 標記、`mark_untrainable`、guard 回傳 dict 的 `taints`） Create `openspec/changes/add-agent-trust-gate/specs/trust-gate/spec.md` (delta spec)
  - SHALL/MUST requirements with #### Scenario blocks (Traditional Chinese + English)
  - Cover: TrustLevel semantics, Provenance structure, taint_index behavior, gateway enforcement, MCP integration

- [x] **T9.2** Update `openspec/specs/memory/spec.md` (delta) - add trust/provenance fields to page frontmatter
- [x] **T9.3** Create `openspec/specs/skills/spec.md` (delta) - skill item trust/provenance, collect filter
- [x] **T9.4** Update `openspec/specs/training-data/spec.md` (delta) - example trust/provenance/fetched_at, export filter
- [x] **T9.5** Update `openspec/specs/injection-guard/spec.md` (delta) - guard returns taint_id, cross-channel isolation
- [x] **T9.6** Update `openspec/specs/trajectory/spec.md` (delta) - record trust_level/provenance
- [x] **T9.7** Create `openspec/specs/escalation/spec.md` (delta) - cloud output enforcement

### Phase 10: Validation & Polish / 驗證與收尾

- [x] **T10.1** Run `openspec validate add-agent-trust-gate --strict` - must pass
- [x] **T10.2** Run `openspec validate --all --strict` - must pass
- [x] **T10.3** Run `PYTHONPATH=src:tests .venv/bin/python -m unittest discover -s tests` - all tests pass
- [x] **T10.3** Run `GIT_MASTER=1 git diff --check` - no whitespace errors
- [ ] **T10.4**（未執行：專案未安裝 ruff／mypy，依使用者「不准自行安裝套件」不裝；以 `python -m py_compile` 代替，通過。要不要加進 dev 相依由使用者決定） Run `mypy src/jiezi/trust.py` and `ruff check src/jiezi/trust.py` - clean
- [x] **T10.5**（實作範圍：trust.py、injection.py、memory.py、skills.py、training_data.py、agent/server.py、agent/grants.py、runtime/gateway.py、runtime/__main__.py 與對應 tests） Verify no `src/` or `tests/` files modified outside this change scope (proposal only - wait, this IS the implementation phase)

> **Note**: This task list is for the **implementation phase**. The current phase is **proposal only** - tasks T1-T10 will be executed after the proposal is approved. The proposal deliverables are:
> - `.openspec.yaml` ✓
> - `proposal.md` ✓
> - `design.md` ✓
> - `tasks.md` ✓ (this file)
> - `specs/trust-gate/spec.md` (next)
## 歸檔前待辦 / Before archiving（主控 2026-11-23）

- [x] A1（2026-11-23 主控：W10 回報完成但檢查腳本仍有 7 個問題、且內容與實作不符〔寫成頂層 trust_level、本機回答 trusted〕，改由主控以腳本重新產生：MODIFIED＝主規格原文全文＋描述實際實作的新句與新 Scenario；未修改的需求〔Recall From Memory、escalation 各項〕移出 delta；trust-gate 收斂為 5 條 ADDED；skills 1 條 ADDED。check_modified ALL OK、strict 通過）整理 spec delta 再歸檔：MODIFIED 的 `Claude Consultation`、`Recall From Memory` 等少了主規格原有的 Scenario 文字（歸檔會整段覆蓋主規格）；trust-gate 裡的 `Test Suite`、`Code Quality`、`OpenSpec Validation` 是開發流程不是系統行為，應刪；與 skills／injection-guard 重複的需求只留一處。整理方法：每個 MODIFIED 先貼主規格原文全文，再加上新句子與新 Scenario（檢查腳本見 2026-11-23.md #3 對 A8 的做法）。
