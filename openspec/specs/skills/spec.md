# skills Specification

## Purpose
TBD - created by archiving change add-agent-trust-gate. Update Purpose after archive.
## Requirements
### Requirement: Skill Trust / 技能的信任等級
技能庫 SHALL 只用 `verified` 以上的範例作答時參考；新學到的技能（schema 驗證成功的工具呼叫）SHALL 記錄 `trust_level` 與 provenance；本功能之前存下、缺欄位的技能 SHALL 視為 `verified`（它們都由 schema 驗證成功的呼叫產生），否則既有技能會全部失效。
Only verified-or-better examples SHALL be used; new skills record trust and provenance; older skills without the fields SHALL count as verified.

#### Scenario: 舊技能照常可用 / Old skills still work

- **WHEN** 技能檔裡有本功能之前存的範例
  The skill file holds examples saved before this change
- **THEN** 它們照常被挑選作為範例
  They are still picked as examples

#### Scenario: 未驗證的不用 / Unverified ones are skipped

- **WHEN** 技能檔裡有一筆 `trust_level: unverified`
  A skill row is marked unverified
- **THEN** 作答時不會被挑選
  It is never picked

