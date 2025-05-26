from ollama import chat, ChatResponse
from ollama._types import ResponseError
from ollama import list as ollama_list

from config.model_config import ollama_model, ollama_model_visual
from requests.exceptions import ConnectionError as RequestsConnectionError


# Возвращает словарь параметров температуры по выбранному уровню (0-2).
def get_temperature_options(
    temp_level: int, stop: list | None, max_tokens: int
) -> dict | None:
    if temp_level == -1:
        return None

    if temp_level == 0:
        return {
            "temperature": 1.17,
            "min_p": 0.0597,
            "top_p": 0.87,
            "top_k": 64,
            "repeat_penalty": 1.09,
            "stop": stop,
            "num_predict": max_tokens,
        }

    if temp_level == 1:
        return {
            "temperature": 1.27,
            "min_p": 0.0497,
            "top_p": 0.87,
            "top_k": 72,
            "repeat_penalty": 1.12,
            "stop": stop,
            "num_predict": max_tokens,
        }

    if temp_level == 2:
        return {
            "temperature": 1.47,
            "min_p": 0.0397,
            "top_p": 0.97,
            "top_k": 99,
            "repeat_penalty": 1.19,
            "stop": stop,
            "num_predict": max_tokens,
        }


# Отправляет обычный (непотоковый) чат-запрос в Ollama, возвращает ответ.
def api_standard(history, temp_level, stop, max_tokens):
    try:
        response: ChatResponse = chat(
            model=ollama_model,
            messages=history,
            keep_alive="25h",
            options=get_temperature_options(temp_level, stop, max_tokens),
        )
        return response.message.content

    except ResponseError as e:
        print(
            f"❌ Ollama ResponseError: {e}\nМодель '{ollama_model}' не найдена или не загружена."
        )
        return f"[Ошибка] Модель '{ollama_model}' не найдена. Проверь конфигурацию или загрузи модель вручную."


# Отправляет запрос с stream=True — генерация потока текста.
def api_stream(history, temp_level, stop, max_tokens):
    try:
        return chat(
            model=ollama_model,
            messages=history,
            stream=True,
            keep_alive="25h",
            options=get_temperature_options(temp_level, stop, max_tokens),
        )
    except ResponseError as e:
        print(f"❌ Ollama ResponseError: {e}")
        return None
    except Exception as e:
        print(f"❌ Неизвестная ошибка в stream: {e}")
        return None


# Запрос к визуальной модели.
def api_standard_image(history):
    try:
        response: ChatResponse = chat(
            model=ollama_model_visual,
            messages=history,
            keep_alive="25h",
        )
        return response.message.content

    except ResponseError as e:
        print(f"❌ Vision-модель '{ollama_model_visual}' не найдена: {e}")
        return "[Ошибка] Визуальная модель не загружена."


# Потоковая генерация с визуальной моделью.
def api_stream_image(history):
    try:
        return chat(
            model=ollama_model_visual,
            messages=history,
            stream=True,
            keep_alive="25h",
        )
    except ResponseError as e:
        print(f"❌ Ollama ResponseError: {e}")
        return None
    except Exception as e:
        print(f"❌ Неизвестная ошибка в stream: {e}")
        return None


def is_ollama_available() -> bool:
    try:
        ollama_list()
        return True
    except (ResponseError, RequestsConnectionError, ConnectionError):
        return False
    except Exception as e:
        print(f"[!] Ошибка при проверке Ollama: {e}")
        return False


# Возвращает список доступных моделей, если Ollama работает. Иначе — сообщение об ошибке
def get_models():
    if not is_ollama_available():
        return {
            "status": "error",
            "message": "Ollama не установлена, не запущена или недоступна 💤",
        }

    try:
        models = ollama_list()
        model_list = models.models  # это не dict, а атрибут

        return {
            "status": "ok",
            "models": [m.model for m in model_list],  # доступ к полю объекта
        }

    except ResponseError as e:
        return {"status": "error", "message": f"Ollama вернула ошибку: {str(e)}"}

    except Exception as e:
        import traceback

        traceback.print_exc()

        return {
            "status": "error",
            "message": f"Неизвестная ошибка при получении моделей: {str(e)}",
        }
