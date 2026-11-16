"""bootstrap 主程式：依序執行各步驟，記錄狀態，可續跑（規格 bootstrap；design D1）。
Bootstrap main: runs the steps in order, records state, and can resume (spec bootstrap; design D1).

步驟 / Steps: prereqs → env → python → llama.cpp → hwprobe → cuda (可選 / optional)
             → build → sandbox (可選 / optional) → model → smoke

每個步驟都會自行檢查「已完成且仍有效」並略過，所以重跑時會從失敗的步驟接續。
Every step checks "done and still valid" itself and skips, so a re-run resumes at the failed step."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from . import build, models, sandbox_tool, smoke, source, sudo_window
from .build import budget_prefix
from .common import StepError, load_env, project_root

INSTALL_HINTS = {
    "git": "sudo apt install git",
    "cc": "sudo apt install build-essential",
    "c++": "sudo apt install build-essential",
    "openssl-headers": "sudo apt install libssl-dev",
}


def has_openssl_headers(cc: str = "cc") -> bool:
    """以編譯器前處理器確認找得到 OpenSSL 3.x 標頭（HTTPS 對外連線所需）。
    Ask the compiler's preprocessor whether OpenSSL 3.x headers are available (needed for HTTPS)."""
    if not shutil.which(cc):
        return False
    src = "#include <openssl/opensslv.h>\n#if OPENSSL_VERSION_NUMBER < 0x30000000L\n#error old\n#endif\n"
    p = subprocess.run([cc, "-E", "-x", "c", "-"], input=src, capture_output=True, text=True)
    return p.returncode == 0
NETWORK_PROBES = ("https://github.com", "https://huggingface.co")


class Ctx:
    def __init__(self, root: Path, offer_setup: bool):
        self.root = root
        self.offer_setup = offer_setup
        self.facts: dict = {}
        self.model_path: Path | None = None
        self.notes: list[str] = []


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ── 步驟 / Steps ────────────────────────────────────────────────────────────

def step_prereqs(ctx: Ctx) -> str:
    missing = [t for t in ("git", "cc", "c++") if not shutil.which(t)]
    if not shutil.which("uv"):  # bash 入口已檢查，這裡防直接呼叫 / guarded by the bash entry too
        missing.append("uv")
    if "cc" not in missing and not has_openssl_headers():
        missing.append("openssl-headers")
    if missing:
        platform = sudo_window.detect_platform()
        lines = [f"  - {t}: {INSTALL_HINTS.get(t, 'https://docs.astral.sh/uv/getting-started/installation/')}"
                 for t in missing]
        raise StepError(f"missing prerequisites on {platform} (bootstrap never installs system packages itself):\n"
                        + "\n".join(lines))
    needs_net = not (ctx.root / "vendor" / "llama.cpp").exists() or not _smoke_model_present(ctx)
    if needs_net:
        for url in NETWORK_PROBES:
            try:
                urllib.request.urlopen(urllib.request.Request(url, method="HEAD",
                                                              headers={"User-Agent": "jiezi-bootstrap"}), timeout=15)
            except Exception as exc:  # noqa: BLE001
                raise StepError(f"network check failed for {url}: {exc}") from exc
        return "git, compiler, uv, OpenSSL headers, network ok"
    return "git, compiler, uv, OpenSSL headers ok (network not needed: sources and model already present)"


def _smoke_model_present(ctx: Ctx) -> bool:
    try:
        m = models.smoke_model(models.load_manifest(ctx.root / "models" / "manifest.toml"))
    except StepError:
        return False
    return (models.models_dir(ctx.root) / m.file).exists()


