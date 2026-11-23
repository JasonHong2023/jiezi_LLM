"""Trust Gate 核心模組：統一的外部內容信任評估、provenance 記錄、污染隔離與雲端輸出強制標記。
Trust Gate core module: unified trust evaluation, provenance recording, contamination isolation, and cloud output mandatory labeling."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import IntEnum
from typing import Any, Dict, List, Optional


def _now_iso_z() -> str:
    """當前 UTC 時間的 ISO 8601 字串（以 Z 結尾）。/ Current UTC time as ISO 8601 string ending with Z."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class TrustLevel(IntEnum):
    """信任等級，數值越大越可信。Cloud 為特殊標記，不參與排序。
    Trust levels, higher = more trusted. Cloud is a special marker, not part of ordering."""

    TAINTED = 0      # 污染：完全隔離，不入記憶/技能/訓練 / Tainted: fully isolated
    UNVERIFIED = 1   # 未驗證：僅可入記憶，不可入技能/訓練 / Unverified: memory only
    VERIFIED = 2     # 已驗證：可入記憶/技能，不可入訓練 / Verified: memory + skills, no training
    TRUSTED = 3      # 受信：可入記憶/技能/訓練（需 training_use=True）/ Trusted: all three

    @property
    def can_memory(self) -> bool:
        """是否可寫入記憶 / Can write to memory."""
        return self >= TrustLevel.UNVERIFIED

    @property
    def can_skill(self) -> bool:
        """是否可寫入技能庫 / Can write to skills."""
        return self >= TrustLevel.VERIFIED

    @property
    def can_train(self) -> bool:
        """是否可進訓練資料 / Can enter training data."""
        return self == TrustLevel.TRUSTED

    @property
    def is_cloud(self) -> bool:
        """Cloud 由 Provenance 的 source_type="cloud" 標記，非等級屬性。"""
        return False


@dataclass
class Provenance:
    """來源證明，最小集；欄位名預留 prov: 前綴供未來對齊 PROV-O/in-toto/SLSA。
    Provenance minimal set; field names reserve prov: prefix for future alignment."""

    source_channel: str           # "web" | "doc" | "mcp" | "cloud" | "user" | "skill" | "correction"
    source_id: str                # 邏輯識別：URL、doc-id、mcp-server-name、model-name、user、skill-id
    content_hash: str             # SHA-256 hex（前 16 碼作為 taint_id）
    fetched_at: str               # ISO 8601 UTC
    version: Optional[str] = None             # 文件版本、網頁 etag、MCP tool 版本
    retrieval_method: Optional[str] = None    # "fetch" | "mcp_call" | "consult" | "upload" | "derivation"
    extra: Dict[str, Any] = field(default_factory=dict)  # 預留擴充 / reserved for extension

    def to_dict(self) -> Dict[str, Any]:
        """序列化為 dict，略過 None 值。/ Serialize, skipping None values."""
        return {k: v for k, v in self.__dict__.items() if v is not None}

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "Provenance":
        """從 dict 反序列化，對缺欄位寬容。/ Deserialize, tolerant of missing fields."""
        valid_keys = Provenance.__dataclass_fields__.keys()
        return Provenance(**{k: v for k, v in d.items() if k in valid_keys})


@dataclass
class TaintRecord:
    """污染記錄：注入偵測到時寫入 taint_index。/ Taint record written when injection detected."""

    taint_id: str                 # content_hash 前 16 碼 / first 16 chars of content_hash
    content_hash: str             # 完整 SHA-256 / full SHA-256
    detected_at: str              # ISO 8601 UTC
    source_channel: str
    source_id: str
    injection_type: str           # injection.py 偵測類型 / detection type from injection.py
    snippet: str                  # 觸發片段（前 200 字） / triggering snippet (first 200 chars)


