import json
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from core.websocket_manager import manager
from services import api_service, database_service, config_service

ws_router = APIRouter(prefix="/api", tags=["WebSocket"])


@ws_router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            raw_data = await websocket.receive_text()
            print(f"[WS] ⬅️ From client: {raw_data}")

            try:
                payload = json.loads(raw_data)
            except json.JSONDecodeError:
                await websocket.send_json({"type": "error", "message": "Invalid JSON"})
                continue

            action = payload.get("action")
            data = payload.get("payload", {})

            if not action:
                await websocket.send_json(
                    {"type": "error", "message": "Missing 'action'"}
                )
                continue

            # === ROUTING ===
            if action == "send_message":
                try:
                    await api_service.run_stream_message(websocket, [data])
                except ValueError as e:
                    await websocket.send_json({"type": "error", "message": str(e)})

            elif action == "fetch_history":
                limit = data.get("limit", 32)
                char_name = config_service.get_config_value(
                    "char_name", "default_waifu"
                )
                history = database_service.get_history(char_name, limit)
                await websocket.send_json({"type": "history", "items": history})

            elif action == "delete_message":
                message_id = data.get("message_id")
                chain = data.get("chain", False)
                if not message_id:
                    await websocket.send_json(
                        {"type": "error", "message": "message_id required"}
                    )
                else:
                    if chain:
                        database_service.delete_message_chain(message_id)
                        await websocket.send_json(
                            {
                                "type": "deleted",
                                "message_id": message_id,
                                "chain": True,
                            }
                        )
                    else:
                        database_service.delete_message(message_id)
                        await websocket.send_json(
                            {
                                "type": "deleted",
                                "message_id": message_id,
                                "chain": False,
                            }
                        )

            elif action == "reroll_message":
                message_id = data.get("message_id")
                if not message_id:
                    await websocket.send_json(
                        {"type": "error", "message": "message_id required"}
                    )
                else:
                    new_msg = await database_service.reroll_message(
                        message_id
                    )  # Добавил await
                    await websocket.send_json(
                        {"type": "reroll", "old_id": message_id, "new_message": new_msg}
                    )

            else:
                await websocket.send_json(
                    {"type": "error", "message": f"Unknown action '{action}'"}
                )

    except WebSocketDisconnect:
        manager.disconnect(websocket)
        print("[WS] ⚠️ Client disconnected")
