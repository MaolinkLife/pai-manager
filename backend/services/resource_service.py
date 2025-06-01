from utils.audio_devices import (
    get_output_devices,
    get_windows_output_candidates,
    get_device_name_by_id
)

# Здесь можно будет централизованно объединять и другие ресурсы:
# CPU, диск, монитор, микрофон, переменные среды и т.д.

def get_audio_resources():
    return {
        "all_devices": get_output_devices(),
        "get_windows_output": get_windows_output_candidates()
    }

def get_audio_device_name(device_id):
    return get_device_name_by_id(device_id)