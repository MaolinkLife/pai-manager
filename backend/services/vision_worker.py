# services/vision_worker.py
import mss
import cv2
import numpy as np
import time
import threading
from collections import deque
from datetime import datetime
from typing import Optional, List, Tuple, Dict, Any
import json

from services.config_service import get_config_value
from services.logger_service import log_audit_entry, AuditStatus


class VisionBuffer:
    """Циклический буфер для хранения кадров"""

    def __init__(self):
        buffer_sec = get_config_value("vision.buffer_sec", 4)
        fps = get_config_value("vision.fps", 5)
        self.max_frames = int(buffer_sec * fps)
        self.frames = deque(maxlen=self.max_frames)
        self.lock = threading.Lock()

    def push(self, frame_bgr: np.ndarray):
        """Добавить кадр в буфер"""
        with self.lock:
            timestamp = time.time()
            self.frames.append((timestamp, frame_bgr.copy()))

    def get_latest_frames(self, n: int = 1) -> List[Tuple[float, np.ndarray]]:
        """Получить последние N кадров"""
        with self.lock:
            if not self.frames:
                return []
            return list(self.frames)[-n:]

    def get_frames_in_time_window(
        self, seconds: float = 4.0
    ) -> List[Tuple[float, np.ndarray]]:
        """Получить кадры за последние N секунд"""
        with self.lock:
            if not self.frames:
                return []

            current_time = time.time()
            result = []
            for timestamp, frame in reversed(self.frames):
                if current_time - timestamp <= seconds:
                    result.append((timestamp, frame))
                else:
                    break
            return list(reversed(result))

    def clear(self):
        """Очистить буфер"""
        with self.lock:
            self.frames.clear()


class ScreenCapturer:
    """Захват экрана в фоновом режиме"""

    def __init__(self, vision_buffer: VisionBuffer):
        self.buf = vision_buffer
        self.running = False
        self.capture_thread = None
        self.sct = None

    def start(self):
        """Запустить захват экрана"""
        if not get_config_value("vision.enabled", False):
            log_audit_entry(
                event_type="vision_disabled",
                msg="[Vision] Модуль зрения отключен в конфигурации",
                status=AuditStatus.INFO,
            )
            return

        if self.running:
            return

        self.running = True
        self.capture_thread = threading.Thread(target=self._capture_loop, daemon=True)
        self.capture_thread.start()
        log_audit_entry(
            event_type="vision_started",
            msg="[Vision] Модуль зрения запущен",
            status=AuditStatus.SUCCESS,
        )

    def stop(self):
        """Остановить захват экрана"""
        self.running = False
        if self.capture_thread:
            self.capture_thread.join()
        log_audit_entry(
            event_type="vision_stopped",
            msg="[Vision] Модуль зрения остановлен",
            status=AuditStatus.INFO,
        )

    def _capture_loop(self):
        """Основной цикл захвата"""
        try:
            fps = get_config_value("vision.fps", 5)
            monitor_idx = get_config_value("vision.monitor_index", 1)
            downscale_width = get_config_value("vision.downscale_width", 1280)
            region = get_config_value("vision.region", None)

            with mss.mss() as sct:
                # Определяем монитор
                if region:
                    monitor = region
                else:
                    if monitor_idx >= len(sct.monitors):
                        monitor_idx = 1  # fallback
                    monitor = sct.monitors[monitor_idx]

                while self.running:
                    try:
                        # Захват кадра
                        screenshot = sct.grab(monitor)
                        frame = np.array(screenshot)

                        # Конвертируем BGRA в BGR
                        if frame.shape[2] == 4:
                            frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)

                        # Даунскейлим если нужно
                        if downscale_width and frame.shape[1] > downscale_width:
                            h, w = frame.shape[:2]
                            downscale_height = int(h * (downscale_width / w))
                            frame = cv2.resize(
                                frame,
                                (downscale_width, downscale_height),
                                interpolation=cv2.INTER_AREA,
                            )

                        # Сохраняем в буфер
                        self.buf.push(frame)

                        # Ждем следующий кадр
                        time.sleep(1.0 / fps)

                    except Exception as e:
                        log_audit_entry(
                            event_type="vision_capture_error",
                            msg=f"[Vision] Ошибка захвата кадра: {str(e)}",
                            status=AuditStatus.ERROR,
                        )
                        time.sleep(0.1)  # пауза при ошибке

        except Exception as e:
            log_audit_entry(
                event_type="vision_fatal_error",
                msg=f"[Vision] Фатальная ошибка захвата: {str(e)}",
                status=AuditStatus.ERROR,
            )
