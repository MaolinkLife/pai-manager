import json
import os
import threading
from datetime import datetime, timezone
from typing import Any, Dict

from fastapi import APIRouter, Body, HTTPException, Query, Request, status
from fastapi.responses import Response

from core.decision_layer import decision_layer
from core.websocket_manager import manager
from modules.generative.conversation import generate_standard, play_message
from modules.tts.paths import create_temp_audio_file
from modules.tts.providers.base import TTSProviderError
from modules.tts.providers.coqui import CoquiTTSProvider
from modules.tts.providers.edge import EdgeTTSProvider
from modules.tts.providers.elevenlabs import ElevenLabsProvider
from modules.tts.providers.gtts import GTTSProvider
from modules.tts.providers.offline import OfflineTTSProvider
from modules.tts.service import (
    check_if_speaking,
    describe_providers as describe_tts_providers,
    force_cut_voice,
    speak_line,
)
from modules.tts.state import voice_state
from modules.tts.text_processing import prepare_tts_text
from modules.tts.types import TTSRequest
from modules.tts.voice_import import import_voice_sample
from modules.voice.vad_listener import is_vad_running, start_vad_background, stop_vad
from services import config_service, voice_controller
from services.interaction_policy import (
    resolve_actor_uuid_from_auth_header,
    resolve_interaction_policy,
)
from modules.system.service import get_active_character_name
from services.rvc_bootstrap_service import get_rvc_status
from services.xtts_model_service import start_xtts_model_download

router = APIRouter(prefix="/api/voice", tags=["Voice"])

_preview_provider_lock = threading.Lock()
_preview_provider = None
_preview_provider_key: str | None = None
_preview_provider_module: str | None = None


def _pick(mapping: Dict[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        if key in mapping:
            return mapping[key]
    return default


def _resolve_voice_payload(payload: Dict[str, Any]) -> tuple[str, Dict[str, Dict[str, Any]]]:
    active_module = str(
        _pick(payload, "active_module", "activeModule", default="coqui") or "coqui"
    ).strip().lower()
    voice_modules = _pick(payload, "voice_modules", "voiceModules", default={}) or {}
    if active_module == "coqui" and "coqui" not in voice_modules and isinstance(payload, dict):
        voice_modules["coqui"] = payload.get("coqui", {}) or {}
    return active_module, voice_modules


def _build_preview_provider(active_module: str, voice_modules: Dict[str, Dict[str, Any]]):
    module_cfg = voice_modules.get(active_module, {}) or {}
    if active_module == "coqui":
        return CoquiTTSProvider(module_cfg)
    if active_module == "edge":
        default_voice = _pick(
            module_cfg,
            "voice_language",
            "voiceLanguage",
            default="ru-RU-SvetlanaNeural",
        )
        return EdgeTTSProvider(default_voice=default_voice)
    if active_module == "elevenlabs":
        return ElevenLabsProvider(module_cfg)
    if active_module == "gtts":
        return GTTSProvider(module_cfg)
    if active_module == "offline":
        voice = _pick(module_cfg, "voice")
        return OfflineTTSProvider(voice=voice)

    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=f"Unsupported voice module '{active_module}'",
    )


def _preview_cache_enabled(active_module: str, module_cfg: Dict[str, Any]) -> bool:
    if active_module != "coqui":
        return False
    return bool(_pick(module_cfg, "keep_model_loaded", "keepModelLoaded", default=False))


def _preview_cache_key(active_module: str, module_cfg: Dict[str, Any]) -> str:
    return json.dumps(
        {
            "active_module": active_module,
            "config": module_cfg,
        },
        ensure_ascii=False,
        sort_keys=True,
    )


def _shutdown_preview_provider_locked() -> None:
    global _preview_provider, _preview_provider_key, _preview_provider_module
    provider = _preview_provider
    _preview_provider = None
    _preview_provider_key = None
    _preview_provider_module = None
    if provider is not None:
        try:
            provider.shutdown()
        except Exception:
            pass


def _get_preview_provider(active_module: str, voice_modules: Dict[str, Dict[str, Any]]):
    global _preview_provider, _preview_provider_key, _preview_provider_module

    module_cfg = voice_modules.get(active_module, {}) or {}
    cache_enabled = _preview_cache_enabled(active_module, module_cfg)
    cache_key = _preview_cache_key(active_module, module_cfg)

    with _preview_provider_lock:
        if (
            cache_enabled
            and _preview_provider is not None
            and _preview_provider_module == active_module
            and _preview_provider_key == cache_key
        ):
            return _preview_provider, True, cache_enabled

        _shutdown_preview_provider_locked()
        provider = _build_preview_provider(active_module, voice_modules)

        if cache_enabled:
            _preview_provider = provider
            _preview_provider_key = cache_key
            _preview_provider_module = active_module

        return provider, False, cache_enabled


@router.post("/preview")
async def preview_voice(payload: dict = Body(...)):
    text = str(payload.get("text") or "").strip()
    if not text:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Preview text is required",
        )

    voice_payload = payload.get("voice") or {}
    if not isinstance(voice_payload, dict) or not voice_payload:
        queued = speak_line(text, refuse_pause=True)
        return {
            "status": "ok" if queued else "error",
            "queued": bool(queued),
        }

    active_module, voice_modules = _resolve_voice_payload(voice_payload)
    module_cfg = voice_modules.get(active_module, {}) or {}
    if active_module == "coqui":
        rvc_cfg = module_cfg.get("rvc") or {}
        log_audit_entry(
            "voice_preview_request",
            "[Voice] Preview request received for Coqui.",
            AuditStatus.INFO,
            details={
                "model_revision": module_cfg.get("model_revision"),
                "speaker_wav": module_cfg.get("speaker_wav"),
                "rvc_enabled": rvc_cfg.get("enabled"),
                "rvc_model_file": rvc_cfg.get("model_file"),
                "rvc_pitch": rvc_cfg.get("pitch"),
                "rvc_f0_method": rvc_cfg.get("f0_method"),
            },
        )
    text = prepare_tts_text(text, module_cfg)
    if not text:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Preview text is empty after TTS filters",
        )

    provider, _, keep_loaded = _get_preview_provider(active_module, voice_modules)
    if not provider.is_available():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Provider '{active_module}' is unavailable",
        )

    tmp_fd, tmp_path = create_temp_audio_file(prefix="preview_", suffix=".mp3")
    os.close(tmp_fd)

    try:
        result = provider.synthesize(TTSRequest(text=text), tmp_path)
        if not result.success or not os.path.exists(tmp_path):
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=result.error or "Preview generation failed",
            )

        with open(tmp_path, "rb") as fh:
            audio_bytes = fh.read()

        return Response(
            content=audio_bytes,
            media_type="audio/mpeg",
            headers={"X-TTS-Provider": active_module},
        )
    except TTSProviderError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Preview generation failed: {exc}",
        ) from exc
    finally:
        if not keep_loaded:
            try:
                provider.shutdown()
            except Exception:
                pass
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass


