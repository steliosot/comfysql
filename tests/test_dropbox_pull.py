from __future__ import annotations

import json
from pathlib import Path
import zipfile

import pytest

from comfy_custom import dropbox_pull


def test_validate_manifest_rejects_bad_category() -> None:
    payload = {"models": [{"source": "https://dropbox.com/s/file.safetensors?dl=0", "category": "bad"}]}
    with pytest.raises(dropbox_pull.PullError):
        dropbox_pull.validate_manifest(payload)


def test_validate_manifest_accepts_valid_entry() -> None:
    payload = {"models": [{"source": "https://dropbox.com/s/file.safetensors?dl=0", "category": "checkpoints"}]}
    entries = dropbox_pull.validate_manifest(payload)
    assert len(entries) == 1
    assert entries[0].category == "checkpoints"
    assert entries[0].filename == "file.safetensors"


def test_ensure_confirmed_cancelled() -> None:
    with pytest.raises(dropbox_pull.PullError):
        dropbox_pull.ensure_confirmed(yes=False, prompt_fn=lambda _prompt: "n")


def test_execute_pull_dry_run(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    models_dir = tmp_path / "models"
    state_dir = tmp_path / ".state"
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "models": [
                    {
                        "source": "https://www.dropbox.com/s/abc/model.safetensors?dl=0",
                        "category": "checkpoints",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(dropbox_pull, "estimate_total_bytes", lambda entries: None)
    report = dropbox_pull.execute_pull(
        dropbox_url="https://www.dropbox.com/s/root/shared?dl=0",
        manifest=str(manifest_path),
        models_dir=models_dir,
        state_dir=state_dir,
        yes=True,
        dry_run=True,
        log_fn=lambda _msg: None,
    )
    assert report.copied == 1
    assert report.failed == 0
    assert not (models_dir / "checkpoints" / "model.safetensors").exists()


def test_execute_pull_skips_existing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    models_dir = tmp_path / "models"
    existing = models_dir / "checkpoints" / "model.safetensors"
    existing.parent.mkdir(parents=True, exist_ok=True)
    existing.write_bytes(b"abc")
    state_dir = tmp_path / ".state"

    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "models": [
                    {
                        "source": "https://www.dropbox.com/s/abc/model.safetensors?dl=0",
                        "category": "checkpoints",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(dropbox_pull, "estimate_total_bytes", lambda entries: None)
    report = dropbox_pull.execute_pull(
        dropbox_url="https://www.dropbox.com/s/root/shared?dl=0",
        manifest=str(manifest_path),
        models_dir=models_dir,
        state_dir=state_dir,
        yes=True,
        dry_run=False,
        log_fn=lambda _msg: None,
    )
    assert report.skipped_exists == 1
    assert report.copied == 0


def test_execute_pull_auto_map_dry_run(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    models_dir = tmp_path / "models"
    input_dir = tmp_path / "input"
    state_dir = tmp_path / ".state"

    archive = tmp_path / "shared.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("comfyui-defaults/models/checkpoints/a.safetensors", b"abc")
        zf.writestr("comfyui-defaults/input/woman.jpg", b"abc")
        zf.writestr("comfyui-defaults/other/ignored.txt", b"abc")
    monkeypatch.setattr(
        dropbox_pull,
        "_load_shared_folder_archive_index",
        lambda _url, log_fn=None: (
            archive,
            [
                dropbox_pull.DropboxFileEntry(rel_path="comfyui-defaults/models/checkpoints/a.safetensors", size=3),
                dropbox_pull.DropboxFileEntry(rel_path="comfyui-defaults/input/woman.jpg", size=3),
                dropbox_pull.DropboxFileEntry(rel_path="comfyui-defaults/other/ignored.txt", size=3),
            ],
        ),
    )
    report = dropbox_pull.execute_pull(
        dropbox_url="https://www.dropbox.com/s/root/shared?dl=0",
        manifest=None,
        models_dir=models_dir,
        input_dir=input_dir,
        state_dir=state_dir,
        yes=True,
        dry_run=True,
        log_fn=lambda _msg: None,
    )
    assert report.total == 2
    assert report.copied == 2
    assert report.failed == 0
    assert not (models_dir / "checkpoints" / "a.safetensors").exists()
    assert not (input_dir / "woman.jpg").exists()
