## ADDED Requirements

### Requirement: Agent Tool Call Audit

代理工具呼叫稽核紀錄 SHALL 對齊 `observability.UNIFIED_FIELDS`，所有寫入 `var/audit/` 的記錄 SHALL 經 `_scrub_all()` 處理。

#### 記錄欄位 / Record Fields

| 欄位 / Field | 型別 / Type | 說明 / Description |
|------------|------------|-------------------|
| `request_id` | `str` (UUIDv4) | 關聯 trajectory |
| `timestamp` | `str` (ISO 8601 UTC) | 統一命名 |
| `tool` | `str` | 工具名稱 |
| `arguments` | `object` | 參數（經 `_scrub_text()`） |
| `allowed` | `bool` | 是否通過 grant |
| `result_summary` | `object` | `{ok: bool, result_chars: int, error_type?: str, latency_ms: int}` (經 `_scrub_tool_result()`) |
| `terminal_state` | `str` | `completed`/`failed`/`aborted`/`fail_closed` (統一值域) |
| `injection_suspected` | `bool` | 提示注入疑似 |
| `fail_closed` | `bool` | 是否觸發 fail-closed |
| `fail_closed_reason` | `str?` | 原因碼（僅 `fail_closed=true` 時） |

#### Scenario: 稽核欄位對齊 / Audit fields aligned

- **WHEN** agent 執行工具呼叫，寫入稽核紀錄。/ **WHEN** agent makes a tool call, writes audit record.
- **THEN** 紀錄含上表所有欄位、值域正確、`arguments`/`result_summary` 已遮罩。/ **THEN** record has all fields, correct domains, masked args/result.

#### Scenario: 敏感內容零洩漏 / No sensitive leakage

- **WHEN** 工具參數含 `sk-xxx`、檔案路徑含 `.env`、結果含私鑰。/ **WHEN** tool args contain secrets, paths contain .env, result contains private key.
- **THEN** 寫入 `var/audit/` 的 JSONL 經 `_scrub_all()`，無明文敏感資訊。/ **THEN** written JSONL has no plaintext secrets.