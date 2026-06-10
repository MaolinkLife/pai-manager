import json
import os
import asyncio
import threading
from datetime import datetime, timezone
from typing import Any, Dict

from fastapi import APIRouter, Body, HTTPException, Query, Request, status
from fastapi.responses import Response

from core.decision_layer import decision_layer
from core.websocket_manager import manager
from modules.generative.conversation import play_message
from modules.tts.paths import create_temp_audio_file
from modules.tts.paths import voices_root
from modules.tts.ffmpeg_tools import FFmpegError
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
from modules.system import config as config_service
from modules.voice import controller as voice_controller
from core.interaction import (
    resolve_actor_uuid_from_auth_header,
    resolve_interaction_policy,
)
from modules.system.logger import AuditStatus, log_audit_entry
from modules.system.service import get_active_character_name
from modules.tts.rvc_service import get_rvc_status, import_rvc_model
from modules.tts.xtts import start_xtts_model_download

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


def _validate_preview_voice_config(active_module: str, module_cfg: Dict[str, Any]) -> None:
    if active_module != "coqui":
        return

    speaker_wav = str(
        _pick(module_cfg, "speaker_wav", "speakerWav", default="") or ""
    ).strip()
    if not speaker_wav:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="XTTS voice file is not selected. Select or import a voice file before generating preview.",
        )

    resolved = (voices_root() / speaker_wav).resolve()
    root = voices_root().resolve()
    if root not in resolved.parents and resolved != root:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="XTTS voice file path is outside the local voices folder.",
        )
    if not resolved.exists() or not resolved.is_file():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"XTTS voice file was not found in storage/models/tts/voices: {speaker_wav}",
        )


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
    _validate_preview_voice_config(active_module, module_cfg)
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
        log_audit_entry(
            "voice_preview_provider_unavailable",
            "[Voice] Preview provider is unavailable.",
            AuditStatus.WARNING,
            details={"provider": active_module, "module_config": module_cfg},
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Provider '{active_module}' is unavailable",
        )

    tmp_fd, tmp_path = create_temp_audio_file(prefix="preview_", suffix=".mp3")
    os.close(tmp_fd)

    try:
        result = await asyncio.to_thread(
            provider.synthesize,
            TTSRequest(text=text),
            tmp_path,
        )
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
        log_audit_entry(
            "voice_preview_provider_failed",
            "[Voice] Preview provider failed.",
            AuditStatus.ERROR,
            details={"provider": active_module, "error": str(exc)},
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except HTTPException:
        raise
    except Exception as exc:
        log_audit_entry(
            "voice_preview_failed",
            "[Voice] Preview failed unexpectedly.",
            AuditStatus.ERROR,
            details={"provider": active_module, "error": str(exc)},
        )
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
    try:
        return voice_controller.start_recording()
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "status": "error",
                "code": "audio_input_unavailable",
                "message": "Аудиовход недоступен.",
            },
        ) from exc


