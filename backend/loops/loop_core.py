from threading import Thread
from loops.loop_initiative import initiative_monitor
from services.logger_service import log_audit
# from loops.loop_emotion import emotion_drift_monitor   ← (позже сюда)
# from loops.loop_anchors import anchor_check_monitor    ← (позже сюда)

def run_loop():
    Thread(target=initiative_monitor, daemon=True).start()
    # Thread(target=emotion_drift_monitor, daemon=True).start()
    # Thread(target=anchor_check_monitor, daemon=True).start()
    print("[LIM] ✅ Loop system запущен.")
    log_audit("loop_started", {"loop": "initiative_monitor", "msg": "[Initiative] Loop system запущен", "status": "OK"})