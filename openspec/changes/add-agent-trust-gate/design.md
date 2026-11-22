## Context / 背景

芥子專案已具備 `training_use` 旗標（R6、R18.3、R20）、防提示注入（injection.py）、技能庫僅收驗證成功呼叫（skills.py）、記憶 wiki（memory.py）、訓練資料匯出管線（training_data.py）、軌跡記錄（trajectory.py）。但缺少統一的**前置信任閘門**，導致：
- 同一份外部內容可能以不同管道（網頁、文件、MCP 工具、雲端回答）重複進入，缺乏去重與污染追蹤
- 來源追溯欄位零散，無法完整回答「這筆技能來自哪次軌跡、哪個版本的文件、何時被加入」
- 雲端輸出禁止進訓練的強制點分散在 gateway.py 12+ 處，理由各異（license、injection、private、unverifiable、cloud_hint、helper、consultation），缺乏審計線索

依 `docs/dev-plan.md` §15.5，A5 `add-agent-trust-gate` 要求建立統一 Trust Gate，作為記憶、技能、訓練資料三條管道的共同前置關卡。

## Goals / 目標

1. **統一信任評估**：所有外部內容進入記憶/技能/訓練前，經單一 `evaluate_trust()` 判斷 `TrustLevel` 與 `Provenance`
2. **完整 Provenance**：每筆寫入自動記錄 `source_channel`、`source_id`、`content_hash`、`fetched_at`、`version`、`retrieval_method`
3. **跨管道污染隔離**：注入偵測產生 `taint_id`（SHA-256 前 16 碼），Trust Gate 維護 `taint_index`，攔截相同雜湊內容再次進入
4. **雲端輸出單一強制點**：`gateway_enforce_training_use_false()` 取代分散寫法，自動附加 `trust_level: cloud`、`provenance`（含 `extra.reason` 保留具體原因）
5. **MCP 工具輸出納管**：`agent/server.py` 回傳前經 Trust Gate 評估，預設 `unverified`，受信任 server 可升級
6. **零新相依**：不引入外部服務、資料庫、連接埠、模型或 GPU 負載

## Non-Goals / 非目標

- 不實作人工覆核 UI、OAuth/HTTP 授權流、第三方 MCP 完整信任鏈
- 不改核心模型、P1–P8、D1–D12、G1–G5、Phase 0–8 時程
- 不強制回填既有資料（讀取時缺失視為 `unverified`/`unknown`）

## SKILL / MCP / Core Module Classification / 分類與理由

**分類：Core Module（核心現有模組）**

理由：
- 此變更修改既有核心管道（memory、skills、training-data、injection-guard、trajectory、escalation、gateway），不對外提供新工具或 MCP server
- 屬於安全不變量與資料管道前置關卡，屬於核心基礎設施
- 參考 `docs/dev-plan.md` §15.5 將 A5 列為核心遷移項目，非技能擴充

## Existing Solutions Search / 現成方案搜尋（遵循 AGENTS.md：列出方案與「待主控上網查證」）

| 方案 | 相關性 | 狀態 |
|------|--------|------|
| W3C PROV-O (PROV Ontology) | 標準化 provenance 模型（Entity、Activity、Agent、Generation、Derivation） | 待主控上網查證 |
| in-toto (轉供應鏈完整性) | 佈署鏈 provenance、layout、link metadata、公鑰驗證 | 待主控上網查證 |
| SLSA Provenance (Supply chain Levels for Software Artifacts) | Build provenance、材料、環境、參數、產出 | 待主控上網查證 |
| OWASP LLM Top 10 2025 - LLM01 Prompt Injection | 注入分類、緩解、檢測 | 已查證（§15.3） |
| OWASP LLM Top 10 2025 - LLM08 Tool Poisoning | 工具中毒、間接注入 | 已查證（§15.3） |
| OWASP AI Agent Security Cheat Sheet - Memory & Context Security | 記憶投毒、上下文污染 | 已查證（§15.3） |
| OWASP AI Agent Security Cheat Sheet - Scoped Allowlist | 工具授權範圍、最小權限 | 已查證（§15.3） |
| Anthropic Skills / MCP spec (authorization, access control) | 工具權限、伺服器授權 | 已查證（§15.3） |
| Sigstore / cosign / rekor | 簽名、透明度日誌、驗證 | 待主控上網查證 |
| **OWASP Agent Memory Guard** | ASI06 記憶污染參考實作；detectors＋宣告式政策 | **A5 併入（web-research.md）** |
| **memward (PyPI)** | 每筆記憶標來源與信任層級；網頁來源一律不可信 | **A5 併入（web-research.md）** |
| **Flynn memory guard (Go)** | 信任＝寫入來源的純函式（TrustOf） | **A5 併入（web-research.md）** |
| **memgar (PyPI, MIT)** | 快照、hash、provenance、簽章、diff、rollback | **A5 併入（web-research.md）** |
| **memshield / agent-memory-guard (PyPI)** | 包裝向量庫、檢查取回片段 | **A5 併入（web-research.md）** |
| **SMSR (arXiv 2606.12703)** | HMAC provenance＋隨機消融多數決，研究論文非套件 | **A5 併入（web-research.md）** |

