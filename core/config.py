from __future__ import annotations

import json
import os
from copy import deepcopy
from pathlib import Path
from typing import Any

TRACKING_FPS_OPTIONS = (30, 60, 90, 120)


def tracking_interval(fps: int | float | str) -> float:
    """Return the target frame interval for a supported Tracking FPS."""
    try:
        numeric = float(fps)
    except (TypeError, ValueError) as exc:
        raise ValueError("Tracking FPS ต้องเป็น 30, 60, 90 หรือ 120") from exc
    if not numeric.is_integer() or int(numeric) not in TRACKING_FPS_OPTIONS:
        raise ValueError("Tracking FPS ต้องเป็น 30, 60, 90 หรือ 120")
    return 1.0 / int(numeric)


DEFAULT_CONFIG: dict[str, Any] = {
    "version": 5,
    "regions": {
        "cast_point": None,
        "charge": None,
        "slider": None,
        "progress": None,
    },
    "settings": {
        "charge_target": 0.94,
        "charge_timeout": 8.0,
        "charge_detect_grace": 0.9,
        "charge_stale_seconds": 1.4,
        "use_timed_fallback": False,
        "charge_fallback_seconds": 1.5,
        "bite_wait_seconds": 45.0,
        "minigame_finish": 0.985,
        "minigame_timeout": 120.0,
        "target_lost_seconds": 1.5,  # legacy V5 setting
        "handle_lost_seconds": 1.5,  # legacy V5 setting
        "bar_lost_seconds": 1.5,
        "fish_lost_seconds": 1.5,
        "tracking_lookahead_seconds": 0.10,
        "tracking_deadband_ratio": 0.10,
        "tracking_edge_guard_ratio": 0.78,
        "tracking_fps": 120,
        "tracking_auto_scale": True,
        "progress_poll_interval": 0.05,
        "minigame_disappear_success_progress": 0.78,
        "minigame_disappear_confirm_seconds": 0.55,
        "poll_interval": 0.035,
        "max_cursor_step": 42,
        "lookahead_seconds": 0.075,
        "repeat_fishing": True,
        "between_cast_seconds": 1.6,
        "max_run_minutes": 0,
        "auto_focus_roblox": True,
        "stop_if_game_loses_focus": True,
        "recovery_enabled": True,
        "recovery_initial_seconds": 2.5,
        "recovery_max_seconds": 15.0,
        "recovery_max_attempts": 0,
        "recovery_reacquire_seconds": 8.0,
        "wait_for_focus_recovery": True,
    },
}


def _merge(base: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(base)
    for key, value in incoming.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _merge(result[key], value)
        else:
            result[key] = value
    return result


class ConfigStore:
    def __init__(self, folder: Path):
        self.folder = folder
        self.path = folder / "fishing_auto_config_v5.json"
        self.data = deepcopy(DEFAULT_CONFIG)

    def load(self) -> dict[str, Any]:
        self.folder.mkdir(parents=True, exist_ok=True)
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                self.data = _merge(DEFAULT_CONFIG, raw)
        except FileNotFoundError:
            pass
        except Exception as exc:
            # Keep defaults intact; the UI will still open so the user can repair settings.
            self.data = deepcopy(DEFAULT_CONFIG)
            self.data["_load_error"] = str(exc)
        # V5.0 shipped with a 30-minute default. Treat that old default as
        # "unlimited" in this update; an explicit non-default value is kept.
        try:
            if float(self.data["settings"].get("max_run_minutes", 0)) == 30.0:
                self.data["settings"]["max_run_minutes"] = 0
        except (TypeError, ValueError):
            self.data["settings"]["max_run_minutes"] = 0
        self.data["settings"]["repeat_fishing"] = True
        self.data["version"] = 5
        return self.data

    def save(self, data: dict[str, Any] | None = None) -> None:
        if data is not None:
            self.data = data
        self.folder.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(".tmp")
        temp.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temp, self.path)
