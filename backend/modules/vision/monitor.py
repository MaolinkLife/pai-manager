import base64
from typing import Any, Dict, List

import cv2
import mss
import numpy as np


def get_monitor_screens() -> List[Dict[str, Any]]:
    try:
        monitors_info = []

        with mss.mss() as sct:
            monitors = sct.monitors[1:]

            for i, monitor in enumerate(monitors):
                try:
                    screenshot = sct.grab(monitor)
                    frame = np.array(screenshot)

                    if frame.shape[2] == 4:
                        frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)

                    max_preview_width = 300
                    if frame.shape[1] > max_preview_width:
                        h, w = frame.shape[:2]
                        preview_height = int(h * (max_preview_width / w))
                        preview_frame = cv2.resize(
                            frame,
                            (max_preview_width, preview_height),
                            interpolation=cv2.INTER_AREA,
                        )
                    else:
                        preview_frame = frame

                    _, buffer = cv2.imencode(
                        ".jpg", preview_frame, [cv2.IMWRITE_JPEG_QUALITY, 80]
                    )
                    preview_base64 = base64.b64encode(buffer).decode("utf-8")

                    monitors_info.append(
                        {
                            "index": i,
                            "width": monitor["width"],
                            "height": monitor["height"],
                            "left": monitor["left"],
                            "top": monitor["top"],
                            "preview": preview_base64,
                        }
                    )

                except Exception:
                    monitors_info.append(
                        {
                            "index": i,
                            "width": monitor["width"],
                            "height": monitor["height"],
                            "left": monitor["left"],
                            "top": monitor["top"],
                            "preview": None,
                        }
                    )

        return monitors_info

    except Exception as exc:
        print(f"[Monitor Service] Error getting monitors: {exc}")
        return []


def get_monitor_info() -> Dict[str, Any]:
    try:
        with mss.mss() as sct:
            monitors = sct.monitors
            return {
                "total_monitors": max(0, len(monitors) - 1),
                "monitors": [
                    {
                        "index": i,
                        "width": monitor["width"],
                        "height": monitor["height"],
                        "left": monitor["left"],
                        "top": monitor["top"],
                    }
                    for i, monitor in enumerate(monitors[1:])
                ],
            }
    except Exception as exc:
        return {"total_monitors": 0, "monitors": [], "error": str(exc)}