**對齊策略**：Trust Gate 的 `Provenance` 結構採最小集（`source_channel`、`source_id`、`content_hash`、`fetched_at`、`version`、`retrieval_method`），欄位名預留 `prov:` 前綴，未來可對齊 PROV-O / in-toto / SLSA 而不破壞現有結構。**核心內建、不新增相依**；「來源決定信任」的模式直接採用；若要引入任一套件，須另做 OSV／授權掃描交使用者決定。

## Security Analysis / 資安分析

### Threat Model / 威脅模型

| 威脅 | 向量 | 影響 | 緩解 |
|------|------|------|------|
| Prompt Injection | 外部網頁、文件、MCP tool result | 污染記憶、技能、訓練資料 | injection.guard() + Trust Gate taint_index 跨管道攔截 |
| Tool Poisoning | 惡意 MCP server 回傳偽造結果 | 技能學到錯誤呼叫、記憶存入錯誤資訊 | MCP tool output 經 Trust Gate，預設 `unverified`，需人工升級 |
| Memory Poisoning | 重複注入同一惡意內容繞過單管道檢查 | 長期記憶被污染 | taint_index 以 content_hash 去重，跨管道生效 |
| Training Data Contamination | `training_use=true` 錯誤標記雲端輸出 | 模型學到 Anthropic 禁止訓練的內容 | gateway_enforce_training_use_false() 單一強制點 + trust_level: cloud |
| Provenance Tampering | 攻擊者修改 provenance 欄位掩蓋來源 | 審計失效、無法追溯 | provenance 由 Trust Gate 寫入，不接受外部輸入；content_hash 自我驗證 |
| Taint Index DoS | 大量惡意內容填滿 taint_index 記憶體 | 記憶體耗盡、拒絕服務 | LRU + TTL（30 天）自動清理，上限可配置 |

### Residual Risks / 殘留風險

1. **Hash Collision**：SHA-256 碰撞機率極低（~2⁻¹²⁸），可忽略
2. **Provenance Field Leakage**：僅記錄邏輯 `source_id`（如 `web:https://example.com`、`mcp:server-name`、`doc:doc-id`），不記實體檔案路徑或內部結構
3. **Taint Index Persistence**：若選擇持久化，需防範索引檔案本身被竄改（建議簽名或唯讀掛載）
4. **Clock Skew**：`fetched_at` 依賴系統時間，分布式場景下可能不一致（目前單機部署，風險低）

### Verification / 驗證方式

- 單元測試：`tests/test_trust_gate.py` 涵蓋 TrustLevel 排序、Provenance 序列化、taint_index 增刪查、雲端輸出強制標記
- 整合測試：memory/save、skills/collect、training_data/export、injection/guard、gateway/escalation 完整流程
- 回歸測試：現有 `tests/test_memory.py`、`tests/test_skills.py`、`tests/test_training_data.py`、`tests/test_injection.py` 全通過
- 靜態分析：`GIT_MASTER=1 git diff --check`、mypy、ruff

## Data Structures / 資料結構

