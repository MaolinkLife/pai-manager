import json
import asyncio
import uuid
import time
from datetime import datetime, timezone

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from modules.system.service import (
    activate_user_context,
    get_active_character_name,
    reset_user_context,
)
from core.websocket_manager import manager
from modules.generative import conversation
from modules.database import service as database_service
from modules.system import auth as auth_service
from modules.system.logger import log_audit_entry, AuditStatus
from core.interaction import resolve_interaction_policy
from core.decision_layer import decision_layer
from core.channel_router import can_accept_ingress
from core import tool_event_bus

ws_router = APIRouter(prefix="/api", tags=["WebSocket"])


def _is_chat_visible_history_item(item: dict) -> bool:
    if not isinstance(item, dict):
        return False
    role = str(item.get("role") or "").strip().lower()
    if role == "tool":
        return False
    runtime_meta = item.get("runtime_meta")
    if isinstance(runtime_meta, dict):
        event_name = str(runtime_meta.get("event") or "").strip().lower()
        if event_name == "tool_event":
            return False
        transport = runtime_meta.get("transport")
        if isinstance(transport, dict):
            transport_name = str(transport.get("name") or "").strip().lower()
            # Main chat feed must stay isolated from external transports (telegram, etc.).
            if transport_name and transport_name != "main_chat":
                return False
    tags = item.get("tags")
    if isinstance(tags, list):
        lowered = {str(tag).strip().lower() for tag in tags}
        if "tool" in lowered:
            return False
    return True

async def _safe_send_json(websocket: WebSocket, payload: dict) -> bool:
    try:
        await websocket.send_json(payload)
        return True
    except (WebSocketDisconnect, RuntimeError):
        return False


