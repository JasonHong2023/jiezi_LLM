## Implementation Tasks / 實作任務

### Phase 1: Core Trust Gate Module / 核心信任閘門模組

- [ ] **T1.1** Create `src/jiezi/trust.py` with `TrustLevel`, `Provenance`, `TaintRecord`, `TrustGate` classes
  - TrustLevel IntEnum (TAINTED=0, UNVERIFIED=1, VERIFIED=2, TRUSTED=3) with property methods
  - Provenance dataclass with to_dict/from_dict, content_hash, fetched_at, version, retrieval_method
  - TaintRecord dataclass with taint_id, content_hash, detected_at, injection_type, snippet
  - TrustGate with evaluate_trust(), gateway_enforce_training_use_false(), taint_index LRU+TTL
  - Global `get_gate()` singleton accessor

- [ ] **T1.2** Add `tests/test_trust_gate.py` unit tests
  - TrustLevel ordering and property methods (can_memory, can_skill, can_train)
  - Provenance serialization round-trip
  - TaintRecord creation and taint_id extraction (SHA-256[:16])
  - TrustGate.evaluate_trust() returns correct TrustLevel for each source_channel
  - TrustGate.taint_index deduplication across channels (same content_hash blocked)
  - TrustGate.gateway_enforce_training_use_false() sets training_use=false, trust_level=cloud, provenance
  - LRU+TTL cleanup triggers at max_records and ttl_days

### Phase 2: Memory Integration / 記憶整合

- [ ] **T2.1** Modify `src/jiezi/memory.py`
  - `render_page()` adds `trust_level`, `source_url`, `source_version`, `content_hash`, `fetched_at` to frontmatter
  - `save_answer()` calls `get_gate().evaluate_trust(content, "cloud", model, {...})` before writing
  - `save_correction()` calls `get_gate().evaluate_trust(content, "correction", "user", {...})` before writing
  - Page reading: missing trust/provenance fields default to UNVERIFIED/unknown

- [ ] **T2.2** Extend `tests/test_memory.py`
  - save_answer() frontmatter includes trust_level=cloud, provenance with source_channel=cloud
  - save_correction() frontmatter includes trust_level, provenance with source_channel=correction
  - Reading old pages without trust fields defaults correctly
  - Injection-detected content blocked from memory write

### Phase 3: Skills Integration / 技能整合

- [ ] **T3.1** Modify `src/jiezi/skills.py`
  - SkillItem dataclass adds `trust_level: str`, `provenance: Dict`
  - `collect()` filters: only include items with `trust_level in ("verified", "trusted")`
  - `build()` writes trust_level and provenance to skills.jsonl
  - `add()` (online learning) calls `get_gate().evaluate_trust()` before appending
  - `load_skills()` reads trust_level/provenance, defaults to UNVERIFIED

- [ ] **T3.2** Create `tests/test_skills.py` (or extend existing)
  - collect() excludes UNVERIFIED and TAINTED items
  - build() output JSONL includes trust_level and provenance fields
  - add() with cloud content gets trust_level=cloud, not added to skills
  - add() with trusted MCP content gets trust_level=verified, added to skills

### Phase 4: Training Data Integration / 訓練資料整合

- [ ] **T4.1** Modify `src/jiezi/training_data.py`
  - `_ex()` adds `trust_level`, `provenance`, `fetched_at` to each example dict
  - `export()` filters: only `trust_level == "trusted" and training_use == True`
  - Reading: missing fields default to UNVERIFIED/unknown/fetched_at=created_at

- [ ] **T4.2** Extend `tests/test_training_data.py`
  - export() excludes UNVERIFIED, VERIFIED, CLOUD, TAINTED examples
  - export() includes only TRUSTED + training_use=True examples
  - Example dict has all new fields populated

### Phase 5: Injection Guard Integration / 注入防護整合

- [ ] **T5.1** Modify `src/jiezi/injection.py`
  - `InjectionResult` dataclass adds `taint_id: str`, `content_hash: str`
  - `guard()` computes SHA-256 of content, sets taint_id=hash[:16], content_hash=hash
  - Returns enriched result to TrustGate for taint_index registration