```python
# src/jiezi/trust.py

from enum import IntEnum
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Dict, Any, List
import hashlib
import json

class TrustLevel(IntEnum):
    """信任等級，數值越大越可信。Cloud 為特殊標記，不參與排序。"""
    TAINTED = 0      # 污染：完全隔離，不入記憶/技能/訓練
    UNVERIFIED = 1   # 未驗證：僅可入記憶，不可入技能/訓練
    VERIFIED = 2     # 已驗證：可入記憶/技能，不可入訓練（如 MIT 授權文件）
    TRUSTED = 3      # 受信：可入記憶/技能/訓練（需 training_use=True）

    @property
    def can_memory(self) -> bool: return self >= TrustLevel.UNVERIFIED
    @property
    def can_skill(self) -> bool: return self >= TrustLevel.VERIFIED
    @property
    def can_train(self) -> bool: return self == TrustLevel.TRUSTED
    @property
    def is_cloud(self) -> bool: return False  # cloud 由 source_type 標記


@dataclass
class Provenance:
    """來源證明，最小集；欄位名預留 prov: 前綴供未來對齊 PROV-O/in-toto/SLSA"""
    source_channel: str           # "web" | "doc" | "mcp" | "cloud" | "user" | "skill" | "correction"
    source_id: str                # 邏輯識別：URL、doc-id、mcp-server-name、model-name、user、skill-id
    content_hash: str             # SHA-256 hex（前 16 碼作為 taint_id）
    fetched_at: str               # ISO 8601 UTC
    version: Optional[str] = None # 文件版本、網頁 etag、MCP tool 版本
    retrieval_method: Optional[str] = None  # "fetch" | "mcp_call" | "consult" | "upload" | "derivation"
    extra: Dict[str, Any] = field(default_factory=dict)  # 預留擴充

    def to_dict(self) -> Dict[str, Any]:
        d = {k: v for k, v in self.__dict__.items() if v is not None}
        return d

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "Provenance":
        return Provenance(**{k: v for k, v in d.items() if k in Provenance.__dataclass_fields__})


@dataclass
class TaintRecord:
    """污染記錄：注入偵測到時寫入 taint_index"""
    taint_id: str                 # content_hash 前 16 碼
    content_hash: str             # 完整 SHA-256
    detected_at: str              # ISO 8601 UTC
    source_channel: str
    source_id: str
    injection_type: str           # injection.py 偵測類型
    snippet: str                  # 觸發片段（前 200 字）


class TrustGate:
    """統一信任閘門：單例或依賴注入"""
    
    def __init__(self, taint_index_path: Optional[str] = None, max_taint_records: int = 10000, ttl_days: int = 30):
        self.taint_index: Dict[str, TaintRecord] = {}  # taint_id -> TaintRecord
        self.taint_index_path = taint_index_path
        self.max_records = max_taint_records
        self.ttl_days = ttl_days
        if taint_index_path:
            self._load()
    
    def _load(self):
        # 載入 taint_index.jsonl，過濾過期記錄
        pass
    
    def _save(self):
        # 持久化 taint_index
        pass
    
    def _cleanup(self):
        # LRU + TTL 清理
        pass
    
    def compute_content_hash(self, content: str) -> str:
        return hashlib.sha256(content.encode("utf-8")).hexdigest()
    
    def evaluate_trust(
        self,
        content: str,
        source_channel: str,
        source_id: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> tuple[TrustLevel, Provenance, Optional[TaintRecord]]:
        """
        核心判斷函式。
        回傳 (trust_level, provenance, taint_record_if_detected)
        """
        content_hash = self.compute_content_hash(content)
        taint_id = content_hash[:16]
        
        # 1. 檢查 taint_index
        if taint_id in self.taint_index:
            return TrustLevel.TAINTED, Provenance(
                source_channel=source_channel,
                source_id=source_id,
                content_hash=content_hash,
                fetched_at=datetime.utcnow().isoformat() + "Z",
                version=metadata.get("version") if metadata else None,
                retrieval_method=metadata.get("retrieval_method") if metadata else None
            ), self.taint_index[taint_id]
        
        # 2. 注入偵測
        from ..injection import guard
        injection_result = guard(content)
        if injection_result.detected:
            taint = TaintRecord(
                taint_id=taint_id,
                content_hash=content_hash,
                detected_at=datetime.utcnow().isoformat() + "Z",
                source_channel=source_channel,
                source_id=source_id,
                injection_type=injection_result.type,
                snippet=injection_result.snippet[:200]
            )
            self.taint_index[taint_id] = taint
            self._cleanup()
            if self.taint_index_path:
                self._save()
            return TrustLevel.TAINTED, Provenance(...), taint
        
        # 3. 依 source_channel 決定基礎 trust_level
        base_level = self._base_trust_level(source_channel, metadata)
        
        # 4. 若為 cloud 輸出，強制 training_use=false 並標記 cloud
        # （由 gateway_enforce_training_use_false 處理，這裡只回傳基礎等級）
        
        provenance = Provenance(
            source_channel=source_channel,
            source_id=source_id,
            content_hash=content_hash,
            fetched_at=datetime.utcnow().isoformat() + "Z",
            version=metadata.get("version") if metadata else None,
            retrieval_method=metadata.get("retrieval_method") if metadata else None
        )
        return base_level, provenance, None
    
    def _base_trust_level(self, source_channel: str, metadata: Optional[Dict]) -> TrustLevel:
        # web/doc/mcp/user/skill/correction -> UNVERIFIED
        # trusted mcp server (metadata.get("trusted")) -> VERIFIED
        # user explicit mark -> TRUSTED (需人工確認)
        if source_channel == "mcp" and metadata and metadata.get("trusted"):
            return TrustLevel.VERIFIED
        if source_channel == "user" and metadata and metadata.get("explicit_trust"):
            return TrustLevel.TRUSTED
        return TrustLevel.UNVERIFIED
    
    def is_tainted(self, content_hash: str) -> bool:
        return content_hash[:16] in self.taint_index
    
    def gateway_enforce_training_use_false(self, rec: Dict, reason: str, model: str = "claude") -> Dict:
        """雲端輸出單一強制點：設 training_use=false、trust_level: cloud、provenance（含 reason）"""
        content = json.dumps(rec, ensure_ascii=False, sort_keys=True)
        content_hash = self.compute_content_hash(content)
        rec["training_use"] = False
        rec["trust_level"] = "cloud"
        rec["provenance"] = Provenance(
            source_channel="cloud",
            source_id=model,
            content_hash=content_hash,
            fetched_at=datetime.utcnow().isoformat() + "Z",
            retrieval_method="consult",
            extra={"reason": reason}
        ).to_dict()
        return rec


# 全域單例（或由容器注入）
_default_gate: Optional[TrustGate] = None

def get_gate() -> TrustGate:
    global _default_gate
    if _default_gate is None:
        _default_gate = TrustGate(taint_index_path="var/trust/taint_index.jsonl")
    return _default_gate
```

