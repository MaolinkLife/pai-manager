import numpy as np
import torch
from typing import Dict, List
from ultralytics import YOLO


class YOLODetector:
    def __init__(self, model_path: str = "yolov8m.pt", conf_threshold: float = 0.5):
        self.model_path = model_path
        self.conf_threshold = conf_threshold
        self.model = None
        self.class_names = {}
        self._load_model()

    def _load_model(self):
        try:
            self.model = YOLO(self.model_path)
            self.device = "cuda" if torch.cuda.is_available() else "cpu"
            self.model.to(self.device)
            self.class_names = self.model.names
            print(f"[YOLO] Model loaded. Device: {self.device}")
        except Exception as exc:
            print(f"[YOLO] Failed to load model: {exc}")
            raise

    def detect(self, frame: np.ndarray) -> List[Dict]:
        try:
            results = self.model(frame, verbose=False, conf=self.conf_threshold)
            detections = []

            for result in results:
                boxes = result.boxes
                if boxes is not None:
                    for i in range(len(boxes)):
                        cls_id = int(boxes.cls[i].item())
                        conf = float(boxes.conf[i].item())
                        xyxy = boxes.xyxy[i].cpu().numpy().tolist()
                        class_name = self.class_names.get(cls_id, f"unknown_{cls_id}")
                        detections.append(
                            {
                                "class": class_name,
                                "confidence": conf,
                                "bbox": xyxy,
                            }
                        )
            return detections
        except Exception as exc:
            print(f"[YOLO] Detection error: {exc}")
            return []
