from __future__ import annotations

import re
from pathlib import Path

from modules.tts.ffmpeg_tools import FFmpegError, probe_audio, require_binary, run_binary
from modules.tts.paths import voices_root

ALLOWED_EXTENSIONS = {".wav", ".mp3", ".flac", ".ogg", ".m4a"}
MAX_UPLOAD_BYTES = 25 * 1024 * 1024
MIN_PREPARED_SAMPLE_SECONDS = 2.0
MIN_PREPARED_DURATION_RATIO = 0.35
XTTS_TARGET_SAMPLE_RATE = 22050
XTTS_TARGET_CHANNELS = 1
XTTS_TARGET_CODEC = "pcm_s16le"


def _voices_root() -> Path:
    return voices_root()


def _sanitize_stem(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip())
    cleaned = cleaned.strip("._-")
    return cleaned or "voice_sample"


def _unique_path(base_dir: Path, stem: str, suffix: str) -> Path:
    candidate = base_dir / f"{stem}{suffix}"
    if not candidate.exists():
        return candidate

    counter = 2
    while True:
        candidate = base_dir / f"{stem}_{counter}{suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


def _extract_duration_seconds(probe_payload: dict) -> float:
    format_info = probe_payload.get("format") or {}
    raw_duration = format_info.get("duration")
    try:
        duration = float(raw_duration)
    except (TypeError, ValueError):
        duration = 0.0
    return max(0.0, duration)


def _extract_audio_stream(probe_payload: dict) -> dict:
    for stream in probe_payload.get("streams") or []:
        if stream.get("codec_type") == "audio":
            return stream
    return {}


def _probe_voice_file(file_path: str | Path) -> dict:
    path = Path(file_path)
    probe_payload = probe_audio(path)
    stream = _extract_audio_stream(probe_payload)
    duration = _extract_duration_seconds(probe_payload)

    try:
        sample_rate = int(stream.get("sample_rate") or 0)
    except (TypeError, ValueError):
        sample_rate = 0

    try:
        channels = int(stream.get("channels") or 0)
    except (TypeError, ValueError):
        channels = 0

    codec = str(stream.get("codec_name") or path.suffix.lstrip(".") or "").lower()
    size_bytes = 0
    try:
        size_bytes = int(path.stat().st_size)
    except OSError:
        size_bytes = 0

    is_xtts_compatible = (
        path.suffix.lower() == ".wav"
        and sample_rate == XTTS_TARGET_SAMPLE_RATE
        and channels == XTTS_TARGET_CHANNELS
        and codec == XTTS_TARGET_CODEC
    )

    return {
        "probe_payload": probe_payload,
        "stream": stream,
        "duration": duration,
        "sample_rate": sample_rate,
        "channels": channels,
        "codec": codec,
        "size_bytes": size_bytes,
        "is_xtts_compatible": is_xtts_compatible,
    }


def summarize_voice_file(file_path: str | Path) -> dict:
    path = Path(file_path)
    metadata = _probe_voice_file(path)
    duration = metadata["duration"]
    sample_rate = metadata["sample_rate"]
    channels = metadata["channels"]
    codec = metadata["codec"]
    size_bytes = metadata["size_bytes"]
    is_xtts_compatible = metadata["is_xtts_compatible"]
    is_prepared_xtts = bool(
        is_xtts_compatible
        and (path.suffix.lower() == ".wav" and path.stem.lower().endswith("_xtts"))
    )
    health = "ready"
    hint = "Ready to use."
    if duration <= 0:
        health = "unknown"
        hint = "Audio metadata is unavailable."
    elif is_xtts_compatible:
        health = "xtts_ready"
        hint = "Ready for XTTS. No conversion is needed."
    elif duration < 2.0:
        health = "short"
        hint = "Very short sample. Voice cloning may sound unstable."
    elif duration > 45.0:
        health = "long"
        hint = "Long sample. Cleaner shorter speech often clones better."
    elif channels > 1 or sample_rate != XTTS_TARGET_SAMPLE_RATE or codec != XTTS_TARGET_CODEC:
        health = "converted_recommended"
        hint = "Conversion recommended: resample to 22050 Hz mono PCM_S16LE for XTTS."

    return {
        "duration_seconds": round(duration, 2),
        "sample_rate": sample_rate,
        "channels": channels,
        "codec": codec,
        "size_bytes": size_bytes,
        "is_prepared_xtts": is_prepared_xtts,
        "is_xtts_compatible": is_xtts_compatible,
        "health": health,
        "hint": hint,
    }


def _prepared_sample_is_usable(*, source_duration: float, processed_duration: float) -> bool:
    if processed_duration <= 0:
        return False
    if processed_duration >= MIN_PREPARED_SAMPLE_SECONDS:
        return True
    if source_duration <= 0:
        return False
    return processed_duration >= source_duration * MIN_PREPARED_DURATION_RATIO


