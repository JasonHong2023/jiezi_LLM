## ADDED Requirements

### Requirement: Read-Only Desktop Front End

gateway SHALL 在 `/ui/` 提供本機建好的前端，回應 SHALL 帶只允許自身來源的 CSP；前端 SHALL 只呼叫同源的 gateway，SHALL 提供一鍵中止，且 SHALL NOT 操控作業系統；稽核與狀態接口 SHALL 需要 gateway 金鑰。
The gateway SHALL serve the local build under /ui/ with a self-only CSP; the front end SHALL call only the same-origin gateway, offer one-key stop and SHALL NOT control the OS; audit and status endpoints SHALL require the key.

#### Scenario: 沒有金鑰 / No key

- **WHEN** 沒有帶金鑰呼叫 `/admin/trajectories`
  The audit endpoint is called without the key
- **THEN** 回 401
  It returns 401
