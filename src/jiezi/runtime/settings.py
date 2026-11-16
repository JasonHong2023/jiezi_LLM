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
    translate: bool = True          # 整份文件逐段翻譯、譯文檢查、簡轉繁（add-translation）/ chunked translation with checks
    injection_guard: bool = True    # 文件、工具結果、附加資料只當資料（add-injection-guard）/ external content is data
    skills: bool = True             # 工具呼叫附上過去成功的範例（技能庫 v0）/ verified tool-call examples
    laws: bool = True               # 法律問題先查全國法規資料庫（add-laws）/ law questions use the MOJ database
    rag: bool = True                # 知識庫用向量重排（有建向量時）/ vector reranking when vectors exist (add-rag)
    rag_min: float = 0.5            # 向量相似度門檻 / similarity threshold
    samples: int = 4                # 可驗證的問題（工具呼叫、程式）平行取樣幾個；1 = 關閉（add-sampling）
    sample_temperature: float = 0.7
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
        samples=max(1, min(8, _int(env, "JIEZI_SAMPLES", 4))),
        rag=_onoff(env, "JIEZI_RAG", True),
        laws=_onoff(env, "JIEZI_LAWS", True),
        skills=_onoff(env, "JIEZI_SKILLS", True),
        longdoc=_onoff(env, "JIEZI_LONGDOC", True),
        injection_guard=_onoff(env, "JIEZI_INJECTION_GUARD", True),
        translate=_onoff(env, "JIEZI_TRANSLATE", True),
        rag_min=float(env.get("JIEZI_RAG_MIN") or 0.5),
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
