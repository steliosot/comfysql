from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


VALID_CATEGORIES: set[str] = {
    "checkpoints",
    "configs",
    "loras",
    "vae",
    "text_encoders",
    "diffusion_models",
    "clip_vision",
    "style_models",
    "embeddings",
    "diffusers",
    "vae_approx",
    "controlnet",
    "gligen",
    "upscale_models",
    "latent_upscale_models",
    "hypernetworks",
    "photomaker",
    "classifiers",
    "model_patches",
    "audio_encoders",
}


class PullError(RuntimeError):
    def __init__(self, message: str, exit_code: int = 2):
        super().__init__(message)
        self.exit_code = exit_code


@dataclass
class HFModelEntry:
    repo: str
    filename: str
    category: str
    repo_type: str = "model"
    revision: str | None = None
    platforms: list[str] | None = None


@dataclass
class PullReport:
    copied: int
    skipped_exists: int
    failed: int
    bytes_copied: int
    total: int
    dry_run: bool
    existing_before: int = 0
    need_download_before: int = 0
    skipped_platform: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "copied": self.copied,
            "skipped_exists": self.skipped_exists,
            "failed": self.failed,
            "bytes_copied": self.bytes_copied,
            "total": self.total,
            "dry_run": self.dry_run,
            "existing_before": self.existing_before,
            "need_download_before": self.need_download_before,
            "skipped_platform": self.skipped_platform,
        }


def ensure_confirmed(*, yes: bool, prompt_fn=input, message: str | None = None) -> None:
    if yes:
        return
    prompt = message or "Are you sure this may take time? [y/N]: "
    answer = str(prompt_fn(prompt)).strip().lower()
    if answer not in {"y", "yes"}:
        raise PullError("Cancelled by user.", exit_code=130)


def load_config(config_path: Path) -> dict[str, Any]:
    if not config_path.exists():
        raise PullError(
            f"HF pull config not found: {config_path}\n"
            "Create it first, or use --config <path>.",
            exit_code=2,
        )
    try:
        return json.loads(config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise PullError(f"Invalid HF pull config JSON: {exc}", exit_code=2) from exc


def validate_config(payload: dict[str, Any]) -> list[HFModelEntry]:
    models = payload.get("models")
    if not isinstance(models, list) or not models:
        raise PullError("HF pull config must contain non-empty 'models' array.", exit_code=2)

    out: list[HFModelEntry] = []
    for idx, item in enumerate(models):
        if not isinstance(item, dict):
            raise PullError(f"models[{idx}] must be an object.", exit_code=2)
        repo = str(item.get("repo", "")).strip()
        filename = str(item.get("filename", "")).strip()
        category = str(item.get("category", "")).strip()
        repo_type = str(item.get("repo_type", "model")).strip() or "model"
        revision_raw = item.get("revision")
        revision = str(revision_raw).strip() if isinstance(revision_raw, str) and revision_raw.strip() else None
        platforms_raw = item.get("platforms")
        platforms: list[str] | None = None

        if not repo or not filename or not category:
            raise PullError(f"models[{idx}] requires repo, filename, category.", exit_code=2)
        if category not in VALID_CATEGORIES:
            raise PullError(
                f"models[{idx}] has invalid category '{category}'. "
                f"Allowed: {', '.join(sorted(VALID_CATEGORIES))}",
                exit_code=2,
            )
        if repo_type not in {"model", "dataset", "space"}:
            raise PullError(f"models[{idx}] has invalid repo_type '{repo_type}'.", exit_code=2)
        if platforms_raw is not None:
            if isinstance(platforms_raw, str):
                platforms = [platforms_raw.strip().lower()] if platforms_raw.strip() else []
            elif isinstance(platforms_raw, list):
                platforms = [str(x).strip().lower() for x in platforms_raw if str(x).strip()]
            else:
                raise PullError(f"models[{idx}] 'platforms' must be a string or array.", exit_code=2)

        out.append(
            HFModelEntry(
                repo=repo,
                filename=filename,
                category=category,
                repo_type=repo_type,
                revision=revision,
                platforms=platforms,
            )
        )
    return out


def current_platform_tags() -> set[str]:
    # Manual override for testing/cross-platform prefetching.
    override = os.environ.get("COMFY_PULL_PLATFORM", "").strip().lower()
    if override:
        return {override}

    tags: set[str] = set()
    sp = sys.platform.lower()
    tags.add(sp)
    if sp.startswith("darwin"):
        tags.update({"mac", "macos", "darwin"})
    elif sp.startswith("linux"):
        tags.update({"linux"})
        os_release = Path("/etc/os-release")
        if os_release.exists():
            try:
                text = os_release.read_text(encoding="utf-8", errors="replace").lower()
                for line in text.splitlines():
                    if line.startswith("id="):
                        distro = line.split("=", 1)[1].strip().strip('"')
                        if distro:
                            tags.add(distro)
                    if line.startswith("id_like="):
                        values = line.split("=", 1)[1].strip().strip('"').split()
                        tags.update(v for v in values if v)
            except Exception:
                pass
    elif sp.startswith("win"):
        tags.update({"windows", "win"})
    return tags


def _ensure_hf_cli_available() -> str:
    candidates: list[str] = []
    by_path_hf = shutil.which("hf")
    by_path_hf_legacy = shutil.which("huggingface-cli")
    if by_path_hf:
        candidates.append(by_path_hf)
    if by_path_hf_legacy:
        candidates.append(by_path_hf_legacy)

    py_bin = Path(sys.executable).parent
    for name in ("hf", "huggingface-cli"):
        local = py_bin / name
        if local.exists():
            candidates.append(str(local))

    hf_path = next((c for c in candidates if c), None)
    if not hf_path:
        raise PullError(
            "Missing required 'hf' CLI. Install with: ./venv/bin/python -m pip install -U huggingface_hub[hf_transfer]",
            exit_code=5,
        )
    return hf_path


def _run_hf_download(*, hf_bin: str, entry: HFModelEntry, local_dir: Path) -> tuple[bool, int]:
    local_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        hf_bin,
        "download",
        entry.repo,
        entry.filename,
        "--repo-type",
        entry.repo_type,
        "--local-dir",
        str(local_dir),
    ]
    if entry.revision:
        cmd.extend(["--revision", entry.revision])
    proc = subprocess.run(cmd, text=True, capture_output=True)
    if proc.returncode != 0:
        return (False, 0)
    dest = local_dir / Path(entry.filename).name
    size = dest.stat().st_size if dest.exists() else 0
    return (True, size)


