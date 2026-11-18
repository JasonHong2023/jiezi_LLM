"""runtime 設定：全部來自 `.env` 或環境變數（R21.3），在啟動時檢查（add-gateway design D3、D4、D6、D7）。
Runtime settings, all from `.env` or the environment (R21.3), validated at startup."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ..config import GATEWAY_KEY_VAR, load_env, port_base, project_root
from ..errors import JieziError

LOCAL_HOST = "127.0.0.1"
POLICIES = ("jiezi", "jiezi-local", "jiezi-cloud", "jiezi-ask-claude")
DEFAULT_CORE = "qwen3-0.6b-q8_0"


def _int(env: dict, key: str, default: int) -> int:
    v = env.get(key)
    try:
        return int(v) if v else default
    except ValueError as exc:
        raise JieziError(f"{key} must be an integer, got {v!r}") from exc


def _onoff(env: dict, key: str, default: bool) -> bool:
    v = (env.get(key) or "").strip().lower()
    if not v:
        return default
    if v in ("on", "true", "1", "yes"):
        return True
    if v in ("off", "false", "0", "no"):
        return False
    raise JieziError(f"{key} must be on or off, got {v!r}")


def _recall(value: str | None) -> str:
    from ..longdoc import RECALL_MODES
    v = (value or "off").strip().lower()
    if v not in RECALL_MODES:
        raise JieziError(f"JIEZI_DOC_RECALL must be one of {', '.join(RECALL_MODES)}, got {v!r}")
    return v


@dataclass
class Settings:
    root: Path
    key: str
    gateway_port: int
    engine_port: int
    core_model: str = DEFAULT_CORE
    models_dir: Path | None = None
    idle_unload_s: int = 900
    cloud_escalation: bool = False
    cloud_base: str | None = None
    cloud_key: str | None = None
    escalation_models: list[str] = field(default_factory=list)
    cloud_daily_max: int = 200
    trajectory: bool = True
    retention_days: int = 0
    request_max_bytes: int = 8 << 20   # 圖片以 base64 傳入，放寬到 8 MB（add-vision）/ images arrive as base64
    request_timeout_s: float = 600.0
    host: str = LOCAL_HOST
    consult: str = "off"            # off | claude-cli（design D9）
    consult_daily_max: int = 0      # 0 = 不限（使用者 2026-11-15）/ 0 = unlimited (user, 2026-11-15)
    consult_timeout_s: int = 300
    consult_model: str | None = None
    system_prompt: str | None = None   # 請求沒有 system 訊息時加上（design D10）/ added when a request has none
    consult_web: bool = True        # 請教時可讀網頁與搜尋（使用者 2026-11-15）/ web reading and search when consulting
    dictionary: bool = True         # 詞語問題先查本機辭典（add-dictionary）/ consult the local dictionary for word questions
    longdoc: bool = True            # 長文件先分段濃縮（add-long-documents）/ condense long documents first
    ladder: bool = True             # 本機先試到底：重答 → 思考模式 → 雲端提示 → 最後才 Claude（local-first-solving）
    ladder_think: bool = True       # 階梯的思考模式那一步 / the think-mode rung
    web_read: bool = True           # 使用者訊息裡的網址在本機讀取（add-web-read）/ read typed URLs locally
    experience: bool = True         # 解題經驗記錄與提示（local-first-solving）/ experience records
    tier2: bool = False             # 第 2 層：只向協助者要回饋、本機重答（add-partial-escalation；量測後才預設開啟）
    translate: bool = True          # 整份文件逐段翻譯、譯文檢查、簡轉繁（add-translation）/ chunked translation with checks
    injection_guard: bool = True    # 文件、工具結果、附加資料只當資料（add-injection-guard）/ external content is data
    skills: bool = True             # 工具呼叫附上過去成功的範例（技能庫 v0）/ verified tool-call examples
    laws: bool = True               # 法律問題先查全國法規資料庫（add-laws）/ law questions use the MOJ database
    rag: bool = True                # 知識庫用向量重排（有建向量時）/ vector reranking when vectors exist (add-rag)
    rag_min: float = 0.6            # 知識庫向量門檻（tune-knowledge-relevance 2026-11-18 量測後使用者選 0.6）/ knowledge base
    laws_rag_min: float = 0.5       # 法規向量門檻（還沒量測，維持原值）/ statutes, not yet measured
    doc_semantic: bool = True       # 長文件問答用語意挑段落（add-semantic-chunks）/ semantic chunk selection
    doc_embed_timeout_s: float = 20.0  # 第一題最多等段落向量幾秒，之後先用字面 / first-question wait for chunk vectors
    doc_recall: str = "off"         # 段落召回 off／reserve／hyde（add-chunk-recall）/ chunk recall mode
    progress: bool = True           # 串流時回報處理階段（add-progress-events；使用者 2026-11-18：預設開）/ stage events
    agent: bool = False             # 唯讀代理（add-agent-readonly；預設關）/ read-only file agent, off by default
    agent_max_steps: int = 6        # 一個請求最多幾步工具呼叫（使用者 2026-11-17：6）/ tool steps per request
    rerank: bool = False            # 向量前 N 名再重排序（add-reranker；量測過門檻才預設開啟）/ rerank the top N (off until measured)
    rerank_gpu: bool = False        # 重排序放 GPU（預設 CPU，不和核心搶顯示記憶體）/ reranker on GPU (CPU by default)
    rerank_timeout_s: float = 10.0  # 逾時就退回向量排序 / fall back to vector order on timeout
    samples: int = 4                # 可驗證的問題（工具呼叫、程式）平行取樣幾個；1 = 關閉（add-sampling）
    sample_temperature: float = 0.7
    vision_tools: bool = False      # 本機看圖工具：偵測、提示、核對（add-vision-tools；量測過才預設開）/ off until measured
    image_paths: bool = True        # 使用者訊息裡的本機圖片／文件路徑由 gateway 讀檔附上（add-image-paths）/ read typed file paths
    tool_note: bool = True          # 帶工具的請求加參數填寫規則（add-strong-tool-calling）/ argument rules for tool requests
    tools: bool = True              # 計算、單位換算、日期由程式算好（add-tools）/ computed by code
    memory: bool = True             # 記憶 wiki：請教過的答案、記住的事、更正（add-memory）/ memory wiki
    tw_phrases: bool = True         # 本機輸出換成台灣用語（OpenCC TWPhrases 篩選）/ Taiwan phrasing for local output
    knowledge: bool = True          # 台灣知識問題先查 taiwan-md（add-knowledge）/ Taiwan questions use taiwan-md
    writing_refs: bool = True       # 寫作問題附延伸閱讀連結（add-curriculum D6）/ further-reading links for writing questions
    curriculum: bool = True         # 課綱／國小學習問題先查知識圖譜（add-curriculum）/ curriculum questions use the graph
    consult_auto: bool = True       # 自動請教，不用逐次同意（使用者 2026-11-15）/ auto-consult without per-call approval

    @property
    def cloud_ready(self) -> bool:
        return self.cloud_escalation and bool(self.cloud_base) and bool(self.escalation_models)

    @property
    def var(self) -> Path:
        return self.root / "var"


def load_settings(root: Path | None = None, env: dict | None = None) -> Settings:
    """讀設定並檢查：只允許 127.0.0.1，必須有金鑰。 / Read and validate: 127.0.0.1 only, a key is required."""
    root = root or project_root()
    env = load_env(root) if env is None else env
    host = (env.get("JIEZI_GATEWAY_HOST") or LOCAL_HOST).strip()
    if host != LOCAL_HOST:
        raise JieziError(f"JIEZI_GATEWAY_HOST={host!r}: the gateway binds only to {LOCAL_HOST} (R6.12)")
    key = (env.get(GATEWAY_KEY_VAR) or "").strip()
    if len(key) < 16:
        raise JieziError(f"{GATEWAY_KEY_VAR} is missing or too short; run scripts/bootstrap or "
                         "`scripts/jiezi init-key` to generate one")
    base = port_base(env)
    md = env.get("JIEZI_MODELS_DIR")
    return Settings(
        root=root, key=key, gateway_port=base, engine_port=base + 1,
        core_model=(env.get("JIEZI_CORE_MODEL") or DEFAULT_CORE).strip(),
        models_dir=Path(md).expanduser() if md else root / "models",
        idle_unload_s=_int(env, "JIEZI_IDLE_UNLOAD_S", 900),
        cloud_escalation=_onoff(env, "JIEZI_CLOUD_ESCALATION", False),
        cloud_base=(env.get("JIEZI_CLOUD_BASE_URL") or "").rstrip("/") or None,
        cloud_key=env.get("JIEZI_CLOUD_API_KEY") or None,
        escalation_models=[m.strip() for m in (env.get("JIEZI_ESCALATION_MODELS") or "").split(",") if m.strip()],
        cloud_daily_max=_int(env, "JIEZI_CLOUD_DAILY_MAX", 200),
        trajectory=_onoff(env, "JIEZI_TRAJECTORY", True),
        retention_days=_int(env, "JIEZI_TRAJECTORY_RETENTION_DAYS", 0),
        consult=_consult(env),
        consult_daily_max=_int(env, "JIEZI_CONSULT_DAILY_MAX", 0),
        consult_timeout_s=_int(env, "JIEZI_CONSULT_TIMEOUT_S", 300),
        consult_model=env.get("JIEZI_CONSULT_MODEL") or None,
        consult_auto=_onoff(env, "JIEZI_CONSULT_AUTO", True),
        dictionary=_onoff(env, "JIEZI_DICTIONARY", True),
        curriculum=_onoff(env, "JIEZI_CURRICULUM", True),
        writing_refs=_onoff(env, "JIEZI_WRITING_REFS", True),
        knowledge=_onoff(env, "JIEZI_KNOWLEDGE", True),
        tw_phrases=_onoff(env, "JIEZI_TW_PHRASES", True),
        memory=_onoff(env, "JIEZI_MEMORY", True),
        tools=_onoff(env, "JIEZI_TOOLS", True),
        tool_note=_onoff(env, "JIEZI_TOOL_NOTE", True),
        image_paths=_onoff(env, "JIEZI_IMAGE_PATHS", True),
        vision_tools=_onoff(env, "JIEZI_VISION_TOOLS", False),
        samples=max(1, min(8, _int(env, "JIEZI_SAMPLES", 4))),
        rag=_onoff(env, "JIEZI_RAG", True),
        laws=_onoff(env, "JIEZI_LAWS", True),
        skills=_onoff(env, "JIEZI_SKILLS", True),
        longdoc=_onoff(env, "JIEZI_LONGDOC", True),
        injection_guard=_onoff(env, "JIEZI_INJECTION_GUARD", True),
        translate=_onoff(env, "JIEZI_TRANSLATE", True),
        tier2=_onoff(env, "JIEZI_TIER2", False),
        ladder=_onoff(env, "JIEZI_LADDER", True),
        ladder_think=_onoff(env, "JIEZI_LADDER_THINK", True),
        experience=_onoff(env, "JIEZI_EXPERIENCE", True),
        web_read=_onoff(env, "JIEZI_WEB_READ", True),
        rag_min=float(env.get("JIEZI_RAG_MIN") or 0.6),
        laws_rag_min=float(env.get("JIEZI_LAWS_RAG_MIN") or 0.5),
        doc_semantic=_onoff(env, "JIEZI_DOC_SEMANTIC", True),
        doc_embed_timeout_s=float(env.get("JIEZI_DOC_EMBED_TIMEOUT") or 20.0),
        doc_recall=_recall(env.get("JIEZI_DOC_RECALL")),
        agent=_onoff(env, "JIEZI_AGENT", False),
        progress=_onoff(env, "JIEZI_PROGRESS", True),
        agent_max_steps=max(1, min(12, _int(env, "JIEZI_AGENT_STEPS", 6))),
        rerank=_onoff(env, "JIEZI_RERANK", False),
        rerank_gpu=_onoff(env, "JIEZI_RERANK_GPU", False),
        rerank_timeout_s=float(env.get("JIEZI_RERANK_TIMEOUT") or 10.0),
        consult_web=_onoff(env, "JIEZI_CONSULT_WEB", True),
        system_prompt=_system_prompt(root, env),
    )


DEFAULT_SYSTEM_PROMPT = Path(__file__).resolve().parent / "data" / "system_prompt.md"


def _system_prompt(root: Path, env: dict) -> str | None:
    """預設的身分與語言提示；`JIEZI_SYSTEM_PROMPT_FILE=off` 關閉，或指向自己的檔案。
    The default identity and language prompt; `JIEZI_SYSTEM_PROMPT_FILE=off` disables it, or point it at a file."""
    v = (env.get("JIEZI_SYSTEM_PROMPT_FILE") or "").strip()
    if v.lower() == "off":
        return None
    path = Path(v).expanduser() if v else DEFAULT_SYSTEM_PROMPT
    if not path.is_absolute():
        path = root / path
    try:
        return path.read_text(encoding="utf-8").strip() or None
    except OSError as exc:
        raise JieziError(f"JIEZI_SYSTEM_PROMPT_FILE {path}: {exc}") from exc


def _consult(env: dict) -> str:
    v = (env.get("JIEZI_CONSULT") or "off").strip().lower()
    if v not in ("off", "claude-cli"):
        raise JieziError(f"JIEZI_CONSULT must be off or claude-cli, got {v!r}")
    return v
