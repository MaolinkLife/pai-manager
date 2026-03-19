import asyncio
import mimetypes
import re
from pathlib import Path

import edge_tts
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse

from modules.tts.paths import voices_root
from modules.tts.voice_import import summarize_voice_file
from services import config_service
from services.monitor_service import get_monitor_info, get_monitor_screens
from services.resource_service import get_audio_resources
from services.rvc_bootstrap_service import list_local_rvc_models
from services.xtts_model_service import list_xtts_models

router = APIRouter(prefix="/api/resources", tags=["Resources"])

DEFAULT_VOICE_TIMEOUT = 8
VOICE_AUDIO_EXTENSIONS = {".wav", ".mp3", ".flac", ".ogg", ".m4a"}


def parse_voice_shortname(raw_name: str) -> str:
    match = re.search(r"\(([^,]+),\s*([^)]+)\)", raw_name)
    if match:
        locale = match.group(1)
        shortname = match.group(2)
        return f"{locale}-{shortname}"
    return raw_name


def _voices_root() -> Path:
    return voices_root()


@router.get("/devices")
def get_audio_devices():
    try:
        return get_audio_resources()
    except Exception as e:
        return {
            "status": "error",
            "content": f"Error while getting audio devices: {str(e)}",
        }


@router.get("/monitors/screens")
def get_monitor_screens_endpoint():
    try:
        monitors = get_monitor_screens()
        return {"status": "success", "monitors": monitors}
    except Exception as e:
        return {
            "status": "error",
            "message": f"Error getting monitor screens: {str(e)}",
            "monitors": [],
        }


@router.get("/monitors/info")
def get_monitor_info_endpoint():
    try:
        info = get_monitor_info()
        return {"status": "success", "data": info}
    except Exception as e:
        return {
            "status": "error",
            "message": f"Error getting monitor info: {str(e)}",
            "data": {},
        }


@router.get("/voices")
async def get_edge_voices():
    try:
        timeout_raw = config_service.get_config_value(
            "voice.voices_timeout_seconds", DEFAULT_VOICE_TIMEOUT
        )
        try:
            timeout = max(1, int(timeout_raw))
        except (TypeError, ValueError):
            timeout = DEFAULT_VOICE_TIMEOUT

        voices = await asyncio.wait_for(edge_tts.list_voices(), timeout=timeout)
        simplified = [
            {
                "name": parse_voice_shortname(v.get("Name")),
                "gender": v.get("Gender", "Unknown"),
                "styles": v.get("VoicePersonalities", []),
                "categories": v.get("ContentCategories", []),
            }
            for v in voices
        ]
        return {"status": "success", "voices": simplified}
    except asyncio.TimeoutError:
        return {
            "status": "error",
            "message": f"Voice provider timeout after {timeout} seconds.",
            "voices": [],
        }
    except Exception as e:
        return {
            "status": "error",
            "message": f"Error getting voices: {str(e)}",
            "voices": [],
        }


@router.get("/local-voice-files")
def get_local_voice_files():
    try:
        voices_root = _voices_root()
        if not voices_root.exists():
            return {"status": "success", "files": []}

        files = []
        for path in sorted(voices_root.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in VOICE_AUDIO_EXTENSIONS:
                continue

            relative_path = path.relative_to(voices_root).as_posix()
            try:
                summary = summarize_voice_file(path)
            except Exception:
                summary = {
                    "duration_seconds": 0,
                    "sample_rate": 0,
                    "channels": 0,
                    "codec": path.suffix.lstrip(".").lower(),
                    "size_bytes": path.stat().st_size if path.exists() else 0,
                    "is_prepared_xtts": path.suffix.lower() == ".wav"
                    and path.stem.lower().endswith("_xtts"),
                    "health": "unknown",
                    "hint": "Audio metadata is unavailable for this file.",
                }

            files.append(
                {
                    "name": path.name,
                    "path": relative_path,
                    "summary": summary,
                }
            )

        return {"status": "success", "files": files}
    except Exception as e:
        return {
            "status": "error",
            "message": f"Error getting local voice files: {str(e)}",
            "files": [],
        }


@router.get("/local-voice-file")
def get_local_voice_file(path: str = Query(..., min_length=1)):
    voices_root = _voices_root().resolve()
    target_path = (voices_root / path).resolve()

    if voices_root not in target_path.parents and target_path != voices_root:
        raise HTTPException(status_code=400, detail="Invalid voice file path")

    if not target_path.exists() or not target_path.is_file():
        raise HTTPException(status_code=404, detail="Voice file not found")

    if target_path.suffix.lower() not in VOICE_AUDIO_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Unsupported voice file type")

    media_type = mimetypes.guess_type(target_path.name)[0] or "application/octet-stream"
    return FileResponse(path=target_path, media_type=media_type, filename=target_path.name)


@router.get("/local-xtts-models")
def get_local_xtts_models():
    try:
        return {"status": "success", "models": list_xtts_models()}
    except Exception as e:
        return {
            "status": "error",
            "message": f"Error getting local XTTS models: {str(e)}",
            "models": [],
        }


@router.get("/local-rvc-models")
def get_local_rvc_models():
    try:
        return {"status": "success", "models": list_local_rvc_models()}
    except Exception as e:
        return {
            "status": "error",
            "message": f"Error getting local RVC models: {str(e)}",
            "models": [],
        }
