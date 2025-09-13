# services/yolo_detector.py
import numpy as np
from typing import List, Dict
from ultralytics import YOLO
import torch


class YOLODetector:
    def __init__(self, model_path: str = "yolov8m.pt", conf_threshold: float = 0.5):
        """
        Инициализация YOLO-детектора.
        :param model_path: Путь к весам модели (например, yolov8n.pt)
        :param conf_threshold: Порог уверенности для детекции
        """
        self.model_path = model_path
        self.conf_threshold = conf_threshold
        self.model = None
        self.class_names = {}
        self._load_model()

    def _load_model(self):
        """Загрузка модели YOLO."""
        try:
            self.model = YOLO(self.model_path)
            # Определяем устройство
            self.device = "cuda" if torch.cuda.is_available() else "cpu"
            self.model.to(self.device)
            # Получаем имена классов
            self.class_names = self.model.names
            print(f"[YOLO] Модель загружена. Устройство: {self.device}")
        except Exception as e:
            print(f"[YOLO] Ошибка загрузки модели: {e}")
            raise

    def detect(self, frame: np.ndarray) -> List[Dict]:
        """
        Обнаружение объектов на одном кадре.
        :param frame: Изображение в формате numpy.ndarray (BGR)
        :return: Список обнаруженных объектов:
                 [
                     {
                         "class": "person",
                         "confidence": 0.92,
                         "bbox": [x1, y1, x2, y2]
                     },
                     ...
                 ]
        """
        try:
            # Выполняем предикт
            results = self.model(frame, verbose=False, conf=self.conf_threshold)
            detections = []

            # Обрабатываем результаты
            for result in results:
                boxes = result.boxes
                if boxes is not None:
                    for i in range(len(boxes)):
                        # Извлекаем данные
                        cls_id = int(boxes.cls[i].item())
                        conf = float(boxes.conf[i].item())
                        xyxy = boxes.xyxy[i].cpu().numpy().tolist()

                        # Получаем имя класса
                        class_name = self.class_names.get(cls_id, f"unknown_{cls_id}")

                        detections.append(
                            {
                                "class": class_name,
                                "confidence": conf,
                                "bbox": xyxy,  # [x1, y1, x2, y2]
                            }
                        )
            return detections
        except Exception as e:
            print(f"[YOLO] Ошибка при детекции: {e}")
            return []