@router.post("/stop")
async def stop_voice():
    force_cut_voice()
    return {"status": "ok", "message": "Playback has stopped"}


@router.get("/playback/status")
async def playback_status():
    return {
        "status": "ok",
        "speaking": check_if_speaking(),
        "stage": voice_state.stage().value,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.post("/play")
def play_message_by_id(request: Request, payload: dict = Body(...)):
    actor_user_uuid = resolve_actor_uuid_from_auth_header(
        request.headers.get("authorization")
    )
    interaction_policy = resolve_interaction_policy(actor_user_uuid)
    if not interaction_policy.can_affect_global_memory:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Playback by message id is not available for current role",
        )

    message_id = payload.get("message_id")
    if not message_id:
        return {"status": "error", "message": "message_id не указан"}

    play_message(message_id)
    return {"status": "ok", "message": f"Playing the message: {message_id}"}


@router.post("/record/start")
def start_record():
    return voice_controller.start_recording()


@router.post("/record/stop")
async def stop_record(request: Request):
    actor_user_uuid = resolve_actor_uuid_from_auth_header(
        request.headers.get("authorization")
    )
    char_name = get_active_character_name(
        user_uuid=actor_user_uuid,
        default="default_waifu",
    )
    data = voice_controller.stop_recording_and_process(char_name)
    if not data:
        return {"status": "error", "message": "No transcription"}

    user_message = dict(data)
    user_message.setdefault("history", [])
    if actor_user_uuid:
        user_message["actor_user_uuid"] = actor_user_uuid
    interaction_policy = resolve_interaction_policy(actor_user_uuid)

    decision_context = await decision_layer.process_message(user_message, None)
    decision_context.pop("raw_media", None)

    async def push_ws(msg):
        await manager.send_message(json.dumps(msg, ensure_ascii=False))

    await generate_standard(
        decision_context,
        [user_message],
        user_message,
        emit_ws_fn=push_ws,
        store=interaction_policy.can_affect_global_memory,
    )

    return {
        "status": "ok",
        "data": data,
    }


@router.post("/mode/start")
async def start_voice_mode():
    started, message = await start_vad_background()
    status_code_text = "ok" if started else "error"
    return {"status": status_code_text, "message": message, "running": is_vad_running()}


@router.post("/mode/stop")
async def stop_voice_mode():
    stopped, message = await stop_vad(wait=True)
    status_code_text = "ok" if stopped else "error"
    return {"status": status_code_text, "message": message, "running": is_vad_running()}


@router.get("/mode/status")
async def voice_mode_status():
    return {"status": "ok", "running": is_vad_running()}


@router.get("/providers")
async def voice_providers_status():
    providers = describe_tts_providers()
    return {"status": "ok", "providers": providers}


@router.get("/rvc/status")
async def rvc_status():
    voice_cfg = config_service.get_config_value("voice", {}) or {}
    rvc_cfg = (
        voice_cfg.get("rvc")
        or ((voice_cfg.get("voice_modules") or {}).get("coqui", {}) or {}).get("rvc")
        or {}
    )
    return {"status": "ok", "rvc": get_rvc_status(rvc_cfg)}


@router.post("/xtts/download")
async def download_xtts_model(request: dict = Body(...)):
    model_name = str(request.get("model") or "").strip()
    if not model_name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="XTTS model name is required",
        )
    try:
        state = start_xtts_model_download(model_name)
        return {"status": "ok", "model": model_name, "download": state}
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/import")
async def import_voice(
    request: Request,
    filename: str = Query(..., min_length=1, max_length=255),
):
    try:
        file_bytes = await request.body()
        result = import_voice_sample(filename, file_bytes)
        return {"status": "ok", **result}
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except TTSProviderError as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Voice import failed: {exc}",
        ) from exc
