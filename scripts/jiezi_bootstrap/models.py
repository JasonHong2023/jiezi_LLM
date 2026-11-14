"""模型清單解析、授權檢查、下載與 SHA-256 驗證（design D7；規則 R18.3）。
Model manifest parsing, license checks, download, and SHA-256 verification (design D7; rule R18.3)."""

from __future__ import annotations

import hashlib
import tomllib
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from .common import StepError, load_env, project_root

REQUIRED = ("name", "file", "url", "sha256", "size", "license", "license_url")


@dataclass(frozen=True)
class Model:
    name: str
    file: str
    url: str
    sha256: str
    size: int
    license: str
    license_url: str
    smoke_test: bool = False


def load_manifest(path: Path | None = None) -> list[Model]:
    """解析清單；缺必要欄位（包含授權）或格式錯誤就停止。
    Parse the manifest; stop on any missing required field (license included) or bad value."""
    path = path or project_root() / "models" / "manifest.toml"
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise StepError(f"{path}: {exc}") from exc
    models = []
    for i, entry in enumerate(data.get("model") or []):
        label = entry.get("name") or f"entry #{i + 1}"
        missing = [k for k in REQUIRED if not entry.get(k)]
        if missing:
            raise StepError(f"{path}: {label} is missing {', '.join(missing)} (license fields are mandatory, R18.3)")
        sha = str(entry["sha256"]).lower()
        if len(sha) != 64 or any(c not in "0123456789abcdef" for c in sha):
            raise StepError(f"{path}: {label} has an invalid sha256")
        if "/" in entry["file"] or entry["file"].startswith("."):
            raise StepError(f"{path}: {label} file must be a plain file name")
        models.append(Model(name=entry["name"], file=entry["file"], url=entry["url"], sha256=sha,
                            size=int(entry["size"]), license=entry["license"],
                            license_url=entry["license_url"], smoke_test=bool(entry.get("smoke_test", False))))
    if not models:
        raise StepError(f"{path}: no [[model]] entries")
    return models


def smoke_model(models: list[Model]) -> Model:
    """冒煙測試用：標記 smoke_test 的最小模型。 / The smallest entry marked smoke_test."""
    marked = [m for m in models if m.smoke_test]
    if not marked:
        raise StepError("manifest has no entry with smoke_test = true")
    return min(marked, key=lambda m: m.size)


def models_dir(root: Path | None = None) -> Path:
    root = root or project_root()
    configured = load_env(root).get("JIEZI_MODELS_DIR")
    return Path(configured).expanduser().resolve() if configured else root / "models"


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


def is_valid(model: Model, path: Path) -> bool:
    return path.is_file() and path.stat().st_size == model.size and sha256_of(path) == model.sha256


def _download(url: str, dest: Path, log=print) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": "jiezi-bootstrap"})
    with urllib.request.urlopen(req, timeout=120) as r, dest.open("wb") as fh:
        total = int(r.headers.get("Content-Length") or 0)
        done, next_report = 0, 0.1
        while chunk := r.read(1 << 20):
            fh.write(chunk)
            done += len(chunk)
            if total and done / total >= next_report:
                log(f"  {done * 100 // total}% ({done >> 20} / {total >> 20} MiB)")
                next_report += 0.1


def ensure(model: Model, directory: Path, download=_download, log=print) -> tuple[Path, str]:
    """確保模型存在且 SHA-256 吻合；回傳 (路徑, 'present' | 'downloaded')。
    不吻合的下載會被刪除並停止；既有但不吻合的檔案不會被覆蓋。
    Ensure the model exists with a matching SHA-256; return (path, 'present' | 'downloaded').
    A mismatching download is deleted and stops the step; an existing mismatching file is not overwritten."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / model.file
    if path.exists():
        if is_valid(model, path):
            return path, "present"
        raise StepError(f"{path} exists but its size or SHA-256 does not match the manifest; "
                        "remove it and re-run (not overwriting an unknown file)")
    part = path.with_name(path.name + ".part")
    part.unlink(missing_ok=True)
    log(f"downloading {model.name} ({model.size >> 20} MiB, license {model.license})")
    try:
        download(model.url, part, log=log)
        if part.stat().st_size != model.size:
            raise StepError(f"{model.name}: size {part.stat().st_size} != manifest {model.size}")
        got = sha256_of(part)
        if got != model.sha256:
            raise StepError(f"{model.name}: SHA-256 mismatch (got {got}, manifest {model.sha256})")
    except BaseException:
        part.unlink(missing_ok=True)
        raise
    part.rename(path)
    return path, "downloaded"
