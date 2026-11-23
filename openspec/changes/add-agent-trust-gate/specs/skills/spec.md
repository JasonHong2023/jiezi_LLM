## ADDED Requirements

### Requirement: Skill Item Trust Fields / 技能項目信任欄位

Each skill item in `skills.jsonl` SHALL have:

`skills.jsonl` 中的每個技能項目必須包含：

| Field / 欄位 | Description / 說明 |
|-------------|------------------|
| `trust_level` | `"verified" | "trusted"` (UNVERIFIED and TAINTED excluded) / `"verified" | "trusted"`（排除 UNVERIFIED 和 TAINTED） |
| `provenance` | Full Provenance object / 完整 Provenance 物件 |

#### Scenario: Skill Item Has Trust Fields / 技能項目包含信任欄位

```gherkin
Given a skill learned via SkillBuilder.add() from a trusted MCP server
When the skill item is written to skills.jsonl
Then it contains trust_level == "verified"
And it contains provenance with source_channel == "mcp"
And provenance.content_hash matches the skill content
```

---

### Requirement: Collect Filter / 收集過濾

`SkillCollector.collect()` SHALL only include skill items where `trust_level` is `VERIFIED` or `TRUSTED`. Items with `UNVERIFIED`, `TAINTED`, or `CLOUD` SHALL be excluded.

`SkillCollector.collect()` 必須只包含 `trust_level` 為 `VERIFIED` 或 `TRUSTED` 的技能項目。`UNVERIFIED`、`TAINTED`、`CLOUD` 的項目必須被排除。

#### Scenario: Unverified Skills Not Collected / 未驗證技能不被收集

```gherkin
Given skills.jsonl contains items with trust_level: trusted, verified, unverified, cloud, tainted
When SkillCollector.collect() runs
Then only trusted and verified items are returned
And unverified, cloud, tainted items are excluded
```

#### Scenario: Cloud Skills Not Collected / 雲端技能不被收集

```gherkin
Given a skill learned from Claude consultation (trust.level="unverified"＋provenance.source_channel="cloud")
When SkillCollector.collect() runs
Then the cloud skill is excluded from collected skills
```

---

### Requirement: Online Learning Trust Gate / 線上學習信任閘門

`SkillBuilder.add()` (online learning) SHALL call `TrustGate.evaluate_trust()` on the new skill content before appending. Only content with `trust_level >= VERIFIED` SHALL be added.

`SkillBuilder.add()`（線上學習）在附加新技能前必須呼叫 `TrustGate.evaluate_trust()`。只有 `trust_level >= VERIFIED` 的內容才能被加入。

#### Scenario: Cloud Skill Not Added Online / 雲端技能不被線上加入

```gherkin
Given a cloud consultation produces a valid tool call
When SkillBuilder.add() attempts to learn it online
Then TrustGate evaluates it as trust.level="unverified"＋provenance.source_channel="cloud" (UNVERIFIED base)
And the skill is NOT added to skills.jsonl
And no error is raised (silently dropped per UNVERIFIED.can_skill == False)
```

#### Scenario: Verified MCP Skill Added Online / 受信 MCP 技能被線上加入

```gherkin
Given a trusted MCP server "internal-tools" returns a valid tool call
When SkillBuilder.add() attempts to learn it online
Then TrustGate evaluates it as trust_level="verified"
And the skill IS added to skills.jsonl with trust_level="verified" and provenance
```

#### Scenario: User Explicitly Trusted Skill Added / 使用者明確信任的技能被加入

```gherkin
Given user explicitly marks a skill as trusted via trust-mcp or similar
When SkillBuilder.add() attempts to learn it
Then TrustGate evaluates it as trust_level="trusted"
And the skill IS added with trust_level="trusted"
```

---

### Requirement: Trust Management Command / 信任管理指令

The system SHALL provide `scripts/jiezi agent trust-mcp <name>` to mark/unmark MCP servers as trusted. This SHALL persist to a configuration file readable by `Grants.is_trusted()`.

系統必須提供 `scripts/jiezi agent trust-mcp <name>` 來標記/取消標記 MCP 伺服器為受信。此設定必須持久化至 `Grants.is_trusted()` 可讀取的設定檔。

#### Scenario: Trust MCP Command Marks Server / trust-mcp 指令標記伺服器

```gherkin
Given no trusted MCP servers configured
When scripts/jiezi agent trust-mcp internal-tools is run
Then Grants.is_trusted("internal-tools") returns True
And subsequent tool outputs from internal-tools receive VERIFIED trust level
```

#### Scenario: Untrust MCP Command Removes Trust / 取消信任指令移除受信

```gherkin
Given MCP server "internal-tools" is marked trusted
When scripts/jiezi agent trust-mcp --remove internal-tools is run
Then Grants.is_trusted("internal-tools") returns False
And subsequent tool outputs from internal-tools receive UNVERIFIED trust level
```

---

### Requirement: Migration & Backwards Compatibility / 遷移與向後相容

When reading existing skill items that lack `trust_level` or `provenance` fields, the system SHALL default `trust_level` to `"unverified"` and `provenance` to `{"source_channel": "unknown"}`. No bulk backfill script SHALL be provided.

讀取缺少 `trust_level` 或 `provenance` 欄位的既有技能項目時，系統必須將 `trust_level` 預設為 `"unverified"`、`provenance` 預設為 `{"source_channel": "unknown"}`。不提供批量回填腳本。

- `trust_level` SHALL default to `"unverified"` / `trust_level` 預設為 `"unverified"`
- `provenance` SHALL default to `{"source_channel": "unknown"}` / `provenance` 預設為 `{"source_channel": "unknown"}`

No bulk backfill script SHALL be provided.

不提供批量回填腳本。

#### Scenario: Legacy Skill Defaults / 舊技能預設值

```gherkin
Given a skill item created before trust-gate with no trust_level field
When the skill is read by SkillCollector.collect()
Then trust_level defaults to "unverified"
And provenance defaults to {"source_channel": "unknown"}
And the skill is excluded from collection (UNVERIFIED.can_skill == False)
```