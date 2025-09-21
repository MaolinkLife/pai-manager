"""
Vision Service: Main service for vision analysis.
"""

import threading
from typing import Optional, Dict, Any
from datetime import datetime

from .worker import VisionBuffer, ScreenCapturer
from .analyzer import VisionAnalyzer
from services.config_service import get_config_value
from services.logger_service import log_audit_entry, AuditStatus


class VisionService:
    """Main vision service for LIM."""

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
        """Start the vision service."""
        self.capturer.start()

    def stop(self):
        """Stop the vision service."""
        self.capturer.stop()

    def analyze_recent_context(self, seconds: float = 4.0) -> Dict[str, Any]:
        """
        Deterministic screen analysis:
        - Active window (title + process)
        - Top OCR lines with high confidence
        - Raw YOLO detections (evidence only)
        - SSIM/Optical Flow as auxiliary evidence
        """
        frames = self.buffer.get_frames_in_time_window(seconds)
        if not frames:
            log_audit_entry(
                "vision_no_frames",
                f"[Vision] No frames in {seconds}s",
                AuditStatus.INFO,
            )
            return {
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "event": "no_data",
                "summary": "No visual data available",
                "confidence": 0.0,
            }

        _, last_frame = frames[-1]
        prev_frame = frames[-2][1] if len(frames) >= 2 else None

        win = _get_active_window_info_safe()

        ocr_lang = get_config_value("vision.ocr_lang", "rus+eng")
        min_conf = int(get_config_value("vision.ocr_min_conf", 70))
        max_lines = int(get_config_value("vision.ocr_max_lines", 5))
        text_blocks = _extract_top_text_blocks(
            last_frame, lang=ocr_lang, min_conf=min_conf, max_lines=max_lines
        )

        yolo_list = []
        yolo_summary = None
        if get_config_value("vision.yolo_enabled", True):
            try:
                yolo_list = self.analyzer.detect_objects_yolo(last_frame) or []
                yolo_summary = self.analyzer.summarize_yolo_detections(yolo_list)
                log_audit_entry(
                    "vision_yolo_detected" if yolo_list else "vision_yolo_empty",
                    f"[Vision] YOLO: {len(yolo_list)} detections",
                    AuditStatus.INFO,
                    details={"detections": yolo_list[:10]},
                )
            except Exception as e:
                log_audit_entry(
                    "vision_yolo_error", f"[Vision] YOLO error: {e}", AuditStatus.ERROR
                )

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

        top_lines = [b["text"] for b in text_blocks if b.get("text")]
        readable = " | ".join(top_lines) if top_lines else "No text recognized"

        parts = []
        if win:
            parts.append(f"Active window: \"{win['title']}\" (proc: {win['process']})")
        parts.append(f"Screen text: {readable}")
        if yolo_summary and yolo_summary != "Nothing detected.":
            parts.append(f"Detected: {yolo_summary}")

        summary = ". ".join(parts) + "."

        ocr_conf = 0.0
        if text_blocks:
            confs = [
                b["conf"]
                for b in text_blocks
                if isinstance(b.get("conf"), (int, float))
            ]
            if confs:
                confs_sorted = sorted(confs)
                ocr_conf = confs_sorted[len(confs_sorted) // 2] / 100.0

        yolo_conf = max((d.get("confidence", 0.0) for d in yolo_list), default=0.0)
        confidence = round(min(0.95, max(0.55, ocr_conf, yolo_conf)), 2)

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
                    "lines": text_blocks,
                    "lang": ocr_lang,
                    "min_conf": min_conf,
                },
                "yolo": {
                    "detections": yolo_list,
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
        """Handle vision context query."""
        vision_keywords = [
            "видела",
            "заметила",
            "на экране",
            "ты видишь",
            "что там",
            "what's on screen",
            "do you see",
            "what do you see",
        ]

        query_lower = query.lower()
        if any(keyword in query_lower for keyword in vision_keywords):
            return self.analyze_recent_context(4.0)

        return None


# --- Helpers ---
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
        return None


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

        rows.sort(key=lambda r: r["conf"], reverse=True)
        return rows[:max_lines]
    except Exception:
        return []
