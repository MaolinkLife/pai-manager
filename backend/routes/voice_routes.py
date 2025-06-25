import json
from fastapi import APIRouter, Body

from services.voice_service import force_cut_voice
from services.api_service import play_message, run_standard
from services import config_service, voice_controller

from core.websocket_manager import manager

router = APIRouter(prefix="/api/voice", tags=["Voice"])

@router.post("/stop")
async def stop_voice():
    force_cut_voice()
    return {"status": "ok", "message": "Playback has stopped"}


@router.post("/play")
def play_message_by_id(request: dict = Body(...)):
    message_id = request.get("message_id")
    if not message_id:
        return {"status": "error", "message": "message_id не указан"}
    
    play_message(message_id)
    return {"status": "ok", "message": f"Playing the message: {message_id}"}


@router.post("/record/start")
def start_record():
    return voice_controller.start_recording()


@router.post("/record/stop")
async def stop_record():
    char_name = config_service.get_config_value("char_name", "default_waifu")
    data = voice_controller.stop_recording_and_process(char_name)
    
    async def push_ws(msg):
        await manager.send_message(json.dumps(msg, ensure_ascii=False))
    
    await run_standard([data], emit_ws_fn=push_ws)

    return {
        "status": "ok",
        "data": data
    }