@ws_router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    session_user_uuid = None
    access_token = websocket.query_params.get("access_token")
    if access_token:
        try:
            token_user = auth_service.get_user_from_access_token(access_token)
            if token_user:
                session_user_uuid = token_user.uuid
        except Exception:
            session_user_uuid = None

    await manager.connect(websocket)
    active_generation_task = None
    active_stop_event = None
    active_run_id = None

    try:
        while True:
            try:
                raw_data = await websocket.receive_text()
            except WebSocketDisconnect:
                break
            except RuntimeError:
                # WebSocket may not be connected or already closed
                break

            log_audit_entry(
                'ws_receive',
                '[WS] Received payload from client.',
                AuditStatus.INFO,
                details={'size': len(raw_data)},
            )

            try:
                payload = json.loads(raw_data)
            except json.JSONDecodeError:
                if not await _safe_send_json(
                    websocket, {"type": "error", "message": "Invalid JSON"}
                ):
                    break
                continue

            action = payload.get("action")
            data = payload.get("payload", {})
            if isinstance(data, dict) and session_user_uuid and not data.get("actor_user_uuid"):
                data["actor_user_uuid"] = session_user_uuid

            log_audit_entry(
                "ws_action_received",
                "[WS] Action received.",
                AuditStatus.INFO,
                details={"action": action},
            )

            if not action:
                if not await _safe_send_json(
                    websocket, {"type": "error", "message": "Missing 'action'"}
                ):
                    break
                continue

            if action == "reroll_message":
                actor_policy = resolve_interaction_policy(data.get("actor_user_uuid"))
                if not actor_policy.can_affect_global_memory:
                    if not await _safe_send_json(
                        websocket,
                        {
                            "type": "error",
                            "message": "Reroll is not available for current role",
                            "code": "reroll_forbidden",
                        },
                    ):
                        break
                    continue
                message_id = data.get("message_id")
                requested_run_id = data.get("run_id")
                client_user_id = data.get("client_user_id")
                if not message_id:
                    if not await _safe_send_json(
                        websocket, {"type": "error", "message": "message_id required"}
                    ):
                        break
                    continue
                try:
                    data = database_service.prepare_reroll_payload(message_id)
                    if requested_run_id:
                        data["run_id"] = requested_run_id
                    if client_user_id:
                        data["id"] = client_user_id
                    action = "send_message"
                except Exception as e:
                    if not await _safe_send_json(
                        websocket, {"type": "error", "message": str(e)}
                    ):
                        break
                    continue

            if action == "edit_message":
                actor_policy = resolve_interaction_policy(data.get("actor_user_uuid"))
                if not actor_policy.can_affect_global_memory:
                    if not await _safe_send_json(
                        websocket,
                        {
                            "type": "error",
                            "message": "Edit is not available for current role",
                            "code": "edit_forbidden",
                        },
                    ):
                        break
                    continue
                message_id = data.get("message_id")
                new_content = data.get("new_content")
                requested_run_id = data.get("run_id")
                client_user_id = data.get("client_user_id")
                if not message_id:
                    if not await _safe_send_json(
                        websocket, {"type": "error", "message": "message_id required"}
                    ):
                        break
                    continue
                if not (isinstance(new_content, str) and new_content.strip()):
                    if not await _safe_send_json(
                        websocket, {"type": "error", "message": "new_content required"}
                    ):
                        break
                    continue
                try:
                    data = database_service.prepare_edit_payload(
                        message_id, new_content.strip()
                    )
                    if requested_run_id:
                        data["run_id"] = requested_run_id
                    if client_user_id:
                        data["id"] = client_user_id
                    action = "send_message"
                except Exception as e:
                    if not await _safe_send_json(
                        websocket, {"type": "error", "message": str(e)}
                    ):
                        break
                    continue

            if action == "send_message":
                channel_allowed, reason = can_accept_ingress("main_chat")
                if not channel_allowed:
                    tool_event_bus.emit_tool_event(
                        tool_name="channel.policy",
                        status="error",
                        source="ws_pipeline",
                        content=(
                            "[ERROR]: main_chat channel is disabled by communication policy. "
                            f"reason={reason}"
                        ),
                        runtime_meta={
                            "event": "tool_event",
                            "tool": {"name": "channel.policy", "status": "error"},
                            "transport": {"name": "main_chat"},
                            "reason": reason,
                            "actor_user_uuid": data.get("actor_user_uuid"),
                        },
                        tags=["tool", "policy", "error"],
                    )
                    if not await _safe_send_json(
                        websocket,
                        {
                            "type": "error",
                            "message": "Main chat channel is disabled by communication policy",
                            "code": "main_chat_disabled",
                            "reason": reason,
                        },
                    ):
                        break
                    continue

                log_audit_entry(
                    "ws_send_message_received",
                    "[WS] send_message action received.",
                    AuditStatus.INFO,
                    details={
                        "has_content": bool((data or {}).get("content")),
                        "media_count": len((data or {}).get("media") or []),
                    },
                )
                if active_generation_task and not active_generation_task.done():
                    if not await _safe_send_json(
                        websocket,
                        {
                            "type": "error",
                            "message": "Generation is already running",
                            "code": "generation_busy",
                            "run_id": active_run_id,
                        },
                    ):
                        break
                    continue

                run_id = data.get("run_id") or str(uuid.uuid4())
                stop_event = asyncio.Event()
                active_run_id = run_id
                active_stop_event = stop_event

                async def _run_generation(payload_data: dict, payload_run_id: str):
                    nonlocal active_generation_task, active_stop_event, active_run_id
                    config_ctx_token = None
                    try:
                        actor_user_uuid = payload_data.get("actor_user_uuid")
                        interaction_policy = resolve_interaction_policy(actor_user_uuid)
                        allow_global_store = interaction_policy.can_affect_global_memory
                        if actor_user_uuid:
                            config_ctx_token = activate_user_context(actor_user_uuid)

                        run_started = time.perf_counter()
                        trace_events = []
                        final_message_id = None
                        final_message_model = None
                        final_message_usage = None
                        final_message_provider = None
                        final_message_stopped = False
                        final_message_reasoning_elapsed = None
                        final_message_meta = None
                        if not await _safe_send_json(
                            websocket,
                            {
                                "type": "run_status",
                                "run_id": payload_run_id,
                                "status": "started",
                                "timestamp": datetime.now(timezone.utc).isoformat(),
                            },
                        ):
                            return

                        async def trace_hook(trace_payload: dict):
                            event_payload = {
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
                                }
                            )
                            await _safe_send_json(websocket, event_payload)

                        try:
                            await trace_hook({"stage": "pipeline", "state": "start"})
                            from core.instructor import Instructor

                            processing_result = await decision_layer.process_message(
                                payload_data, websocket, trace_hook=trace_hook
                            )
                            decisions_payload = processing_result.get("decisions") or {}
                            active_decisions = [
                                name
                                for name, is_active in decisions_payload.items()
                                if bool(is_active)
                            ]
                            memory_context_payload = processing_result.get("memory_context") or {}
                            conversation_state = memory_context_payload.get("conversation_state") or {}
                            memory_status = memory_context_payload.get("memory_status")
                            if not memory_status:
                                memory_status = "available" if memory_context_payload else "unknown"
                            tool_event_bus.emit_tool_event(
                                tool_name="pipeline.decision_layer",
                                status="ok",
                                content=(
                                    "[OK]: decision context prepared. "
                                    f"active_decisions={active_decisions or ['none']}; "
                                    f"memory_status={memory_status}; "
                                    f"last_topic={conversation_state.get('last_topic') or '-'}"
                                ),
                                source="ws_pipeline",
                                runtime_meta={
                                    "run_id": payload_run_id,
                                    "transport": {"name": "main_chat"},
                                    "decisions": decisions_payload,
                                    "actor_user_uuid": payload_data.get("actor_user_uuid"),
                                },
                                tags=["tool", "pipeline", "ok"],
                            )
                            moral_state_payload = processing_result.get("moral_state")
                            if isinstance(moral_state_payload, dict):
                                await _safe_send_json(
                                    websocket,
                                    {
                                        "type": "moral_state",
                                        "run_id": payload_run_id,
                                        "state": moral_state_payload,
                                        "timestamp": datetime.now(timezone.utc).isoformat(),
                                    },
                                )

                            instructor = Instructor()
                            raw_media_payload = processing_result.pop("raw_media", None)
                            media_payload = (
                                raw_media_payload
                                if raw_media_payload is not None
                                else payload_data.get("media")
                            )
                            if media_payload:
                                log_audit_entry(
                                    "ws_media_received",
                                    "[WS] Incoming media payload for send_message.",
                                    AuditStatus.INFO,
                                    details={"count": len(media_payload)},
                                )
                                visual_context = processing_result.get("visual_context") or {}
                                attachments_info = (visual_context.get("attachments") or {}).get("items", [])
                                applied = 0
                                for item in attachments_info:
                                    idx = item.get("index")
                                    description = (item.get("description") or "").strip()
                                    if (
                                        isinstance(idx, int)
                                        and 0 <= idx < len(media_payload)
                                        and description
                                    ):
                                        media_payload[idx]["description"] = description
                                        applied += 1
                                if applied:
                                    log_audit_entry(
                                        "ws_media_described",
                                        "[WS] Image attachments described via decision layer vision.",
                                        AuditStatus.INFO,
                                        details={"count": applied},
                                    )
                                elif attachments_info:
                                    log_audit_entry(
                                        "ws_media_description_missing",
                                        "[WS] Vision module returned attachment metadata without summaries.",
                                        AuditStatus.WARNING,
                                        details={"count": len(attachments_info)},
                                    )

                            formatted_history = await instructor.format_for_api(
                                processing_result["system_prompt"],
                                processing_result["user_message"],
                                memory_context=processing_result.get("memory_context"),
                            )

                            async def emit(payload: dict) -> bool:
                                nonlocal final_message_id, final_message_model, final_message_usage, final_message_provider, final_message_stopped, final_message_reasoning_elapsed, final_message_meta
                                if active_stop_event and active_stop_event.is_set():
                                    return False
                                if payload.get("type") == "message_end":
                                    final_message_id = payload.get("id")
                                    final_message_model = payload.get("model")
                                    final_message_usage = payload.get("usage")
                                    final_message_provider = payload.get("provider")
                                    final_message_stopped = bool(payload.get("stopped"))
                                    final_message_reasoning_elapsed = payload.get("reasoning_elapsed_ms")
                                    final_message_meta = payload.get("meta")
                                return await _safe_send_json(websocket, payload)

                            generation_started = time.perf_counter()
                            await trace_hook({"stage": "generation", "state": "start"})
                            await conversation.generate_stream(
                                processing_result,
                                formatted_history,
                                emit_fn=emit,
                                last_user_message=processing_result.get("user_message"),
                                raw_user_media=media_payload,
                                store=allow_global_store,
                                run_id=payload_run_id,
                                should_stop=stop_event.is_set,
                            )
                            await trace_hook(
                                {
                                    "stage": "generation",
                                    "state": "end",
                                    "elapsed_ms": round(
                                        (time.perf_counter() - generation_started) * 1000,
                                        2,
                                    ),
                                }
                            )
                            await trace_hook(
                                {
                                    "stage": "pipeline",
                                    "state": "end",
                                    "elapsed_ms": round(
                                        (time.perf_counter() - run_started) * 1000, 2
                                    ),
                                }
                            )
                            if allow_global_store and final_message_id:
                                database_service.update_history_runtime_meta(
                                    final_message_id,
                                    {
                                        "run_id": payload_run_id,
                                        "actor_user_uuid": payload_data.get("actor_user_uuid"),
                                        "actor_role": interaction_policy.actor_role,
                                        "model": final_message_model,
                                        "provider": final_message_provider,
                                        "usage": final_message_usage or {},
                                        "meta": final_message_meta or {},
                                        "traces": trace_events,
                                        "elapsed_ms": round(
                                            (time.perf_counter() - run_started) * 1000, 2
                                        ),
                                        "reasoning_elapsed_ms": final_message_reasoning_elapsed,
                                        "stopped": final_message_stopped,
                                        "timestamp": datetime.now(timezone.utc).isoformat(),
                                        "store_enabled": allow_global_store,
                                    },
                                )
                            status = "stopped" if stop_event.is_set() else "completed"
                            await _safe_send_json(
                                websocket,
                                {
                                    "type": "run_status",
                                    "run_id": payload_run_id,
                                    "status": status,
                                    "timestamp": datetime.now(timezone.utc).isoformat(),
                                },
                            )
                        except asyncio.CancelledError:
                            await _safe_send_json(
                                websocket,
                                {
                                    "type": "run_status",
                                    "run_id": payload_run_id,
                                    "status": "stopped",
                                    "timestamp": datetime.now(timezone.utc).isoformat(),
                                },
                            )
                            await _safe_send_json(
                                websocket,
                                {
                                    "type": "system",
                                    "event": "typing_end",
                                    "run_id": payload_run_id,
                                },
                            )
                        except Exception as e:
                            tool_event_bus.emit_tool_event(
                                tool_name="pipeline.run",
                                status="error",
                                content=f"[ERROR]: ws generation run failed: {e}",
                                source="ws_pipeline",
                                runtime_meta={
                                    "run_id": payload_run_id,
                                    "transport": {"name": "main_chat"},
                                    "actor_user_uuid": payload_data.get("actor_user_uuid"),
                                },
                                tags=["tool", "pipeline", "error"],
                            )
                            log_audit_entry(
                                "ws_send_message_error",
                                "[WS] Error while processing message.",
                                AuditStatus.ERROR,
                                details={"error": str(e), "run_id": payload_run_id},
                            )
                            import traceback

                            traceback.print_exc()
                            await _safe_send_json(
                                websocket,
                                {"type": "error", "message": str(e), "run_id": payload_run_id},
                            )
                    finally:
                        if config_ctx_token is not None:
                            reset_user_context(config_ctx_token)
                        if active_run_id == payload_run_id:
                            active_generation_task = None
                            active_stop_event = None
                            active_run_id = None

                active_generation_task = asyncio.create_task(
                    _run_generation(data, run_id)
                )
                continue

            elif action == "stop_generation":
                requested_run_id = data.get("run_id")
                if (
                    not active_generation_task
                    or active_generation_task.done()
                    or not active_run_id
                ):
                    if not await _safe_send_json(
                        websocket,
                        {
                            "type": "run_status",
                            "status": "no_active_run",
                            "run_id": requested_run_id,
                        },
                    ):
                        break
                    continue

                if requested_run_id and requested_run_id != active_run_id:
                    if not await _safe_send_json(
                        websocket,
                        {
                            "type": "error",
                            "message": "run_id does not match active run",
                            "code": "run_mismatch",
                            "run_id": requested_run_id,
                        },
                    ):
                        break
                    continue

                if active_stop_event:
                    active_stop_event.set()
                if active_generation_task and not active_generation_task.done():
                    active_generation_task.cancel()
                if not await _safe_send_json(
                    websocket,
                    {
                        "type": "run_status",
                        "run_id": active_run_id,
                        "status": "stopping",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    },
                ):
                    break
                continue

            elif action == "fetch_history":
                limit = data.get("limit", 32)
                offset = data.get("offset", 0)
                actor_user_uuid = data.get("actor_user_uuid") or session_user_uuid
                char_name = get_active_character_name(
                    user_uuid=actor_user_uuid,
                    default="default_waifu",
                )
                # Hide internal tool-role telemetry from the end-user chat feed.
                raw_history = database_service.get_history(
                    char_name,
                    max(1, int(limit)) * 3,
                    max(0, int(offset)),
                )
                history = [
                    item for item in (raw_history or []) if _is_chat_visible_history_item(item)
                ][: max(1, int(limit))]
                if not await _safe_send_json(
                    websocket, {"type": "history", "items": history}
                ):
                    break

            elif action == "delete_message":
                actor_policy = resolve_interaction_policy(data.get("actor_user_uuid"))
                if not actor_policy.can_affect_global_memory:
                    if not await _safe_send_json(
                        websocket,
                        {
                            "type": "error",
                            "message": "Delete is not available for current role",
                            "code": "delete_forbidden",
                        },
                    ):
                        break
                    continue
                message_id = data.get("message_id")
                chain = data.get("chain", False)
                if not message_id:
                    if not await _safe_send_json(
                        websocket, {"type": "error", "message": "message_id required"}
                    ):
                        break
                else:
                    if chain:
                        database_service.delete_message_chain(message_id)
                        if not await _safe_send_json(
                            websocket,
                            {
                                "type": "deleted",
                                "message_id": message_id,
                                "chain": True,
                            },
                        ):
                            break
                    else:
                        database_service.delete_message(message_id)
                        if not await _safe_send_json(
                            websocket,
                            {
                                "type": "deleted",
                                "message_id": message_id,
                                "chain": False,
                            },
                        ):
                            break

            else:
                if not await _safe_send_json(
                    websocket,
                    {"type": "error", "message": f"Unknown action '{action}'"},
                ):
                    break

    except WebSocketDisconnect:
        manager.disconnect(websocket)
        log_audit_entry(
            'ws_disconnect',
            '[WS] Client disconnected.',
            AuditStatus.INFO,
        )
    finally:
        if active_stop_event:
            active_stop_event.set()
        if active_generation_task and not active_generation_task.done():
            active_generation_task.cancel()
        manager.disconnect(websocket)
