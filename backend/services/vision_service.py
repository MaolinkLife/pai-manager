import threading
from typing import Optional, Dict, Any
from datetime import datetime

from services.vision_worker import VisionBuffer, ScreenCapturer
from services.vision_analyzer import VisionAnalyzer
from services.config_service import get_config_value
from services.logger_service import log_audit_entry, AuditStatus
from core.visual_module import VisualModule


class VisionService:
    """Основной сервис зрения для LIM"""

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super(VisionService, cls).__new__(cls)
        return cls._instance

    def __init__(self):
        if hasattr(self, "initialized"):
            return

        self.buffer = VisionBuffer()
        self.capturer = ScreenCapturer(self.buffer)
        self.analyzer = VisionAnalyzer()
        self.initialized = True

    def start(self):
        """Запустить сервис зрения"""
        self.capturer.start()

    def stop(self):
        """Остановить сервис зрения"""
        self.capturer.stop()

    def analyze_recent_context(self, seconds: float = 4.0) -> Dict[str, Any]:
        """
        Детерминированный обзор экрана:
        - Активное окно (заголовок + процесс)
        - Топ-строки OCR с высокой уверенностью
        - Сырые объекты YOLO (только evidence)
        - SSIM/Optical Flow как вспомогательное evidence
        """
        frames = self.buffer.get_frames_in_time_window(seconds)
        if not frames:
            log_audit_entry(
                "vision_no_frames",
                f"[Vision] Нет кадров за {seconds}s",
                AuditStatus.INFO,
            )
            return {
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "event": "no_data",
                "summary": "Нет доступных визуальных данных",
                "confidence": 0.0,
            }

        # --- последний кадр (+ предыдущий для сцены) ---
        _, last_frame = frames[-1]
        prev_frame = frames[-2][1] if len(frames) >= 2 else None

        # --- 1) Активное окно (best-effort) ---
        win = _get_active_window_info_safe()

        # --- 2) OCR: берём самые уверенные строки ---
        ocr_lang = get_config_value("vision.ocr_lang", "rus+eng")
        min_conf = int(get_config_value("vision.ocr_min_conf", 70))
        max_lines = int(get_config_value("vision.ocr_max_lines", 5))
        text_blocks = _extract_top_text_blocks(
            last_frame, lang=ocr_lang, min_conf=min_conf, max_lines=max_lines
        )

        # --- 3) YOLO: сырые детекции в evidence ---
        yolo_list = []
        yolo_summary = None
        try:
            if get_config_value("vision.yolo_enabled", True):
                yolo_list = self.analyzer.detect_objects_yolo(last_frame) or []
                yolo_summary = self.analyzer.summarize_yolo_detections(yolo_list)
                log_audit_entry(
                    "vision_yolo_detected" if yolo_list else "vision_yolo_empty",
                    f"[Vision] YOLO: {len(yolo_list)} детекций",
                    AuditStatus.INFO,
                    details={"detections": yolo_list[:10]},  # не раздуваем лог
                )
        except Exception as e:
            log_audit_entry(
                "vision_yolo_error", f"[Vision] YOLO error: {e}", AuditStatus.ERROR
            )

        # --- 4) Изменения сцены (evidence-only) ---
        scene_change = None
        flow_info = None
        if prev_frame is not None:
            try:
                ssim_value = self.analyzer.calculate_ssim(prev_frame, last_frame)
                scene_change = {
                    "ssim": float(ssim_value),
                    "ssim_drop": float(1.0 - ssim_value),
                }
                log_audit_entry(
                    "vision_scene_change",
                    f"[Vision] SSIM={ssim_value:.6f}, drop={1.0 - ssim_value:.6f}",
                    AuditStatus.INFO,
                    details=scene_change,
                )
            except Exception as e:
                log_audit_entry(
                    "vision_ssim_error", f"[Vision] SSIM error: {e}", AuditStatus.ERROR
                )

            try:
                flow_info = self.analyzer.calculate_optical_flow(prev_frame, last_frame)
            except Exception as e:
                log_audit_entry(
                    "vision_optical_flow_error",
                    f"[Vision] Flow error: {e}",
                    AuditStatus.ERROR,
                )

        # --- 5) Итоговый summary (детерминированный, без “угадалок”) ---
        top_lines = [b["text"] for b in text_blocks if b.get("text")]
        readable = " | ".join(top_lines) if top_lines else "Текст не распознан"

        parts = []
        if win:
            parts.append(f"Активно окно: \"{win['title']}\" (proc: {win['process']})")
        parts.append(f"На экране читается: {readable}")
        if yolo_summary and yolo_summary != "Ничего не обнаружено.":
            parts.append(f"Обнаружено: {yolo_summary}")

        summary = ". ".join(parts) + "."

        # --- 6) Уверенность: по данным, которые реально есть ---
        ocr_conf = 0.0
        if text_blocks:
            confs = [
                b["conf"]
                for b in text_blocks
                if isinstance(b.get("conf"), (int, float))
            ]
            if confs:
                confs_sorted = sorted(confs)
                ocr_conf = (
                    confs_sorted[len(confs_sorted) // 2] / 100.0
                )  # медиана → [0..1]

        yolo_conf = max((d.get("confidence", 0.0) for d in yolo_list), default=0.0)

        confidence = round(min(0.95, max(0.55, ocr_conf, yolo_conf)), 2)

        # --- 7) Результат ---
        result = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "monitor": get_config_value("vision.monitor_index", 1),
            "event": "screen_snapshot",
            "cause": "none",
            "confidence": confidence,
            "summary": summary,
            "evidence": {
                "window": win or {},
                "ocr": {
                    "lines": text_blocks,  # [{text, conf, bbox:{x,y,w,h}}]
                    "lang": ocr_lang,
                    "min_conf": min_conf,
                },
                "yolo": {
                    "detections": yolo_list,  # [{class, confidence, bbox:[x1,y1,x2,y2]}, ...]
                    "summary": yolo_summary,
                },
                "scene_change": scene_change or {},
                "optical_flow": flow_info or {},
            },
        }

        log_audit_entry(
            "vision_analysis_complete",
            f"[Vision] OK: conf={confidence:.2f}",
            AuditStatus.INFO,
            details=result,
        )
        return result

    def handle_vision_query(self, query: str) -> Optional[Dict[str, Any]]:
        """Обработать запрос о визуальном контексте"""
        # Проверяем ключевые слова запроса
        vision_keywords = [
            "видела",
            "заметила",
            "на экране",
            "ты видишь",
            "что там",
            "что на экране",
            "ты это видела",
        ]

        query_lower = query.lower()
        if any(keyword in query_lower for keyword in vision_keywords):
            return self.analyze_recent_context(4.0)

        return None