def step_env(ctx: Ctx) -> str:
    env_file, example = ctx.root / ".env", ctx.root / ".env.example"
    created = False
    if not env_file.exists():
        shutil.copyfile(example, env_file)
        env_file.chmod(0o600)
        created = True
    from jiezi.config import ensure_gateway_key
    if ensure_gateway_key(ctx.root):
        ctx.notes.append("已在 .env 產生 gateway 本機金鑰 JIEZI_GATEWAY_KEY / generated the local gateway key in .env")
    if not load_env(ctx.root).get("JIEZI_CLOUD_BASE_URL"):
        ctx.notes.append("JIEZI_CLOUD_BASE_URL 未設定：系統將以純本機模式運作 / "
                         "JIEZI_CLOUD_BASE_URL unset: the system will run local-only")
    return ".env created from .env.example" if created else ".env present"


def step_python(ctx: Ctx) -> str:
    p = subprocess.run(["uv", "sync", "--project", str(ctx.root)], capture_output=True, text=True)
    if p.returncode != 0:
        raise StepError(f"uv sync failed:\n{p.stderr.strip()}")
    return "uv sync ok"


def step_llama_cpp(ctx: Ctx) -> str:
    pin = source.read_pin(ctx.root / "openspec" / "specs" / "stack.md")
    state = source.fetch(ctx.root / "vendor" / "llama.cpp", pin)
    return f"{state} at {pin.commit[:12]}"


def step_hwprobe(ctx: Ctx) -> str:
    out = ctx.root / "facts.json"
    p = subprocess.run([sys.executable, str(ctx.root / "scripts" / "hwprobe.py"), "--out", str(out)],
                       capture_output=True, text=True)
    if p.returncode != 0 or not out.exists():
        raise StepError(f"hwprobe failed:\n{p.stderr.strip()}")
    ctx.facts = json.loads(out.read_text(encoding="utf-8"))
    return f"facts.json written (fingerprint {(ctx.facts.get('fingerprint') or {}).get('id')})"


def step_cuda(ctx: Ctx) -> str:
    cuda = ((ctx.facts.get("backends") or {}).get("buildable") or {}).get("cuda") or {}
    reason = cuda.get("reason") or ""
    if cuda.get("ok"):
        return "CUDA toolkit present"
    if "nvidia driver" in reason or "nvcc" not in reason:
        return f"skipped: {reason or 'no NVIDIA GPU'}"
    platform = sudo_window.detect_platform()
    if platform not in ("wsl2", "ubuntu"):
        return f"skipped: no CUDA setup for platform {platform}"
    if not ctx.offer_setup:
        return "skipped: --no-setup (CPU only)"
    script = ctx.root / "scripts" / "setup" / platform / "install_cuda"
    rc = subprocess.run([str(script)]).returncode
    if rc != 0:
        ctx.notes.append("CUDA toolkit 未安裝，以純 CPU 繼續 / CUDA toolkit not installed; continuing CPU-only")
        return f"skipped: installer exit code {rc}"
    step_hwprobe(ctx)  # 重新偵測 / re-detect
    return "CUDA toolkit installed; facts.json refreshed"


def step_build(ctx: Ctx) -> str:
    commit = source.read_pin(ctx.root / "openspec" / "specs" / "stack.md").commit
    summary = build.build_all(ctx.facts, ctx.root / "vendor" / "llama.cpp", commit, ctx.root)
    return ", ".join(f"{s['backend']}={s['result']}" for s in summary)


def step_sandbox(ctx: Ctx) -> str:
    """選用：建置程式驗證用的 bubblewrap；缺系統前置時略過，只停用程式驗證。
    Optional: build bubblewrap for code verification; skipped when system prerequisites are missing,
    which only disables code verification."""
    missing = sandbox_tool.has_build_deps()
    if missing and not sandbox_tool.binary(ctx.root).exists():
        ctx.notes.append(f"程式驗證沙盒未建置（缺 {missing}）；安裝：{sandbox_tool.DEPS_HINT} / "
                         f"code sandbox not built (missing {missing}); install with {sandbox_tool.DEPS_HINT}")
        return f"skipped: missing {missing}"
    prefix, _, _ = budget_prefix(ctx.facts)
    state, rec = sandbox_tool.build(ctx.root, prefix=prefix)
    return f"bubblewrap {state}: {rec['version']} ({rec['commit'][:12]})"


