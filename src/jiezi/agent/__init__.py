"""唯讀代理（add-agent-readonly；開發計畫 Phase 8.1、8.2）：授權資料夾內的列目錄、找檔、讀檔、檔案資訊。
Read-only agent (Phase 8.1/8.2): list, find, read and stat files inside folders the user granted.

- grants：授權資料夾（預設空的）與寫死的拒絕清單；模型與工具都不能改授權（R22.2、R22.5）。
- tools：四個唯讀工具。/ the four read-only tools.
- server：MCP stdio 子集（initialize、tools/list、tools/call），gateway 與 Hermes／OpenCode 都能接（R9）。
- audit：每個工具呼叫寫入 var/agent/audit/，不存檔案內容（R22.3）。"""