class TrustGate:
    """統一信任閘門：單例或依賴注入。/ Unified trust gate: singleton or DI."""

    def __init__(
        self,
        taint_index_path: Optional[str] = None,
        max_taint_records: int = 10000,
        ttl_days: int = 30
    ):
        self.taint_index: Dict[str, TaintRecord] = {}  # taint_id -> TaintRecord
        self.taint_index_path = taint_index_path
        self.max_records = max_taint_records
        self.ttl_days = ttl_days
        if taint_index_path:
            self._load()

    def _load(self) -> None:
        """載入 taint_index.jsonl，過濾超過 30 天的記錄。/ Load taint index, filter expired records."""
        if not self.taint_index_path or not os.path.exists(self.taint_index_path):
            return
        cutoff = datetime.now(timezone.utc) - timedelta(days=self.ttl_days)
        with open(self.taint_index_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:  # 壞掉的一行只跳過該行，不清掉整個索引（否則污染紀錄全部失效）/ skip only the bad line
                    rec = json.loads(line)
                    detected_at = datetime.fromisoformat(rec["detected_at"].replace("Z", "+00:00"))
                    if detected_at >= cutoff:
                        self.taint_index[rec["taint_id"]] = TaintRecord(**rec)
                except (json.JSONDecodeError, KeyError, TypeError, ValueError):
                    continue
        # 載入後再做一次 LRU 清理 / LRU cleanup after load
        self._cleanup()

    def _save(self) -> None:
        """持久化 taint_index 到 JSONL。/ Persist taint index to JSONL."""
        if not self.taint_index_path:
            return
        os.makedirs(os.path.dirname(self.taint_index_path), exist_ok=True)
        # 按 detected_at 排序（最舊在前），寫入前 max_records 筆 / sort by detected_at, keep newest
        items = sorted(self.taint_index.values(), key=lambda r: r.detected_at)
        with open(self.taint_index_path, "w", encoding="utf-8") as f:
            for rec in items[-self.max_records:]:
                f.write(json.dumps(rec.__dict__, ensure_ascii=False) + "\n")

    def _cleanup(self) -> None:
        """LRU + TTL 清理：先刪過期，再若超過上限刪最舊。/ LRU+TTL cleanup: expire old, then evict oldest if over limit."""
        if not self.taint_index:
            return
        cutoff = datetime.now(timezone.utc) - timedelta(days=self.ttl_days)
        # 1. 刪除過期 / remove expired
        expired = [tid for tid, rec in self.taint_index.items()
                   if datetime.fromisoformat(rec.detected_at.replace("Z", "+00:00")) < cutoff]
        for tid in expired:
            del self.taint_index[tid]
        # 2. LRU 淘汰最舊 / evict oldest if over limit
        if len(self.taint_index) > self.max_records:
            items = sorted(self.taint_index.items(), key=lambda kv: kv[1].detected_at)
            for tid, _ in items[:len(self.taint_index) - self.max_records]:
                del self.taint_index[tid]
        # 3. 若有持久化路徑，寫回 / persist if configured
        if self.taint_index_path:
            self._save()

    def compute_content_hash(self, content: str) -> str:
        """計算內容 SHA-256。/ Compute SHA-256 of content."""
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    def evaluate_trust(
        self,
        content: str,
        source_channel: str,
        source_id: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> tuple[TrustLevel, Provenance, Optional[TaintRecord]]:
        """
        核心判斷函式。/ Core evaluation function.
        回傳 (trust_level, provenance, taint_record_if_detected)
        """
        content_hash = self.compute_content_hash(content)
        taint_id = content_hash[:16]

        # 1. 檢查 taint_index / Check taint index
        if taint_id in self.taint_index:
            taint_rec = self.taint_index[taint_id]
            provenance = Provenance(
                source_channel=source_channel,
                source_id=source_id,
                content_hash=content_hash,
                fetched_at=_now_iso_z(),
                version=metadata.get("version") if metadata else None,
                retrieval_method=metadata.get("retrieval_method") if metadata else None
            )
            return TrustLevel.TAINTED, provenance, taint_rec

        # 2. 注入偵測 / Injection detection
        # 依 source_channel 將內容包裝為 guard 會掃描的格式
        from .injection import guard
        from .documents import attach as doc_attach
        data_ids: set[int] | None = None
        if source_channel in ("web", "doc"):
            # 文件格式 / document format
            messages = [{"role": "user", "content": doc_attach({"name": source_id, "text": content}, "")}]
        elif source_channel == "mcp":
            # 工具結果格式 / tool result format
            messages = [{"role": "tool", "content": content}]
        elif source_channel == "cloud":
            # gateway 附加資料格式 / gateway-attached data format
            msg = {"role": "system", "content": content}
            messages = [msg]
            data_ids = {id(msg)}
        else:
            # 其他管道：不掃描（使用者自有文字、技能、更正等）
            messages = []

        injection_result = guard(messages, data_ids)
        if injection_result.get("untrusted") and injection_result.get("suspected"):
            taint = TaintRecord(
                taint_id=taint_id,
                content_hash=content_hash,
                detected_at=_now_iso_z(),
                source_channel=source_channel,
                source_id=source_id,
                injection_type=injection_result["suspected"][0],
                snippet=content[:200]
            )
            self.taint_index[taint_id] = taint
            self._cleanup()
            provenance = Provenance(
                source_channel=source_channel,
                source_id=source_id,
                content_hash=content_hash,
                fetched_at=_now_iso_z(),
                version=metadata.get("version") if metadata else None,
                retrieval_method=metadata.get("retrieval_method") if metadata else None
            )
            return TrustLevel.TAINTED, provenance, taint

        # 3. 依 source_channel 決定基礎 trust_level / Determine base trust level
        base_level = self._base_trust_level(source_channel, metadata)

        provenance = Provenance(
            source_channel=source_channel,
            source_id=source_id,
            content_hash=content_hash,
            fetched_at=_now_iso_z(),
            version=metadata.get("version") if metadata else None,
            retrieval_method=metadata.get("retrieval_method") if metadata else None
        )
        return base_level, provenance, None

    def _base_trust_level(self, source_channel: str, metadata: Optional[Dict]) -> TrustLevel:
        """依管道決定基礎信任等級。/ Determine base trust level by channel."""
        # trusted mcp server (metadata.get("trusted")) -> VERIFIED
        if source_channel == "mcp" and metadata and metadata.get("trusted"):
            return TrustLevel.VERIFIED
        # user explicit mark -> TRUSTED (需人工確認)
        if source_channel == "user" and metadata and metadata.get("explicit_trust"):
            return TrustLevel.TRUSTED
        # web/doc/mcp/user/skill/correction -> UNVERIFIED
        return TrustLevel.UNVERIFIED

    def is_tainted(self, content_hash: str) -> bool:
        """檢查內容雜湊是否在污染索引中。/ Check if content hash is in taint index."""
        return content_hash[:16] in self.taint_index

    def register_hash(self, content_hash: str, source_channel: str, source_id: str, injection_type: str,
                      snippet: str = "") -> TaintRecord:
        """只有雜湊時登記污染（gateway 從 injection.guard() 的 taints 取得）。 / Register a taint from a hash alone."""
        taint_id = content_hash[:16]
        if taint_id in self.taint_index:
            return self.taint_index[taint_id]
        taint = TaintRecord(taint_id=taint_id, content_hash=content_hash, detected_at=_now_iso_z(),
                            source_channel=source_channel, source_id=source_id, injection_type=injection_type,
                            snippet=snippet[:200])
        self.taint_index[taint_id] = taint
        self._cleanup()
        return taint

    def register_taint(self, injection_result: Dict[str, Any], content: str,
                       source_channel: str, source_id: str) -> Optional[TaintRecord]:
        """從注入結果註冊污染記錄。/ Register taint from injection result."""
        content_hash = self.compute_content_hash(content)
        taint_id = content_hash[:16]
        if not injection_result.get("untrusted") or not injection_result.get("suspected"):
            return None
        if taint_id in self.taint_index:
            return self.taint_index[taint_id]
        taint = TaintRecord(
            taint_id=taint_id,
            content_hash=content_hash,
            detected_at=_now_iso_z(),
            source_channel=source_channel,
            source_id=source_id,
            injection_type=injection_result["suspected"][0],
            snippet=content[:200]
        )
        self.taint_index[taint_id] = taint
        self._cleanup()
        return taint

    def mark_untrainable(self, rec: Dict, reason: str, model: Optional[str] = None) -> Dict:
        """不可訓練的單一標記點：rec["training_use"]=False，並附 rec["trust"]={level, reason, provenance}。
        reason 保留具體原因（license／private／cloud／unverifiable／helper／injection…），不全部當 cloud。
        雲端不是信任等級（OQ1）：雲端來源記在 provenance.source_channel="cloud"，等級為 UNVERIFIED。
        Single place that marks a record untrainable, keeping the concrete reason."""
        content_hash = self.compute_content_hash(json.dumps(rec, ensure_ascii=False, sort_keys=True, default=str))
        rec["training_use"] = False
        level = TrustLevel.TAINTED if reason == "injection" else TrustLevel.UNVERIFIED
        channel = "cloud" if reason in CLOUD_REASONS else "local"
        rec["trust"] = {
            "level": level.name.lower(),
            "reason": reason,
            "provenance": Provenance(
                source_channel=channel,
                source_id=model or ("cloud" if channel == "cloud" else "gateway"),
                content_hash=content_hash,
                fetched_at=_now_iso_z(),
                retrieval_method="consult" if channel == "cloud" else None,
                extra={"reason": reason},
            ).to_dict(),
        }
        return rec


CLOUD_REASONS = frozenset({"cloud", "cloud_hint", "helper", "consultation", "escalation"})


# 每個專案根目錄一個實例；沒給 root 的共用一個只放記憶體的實例 / one gate per project root
_gates: Dict[Optional[str], TrustGate] = {}


def get_gate(root=None) -> TrustGate:
    """取得 TrustGate。給 root 時索引存在 <root>/var/trust/taint_index.jsonl（絕對路徑，不受工作目錄影響）；
    沒給 root 只放記憶體。不同 root 各自一份，測試的暫存目錄不會共用。
    Gate per root; persisted under <root>/var/trust when root is given."""
    key = os.path.abspath(str(root)) if root is not None else None
    if key not in _gates:
        path = os.path.join(key, "var", "trust", "taint_index.jsonl") if key is not None else None
        _gates[key] = TrustGate(taint_index_path=path)
    return _gates[key]


def reset_gate() -> None:
    """測試用：丟掉所有實例。 / Tests: drop every instance."""
    _gates.clear()
