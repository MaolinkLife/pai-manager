import torch
from PIL import Image
import gc
from typing import Dict, Any

from datetime import datetime

from services.logger_service import log_audit_entry, AuditStatus
from services.config_service import get_config_value
from constants.visual import DEFAULT_VISUAL_MODEL

from modules.vision.providers.apple_vision import AppleVisionProvider


class VisualModule:
    """
    Universal Visual Language Model (VLM) module wrapper.
    Supports FastVLM, LLaVA, BLIP and similar architectures.
    """

    def __init__(self, provider_name: str = None):
        self.provider_name = provider_name or get_config_value(
            "vision.active_provider", "apple_vision"
        )
        self.provider = self._load_provider()

    def _load_provider(self):
        if self.provider_name == "apple_vision":
            return AppleVisionProvider()
        else:
            # Можно добавить другие провайдеры: openai_vision, llava_vision и т.п.
            raise ValueError(f"Unknown vision provider: {self.provider_name}")

    def is_ready(self) -> bool:
        return self.provider.is_ready()

    def describe_image(
        self,
        image: Image.Image,
        prompt: str = "Describe the image in detail in English.",
    ) -> Dict[str, Any]:
        return self.provider.describe_image(image, prompt)

    # ===========================================================
    # Vision Context Integration (Moved from api_service.py)
    # ===========================================================
    def add_vision_context_to_system_prompt(
        self,
        base_system_prompt: str,
        last_user_message_content: str = "",
        decisions: Dict[str, bool] = None,
    ) -> str:
        decisions = decisions or {}
        session_id = "unknown_session"
        try:
            from services.logger_service import get_session_id

            session_id = get_session_id()
        except ImportError:
            pass

        event_prefix = "vision_context"

        if not get_config_value("vision.enabled", False):
            log_audit_entry(
                event_type=f"{event_prefix}_disabled",
                msg="[Vision Context] Визуальный модуль отключен в конфигурации.",
                status=AuditStatus.INFO,
                meta={"session_id": session_id},
            )
            return base_system_prompt

        visual_module_instance = None
        try:
            from modules.vision.service import VisionService

            log_audit_entry(
                event_type=f"{event_prefix}_init",
                msg="[Vision Context] Создаю экземпляр VisualModule...",
                status=AuditStatus.INFO,
                meta={"session_id": session_id},
            )
            visual_module_instance = self

            # --- Determine whether this is a vision query ---
            vision_keywords = [
                "видела",
                "заметила",
                "на экране",
                "ты видишь",
                "ты это видела",
                "что видишь",
                "что на экране",
                "опиши экран",
                "расскажи, что на экране",
                "что ты видишь",
                "скажи, что видишь",
                "видишь ли ты",
            ]

            needs_vision_from_layer = decisions.get("needs_vision", False)
            is_vision_query = needs_vision_from_layer or any(
                kw in last_user_message_content.lower() for kw in vision_keywords
            )

            log_audit_entry(
                event_type=f"{event_prefix}_query_check",
                msg=f"[Vision Context] Сообщение пользователя: '{last_user_message_content}'",
                status=AuditStatus.INFO,
                details={
                    "is_vision_query": is_vision_query,
                    "keywords_matched": [
                        kw
                        for kw in vision_keywords
                        if kw in last_user_message_content.lower()
                    ],
                },
                meta={"session_id": session_id},
            )

            # --- Gather baseline analysis (OCR/YOLO) ---
            log_audit_entry(
                event_type=f"{event_prefix}_analyzing",
                msg="[Vision Context] Запрашиваю анализ у VisionService...",
                status=AuditStatus.INFO,
                meta={"session_id": session_id},
            )
            vision_service = VisionService()
            visual_data = vision_service.analyze_recent_context(4.0)
            confidence = visual_data.get("confidence", "N/A") if visual_data else "N/A"
            log_audit_entry(
                event_type=f"{event_prefix}_analyzed",
                msg=f"[Vision Context] Получен анализ от VisionService.",
                status=AuditStatus.INFO,
                details={
                    "confidence": confidence,
                    "summary_preview": (
                        visual_data.get("summary", "")[:100] if visual_data else None
                    ),
                },
                meta={"session_id": session_id},
            )

            # --- Try using FastVLM ---
            vlm_used = False
            if is_vision_query:
                log_audit_entry(
                    event_type=f"{event_prefix}_vlm_check",
                    msg="[Vision Context] Это визуальный запрос. Проверяю готовность VisualModule...",
                    status=AuditStatus.INFO,
                    meta={"session_id": session_id},
                )

                is_vm_ready = (
                    visual_module_instance.is_ready()
                    if visual_module_instance
                    else False
                )
                log_audit_entry(
                    event_type=f"{event_prefix}_vlm_status",
                    msg=f"[Vision Context] Статус VisualModule: {'Готов' if is_vm_ready else 'Не готов'}.",
                    status=AuditStatus.INFO,
                    meta={"session_id": session_id},
                )

                if is_vm_ready:
                    log_audit_entry(
                        event_type=f"{event_prefix}_vlm_fetching_frame",
                        msg="[Vision Context] VisualModule готов. Получаю кадры...",
                        status=AuditStatus.INFO,
                        meta={"session_id": session_id},
                    )
                    frames = vision_service.buffer.get_latest_frames(1)
                    if frames:
                        log_audit_entry(
                            event_type=f"{event_prefix}_vlm_processing_image",
                            msg="[Vision Context] Получен кадр. Преобразую в PIL Image и вызываю describe_image...",
                            status=AuditStatus.INFO,
                            meta={"session_id": session_id},
                        )
                        try:
                            _, last_frame = frames[-1]

                            import cv2

                            img_rgb = cv2.cvtColor(last_frame, cv2.COLOR_BGR2RGB)
                            pil_img = Image.fromarray(img_rgb)

                            # Invoke FastVLM
                            vlm_result = visual_module_instance.describe_image(
                                pil_img,
                                "Describe the screen in detail in English.",
                            )

                            log_audit_entry(
                                event_type=f"{event_prefix}_vlm_success",
                                msg="[Vision Context] Получен результат от VisualModule.",
                                status=AuditStatus.SUCCESS,
                                details={
                                    "model": vlm_result.get("model"),
                                    "prompt": vlm_result.get("prompt"),
                                    "summary_preview": vlm_result.get("summary", "")[
                                        :150
                                    ],
                                    "status": vlm_result.get("status"),
                                },
                                meta={"session_id": session_id},
                            )

                            visual_summary = vlm_result.get("summary", "")
                            if visual_summary:
                                final_prompt = (
                                    f"{base_system_prompt}\n\n[CONTEXT:VISUAL]: {visual_summary}"
                                    "\n\n[INSTRUCTION]\n"
                                    "You currently see on the user's screen: "
                                    f"{visual_summary}. Reference relevant visual details "
                                    "in your reply when helpful."
                                )
                                log_audit_entry(
                                    event_type=f"{event_prefix}_vlm_added",
                                    msg="[Vision Context] Добавлен контекст от VisualModule.",
                                    status=AuditStatus.SUCCESS,
                                    details={"summary_length": len(visual_summary)},
                                    meta={"session_id": session_id},
                                )
                                vlm_used = True
                                return final_prompt
                            else:
                                log_audit_entry(
                                    event_type=f"{event_prefix}_vlm_empty_summary",
                                    msg="[Vision Context] VisualModule вернул пустой summary.",
                                    status=AuditStatus.WARNING,
                                    meta={"session_id": session_id},
                                )
                        except Exception as img_proc_err:
                            log_audit_entry(
                                event_type=f"{event_prefix}_vlm_image_error",
                                msg=f"[Vision Context] Ошибка при обработке изображения или вызове describe_image: {img_proc_err}",
                                status=AuditStatus.ERROR,
                                meta={"session_id": session_id},
                            )
                    else:
                        log_audit_entry(
                            event_type=f"{event_prefix}_no_frames",
                            msg="[Vision Context] Нет доступных кадров для анализа VisualModule.",
                            status=AuditStatus.WARNING,
                            meta={"session_id": session_id},
                        )
                else:
                    log_audit_entry(
                        event_type=f"{event_prefix}_vlm_not_ready",
                        msg="[Vision Context] VisualModule не готов для использования.",
                        status=AuditStatus.WARNING,
                        meta={"session_id": session_id},
                    )

            # --- Fallback to OCR/YOLO ---
            if not vlm_used and visual_data and visual_data.get("confidence", 0) > 0.5:
                ocr_yolo_summary = visual_data.get("summary", "")
                final_prompt = (
                    f"{base_system_prompt}\n\n[CONTEXT:VISUAL]: {ocr_yolo_summary}"
                    "\n\n[INSTRUCTION]\n"
                    "You currently see on the user's screen: "
                    f"{ocr_yolo_summary}. Reference relevant visual details in "
                    "your reply when helpful."
                )
                log_audit_entry(
                    event_type=f"{event_prefix}_ocr_yolo_added",
                    msg="[Vision Context] Добавлен контекст от OCR/YOLO.",
                    status=AuditStatus.SUCCESS,
                    details={
                        "summary_preview": ocr_yolo_summary[:100],
                        "confidence": visual_data.get("confidence"),
                    },
                    meta={"session_id": session_id},
                )
                return final_prompt
            else:
                log_audit_entry(
                    event_type=f"{event_prefix}_low_confidence",
                    msg="[Vision Context] Уверенность OCR/YOLO низкая или данные отсутствуют.",
                    status=AuditStatus.INFO,
                    details={"confidence": confidence},
                    meta={"session_id": session_id},
                )

        except Exception as e:
            log_audit_entry(
                event_type=f"{event_prefix}_error",
                msg=f"[Vision Context] Ошибка добавления контекста: {e}",
                status=AuditStatus.ERROR,
                details={"error": str(e)},
                meta={"session_id": session_id},
            )
        finally:
            # --- Force resource cleanup ---
            if visual_module_instance is not None and visual_module_instance != self:
                del visual_module_instance
                import gc

                gc.collect()
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
                log_audit_entry(
                    event_type=f"{event_prefix}_cleanup",
                    msg="[Vision Context] Ресурсы VisualModule освобождены.",
                    status=AuditStatus.INFO,
                    meta={"session_id": session_id},
                )

        log_audit_entry(
            event_type=f"{event_prefix}_fallback",
            msg="[Vision Context] Возвращаю оригинальный промпт без визуального контекста.",
            status=AuditStatus.INFO,
            meta={"session_id": session_id},
        )
        return base_system_prompt
