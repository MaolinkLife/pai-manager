from fastapi import APIRouter
from services.voice_service import force_cut_voice
from services.api_service import play_message

router = APIRouter(prefix="/api/voice", tags=["Voice"])

@router.post("/stop")
async def stop_voice():
    force_cut_voice()
    return {"status": "ok", "message": "Speech playback stopped."}


@router.post("/play")
def play_message_by_id(request: dict):
    message_id = request.get("message_id")
    play_message(message_id)
    return {"status": "ok", "message": f"Play Message by Id {message_id}"}