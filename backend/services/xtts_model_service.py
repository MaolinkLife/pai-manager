from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

import requests

from constants.paths import TTS_MODELS_DIR


XTTS_REPO_ID = "coqui/XTTS-v2"
OFFICIAL_XTTS_MODELS: list[dict[str, Any]] = [
    {"name": "xttsv2_2.0.0", "revision": "v2.0.0", "downloadable": True, "custom": False},
    {"name": "xttsv2_2.0.1", "revision": "v2.0.1", "downloadable": True, "custom": False},
    {"name": "xttsv2_2.0.2", "revision": "v2.0.2", "downloadable": True, "custom": False},
    {"name": "xttsv2_2.0.3", "revision": "v2.0.3", "downloadable": True, "custom": False},
]
CUSTOM_XTTS_MODEL = {
    "name": "xttsv2_test",
    "revision": None,
    "downloadable": False,
    "custom": True,
}
XTTS_REQUIRED_FILES = [
    "config.json",
    "model.pth",
    "dvae.pth",
    "mel_stats.pth",
    "speakers_xtts.pth",
    "vocab.json",
]
HF_RESOLVE_URL = "https://huggingface.co/{repo_id}/resolve/{revision}/{filename}"

_download_lock = threading.Lock()
_download_state: dict[str, dict[str, Any]] = {}


def _xtts_root() -> Path:
    root = Path(TTS_MODELS_DIR) / "xtts"
    root.mkdir(parents=True, exist_ok=True)
    (root / CUSTOM_XTTS_MODEL["name"]).mkdir(parents=True, exist_ok=True)
    return root


def _model_dir(model_name: str) -> Path:
    return _xtts_root() / model_name


def _is_model_installed(model_name: str) -> bool:
    model_dir = _model_dir(model_name)
    return all((model_dir / file_name).is_file() for file_name in XTTS_REQUIRED_FILES)


def _copy_state(state: dict[str, Any] | None) -> dict[str, Any]:
    if not state:
        return {
            "status": "idle",
            "progress": 0.0,
            "message": "",
            "downloaded_bytes": 0,
            "total_bytes": 0,
        }
    return dict(state)


def _set_download_state(model_name: str, **updates: Any) -> None:
    with _download_lock:
        current = _copy_state(_download_state.get(model_name))
        current.update(updates)
        _download_state[model_name] = current


def _get_download_state(model_name: str) -> dict[str, Any]:
    with _download_lock:
        return _copy_state(_download_state.get(model_name))


def _iter_catalog_entries() -> list[dict[str, Any]]:
    known_names = {item["name"] for item in OFFICIAL_XTTS_MODELS}
    entries = [dict(item) for item in OFFICIAL_XTTS_MODELS]
    entries.append(dict(CUSTOM_XTTS_MODEL))

    for child in sorted(_xtts_root().iterdir(), key=lambda path: path.name.lower()):
        if not child.is_dir() or child.name in known_names or child.name == CUSTOM_XTTS_MODEL["name"]:
            continue
        entries.append(
            {
                "name": child.name,
                "revision": None,
                "downloadable": False,
                "custom": True,
            }
        )

    return entries


def list_xtts_models() -> list[dict[str, Any]]:
    models: list[dict[str, Any]] = []
    for item in _iter_catalog_entries():
        state = _get_download_state(item["name"])
        installed = _is_model_installed(item["name"])
        models.append(
            {
                "name": item["name"],
                "path": item["name"],
                "revision": item["revision"],
                "downloadable": item["downloadable"],
                "custom": item["custom"],
                "installed": installed,
                "status": state["status"],
                "progress": state["progress"],
                "message": state["message"],
                "downloading": state["status"] == "downloading",
                "downloaded_bytes": state["downloaded_bytes"],
                "total_bytes": state["total_bytes"],
            }
        )
    return models


def _find_catalog_model(model_name: str) -> dict[str, Any] | None:
    for item in _iter_catalog_entries():
        if item["name"] == model_name:
            return item
    return None