def _normalize_to_xtts_wav(source_path: Path, destination_path: Path, *, source_duration: float) -> None:
    require_binary("ffmpeg")
    try:
        run_binary(
            "ffmpeg",
            [
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                str(source_path),
                "-vn",
                "-ar",
                str(XTTS_TARGET_SAMPLE_RATE),
                "-ac",
                str(XTTS_TARGET_CHANNELS),
                "-c:a",
                XTTS_TARGET_CODEC,
                "-sample_fmt",
                "s16",
                str(destination_path),
            ],
        )
        processed_probe = probe_audio(destination_path)
        processed_duration = _extract_duration_seconds(processed_probe)
        if not _prepared_sample_is_usable(
            source_duration=source_duration,
            processed_duration=processed_duration,
        ):
            raise ValueError("Prepared XTTS sample became too short after conversion")
    except Exception as exc:
        if destination_path.exists():
            destination_path.unlink(missing_ok=True)
        raise FFmpegError(str(exc) or "Failed to normalize voice sample") from exc


def _prepared_xtts_path(source_path: Path) -> Path:
    if source_path.suffix.lower() == ".wav" and source_path.stem.lower().endswith("_xtts"):
        return source_path
    return source_path.with_name(f"{source_path.stem}_xtts.wav")


def ensure_xtts_reference_file(file_path: str | Path) -> dict:
    source_path = Path(file_path)
    if not source_path.exists() or not source_path.is_file():
        raise FileNotFoundError(f"Voice file not found: {source_path}")

    source_summary = summarize_voice_file(source_path)
    if source_summary.get("is_xtts_compatible"):
        return {
            "path": str(source_path),
            "created": False,
            "reused": False,
            "summary": source_summary,
        }

    prepared_path = _prepared_xtts_path(source_path)
    if prepared_path.exists():
        prepared_summary = summarize_voice_file(prepared_path)
        prepared_new_enough = prepared_path.stat().st_mtime >= source_path.stat().st_mtime
        if prepared_summary.get("is_xtts_compatible") and prepared_new_enough:
            return {
                "path": str(prepared_path),
                "created": False,
                "reused": True,
                "summary": prepared_summary,
            }

    source_metadata = _probe_voice_file(source_path)
    _normalize_to_xtts_wav(
        source_path,
        prepared_path,
        source_duration=float(source_metadata["duration"] or 0.0),
    )
    prepared_summary = summarize_voice_file(prepared_path)
    return {
        "path": str(prepared_path),
        "created": True,
        "reused": False,
        "summary": prepared_summary,
    }


def import_voice_sample(filename: str, file_bytes: bytes) -> dict:
    if not filename:
        raise ValueError("Voice filename is required")
    if not file_bytes:
        raise ValueError("Voice file is empty")
    if len(file_bytes) > MAX_UPLOAD_BYTES:
        raise ValueError("Voice file is too large")

    source_name = Path(filename).name
    suffix = Path(source_name).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise ValueError("Unsupported voice file format")

    voices_root = _voices_root()
    base_stem = _sanitize_stem(Path(source_name).stem)
    original_path = _unique_path(voices_root, base_stem, suffix)
    processed_path = _unique_path(voices_root, f"{base_stem}_xtts", ".wav")

    try:
        original_path.write_bytes(file_bytes)

        original_metadata = _probe_voice_file(original_path)
        original_duration = float(original_metadata["duration"] or 0.0)
        if original_duration <= 0:
            raise ValueError("Could not read voice duration")

        conversion_performed = not bool(original_metadata["is_xtts_compatible"])
        conversion_mode = "skipped" if not conversion_performed else "resample_downmix"
        if conversion_performed:
            _normalize_to_xtts_wav(
                original_path,
                processed_path,
                source_duration=original_duration,
            )
        else:
            processed_path = original_path

        processed_metadata = _probe_voice_file(processed_path)
        processed_duration = float(processed_metadata["duration"] or 0.0)
        if processed_duration <= 0:
            raise ValueError("Prepared XTTS sample is empty")

        processed_channels = int(processed_metadata["channels"] or XTTS_TARGET_CHANNELS)
        processed_sample_rate = int(processed_metadata["sample_rate"] or XTTS_TARGET_SAMPLE_RATE)

        return {
            "original_file": {
                "name": original_path.name,
                "path": original_path.relative_to(voices_root).as_posix(),
                "format": suffix.lstrip("."),
            },
            "processed_file": {
                "name": processed_path.name,
                "path": processed_path.relative_to(voices_root).as_posix(),
                "format": "wav",
            },
            "original_duration_seconds": round(original_duration, 2),
            "processed_duration_seconds": round(processed_duration, 2),
            "sample_rate": processed_sample_rate,
            "channels": processed_channels,
            "conversion_performed": conversion_performed,
            "conversion_mode": conversion_mode,
            "original_summary": summarize_voice_file(original_path),
            "processed_summary": summarize_voice_file(processed_path),
        }
    except Exception:
        original_path.unlink(missing_ok=True)
        if processed_path != original_path:
            processed_path.unlink(missing_ok=True)
        raise
