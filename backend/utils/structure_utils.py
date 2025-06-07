import os
from enum import Enum

class StructureEnum(str, Enum):
    Core = '[CORE]'
    ConfigService = '[CONFIG SERVICE]'
    Logger = '[LOGGER]'
    VoiceService = '[VOICE SERVICE]'
    # Дополняй по вкусу

def get_structure_label(name: str) -> str:
    """
    Преобразует имя (например, 'voice_service') в строковый тег из StructureEnum.
    Возвращает '[CORE]' по умолчанию, если не найдено.
    """
    camel_case = ''.join(part.capitalize() for part in name.split('_'))

    try:
        return StructureEnum[camel_case].value
    except KeyError:
        return StructureEnum['Core'].value

def get_label_from_file(file_path: str) -> str:
    base = os.path.splitext(os.path.basename(file_path))[0]
    return get_structure_label(base)