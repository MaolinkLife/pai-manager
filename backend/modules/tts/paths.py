from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from constants.paths import RVC_MODELS_DIR, TEMP_DIR, TTS_MODELS_DIR


_legacy_paths_migrated = False
VOICE_AUDIO_EXTENSIONS = {".wav", ".mp3", ".flac", ".ogg", ".m4a"}


def project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _migrate_legacy_tree(source: Path, target: Path) -> None:
    if not source.exists() or not source.is_dir():
        return

    target.mkdir(parents=True, exist_ok=True)
    for child in source.iterdir():
        destination = target / child.name
        if destination.exists():
            if child.is_dir():
                _migrate_legacy_tree(child, destination)
                try:
                    child.rmdir()
                except OSError:
                    pass
            continue
        try:
            shutil.move(str(child), str(destination))
        except Exception:
            continue

    try:
        source.rmdir()
    except OSError:
        pass


def _copy_audio_files_tree(source: Path, target: Path) -> None:
    if not source.exists() or not source.is_dir():
        return

    target.mkdir(parents=True, exist_ok=True)
    for child in source.rglob("*"):
        if not child.is_file() or child.suffix.lower() not in VOICE_AUDIO_EXTENSIONS:
            continue
        relative = child.relative_to(source)
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            continue
        try:
            shutil.copy2(str(child), str(destination))
        except Exception:
            continue


def _migrate_legacy_paths_once() -> None:
    global _legacy_paths_migrated
    if _legacy_paths_migrated:
        return

    _migrate_legacy_tree(project_root() / "outputs", Path(TEMP_DIR) / "output")
    _migrate_legacy_tree(project_root() / "voices", Path(TTS_MODELS_DIR) / "voices")
    _migrate_legacy_tree(Path(TTS_MODELS_DIR) / "xtts" / "voices", Path(TTS_MODELS_DIR) / "voices")
    _migrate_legacy_tree(Path(TTS_MODELS_DIR).parent / "xtts" / "voices", Path(TTS_MODELS_DIR) / "voices")
    _copy_audio_files_tree(Path(RVC_MODELS_DIR) / "voices", Path(TTS_MODELS_DIR) / "voices")
    _copy_audio_files_tree(Path(TTS_MODELS_DIR) / "xtts", Path(TTS_MODELS_DIR) / "voices")
    _legacy_paths_migrated = True


def outputs_root() -> Path:
    _migrate_legacy_paths_once()
    path = Path(TEMP_DIR) / "output"
    path.mkdir(parents=True, exist_ok=True)
    return path


def voices_root() -> Path:
    _migrate_legacy_paths_once()
    path = Path(TTS_MODELS_DIR) / "voices"
    path.mkdir(parents=True, exist_ok=True)
    return path


def create_temp_audio_file(*, suffix: str, prefix: str = "tts_") -> tuple[int, str]:
    return tempfile.mkstemp(prefix=prefix, suffix=suffix, dir=str(outputs_root()))
