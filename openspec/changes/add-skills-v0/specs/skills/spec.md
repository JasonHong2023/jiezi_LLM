## ADDED Requirements

### Requirement: Verified Tool-Call Examples

gateway SHALL 只把通過 schema 驗證的工具呼叫收進技能庫，SHALL 只附上所用函式都在本次工具清單中的範例；帶 `X-Jiezi-Eval: 1` 的評測流量 SHALL NOT 被學進技能庫或記憶。
Only schema-verified calls SHALL enter the library, only examples whose functions are available SHALL be attached, and evaluation traffic SHALL NOT be learned.

#### Scenario: 評測流量 / Evaluation traffic

- **WHEN** toolcheck 的請求得到通過驗證的工具呼叫
  A toolcheck request gets a verified call
- **THEN** 不加入技能庫
  It does not enter the library
