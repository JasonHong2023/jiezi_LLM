## ADDED Requirements

### Requirement: Answer Process
Every chat completion response SHALL carry `jiezi.process`, an ordered list of the steps taken for the question — files read, data looked up, vision tools, and each answering tier with who answered, the model, the draft text of tiers that were not delivered (at most 3000 characters), the check result and the time the step finished — and the desktop front end SHALL show the answer and its references by default and the process folded.

#### Scenario: 轉給 Claude 的題目 / An escalated question
- **WHEN** 本機作答沒通過檢查，改請教 Claude
  The local answer fails its check and Claude is consulted
- **THEN** `jiezi.process` 依序有查資料、本機作答（含草稿與檢查失敗原因）、請教 Claude；網頁顯示 Claude 的回答與參考資料，「過程」收合
  The process lists the lookup, the local draft with the failed check, and the consultation; the page shows the answer with the process folded

#### Scenario: 附錄與本文分開 / Appendix apart from the answer
- **WHEN** 回答後面有【計算】或【參考資料】附錄
  The answer carries a gateway appendix
- **THEN** 網頁把附錄放在「參考資料」區，不混在回答本文裡
  The page shows it in the references area, not in the answer body
