## ADDED Requirements

### Requirement: Process View Interface / 處理視圖介面

系統 SHALL 定義既有 `src/jiezi/runtime/process.py` 的對外介面規格，供前端穩定讀取，與內部 trajectory 結構解耦。

#### 介面 / Interface

```python
def steps(trajectory_record: dict) -> list[ProcessStep]
```

#### ProcessStep 結構 / ProcessStep Structure

```python
@dataclass
class ProcessStep:
    tier: int                    # 0-3
    provider: str                # local/claude/cloud
    kind: str                    # "answer" | "verification" | "feedback" | "escalation" | "fail_closed"
    label: str                   # 顯示標籤（如 "本機回答"、"驗證失敗→重試"、"Fail-Closed: budget_exceeded"）
    latency_s: float
    tokens_input: int
    tokens_output: int
    cost_usd: float
    verification: dict           # {status: "passed"|"failed"|"not_applicable", details?: str}
    tool_filter: dict | None     # {original, kept, dropped, stage, names} 或 None
    terminal_state: str          # completed/failed/aborted/fail_closed
    fail_closed_reason: str | None
```

#### 映射規則 / Mapping Rules

| Trajectory 來源 | ProcessStep 目標 |
|--------------|-----------------|
| `tiers[0]` | tier=0, kind="answer", label="本機回答" |
| `tiers[0].verification` failed | tier=0, kind="verification", label="驗證失敗" |
| `tiers[1]` (retry) | tier=1, kind="answer", label="本機重試" |
| `tiers[1].verification` failed + tier2 enabled | tier=1, kind="feedback", label="取得回饋" |
| `tiers[2]` (feedback retry) | tier=2, kind="answer", label="回饋後重答" |
| `escalation.claude` | tier=3, kind="escalation", label="諮詢 Claude" |
| `escalation.cloud` | tier=3, kind="escalation", label="雲端轉交" |
| `fail_closed` at any phase | tier=當時層級, kind="fail_closed", label="Fail-Closed: {reason}" |

#### 穩定性承諾 / Stability Commitment

- `ProcessStep` 結構、欄位名、型別、值域 **不得** 在無重大版本號變更時修改
- 新增欄位僅以 optional 方式附加，不破壞既有消費者
- `kind`、`label` 為顯示導向，可隨 UI 需求微調文字，但 enum 值域不變

#### Scenario: 步驟序列正確 / Step sequence correct

- **WHEN** 傳入一筆完整 trajectory（含 tier 0、1、2、3、fail_closed）。/ **WHEN** a complete trajectory is passed.
- **THEN** `steps()` 回傳序列符合映射規則、每步欄位完整、`kind`/`label` 正確。/ **THEN** returned sequence matches mapping, all fields present, kind/label correct.

#### Scenario: 缺失 tier 優雅處理 / Missing tier handled gracefully

- **WHEN** trajectory 只到 tier 0 就完成。/ **WHEN** trajectory completes at tier 0 only.
- **THEN** `steps()` 只回傳 tier 0 步驟、不報錯。/ **THEN** only tier 0 steps returned, no error.