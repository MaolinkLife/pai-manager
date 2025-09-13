# utils/audio_utils.py (обновленный)
import sounddevice as sd


def get_input_devices():
    """Получить список устройств для записи (входных устройств)"""
    devices = sd.query_devices()
    seen_names = set()
    input_devices = []

    for index, device in enumerate(devices):
        name = device["name"]
        if device["max_input_channels"] > 0 and name not in seen_names:
            input_devices.append((index, name))
            seen_names.add(name)

    return input_devices


def get_output_devices():
    """Получить список устройств для воспроизведения (выходных устройств)"""
    devices = sd.query_devices()
    seen_names = set()
    output_devices = []

    for index, device in enumerate(devices):
        name = device["name"]
        if device["max_output_channels"] > 0 and name not in seen_names:
            output_devices.append((index, name))
            seen_names.add(name)

    return output_devices


def get_device_name_by_id(device_id, device_type="input"):
    """Получить имя устройства по ID"""
    if device_type == "input":
        devices = get_input_devices()
    else:
        devices = get_output_devices()

    for idx, name in devices:
        if idx == device_id:
            return f"{name} (ID: {idx})"
    return None


def get_windows_output_candidates():
    """Получить список реальных (не виртуальных) выходных устройств"""
    virtual_keywords = ["VB", "Cable", "VoiceMeeter", "Virtual", "Voicemod"]
    real_devices = []

    for idx, name in get_output_devices():
        if not any(keyword.lower() in name.lower() for keyword in virtual_keywords):
            real_devices.append((idx, name))

    return real_devices


def get_all_audio_devices():
    """Получить все аудиоустройства"""
    try:
        input_devices = get_input_devices()
        output_devices = get_output_devices()
        windows_output = get_windows_output_candidates()

        return {
            "input_devices": input_devices,
            "output_devices": output_devices,
            "windows_output": windows_output,
        }
    except Exception as e:
        return {
            "input_devices": [],
            "output_devices": [],
            "windows_output": [],
            "error": str(e),
        }
