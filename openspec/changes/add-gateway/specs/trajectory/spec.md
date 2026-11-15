## ADDED Requirements

### Requirement: Local Trajectory Records

每個通過金鑰檢查的請求 SHALL 在 `var/trajectories/YYYY-MM-DD.jsonl` 寫一行紀錄：ID、時間、策略、請求訊息、每一層的答案與驗證結果、最後層級、實際模型、延遲、token 與費用。紀錄 SHALL 只存在本機、不進版控。`JIEZI_TRAJECTORY=off` 時 SHALL 不寫任何紀錄；設定保留天數時，SHALL 刪除超過期限的檔案。
Every request that passes the key check SHALL produce one line in `var/trajectories/YYYY-MM-DD.jsonl`: ID, time, policy, request messages, each tier's answer and verification, final tier, actual model, latency, tokens and cost. Records SHALL stay local and never be committed. With `JIEZI_TRAJECTORY=off` nothing SHALL be written; with a retention period set, older files SHALL be deleted.

#### Scenario: 關閉軌跡 / Trajectories off

- **WHEN** `.env` 設定 `JIEZI_TRAJECTORY=off`
  `.env` sets `JIEZI_TRAJECTORY=off`
- **THEN** 請求照常處理，`var/trajectories/` 沒有新增內容，回應的 `jiezi.trajectory_id` 為空
  Requests are served as usual, nothing is added under `var/trajectories/`, and `jiezi.trajectory_id` is empty

#### Scenario: 寫入失敗 / Write failure

- **WHEN** 軌跡檔無法寫入（例如磁碟已滿）
  The trajectory file cannot be written (for example, the disk is full)
- **THEN** 請求仍正常回應，gateway 記錄警告並在 `/health` 顯示軌跡記錄異常
  The request is still answered, and the gateway logs a warning and shows the trajectory problem in `/health`
