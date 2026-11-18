## ADDED Requirements

### Requirement: Escalation Routing By Reason
The gateway SHALL send escalations whose reason is that the request does not fit the local context or that the local engine is reserved to the cloud models first when cloud escalation is configured, SHALL NOT escalate an "unsure" local answer to a question about Jiezi itself, to user feedback, or to a bare file path, SHALL NOT treat a pasted conversation transcript as a web question, and SHALL report escalations per day and reason at `/admin/escalations`.

#### Scenario: 代理程式的大請求 / A large agent request
- **WHEN** Hermes 帶 55 個工具的請求超過本機上下文，雲端轉交已開
  An agent request exceeds the local context and cloud escalation is on
- **THEN** 轉給雲端模型，不請教 Claude；統計記為「雲端・請求太大」
  It goes to the cloud model, not Claude, and is counted as such

#### Scenario: 抱怨不是問題 / Feedback is not a question
- **WHEN** 使用者說「又出現簡體中文字」，本機回答說不確定
  The user complains and the local answer says it is unsure
- **THEN** 回覆本機的回答，不轉交
  The local answer is returned without escalation
