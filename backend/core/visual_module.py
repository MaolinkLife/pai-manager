import torch
from transformers import AutoTokenizer, AutoModelForCausalLM
from PIL import Image
import traceback  # Для детального логирования ошибок
from typing import Dict, Any, Optional
from services.logger_service import log_audit_entry, AuditStatus
from services.config_service import get_config_value


class VisualModule:
    """Универсальный модуль VLM (FastVLM, LLaVA, BLIP и т.п.)"""

    def __init__(self):
        self.model_id = get_config_value("api.visual_model", "apple/FastVLM-1.5B")

        # Явно проверяем доступность CUDA
        if torch.cuda.is_available():
            self.device = "cuda"
            torch_dtype = torch.float16
        else:
            self.device = "cpu"
            torch_dtype = torch.float32

        try:
            log_audit_entry(
                "visual_init",
                f"[Visual] Загружаем {self.model_id} на устройство: {self.device}",
                AuditStatus.INFO,
            )
            print(
                f"[DEBUG] [{datetime.utcnow().isoformat()}Z] [VisualModule] Начинаю загрузку токенизатора для {self.model_id}..."
            )

            # Загружаем токенизатор
            self.tokenizer = AutoTokenizer.from_pretrained(
                self.model_id, trust_remote_code=True
            )
            print(
                f"[DEBUG] [{datetime.utcnow().isoformat()}Z] [VisualModule] Токенизатор загружен успешно."
            )

            print(
                f"[DEBUG] [{datetime.utcnow().isoformat()}Z] [VisualModule] Начинаю загрузку модели {self.model_id} на {self.device}..."
            )
            # Загружаем модель с явным указанием устройства и типа данных
            self.model = AutoModelForCausalLM.from_pretrained(
                self.model_id,
                torch_dtype=torch_dtype,
                device_map=None,
                trust_remote_code=True,
                low_cpu_mem_usage=True,
            )
            print(
                f"[DEBUG] [{datetime.utcnow().isoformat()}Z] [VisualModule] Модель загружена в память. Перемещаю на устройство {self.device}..."
            )

            # Явно перемещаем модель на устройство
            self.model = self.model.to(self.device)
            print(
                f"[DEBUG] [{datetime.utcnow().isoformat()}Z] [VisualModule] Модель перемещена на устройство {self.device}."
            )

            log_audit_entry(
                "visual_loaded",
                f"[Visual] Модель {self.model_id} готова на {self.device}",
                AuditStatus.SUCCESS,
            )
            print(
                f"[DEBUG] [{datetime.utcnow().isoformat()}Z] [VisualModule] Инициализация завершена успешно."
            )
        except Exception as e:
            error_msg = f"[Visual] Ошибка загрузки модели: {e}"
            log_audit_entry(
                "visual_error",
                error_msg,
                AuditStatus.ERROR,
            )
            print(
                f"[ERROR] [{datetime.utcnow().isoformat()}Z] [VisualModule] {error_msg}"
            )
            print(
                f"[ERROR] [{datetime.utcnow().isoformat()}Z] [VisualModule] Подробности ошибки:\n{traceback.format_exc()}"
            )
            self.model = None
            self.tokenizer = None

    def is_ready(self) -> bool:
        is_ready_flag = self.model is not None and self.tokenizer is not None
        print(
            f"[DEBUG] [{datetime.utcnow().isoformat()}Z] [VisualModule] Проверка готовности: {is_ready_flag}"
        )
        return is_ready_flag

    def describe_image(
        self, image: Image.Image, prompt: str = "Опиши, что изображено на экране."
    ) -> Dict[str, Any]:
        print(
            f"[DEBUG] [{datetime.utcnow().isoformat()}Z] [VisualModule] Начало describe_image. Prompt: '{prompt}'"
        )
        if not self.is_ready():
            error_result = {
                "summary": "Visual module not available",
                "model": self.model_id,
                "status": "not_ready",
            }
            print(
                f"[WARN] [{datetime.utcnow().isoformat()}Z] [VisualModule] Модуль не готов. Возвращаю: {error_result}"
            )
            return error_result

        try:
            print(
                f"[DEBUG] [{datetime.utcnow().isoformat()}Z] [VisualModule] Модуль готов. Начинаю обработку изображения..."
            )
            IMAGE_TOKEN_INDEX = -200

            # 1. Собираем сообщение с плейсхолдером <image>
            messages = [{"role": "user", "content": f"<image>\n{prompt}"}]
            print(
                f"[DEBUG] [{datetime.utcnow().isoformat()}Z] [VisualModule] Подготовлены сообщения: {messages}"
            )
            rendered = self.tokenizer.apply_chat_template(
                messages, add_generation_prompt=True, tokenize=False
            )
            print(
                f"[DEBUG] [{datetime.utcnow().isoformat()}Z] [VisualModule] Шаблон применен. Rendered length: {len(rendered)} chars"
            )
            pre, post = rendered.split("<image>", 1)
            print(
                f"[DEBUG] [{datetime.utcnow().isoformat()}Z] [VisualModule] Разделен текст: pre={len(pre)} chars, post={len(post)} chars"
            )

            # 2. Токенизируем текст вокруг <image>
            pre_ids = self.tokenizer(
                pre, return_tensors="pt", add_special_tokens=False
            ).input_ids
            post_ids = self.tokenizer(
                post, return_tensors="pt", add_special_tokens=False
            ).input_ids
            print(
                f"[DEBUG] [{datetime.utcnow().isoformat()}Z] [VisualModule] Токенизация завершена. Pre shape: {pre_ids.shape}, Post shape: {post_ids.shape}"
            )

            # 3. Вставляем спец-токен для картинки
            img_tok = torch.tensor([[IMAGE_TOKEN_INDEX]], dtype=pre_ids.dtype)
            input_ids = torch.cat([pre_ids, img_tok, post_ids], dim=1).to(self.device)
            attention_mask = torch.ones_like(input_ids, device=self.device)
            print(
                f"[DEBUG] [{datetime.utcnow().isoformat()}Z] [VisualModule] Input IDs и Attention Mask подготовлены. Shape: {input_ids.shape}"
            )

            # 4. Прогоняем изображение через vision tower
            px = self.model.get_vision_tower().image_processor(
                images=image, return_tensors="pt"
            )["pixel_values"]
            px = px.to(self.device, dtype=self.model.dtype)
            print(
                f"[DEBUG] [{datetime.utcnow().isoformat()}Z] [VisualModule] Изображение обработано. Pixel values shape: {px.shape}, dtype: {px.dtype}"
            )

            # 5. Генерация
            print(
                f"[DEBUG] [{datetime.utcnow().isoformat()}Z] [VisualModule] Начинаю генерацию..."
            )
            with torch.no_grad():
                out = self.model.generate(
                    inputs=input_ids,
                    attention_mask=attention_mask,
                    images=px,
                    max_new_tokens=128,
                    # Можно добавить больше параметров для отладки, если нужно
                    # do_sample=True, temperature=0.7
                )
            print(
                f"[DEBUG] [{datetime.utcnow().isoformat()}Z] [VisualModule] Генерация завершена. Output shape: {out.shape}"
            )

            text = self.tokenizer.decode(out[0], skip_special_tokens=True)
            result = {
                "summary": text.strip(),
                "model": self.model_id,
                "prompt": prompt,
                "status": "success",
            }
            print(
                f"[DEBUG] [{datetime.utcnow().isoformat()}Z] [VisualModule] Декодирование завершено. Результат: {result}"
            )
            return result

        except Exception as e:
            error_msg = f"[Visual] Ошибка инференса: {e}"
            log_audit_entry(
                "visual_inference_error",
                error_msg,
                AuditStatus.ERROR,
            )
            error_result = {
                "summary": f"Ошибка инференса: {e}",
                "model": self.model_id,
                "status": "error",
            }
            print(
                f"[ERROR] [{datetime.utcnow().isoformat()}Z] [VisualModule] {error_msg}"
            )
            print(
                f"[ERROR] [{datetime.utcnow().isoformat()}Z] [VisualModule] Подробности ошибки:\n{traceback.format_exc()}"
            )
            return error_result


# Для получения времени в логах
from datetime import datetime