## Integration Points / 整合點

| 模組 | 修改處 | 說明 |
|------|--------|------|
| `memory.py` | `render_page()`、`save_answer()`、`save_correction()` | 前言新增 trust/provenance；寫入前經 `get_gate().evaluate_trust()` |
| `skills.py` | `collect()`、`build()`、`add()` | 技能項目新增 trust/provenance；過濾 `trust_level < VERIFIED` |
| `training_data.py` | `_ex()`、`export()` | 範例新增 trust/provenance/fetched_at；匯出加條件 `trust_level == TRUSTED and training_use` |
| `injection.py` | `guard()` 回傳值 | 新增 `taint_id`、`content_hash` 回傳；Trust Gate 維護索引 |
| `trajectory.py` | `TrajectoryRecord` | 新增 `trust_level`、`provenance` 欄位 |
| `gateway.py` | 12+ 處 `training_use=False` | 統一改呼叫 `get_gate().gateway_enforce_training_use_false(reason, model)` |
| `agent/server.py` | `tools/call` 回傳前 | 經 Trust Gate 評估 MCP tool output，記錄 provenance |

## Configuration / 設定

- `var/trust/taint_index.jsonl`：污染索引持久化路徑（可選，預設記憶體）
- `max_taint_records`：索引上限（預設 10000）
- `ttl_days`：記錄保留天數（預設 30）
- `trusted_mcp_servers`：受信任 MCP server 清單（由 `scripts/jiezi agent trust-mcp` 管理）

## Migration / 遷移

- 既有 memory pages、skills、training data 缺少 trust/provenance 欄位
- 讀取時：缺失視為 `trust_level=UNVERIFIED`、`provenance=unknown`
- 新寫入：自動補全
- 不提供一次性回填腳本（避免誤判既有資料信任度）

## Testing Strategy / 測試策略

1. `tests/test_trust_gate.py`：TrustLevel 排序、Provenance 序列化、taint_index 增刪查、雲端輸出強制標記、LRU+TTL 清理
2. `tests/test_memory.py`：擴充測試 save_answer/save_correction 經 Trust Gate、前言欄位完整
3. `tests/test_skills.py`：擴充測試 collect/build/add 過濾 trust_level、provenance 記錄
4. `tests/test_training_data.py`：擴充測試 export 條件含 trust_level、範例欄位完整
5. `tests/test_injection.py`：擴充測試 guard 回傳 taint_id、跨管道攔截
6. 整合測試：web→memory→skill→training 完整管道、cloud→trajectory→memory 管道