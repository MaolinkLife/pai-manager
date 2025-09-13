# services/resource_service.py (обновленный)
from utils.audio_devices import (
    get_output_devices,
    get_windows_output_candidates,
    get_device_name_by_id,
    get_input_devices,  # Добавляем импорт
)


def get_audio_resources():
    """Получить все аудио ресурсы"""
    try:
        return {
            "status": "success",
            "all_devices": get_output_devices(),
            "get_windows_output": get_windows_output_candidates(),
            "recording_devices": get_input_devices(),  # Добавляем устройства записи
            "message": "Audio resources retrieved successfully",
        }
    except Exception as e:
        return {
            "status": "error",
            "content": f"Error while getting audio resources: {str(e)}",
            "all_devices": [],
            "get_windows_output": [],
            "recording_devices": [],
        }


def get_audio_device_name(device_id):
    """Получить имя аудиоустройства по ID"""
    return get_device_name_by_id(device_id)
