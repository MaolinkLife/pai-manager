import asyncio
import mimetypes
import re
from pathlib import Path
from typing import Optional

import edge_tts
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse

from modules.ollama import client as ollama_client
from modules.tts.paths import voices_root
from modules.tts.voice_import import summarize_voice_file
from modules.system import config as config_service
from modules.vision.monitor import get_monitor_info, get_monitor_screens
from modules.vision.providers.apple_vision import AppleVisionProvider
from modules.vision.providers.ollama_vision import OllamaVisionProvider
from modules.system.resource import get_audio_resources, list_local_model_resources
from modules.tts.rvc_service import list_local_rvc_models
from modules.tts.xtts import list_xtts_models

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


@router.get("/local-models")
def get_local_models(
    limit_per_group: int = Query(default=300, ge=1, le=2000),
    include_ollama: bool = Query(default=False),
):
    try:
        payload = list_local_model_resources(limit_per_group=limit_per_group)
        if include_ollama:
            ollama_payload = ollama_client.list_models()
            payload["ollama"] = {
                "status": ollama_payload.get("status", "error"),
                "models": ollama_payload.get("models", []) or [],
                "message": ollama_payload.get("message"),
            }
        return payload
    except Exception as exc:
        return {
            "status": "error",
            "message": f"Error getting local models: {exc}",
            "groups": {},
            "counts": {},
            "total_count": 0,
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


@router.get("/vision/provider-status")
def get_vision_provider_status(
    provider: Optional[str] = Query(default=None),
    model: Optional[str] = Query(default=None),
    probe: bool = Query(default=False),
):
    vision_cfg = config_service.get_config_value("vision", {}) or {}
    provider_name = str(provider or vision_cfg.get("active_provider") or "apple_vision").strip()
    vision_modules = vision_cfg.get("vision_modules") or {}
    provider_cfg = dict(vision_modules.get(provider_name) or {})
    if model:
        if provider_name == "apple_vision":
            provider_cfg["model_id"] = model
        else:
            provider_cfg["model"] = model

    if provider_name == "apple_vision":
        resolved_model = str(provider_cfg.get("model_id") or config_service.get_config_value("api.visual_model") or "").strip()
        if not probe:
            return {
                "status": "ok",
                "provider": {
                    "name": provider_name,
                    "model": resolved_model,
                    "ready": None,
                    "message": "configured",
                    "probe": False,
                },
            }
        try:
            instance = AppleVisionProvider(model_id=resolved_model)
            ready = bool(instance.is_ready())
            return {
                "status": "ok",
                "provider": {
                    "name": provider_name,
                    "model": resolved_model,
                    "ready": ready,
                    "message": "supported" if ready else "unavailable",
                    "probe": True,
                },
            }
        except Exception as exc:
            return {
                "status": "ok",
                "provider": {
                    "name": provider_name,
                    "model": resolved_model,
                    "ready": False,
                    "message": f"probe failed: {exc}",
                    "probe": True,
                },
            }

    if provider_name in {"ollama_vision", "llava"}:
        instance = OllamaVisionProvider(provider_cfg)
        resolved_model = instance.model_id
        if not probe:
            return {
                "status": "ok",
                "provider": {
                    "name": provider_name,
                    "model": resolved_model,
                    "ready": None,
                    "message": "configured",
                    "probe": False,
                },
            }
        ready = bool(instance.is_ready())
        message = "supported" if ready else (instance._last_probe_error or "vision unavailable")
        return {
            "status": "ok",
            "provider": {
                "name": provider_name,
                "model": resolved_model,
                "ready": ready,
                "message": message,
                "probe": True,
            },
        }

    return {
        "status": "error",
        "message": f"Unknown vision provider: {provider_name}",
        "provider": {
            "name": provider_name,
            "model": str(model or ""),
            "ready": False,
            "message": "unknown provider",
            "probe": bool(probe),
        },
    }