def execute_pull_hf(
    *,
    config_path: Path,
    models_dir: Path,
    state_dir: Path,
    yes: bool,
    dry_run: bool,
    log_fn,
    prompt_fn=input,
) -> PullReport:
    _ = state_dir  # reserved for future caching/report extensions
    hf_bin = _ensure_hf_cli_available()
    payload = load_config(config_path)
    all_entries = validate_config(payload)
    tags = current_platform_tags()
    entries: list[HFModelEntry] = []
    skipped_platform = 0
    for entry in all_entries:
        if entry.platforms:
            allowed = {p.lower() for p in entry.platforms}
            if not (allowed & tags):
                skipped_platform += 1
                continue
        entries.append(entry)

    destinations: list[Path] = [models_dir / e.category / Path(e.filename).name for e in entries]
    existing_before = sum(1 for p in destinations if p.exists())
    need_download_before = len(destinations) - existing_before
    log_fn(
        f"hf_config_loaded path={config_path} total={len(all_entries)} selected={len(entries)} "
        f"skipped_platform={skipped_platform} "
        f"already_downloaded={existing_before} need_download={need_download_before}"
    )
    ensure_confirmed(
        yes=yes,
        prompt_fn=prompt_fn,
        message=(
            f"Need to download {need_download_before} model file(s), already downloaded {existing_before}. "
            "Continue? [y/N]: "
        ),
    )

    copied = 0
    skipped_exists = 0
    failed = 0
    bytes_copied = 0

    for entry in entries:
        dest_dir = models_dir / entry.category
        dest_path = dest_dir / Path(entry.filename).name
        if dest_path.exists():
            skipped_exists += 1
            log_fn(f"skipped_exists repo={entry.repo} file={entry.filename} dest={dest_path}")
            continue
        if dry_run:
            copied += 1
            log_fn(f"dry_run_download repo={entry.repo} file={entry.filename} dest={dest_path}")
            continue

        ok, size = _run_hf_download(hf_bin=hf_bin, entry=entry, local_dir=dest_dir)
        if ok:
            copied += 1
            bytes_copied += size
            log_fn(f"copied repo={entry.repo} file={entry.filename} dest={dest_path} bytes={size}")
        else:
            failed += 1
            log_fn(f"failed repo={entry.repo} file={entry.filename}")

    return PullReport(
        copied=copied,
        skipped_exists=skipped_exists,
        failed=failed,
        bytes_copied=bytes_copied,
        total=len(entries),
        dry_run=dry_run,
        existing_before=existing_before,
        need_download_before=need_download_before,
        skipped_platform=skipped_platform,
    )


def ensure_default_hf_pull_config(path: Path) -> None:
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 1,
        "models": [],
        "notes": "Add more entries as needed. Existing local files are skipped by filename. Use 'platforms' to scope entries.",
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
