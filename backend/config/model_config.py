import os
from dotenv import load_dotenv

# Загружаем .env (если будет использоваться)
load_dotenv()

# Получаем названия моделей из переменных окружения или ставим дефолт
ollama_model = os.getenv("ZW_OLLAMA_MODEL", "llama3")
ollama_model_visual = os.getenv("ZW_OLLAMA_MODEL_VISUAL", "llava")