@router.post("/record/stop")
async def stop_record(request: Request):
    actor_user_uuid = resolve_actor_uuid_from_auth_header(
        request.headers.get("authorization")
    )
    char_name = get_active_character_name(
        user_uuid=actor_user_uuid,
        default="default_waifu",
    )
    try:
        data = voice_controller.stop_recording_and_process(char_name)
    except RuntimeError as exc:
        message = str(exc)
        if "Recording is not active" in message:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "status": "error",
                    "code": "recording_not_active",
                    "message": "Запись уже остановлена или не была запущена.",
                },
            ) from exc
        if (
            "Audio input" in message
            or "No audio input" in message
            or "No speech detected" in message
            or "No valid speech detected" in message
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "status": "error",
                    "code": "audio_input_unavailable",
                    "message": "Аудиовход недоступен или речь не обнаружена.",
                },
            ) from exc
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "status": "error",
                "code": "recording_failed",
                "message": message or "Не удалось обработать запись.",
            },
        ) from exc
    if not data:
        return {"status": "error", "message": "No transcription"}

    user_message = dict(data)
    user_message.setdefault("history", [])
    if actor_user_uuid:
        user_message["actor_user_uuid"] = actor_user_uuid
    interaction_policy = resolve_interaction_policy(actor_user_uuid)

    async def push_ws(msg) -> bool:
        await manager.send_message(json.dumps(msg, ensure_ascii=False))
        return True

    # Show the recognised message in the chat right away. The stream pipeline
    # re-emits the same id later — the frontend patches it, no duplicate.
    await push_ws(
        {
            "type": "message",
            "role": "user",
            "content": user_message.get("content", ""),
            "id": user_message.get("id"),
            "timestamp": user_message.get("timestamp"),
        }
    )

    async def _process_voice_turn() -> None:
        # Mirrors the chat WS pipeline 1:1: run_id + trace_hook give the chat
        # the same runtime block (model, modules, traces, timings) as typed
        # messages; the streaming path gives reasoning/chunks/compliance.
        try:
            import time as _time
            import uuid as _uuid

            from core.instructor import Instructor
            from modules.database import service as database_service
            from modules.generative.conversation import generate_stream
            from routes.ws_routes import _clean_runtime_meta_payload

            payload_run_id = str(_uuid.uuid4())
            run_started = _time.perf_counter()
            trace_events: list[Dict[str, Any]] = []

            async def trace_hook(trace_payload: dict) -> None:
                event_payload: Dict[str, Any] = {
                    "type": "runtime_trace",
                    "run_id": payload_run_id,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
                event_payload.update(trace_payload or {})
                trace_events.append(
                    {
                        "stage": event_payload.get("stage"),
                        "state": event_payload.get("state"),
                        "timestamp": event_payload.get("timestamp"),
                        "elapsed_ms": event_payload.get("elapsed_ms"),
                        "details": event_payload.get("details"),
                    }
                )
                await push_ws(event_payload)

            await push_ws(
                {
                    "type": "system",
                    "event": "typing_start",
                    "run_id": payload_run_id,
                }
            )

            processing_result = await decision_layer.process_message(
                user_message, None, trace_hook=trace_hook
            )
            raw_media_payload = processing_result.pop("raw_media", None)
            instructor = Instructor()
            formatted_history = await instructor.format_for_api(
                processing_result["system_prompt"],
                processing_result["user_message"],
                analysis=processing_result.get("analysis"),
                decisions=processing_result.get("decisions"),
                moral_state=processing_result.get("moral_state"),
                memory_context=processing_result.get("memory_context"),
                visual_context=processing_result.get("visual_context"),
                module_tasks=processing_result.get("module_tasks"),
            )

            final_meta: Dict[str, Any] = {}

            async def emit(payload: dict) -> bool:
                if payload.get("type") == "message_end":
                    final_meta.update(
                        {
                            "id": payload.get("id"),
                            "model": payload.get("model"),
                            "usage": payload.get("usage"),
                            "provider": payload.get("provider"),
                            "reasoning_elapsed_ms": payload.get("reasoning_elapsed_ms"),
                            "answer_elapsed_ms": payload.get("answer_elapsed_ms"),
                            "meta": payload.get("meta"),
                            "stopped": bool(payload.get("stopped")),
                        }
                    )
                return await push_ws(payload)

            await generate_stream(
                processing_result,
                formatted_history,
                emit_fn=emit,
                last_user_message=processing_result.get("user_message", user_message),
                raw_user_media=raw_media_payload,
                store=interaction_policy.can_affect_global_memory,
                run_id=payload_run_id,
                trace_hook=trace_hook,
            )

            # Persist generation details (run_id + traces included) so the
            # runtime block and info popup survive reloads — same shape as
            # the chat WS route writes after its streams.
            message_id = final_meta.pop("id", None)
            if interaction_policy.can_affect_global_memory and message_id:
                database_service.update_history_runtime_meta(
                    message_id,
                    _clean_runtime_meta_payload(
                        {
                            **final_meta,
                            "run_id": payload_run_id,
                            "traces": trace_events,
                            "elapsed_ms": round(
                                (_time.perf_counter() - run_started) * 1000, 2
                            ),
                            "actor_user_uuid": actor_user_uuid,
                            "source": "voice_record",
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        }
                    ),
                    merge=True,
                )
            await push_ws(
                {
                    "type": "run_status",
                    "run_id": payload_run_id,
                    "status": "completed",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
            )
        except Exception as exc:
            log_audit_entry(
                "voice_record_processing_failed",
                "[Voice] Background processing of recorded message failed.",
                AuditStatus.ERROR,
                details={"error": str(exc), "message_id": user_message.get("id")},
            )

    # HTTP returns as soon as the transcript is ready: the mic icon must go
    # out when the user stops talking, not when the model finishes replying.
    # The pipeline continues in the background; all chat updates arrive over
    # the websocket.
    asyncio.create_task(_process_voice_turn())

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
    except FFmpegError as exc:
        log_audit_entry(
            "voice_import_ffmpeg_failed",
            "[Voice] Voice import failed during audio probing/conversion.",
            AuditStatus.ERROR,
            details={"filename": filename, "error": str(exc)},
        )
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except TTSProviderError as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc
    except Exception as exc:
        log_audit_entry(
            "voice_import_failed",
            "[Voice] Voice import failed unexpectedly.",
            AuditStatus.ERROR,
            details={"filename": filename, "error": str(exc)},
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Voice import failed: {exc}",
        ) from exc


@router.post("/rvc/import")
async def import_rvc_voice(
    request: Request,
    filename: str = Query(..., min_length=1, max_length=255),
):
    try:
        file_bytes = await request.body()
        model = import_rvc_model(filename, file_bytes)
        return {"status": "ok", "model": model}
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"RVC import failed: {exc}",
        ) from exc