# --- Helpers: активное окно (Windows) ---
def _get_active_window_info_safe():
    try:
        import psutil
        import win32gui
        import win32process

        hwnd = win32gui.GetForegroundWindow()
        title = win32gui.GetWindowText(hwnd) or ""
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        proc = psutil.Process(pid).name() if pid else ""
        title = title.strip()
        proc = (proc or "").strip()
        if not title and not proc:
            return None
        return {"title": title[:128], "process": proc[:64]}
    except Exception:
        # нет win32/psutil — работаем дальше без окна
        return None


# --- Helpers: топ-строки OCR с порогом уверенности ---
def _extract_top_text_blocks(frame, lang="rus+eng", min_conf=70, max_lines=5):
    try:
        import cv2
        import pytesseract
        from pytesseract import Output

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        gray = cv2.convertScaleAbs(gray, alpha=1.4, beta=0)
        _, th = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

        data = pytesseract.image_to_data(th, lang=lang, output_type=Output.DICT)
        n = len(data["text"])
        rows = []
        for i in range(n):
            text = (data["text"][i] or "").strip()
            if not text:
                continue
            try:
                conf = float(data["conf"][i])
            except Exception:
                conf = -1.0
            if conf < float(min_conf):
                continue
            x, y, w, h = (
                int(data["left"][i]),
                int(data["top"][i]),
                int(data["width"][i]),
                int(data["height"][i]),
            )
            rows.append(
                {"text": text, "conf": conf, "bbox": {"x": x, "y": y, "w": w, "h": h}}
            )

        # сортируем по conf и ограничиваем число строк
        rows.sort(key=lambda r: r["conf"], reverse=True)
        return rows[:max_lines]
    except Exception:
        # pytesseract не установлен/ошибка — fallback: пусто
        return []


# Глобальный экземпляр сервиса
vision_service = VisionService()
