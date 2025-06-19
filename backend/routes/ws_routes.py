import json
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from core.websocket_manager import manager
from services.api_service import run_stream_message

ws_router = APIRouter(prefix="/api", tags=["WebSocket"])

@ws_router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            print(f"[WS] Get message from client: {data}")
            
            payload = json.loads(data)

            if not isinstance(payload, dict) or "history" not in payload:
                await websocket.send_text("[WS] Error: Field 'history' is missing")
                continue

            history = payload["history"]
            await run_stream_message(websocket, history)
    except WebSocketDisconnect:
        manager.disconnect(websocket)
        print("[WS] Client Disconnected")