def step_model(ctx: Ctx) -> str:
    m = models.smoke_model(models.load_manifest(ctx.root / "models" / "manifest.toml"))
    ctx.model_path, state = models.ensure(m, models.models_dir(ctx.root))
    return f"{m.file} {state} (SHA-256 ok, license {m.license})"


def step_data(ctx: Ctx) -> str:
    """選用：建置本機資料（辭典、課綱、知識庫、法規、寫作連結）；失敗只記為注意事項。
    Optional: build the local data sets; failures only become notes."""
    import subprocess
    p = subprocess.run([str(ctx.root / "scripts" / "jiezi"), "data", "build"], capture_output=True, text=True)
    failed = [ln for ln in p.stdout.splitlines() if ln.startswith("failed:")]
    if p.returncode != 0:
        ctx.notes.append("部分本機資料沒有建好，之後執行 scripts/jiezi data build / some local data failed; "
                         "run scripts/jiezi data build later")
    return "local data built" if p.returncode == 0 else f"partial ({'; '.join(failed) or p.stderr.strip()[:120]})"


def step_smoke(ctx: Ctx) -> str:
    r = smoke.run(ctx.root, ctx.model_path, ctx.facts)
    (ctx.root / "var" / "smoke.json").write_text(json.dumps({**r, "at": now()}, indent=2, ensure_ascii=False) + "\n",
                                                 encoding="utf-8")
    return (f"build={r['build']} model={r['model']} threads={r['threads']} "
            f"t/s={r['tokens_per_second']:.2f} answer={r['answer']!r}")


STEPS = [
    ("prereqs", step_prereqs), ("env", step_env), ("python", step_python), ("llama.cpp", step_llama_cpp),
    ("hwprobe", step_hwprobe), ("cuda", step_cuda), ("build", step_build), ("sandbox", step_sandbox),
    ("model", step_model), ("data", step_data),
    ("smoke", step_smoke),
]


# ── 狀態 / State ────────────────────────────────────────────────────────────

def state_path(root: Path) -> Path:
    return root / "var" / "bootstrap-state.json"


def load_state(root: Path) -> dict:
    try:
        return json.loads(state_path(root).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"steps": {}}


def save_state(root: Path, state: dict) -> None:
    p = state_path(root)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def run_steps(ctx: Ctx, steps=STEPS, log=print) -> int:
    state = load_state(ctx.root)
    if state.get("failed_step"):
        log(f"上次在「{state['failed_step']}」失敗；已完成的步驟會自動略過 / "
            f"last run failed at '{state['failed_step']}'; finished steps will be skipped")
    for i, (name, fn) in enumerate(steps, 1):
        log(f"\n[{i}/{len(steps)}] {name}")
        try:
            detail = fn(ctx)
        except StepError as exc:
            state["steps"][name] = {"status": "failed", "detail": str(exc), "at": now()}
            state["failed_step"] = name
            save_state(ctx.root, state)
            log(f"  ✗ {exc}\n\n失敗於步驟「{name}」；修正後重新執行 scripts/bootstrap 即可接續 / "
                f"failed at step '{name}'; fix it and re-run scripts/bootstrap to resume")
            return 1
        state["steps"][name] = {"status": "ok", "detail": detail, "at": now()}
        state.pop("failed_step", None)
        save_state(ctx.root, state)
        log(f"  ✓ {detail}")
    for n in ctx.notes:
        log(f"注意 / Note: {n}")
    log("\nbootstrap 完成 / bootstrap complete")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="scripts/bootstrap", description="Jiezi one-command setup")
    ap.add_argument("--no-setup", action="store_true",
                    help="不詢問任何需要 sudo 的安裝（純 CPU 繼續） / never offer sudo installs (continue CPU-only)")
    args = ap.parse_args(argv)
    return run_steps(Ctx(project_root(), offer_setup=not args.no_setup))


if __name__ == "__main__":
    sys.exit(main())
