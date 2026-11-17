> 使用者 2026-11-17 同意（OQ1–OQ4 照建議）。/ Approved 2026-11-17.

- [x] 1.1 授權：`grants.toml` 讀取、路徑解析與比對、寫死的拒絕清單、`scripts/jiezi agent grant|revoke|grants` / grants, path resolution, hard deny list, CLI
- [x] 1.2 工具伺服器：MCP stdio 子集（initialize、tools/list、tools/call）與四個唯讀工具（上限、截短說明、清理）/ MCP stdio subset and four read-only tools
- [x] 1.3 稽核紀錄與 `scripts/jiezi agent audit`；桌面網頁稽核頁顯示 / audit log and views
- [x] 1.4 gateway 代理迴圈：`jiezi_agent`、schema 與授權檢查、結果當資料、步數上限、每步回報、中斷即停、轉交時的內容規則、`JIEZI_AGENT`、`training_use=false` / gateway loop
- [x] 1.5 客戶端：chat `/agent on|off`、桌面網頁開關與步驟顯示 / clients
- [x] 1.6 單元測試（授權外拒絕、符號連結逃逸、拒絕清單、工具結果中的注入不會擴權、步數上限、中止）；R12 流程圖、`docs/clients.md`；`openspec validate add-agent-readonly --strict` / tests and docs
- [ ] 2.1 量測（與實作分開）：G1 選定核心後，5 題固定任務的完成率、每題步數與耗時、中止時間（目標 ≤ 1 秒）/ fixed-task measurement after G1
