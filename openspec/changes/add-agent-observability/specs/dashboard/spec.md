## ADDED Requirements

### Requirement: Dashboard Metrics Interface / 儀表板指標介面

系統 SHALL 提供 `dashboard` 模組的對外介面規格，供前端（TUI/Web/CLI）穩定讀取。

#### 查詢介面 / Query Interface

```python
def compute(
    days: int = 7,           # 統計天數，預設 7
    policy: str | None = None,  # 篩選策略
    include_fail_closed: bool = False  # 是否含 fail_closed 明細
) -> DashboardMetrics
```

#### 回傳結構 / Return Structure

```python
@dataclass
class DashboardMetrics:
    # 總覽
    total_requests: int
    completed: int
    failed: int
    aborted: int
    fail_closed: int
    
    # 成就率 / Achievement Rate
    achievement_rate: float          # completed / total_requests
    
    # 本地處理率 / Local Handling Rate
    local_handling_rate: float       # (tier 0/1 completed) / total_requests
    
    # 速度 / Speed
    speed_tps: float                 # 加權平均 tokens/秒
    
    # Fail-Closed
    fail_closed_rate: float          # fail_closed / total_requests
    fail_closed_reasons: dict[str, int]  # 原因碼分布
    
    # 層級分布 / Tier Distribution
    tier_distribution: dict[int, int]  # tier -> count
    
    # 提供者分布 / Provider Distribution
    provider_distribution: dict[str, int]  # local/claude/cloud -> count
    
    # 轉交原因分布 / Escalation Reason Distribution
    escalation_distribution: dict[str, int]
    
    # 工具使用 / Tool Usage
    tool_usage: dict[str, int]       # tool name -> call count
    tool_filter_stats: dict[str, float]  # average original/kept/dropped per request
    
    # 資源 / Resources
    avg_latency_s: float
    total_tokens_input: int
    total_tokens_output: int
    total_cost_usd: float
    
    # 區間
    period_days: int
    period_start: str  # ISO date
    period_end: str    # ISO date
```

#### Scenario: 指標計算正確 / Metrics compute correctly

- **WHEN** 呼叫 `compute(days=7)`。/ **WHEN** compute is called with 7 days.
- **THEN** 回傳結構含上表所有欄位、數值與 trajectory/process 來源一致、`fail_closed` 統計正確。/ **THEN** all fields present, values match sources, fail_closed stats correct.

#### Scenario: 篩選運作 / Filtering works

- **WHEN** 呼叫 `compute(policy="jiezi-local")`。/ **WHEN** compute with policy filter.
- **THEN** 只統計該策略的請求。/ **THEN** only that policy's requests counted.

---

### Requirement: Dashboard Export Formats / 匯出格式

系統 SHALL 支援 JSON 與 CSV 兩種匯出格式。

#### JSON Export

```json
{
  "metrics": { ... },  // DashboardMetrics as dict
  "generated_at": "2026-11-23T10:00:00Z",
  "version": "1.0"
}
```

#### CSV Export

欄位對應 `DashboardMetrics` 扁平化，巢狀字典展開為 `prefix_key` 形式。

#### Scenario: 匯出格式正確 / Export format correct

- **WHEN** CLI 執行 `jiezi dashboard --format json` / `--format csv`。/ **WHEN** CLI runs with format option.
- **THEN** 輸出符合上述結構、可被標準工具解析。/ **THEN** output matches structure, parseable by standard tools.