def _head_file_size(url: str) -> int:
    try:
        response = requests.head(url, allow_redirects=True, timeout=30)
        response.raise_for_status()
        return int(response.headers.get("Content-Length") or 0)
    except Exception:
        return 0


def _update_progress(
    *,
    model_name: str,
    downloaded_bytes: int,
    total_bytes: int,
    completed_files: int,
    total_files: int,
    message: str,
) -> None:
    if total_bytes > 0:
        progress = round((downloaded_bytes / total_bytes) * 100, 1)
    else:
        progress = round((completed_files / max(total_files, 1)) * 100, 1)

    _set_download_state(
        model_name,
        status="downloading",
        progress=min(progress, 100.0),
        message=message,
        downloaded_bytes=downloaded_bytes,
        total_bytes=total_bytes,
    )


def _download_file(
    url: str,
    destination: Path,
    model_name: str,
    downloaded_bytes: int,
    total_bytes: int,
    completed_files: int,
    total_files: int,
) -> int:
    destination.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = destination.with_suffix(destination.suffix + ".part")

    with requests.get(url, stream=True, timeout=120) as response:
        response.raise_for_status()
        with open(tmp_path, "wb") as file_handle:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if not chunk:
                    continue
                file_handle.write(chunk)
                downloaded_bytes += len(chunk)
                _update_progress(
                    model_name=model_name,
                    downloaded_bytes=downloaded_bytes,
                    total_bytes=total_bytes,
                    completed_files=completed_files,
                    total_files=total_files,
                    message=f"Downloading {destination.name}",
                )

    tmp_path.replace(destination)
    return downloaded_bytes


def _download_xtts_model_worker(model_name: str, revision: str) -> None:
    model_dir = _model_dir(model_name)
    model_dir.mkdir(parents=True, exist_ok=True)

    total_files = len(XTTS_REQUIRED_FILES)
    total_bytes = 0
    file_urls: list[tuple[str, Path]] = []

    for file_name in XTTS_REQUIRED_FILES:
        url = HF_RESOLVE_URL.format(repo_id=XTTS_REPO_ID, revision=revision, filename=file_name)
        file_urls.append((url, model_dir / file_name))
        total_bytes += _head_file_size(url)

    downloaded_bytes = 0
    completed_files = 0
    _set_download_state(
        model_name,
        status="downloading",
        progress=0.0,
        message="Preparing download",
        downloaded_bytes=0,
        total_bytes=total_bytes,
    )

    try:
        for url, destination in file_urls:
            downloaded_bytes = _download_file(
                url,
                destination,
                model_name,
                downloaded_bytes,
                total_bytes,
                completed_files,
                total_files,
            )
            completed_files += 1
            _update_progress(
                model_name=model_name,
                downloaded_bytes=downloaded_bytes,
                total_bytes=total_bytes,
                completed_files=completed_files,
                total_files=total_files,
                message=f"Downloaded {destination.name}",
            )

        try:
            from TTS.utils.manage import ModelManager

            ModelManager(progress_bar=False)._update_paths(model_dir, model_dir / "config.json")
        except Exception:
            pass

        _set_download_state(
            model_name,
            status="completed",
            progress=100.0,
            message="Download completed",
            downloaded_bytes=downloaded_bytes,
            total_bytes=total_bytes,
        )
    except Exception as exc:
        _set_download_state(
            model_name,
            status="error",
            progress=0.0,
            message=str(exc),
            downloaded_bytes=downloaded_bytes,
            total_bytes=total_bytes,
        )


def start_xtts_model_download(model_name: str) -> dict[str, Any]:
    catalog_model = _find_catalog_model(model_name)
    if catalog_model is None:
        raise ValueError(f"Unknown XTTS model '{model_name}'")

    if not catalog_model["downloadable"] or not catalog_model["revision"]:
        raise ValueError(f"XTTS model '{model_name}' must be added manually")

    state = _get_download_state(model_name)
    if state["status"] == "downloading":
        return state

    worker = threading.Thread(
        target=_download_xtts_model_worker,
        args=(model_name, str(catalog_model["revision"])),
        daemon=True,
    )
    worker.start()
    return _get_download_state(model_name)
