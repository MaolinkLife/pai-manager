import json
import asyncio
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from core.websocket_manager import manager
from services import api_service, database_service, config_service
from core.cognitive_analyzer import cognitive_analyzer
from core.decision_layer import decision_layer

ws_router = APIRouter(prefix="/api", tags=["WebSocket"])


async def _safe_send_json(websocket: WebSocket, payload: dict) -> bool:
    try:
        await websocket.send_json(payload)
        return True
    except (WebSocketDisconnect, RuntimeError):
        return False


@ws_router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            try:
                raw_data = await websocket.receive_text()
            except WebSocketDisconnect:
                break
            except RuntimeError:
                # WebSocket may not be connected or already closed
                break

            print(f"[WS] ⬅️ From client: {raw_data}")

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

            if not action:
                if not await _safe_send_json(
                    websocket, {"type": "error", "message": "Missing 'action'"}
                ):
                    break
                continue

            # === ROUTING ===
            if action == "send_message":
                try:
                    from core.instructor import Instructor

                    # Retrieve processed context from the DecisionLayer
                    processing_result = await decision_layer.process_message(
                        data, websocket
                    )

                    # Format history for the API service
                    instructor = Instructor()
                    formatted_history = await instructor.format_for_api(
                        processing_result["system_prompt"],
                        processing_result["user_message"],
                    )

                    # Pass history to the API service (original method)
                    await api_service.run_stream_message(websocket, formatted_history)

                except Exception as e:
                    print(f"[WS] Error while processing message: {e}")
                    import traceback

                    traceback.print_exc()  # For debugging
                    if not await _safe_send_json(
                        websocket, {"type": "error", "message": str(e)}
                    ):
                        break

            elif action == "fetch_history":
                limit = data.get("limit", 32)
                char_name = config_service.get_config_value(
                    "char_name", "default_waifu"
                )
                history = database_service.get_history(char_name, limit)
                if not await _safe_send_json(
                    websocket, {"type": "history", "items": history}
                ):
                    break

            elif action == "delete_message":
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

            elif action == "reroll_message":
                message_id = data.get("message_id")
                if not message_id:
                    if not await _safe_send_json(
                        websocket, {"type": "error", "message": "message_id required"}
                    ):
                        break
                else:
                    new_msg = await database_service.reroll_message(
                        message_id
                    )  # Added await
                    if not await _safe_send_json(
                        websocket,
                        {
                            "type": "reroll",
                            "old_id": message_id,
                            "new_message": new_msg,
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
        print("[WS] ⚠️ Client disconnected")
    finally:
        manager.disconnect(websocket)
