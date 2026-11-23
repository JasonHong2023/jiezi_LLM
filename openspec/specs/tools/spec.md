# tools Specification

## Purpose
TBD - created by archiving change add-tools. Update Purpose after archive.
## Requirements
### Requirement: Computed Facts

問題含算式、單位換算或日期計算時，gateway SHALL 由程式算出結果附給模型，並 SHALL 在回答後附上計算結果；計算 SHALL NOT 使用 eval，且 SHALL 不把模型名稱、日期、電話號碼當成算式。
For arithmetic, unit or date questions the gateway SHALL compute the result in code, attach it, and append it after the answer; it SHALL NOT use eval and SHALL NOT treat model names, dates or phone numbers as expressions.

#### Scenario: 算錯的題目 / A wrong claim

- **WHEN** 使用者問「1+3=2 多少?」
  The user asks "1+3=2 多少?"
- **THEN** 模型收到「1+3 = 4（題目寫的 2 不正確）」
  The model receives that 1+3 is 4 and the claim of 2 is wrong

#### Scenario: 模型算錯 / The model errs

- **WHEN** 問「2^10 是多少」，本機模型回答 2048
  The local model answers 2048 to 2^10
- **THEN** 答案查核不通過，本機帶著錯誤說明重答
  The grounded check fails and the model retries

#### Scenario: 不是算式 / Not an expression

- **WHEN** 使用者問「Qwen3.5-2B 是什麼」或提到電話「0912-345-678」
  The user mentions a model name or a phone number
- **THEN** 不附計算結果
  No computed facts are attached

### Requirement: Optional external MCP tool registration / 可選外部 MCP 工具註冊

The tools capability SHALL register an optional external MCP tool only when it is explicitly enabled, passes the capability's policy validation, and appears in the approved allowlist. / tools 能力 SHALL 只有在明確啟用、通過該能力的政策驗證且出現在核准白名單時，才註冊可選外部 MCP 工具。

#### Scenario: External tool not enabled / 外部工具未啟用

- **WHEN** the external MCP capability switch is off. / **WHEN** 外部 MCP 能力開關為 off。
- **THEN** the tools registry contains no tool from that server. / **THEN** 工具登錄不含該伺服器的任何工具。

#### Scenario: Enabled but policy fails / 已啟用但政策失敗

- **WHEN** the capability is enabled but a tool fails URL, allowlist, or dependency-security validation. / **WHEN** 能力已啟用但工具未通過 URL、白名單或相依資安驗證。
- **THEN** the tool is not registered and the rejection reason is recorded. / **THEN** 工具不註冊，並記錄拒絕原因。

#### Scenario: Preferred backend fails over / 首選後端回退（R19.4）

- **WHEN** the preferred `web-fetch` backend is unavailable and the `scrapling` fallback passes the opt-in switch and all policy/security gates. / **WHEN** 首選 `web-fetch` 後端不可用，且 `scrapling` 回退通過 opt-in 開關與所有政策／資安關卡。
- **THEN** the tools registry MAY register the approved `scrapling` subset and SHALL record the fallback decision. / **THEN** 工具登錄 MAY 註冊核准的 `scrapling` 子集，並 SHALL 記錄回退決定。

