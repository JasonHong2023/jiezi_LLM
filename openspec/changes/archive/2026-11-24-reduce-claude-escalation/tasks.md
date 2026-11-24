## 1. 實作 / Implementation

- [x] 1.1 `_route_for`：context_too_large、engine_unavailable 先走雲端；使用者 .env 開雲端轉交
- [x] 1.2 `_keep_local`：問芥子自己、抱怨回饋、只打路徑時「不確定」不轉交
- [x] 1.3 `TRANSCRIPT`：摘要／下標題的對話貼文不判為要上網
- [x] 1.4 `/admin/escalations` 與狀態頁表格；測試（全套 615 OK）

## 2. 追蹤 / Follow-up

- [x] 2.1（2026-11-25 回報，離線從 var/trajectories 計算：policy `jiezi` 在 11-18 以前 108 題中有 46 題轉 Claude（43%）；11-19 以後 120 題只有 1 題轉 Claude（needs_web），72 題轉雲端（全是 context_too_large，即 Hermes 代理的 3 萬字以上提示，本機 4,096 槽位放不下），47 題本機回答（中位數 5.4 秒；雲端 23.5 秒）。兩段期間的請求組成不同（之後以 Hermes 為主），不是受控 A/B；正確率沒有標準答案，無法比較。結論：Claude 轉交幾乎歸零，剩下的轉交主要是代理提示太長，屬硬體上限，由免費雲端模型處理） 一週後看狀態頁：Claude 次數與原因，回報使用者
