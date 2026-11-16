## ADDED Requirements

### Requirement: Statute Lookup

問題指名現行法律與條號時，gateway SHALL 附上該條原文；條號不存在時 SHALL 說明找不到而非提供其他條文；回答後 SHALL 附上原文、出處、資料日期與不構成法律意見的聲明；已廢止的法律 SHALL NOT 被當成現行法。
Named statutes and articles SHALL be attached verbatim; missing articles SHALL be reported; the appendix SHALL carry the source, data date and a not-legal-advice note; abolished laws SHALL NOT be treated as current.

#### Scenario: 中文數字條號 / Chinese numerals

- **WHEN** 使用者問「勞基法第三十二條規定什麼？」
  The user asks about 勞基法第三十二條
- **THEN** 附上《勞動基準法》第 32 條原文
  Article 32 of the Labor Standards Act is attached

#### Scenario: 不存在的條號 / A missing article

- **WHEN** 使用者問「民法第9999條」
  The user asks for a nonexistent article
- **THEN** 說明民法沒有這一條，不附其他條文
  It states the article does not exist
