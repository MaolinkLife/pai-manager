from utils.audio_devices import (
    get_output_devices,
    get_windows_output_candidates,
    get_device_name_by_id
)

# Here you can centrally combine other resources:
# CPU, disk, monitor, microphone, environment variables, etc.

def get_audio_resources():
    return {
        "all_devices": get_output_devices(),
        "get_windows_output": get_windows_output_candidates()
    }

def get_audio_device_name(device_id):
    return get_device_name_by_id(device_id)