- [ ] **T5.2** Extend `tests/test_injection.py`
  - guard() returns taint_id and content_hash
  - Same injected content blocked across memory/skills/training channels via taint_index

### Phase 6: Trajectory Integration / 軌跡整合

- [ ] **T6.1** Modify `src/jiezi/runtime/trajectory.py`
  - `TrajectoryRecord` dataclass adds `trust_level: Optional[str]`, `provenance: Optional[Dict]`
  - `record_step()` includes trust_level and provenance from gateway enforcement
  - JSON serialization includes new fields

- [ ] **T6.2** Test trajectory records have trust_level/provenance

### Phase 7: Gateway / Escalation Integration / 閘道與轉交整合

- [ ] **T7.1** Modify `src/jiezi/runtime/gateway.py`
  - Replace 7 locations setting `rec["training_use"] = False` with `get_gate().gateway_enforce_training_use_false(rec, reason, model)`
  - Reasons: "web_content", "translation", "cloud_consultation", "cloud_hint", "cloud_helper", "escalation_feedback", "mcp_tool_result"
  - Ensure trajectory records get trust_level="cloud" and provenance

- [ ] **T7.2** Test gateway enforcement replaces all 7 scattered writes

### Phase 8: MCP Server Integration / MCP 伺服器整合

- [ ] **T8.1** Modify `src/jiezi/agent/server.py`
  - In `tools/call` handler, before returning result, call `get_gate().evaluate_trust()` on tool output
  - Source channel: "mcp", source_id: server name from grants
  - Metadata: trusted=grants.is_trusted(server_name), retrieval_method="mcp_call"
  - Attach trust_level and provenance to structuredContent return

- [ ] **T8.2** Add `scripts/jiezi agent trust-mcp <name>` command to mark MCP server as trusted
  - Updates grants/trust config (new file or extend Grants class)

### Phase 9: Specs / 規格文件

- [ ] **T9.1** Create `openspec/changes/add-agent-trust-gate/specs/trust-gate/spec.md` (delta spec)
  - SHALL/MUST requirements with #### Scenario blocks (Traditional Chinese + English)
  - Cover: TrustLevel semantics, Provenance structure, taint_index behavior, gateway enforcement, MCP integration

- [ ] **T9.2** Update `openspec/specs/memory/spec.md` (delta) - add trust/provenance fields to page frontmatter
- [ ] **T9.3** Create `openspec/specs/skills/spec.md` (delta) - skill item trust/provenance, collect filter
- [ ] **T9.4** Update `openspec/specs/training-data/spec.md` (delta) - example trust/provenance/fetched_at, export filter
- [ ] **T9.5** Update `openspec/specs/injection-guard/spec.md` (delta) - guard returns taint_id, cross-channel isolation
- [ ] **T9.6** Update `openspec/specs/trajectory/spec.md` (delta) - record trust_level/provenance
- [ ] **T9.7** Create `openspec/specs/escalation/spec.md` (delta) - cloud output enforcement

### Phase 10: Validation & Polish / 驗證與收尾

- [ ] **T10.1** Run `openspec validate add-agent-trust-gate --strict` - must pass
- [ ] **T10.2** Run `openspec validate --all --strict` - must pass
- [ ] **T10.3** Run `PYTHONPATH=src:tests .venv/bin/python -m unittest discover -s tests` - all tests pass
- [ ] **T10.3** Run `GIT_MASTER=1 git diff --check` - no whitespace errors
- [ ] **T10.4** Run `mypy src/jiezi/trust.py` and `ruff check src/jiezi/trust.py` - clean
- [ ] **T10.5** Verify no `src/` or `tests/` files modified outside this change scope (proposal only - wait, this IS the implementation phase)

> **Note**: This task list is for the **implementation phase**. The current phase is **proposal only** - tasks T1-T10 will be executed after the proposal is approved. The proposal deliverables are:
> - `.openspec.yaml` ✓
> - `proposal.md` ✓
> - `design.md` ✓
> - `tasks.md` ✓ (this file)
> - `specs/trust-gate/spec.md` (next)