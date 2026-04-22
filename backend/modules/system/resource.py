from utils.audio_devices import (
    get_output_devices,
    get_windows_output_candidates,
    get_device_name_by_id,
    get_input_devices,
)


def get_audio_resources():
    try:
        return {
            "status": "success",
            "all_devices": get_output_devices(),
            "get_windows_output": get_windows_output_candidates(),
            "recording_devices": get_input_devices(),
            "message": "Audio resources retrieved successfully",
        }
    except Exception as exc:
        return {
            "status": "error",
            "content": f"Error while getting audio resources: {str(exc)}",
            "all_devices": [],
            "get_windows_output": [],
            "recording_devices": [],
        }


def get_audio_device_name(device_id):
    return get_device_name_by_id(device_id)
