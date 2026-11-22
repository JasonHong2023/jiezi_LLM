## ADDED Requirements

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
