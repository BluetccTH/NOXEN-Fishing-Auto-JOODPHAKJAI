from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from .vision import detect_charge, detect_control_bar, detect_fish_marker, detect_progress
from .win32 import Rect, relative_point_to_screen, relative_rect_to_screen


def capture_rgb(sct, rect: Rect) -> np.ndarray:
    shot = np.asarray(sct.grab(rect.as_mss()))
    return shot[:, :, [2, 1, 0]].copy()


def test_vision(sct, hwnd: int, cfg: dict, bounds: Rect) -> tuple[dict, dict[str, np.ndarray], np.ndarray]:
    regions = cfg["regions"]
    crops: dict[str, np.ndarray] = {}
    metrics: dict = {}
    if isinstance(regions.get("charge"), dict):
        charge_rect = relative_rect_to_screen(regions["charge"], bounds)
        crops["charge"] = capture_rgb(sct, charge_rect)
        metrics["charge"] = detect_charge(crops["charge"])
    if isinstance(regions.get("slider"), dict):
        slider_rect = relative_rect_to_screen(regions["slider"], bounds)
        crops["slider"] = capture_rgb(sct, slider_rect)
        control_bar = detect_control_bar(crops["slider"])
        fish_marker = detect_fish_marker(crops["slider"])
        metrics["bar_center"] = control_bar[0] if control_bar else None
        metrics["bar_width"] = control_bar[1] if control_bar else None
        metrics["fish_x"] = fish_marker[0] if fish_marker else None
        metrics["fish_y"] = fish_marker[1] if fish_marker else None
    if isinstance(regions.get("progress"), dict):
        progress_rect = relative_rect_to_screen(regions["progress"], bounds)
        crops["progress"] = capture_rgb(sct, progress_rect)
        metrics["progress"] = detect_progress(crops["progress"])
    full = capture_rgb(sct, bounds)
    return metrics, crops, full


def save_debug_snapshot(folder: Path, cfg: dict, bounds: Rect, metrics: dict, crops: dict[str, np.ndarray], full: np.ndarray) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    image_path = folder / f"debug_{stamp}.png"
    json_path = folder / f"debug_{stamp}.json"

    image = Image.fromarray(full)
    draw = ImageDraw.Draw(image)
    colors = {"charge": (255, 205, 65), "slider": (75, 210, 170), "progress": (255, 110, 180)}
    for key, color in colors.items():
        region = cfg["regions"].get(key)
        if not isinstance(region, dict):
            continue
        rect = relative_rect_to_screen(region, bounds)
        local_box = (rect.left - bounds.left, rect.top - bounds.top,
                     rect.right - bounds.left, rect.bottom - bounds.top)
        draw.rectangle(local_box, outline=color, width=3)
        draw.text((local_box[0] + 3, max(0, local_box[1] - 18)), key.upper(), fill=color)
    point = cfg["regions"].get("cast_point")
    if isinstance(point, dict):
        x, y = relative_point_to_screen(point, bounds)
        x -= bounds.left
        y -= bounds.top
        draw.ellipse((x - 7, y - 7, x + 7, y + 7), outline=(255, 90, 90), width=3)
        draw.text((x + 9, y - 9), "CAST", fill=(255, 90, 90))
    image.save(image_path)

    payload = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "screen_client_bounds": {"left": bounds.left, "top": bounds.top,
                                "width": bounds.width, "height": bounds.height},
        "metrics": metrics,
        "config": cfg,
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return image_path
