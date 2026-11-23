from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from collections import deque
from typing import Callable

import mss
import numpy as np

from .debug import save_debug_snapshot
from .input_win import MouseController
from .recovery import classify_failure, recovery_delay
from .vision import detect_charge, detect_control_bar, detect_fish_marker, detect_progress, fisch_should_hold
from .win32 import (
    Rect,
    client_rect,
    is_foreground,
    is_window,
    relative_point_to_screen,
    relative_rect_to_screen,
)


class StopRequested(RuntimeError):
    """Internal control-flow exception raised immediately after F7 is requested."""


class FishingEngine:
    """Worker-side state machine with safe pause, re-detection, and retry."""

    def __init__(
        self,
        hwnd: int,
        cfg: dict,
        stop_event: threading.Event,
        emit: Callable[[str, dict], None],
    ):
        self.hwnd = hwnd
        self.cfg = cfg
        self.settings = cfg["settings"]
        self.regions = cfg["regions"]
        self.stop_event = stop_event
        self.emit = emit
        self.mouse = MouseController()
        self.log = logging.getLogger("FishingAutoBotV5")
        self.last_focus_check = 0.0

    def _event(self, kind: str, **payload) -> None:
        try:
            self.emit(kind, payload)
        except Exception:
            pass

    def _check_active(self, force: bool = False) -> bool:
        if self.stop_event.is_set():
            raise StopRequested("ผู้ใช้สั่งหยุด")
        now = time.monotonic()
        if not force and now - self.last_focus_check < 0.30:
            return True
        self.last_focus_check = now
        if not is_window(self.hwnd):
            raise RuntimeError("หน้าต่าง Roblox ถูกปิด")
        if self.settings.get("stop_if_game_loses_focus", True) and not is_foreground(self.hwnd):
            raise RuntimeError("Roblox ไม่ได้อยู่หน้าสุด — พักจนกว่าจะกลับมาอยู่หน้าสุด")
        if client_rect(self.hwnd) is None:
            raise RuntimeError("หน้าต่าง Roblox ถูกย่อหรือยังไม่พร้อม — พักจนกว่าจะขยายเกม")
        return True

    def _bounds(self) -> Rect:
        if not is_window(self.hwnd):
            raise RuntimeError("หน้าต่าง Roblox ถูกปิด")
        bounds = client_rect(self.hwnd)
        if bounds is None:
            raise RuntimeError("หน้าต่าง Roblox ไม่พร้อมใช้งาน หรือถูกย่อ")
        return bounds

    @staticmethod
    def _grab(sct: mss.mss, rect: Rect) -> np.ndarray:
        shot = np.asarray(sct.grab(rect.as_mss()))
        return shot[:, :, [2, 1, 0]].copy()

    def _grab_roi(self, sct: mss.mss, key: str) -> tuple[np.ndarray, Rect]:
        region = self.regions.get(key)
        if not isinstance(region, dict):
            raise RuntimeError(f"ยังไม่ได้ตั้งค่าพื้นที่ {key}")
        rect = relative_rect_to_screen(region, self._bounds())
        return self._grab(sct, rect), rect

    def _interruptible_wait(self, seconds: float) -> bool:
        end = time.monotonic() + max(0.0, seconds)
        while time.monotonic() < end:
            if self.stop_event.wait(min(0.025, max(0.0, end - time.monotonic()))):
                return False
            self._check_active()
        return not self.stop_event.is_set()

    def _release(self) -> None:
        try:
            self.mouse.release()
        except Exception as exc:
            self.log.warning("mouse release error: %s", exc)

    def _wait_until_game_ready(self) -> bool:
        """Pause safely until Roblox is restored and foreground again; never steal focus."""
        if not bool(self.settings.get("wait_for_focus_recovery", True)):
            return False
        self._release()
        last_notice = 0.0
        self._event("phase", text="พักเพื่อความปลอดภัย — รอให้ Roblox กลับมาอยู่หน้าสุด")
        self._event("status", text="บอทพักชั่วคราวและปล่อยเมาส์แล้ว — ขยาย Roblox และคลิกกลับเข้าเกมเพื่อให้ทำงานต่อ")
        self.log.warning("paused: waiting for Roblox to be restored and foreground")
        while not self.stop_event.is_set():
            if not is_window(self.hwnd):
                self.log.error("Roblox window closed while waiting for focus")
                return False
            bounds = client_rect(self.hwnd)
            if bounds is not None and is_foreground(self.hwnd):
                self.last_focus_check = 0.0
                self._check_active(force=True)
                self.log.info("Roblox foreground restored; resuming with a UI rescan")
                self._event("phase", text="Roblox กลับมาแล้ว — กำลังตรวจสถานะก่อนทำต่อ")
                self._event("status", text="กลับมาทำงานต่อแล้ว — กำลังตรวจว่ามินิเกมเดิมยังเปิดอยู่หรือไม่")
                return True
            now = time.monotonic()
            if now - last_notice >= 5.0:
                self._event("phase", text="พักรอ Roblox — ขยายหน้าต่างและคลิกกลับเข้าเกม")
                last_notice = now
            if self.stop_event.wait(0.25):
                break
        return False

    def _save_recovery_snapshot(self, sct: mss.mss, reason: str, attempt: int) -> None:
        """Save a visual diagnostic occasionally so repeated faults can be tuned."""
        if attempt != 1 and attempt % 3 != 0:
            return
        try:
            bounds = self._bounds()
            crops: dict[str, np.ndarray] = {}
            metrics: dict = {"recovery_attempt": attempt, "recovery_reason": reason}
            charge_region = self.regions.get("charge")
            if isinstance(charge_region, dict):
                charge_rect = relative_rect_to_screen(charge_region, bounds)
                crops["charge"] = self._grab(sct, charge_rect)
                metrics["charge"] = detect_charge(crops["charge"])
            slider_region = self.regions.get("slider")
            if isinstance(slider_region, dict):
                slider_rect = relative_rect_to_screen(slider_region, bounds)
                crops["slider"] = self._grab(sct, slider_rect)
                bar = detect_control_bar(crops["slider"])
                fish = detect_fish_marker(crops["slider"])
                metrics["bar_center"] = bar[0] if bar else None
                metrics["bar_width"] = bar[1] if bar else None
                metrics["fish_x"] = fish[0] if fish else None
            progress_region = self.regions.get("progress")
            if isinstance(progress_region, dict):
                progress_rect = relative_rect_to_screen(progress_region, bounds)
                crops["progress"] = self._grab(sct, progress_rect)
                metrics["progress"] = detect_progress(crops["progress"])
            full = self._grab(sct, bounds)
            folder = Path(__file__).resolve().parents[1] / "debug"
            path = save_debug_snapshot(folder, self.cfg, bounds, metrics, crops, full)
            self.log.info("recovery debug snapshot saved: %s", path)
        except Exception as exc:
            self.log.warning("could not save recovery snapshot: %s", exc)

    def _recover_after_failure(self, sct: mss.mss, reason: str, attempt: int) -> bool:
        """Back off, release all input, and decide whether the worker may retry."""
        kind = classify_failure(reason)
        if self.stop_event.is_set() or kind == "stop":
            return False
        if kind == "fatal":
            self.log.error("non-recoverable configuration/window error: %s", reason)
            self._event("status", text=f"แก้ไขการตั้งค่าก่อนเริ่มใหม่: {reason}")
            return False
        if not bool(self.settings.get("recovery_enabled", True)):
            self.log.error("automatic recovery disabled; stopping: %s", reason)
            return False
        max_attempts = int(self.settings.get("recovery_max_attempts", 0))
        if max_attempts > 0 and attempt > max_attempts:
            self.log.error("recovery attempt limit reached (%s): %s", max_attempts, reason)
            self._event("status", text=f"ลองกู้คืนครบ {max_attempts} ครั้งแล้ว: {reason}")
            return False

        self._release()
        delay = recovery_delay(
            attempt,
            float(self.settings.get("recovery_initial_seconds", 2.5)),
            float(self.settings.get("recovery_max_seconds", 15.0)),
        )
        self.log.warning("recovery %s; attempt=%s; pause=%.1fs", reason, attempt, delay)
        self._event("phase", text=f"พบข้อผิดพลาด — พัก {delay:.1f} วินาที แล้วตรวจใหม่ (ครั้งที่ {attempt})")
        self._event("status", text=f"กำลังกู้คืนอัตโนมัติครั้งที่ {attempt}: {reason} — เมาส์ถูกปล่อยแล้ว")

        if kind == "focus":
            # Do not click or force-focus another app. Wait for the user to restore Roblox.
            if not self._wait_until_game_ready():
                return False
            self._save_recovery_snapshot(sct, reason, attempt)
            return True

        end = time.monotonic() + delay
        while time.monotonic() < end:
            if self.stop_event.wait(min(0.10, max(0.0, end - time.monotonic()))):
                return False
        if not is_window(self.hwnd):
            self.log.error("Roblox window disappeared during recovery")
            return False
        bounds = client_rect(self.hwnd)
        if bounds is None or not is_foreground(self.hwnd):
            return self._wait_until_game_ready()
        self.last_focus_check = 0.0
        self._save_recovery_snapshot(sct, reason, attempt)
        return True

    def _complete_round(self, rounds: int, message: str) -> int:
        rounds += 1
        self._event("round", count=rounds, message=message)
        pause = float(self.settings.get("between_cast_seconds", 1.6))
        self._event("phase", text=f"จบรอบที่ {rounds} — เตรียมเหวี่ยงเบ็ดรอบใหม่อัตโนมัติ")
        self.log.info("round %s complete; next auto-cast in %.2fs", rounds, pause)
        return rounds

    def run(self) -> str:
        rounds = 0
        recovery_attempt = 0
        started = time.monotonic()
        need_resync = False
        self.log.info("V5.3 Recovery worker started (hwnd=%s)", self.hwnd)
        max_minutes = float(self.settings.get("max_run_minutes", 0))
        try:
            with mss.mss() as sct:
                while not self.stop_event.is_set():
                    if max_minutes > 0 and time.monotonic() - started >= max_minutes * 60:
                        return f"ครบเวลาทำงาน {max_minutes:g} นาทีแล้ว"
                    try:
                        self._check_active(force=True)

                        # After a fault/focus pause, first look for an existing reel UI.
                        # This prevents an accidental second cast if the previous cast
                        # actually succeeded while the detector briefly lost the UI.
                        if need_resync:
                            probe = max(0.5, float(self.settings.get("recovery_reacquire_seconds", 8.0)))
                            self._event("phase", text="กำลังตรวจว่ามินิเกมเดิมยังเปิดอยู่หรือไม่")
                            found, _probe_message = self._wait_for_minigame(sct, timeout=probe)
                            need_resync = False
                            if found:
                                self.log.info("recovery resync: existing minigame found; resume reel")
                                success, message = self._play_minigame(sct)
                                if success:
                                    rounds = self._complete_round(rounds, message)
                                    recovery_attempt = 0
                                    if not self._interruptible_wait(float(self.settings.get("between_cast_seconds", 1.6))):
                                        break
                                    continue
                                if self.stop_event.is_set():
                                    break
                                recovery_attempt += 1
                                if not self._recover_after_failure(sct, message, recovery_attempt):
                                    if self.stop_event.is_set():
                                        break
                                    return f"หยุดหลังพยายามกู้คืน {recovery_attempt} ครั้ง: {message}"
                                need_resync = True
                                continue

                        success, message = self._charge_and_cast(sct)
                        if not success:
                            if self.stop_event.is_set():
                                break
                            recovery_attempt += 1
                            if not self._recover_after_failure(sct, message, recovery_attempt):
                                if self.stop_event.is_set():
                                    break
                                return f"หยุดหลังพยายามกู้คืน {recovery_attempt} ครั้ง: {message}"
                            need_resync = True
                            continue

                        success, message = self._wait_for_minigame(sct)
                        if not success:
                            if self.stop_event.is_set():
                                break
                            recovery_attempt += 1
                            if not self._recover_after_failure(sct, message, recovery_attempt):
                                if self.stop_event.is_set():
                                    break
                                return f"หยุดหลังพยายามกู้คืน {recovery_attempt} ครั้ง: {message}"
                            # Bite wait already consumed a full wait window. A short rescan
                            # catches a late UI without charging again immediately.
                            need_resync = True
                            continue

                        success, message = self._play_minigame(sct)
                        if not success:
                            if self.stop_event.is_set():
                                break
                            recovery_attempt += 1
                            if not self._recover_after_failure(sct, message, recovery_attempt):
                                if self.stop_event.is_set():
                                    break
                                return f"หยุดหลังพยายามกู้คืน {recovery_attempt} ครั้ง: {message}"
                            need_resync = True
                            continue

                        rounds = self._complete_round(rounds, message)
                        recovery_attempt = 0
                        if not self._interruptible_wait(float(self.settings.get("between_cast_seconds", 1.6))):
                            break

                    except StopRequested:
                        break
                    except Exception as exc:
                        if self.stop_event.is_set():
                            break
                        self.log.exception("engine cycle error")
                        reason = str(exc) or exc.__class__.__name__
                        recovery_attempt += 1
                        if not self._recover_after_failure(sct, reason, recovery_attempt):
                            if self.stop_event.is_set():
                                break
                            return f"หยุดหลังพยายามกู้คืน {recovery_attempt} ครั้ง: {reason}"
                        need_resync = True
        except Exception as exc:
            self.log.exception("engine fatal error")
            return f"ข้อผิดพลาดร้ายแรงของระบบ: {exc}"
        finally:
            self._release()
        return f"ผู้ใช้สั่งหยุด — สำเร็จ {rounds} รอบ"

    def _charge_and_cast(self, sct: mss.mss) -> tuple[bool, str]:
        point = self.regions.get("cast_point")
        if not isinstance(point, dict):
            return False, "ยังไม่ได้ตั้งค่าจุดเหวี่ยงเบ็ด"
        cast_x, cast_y = relative_point_to_screen(point, self._bounds())
        target = float(self.settings.get("charge_target", 0.94))
        timeout = float(self.settings.get("charge_timeout", 8.0))
        grace = float(self.settings.get("charge_detect_grace", 0.9))
        stale_limit = float(self.settings.get("charge_stale_seconds", 1.4))
        allow_fallback = bool(self.settings.get("use_timed_fallback", False))
        fallback = float(self.settings.get("charge_fallback_seconds", 1.5))
        poll = float(self.settings.get("poll_interval", 0.035))

        self._event("phase", text="ชาร์จพลัง — กำลังกดเมาส์ค้าง")
        self._check_active(force=True)
        self.mouse.move(cast_x, cast_y)
        time.sleep(0.06)
        self.mouse.down()
        t0 = time.monotonic()
        last_change = t0
        last_value: float | None = None
        values: deque[float] = deque(maxlen=5)
        last_ui = 0.0
        stable_at_target = 0
        try:
            while not self.stop_event.is_set():
                self._check_active()
                now = time.monotonic()
                elapsed = now - t0
                if elapsed >= timeout:
                    return False, "ชาร์จเกินเวลาสูงสุด — ปล่อยเมาส์และลองกู้คืน"
                frame, _rect = self._grab_roi(sct, "charge")
                value = detect_charge(frame)
                if value is not None:
                    values.append(value)
                    smooth = float(np.median(np.asarray(values)))
                    self._event("metrics", charge=smooth)
                    if last_value is None or abs(smooth - last_value) >= 0.004:
                        last_change = now
                    last_value = smooth
                    if smooth >= target and elapsed >= 0.18:
                        stable_at_target += 1
                    else:
                        stable_at_target = 0
                    if stable_at_target >= 2:
                        self._event("phase", text=f"พลังถึง {smooth * 100:.1f}% — ปล่อยเหวี่ยงเบ็ด")
                        self.log.info("charge threshold reached %.3f after %.2fs", smooth, elapsed)
                        self._release()
                        return True, "เหวี่ยงเบ็ดแล้ว"
                    if elapsed >= grace and now - last_change >= stale_limit:
                        if allow_fallback and elapsed >= fallback:
                            self.log.warning("charge meter stale; timed fallback at %.2fs", elapsed)
                            self._release()
                            return True, "แถบพลังไม่ขยับ — ปล่อยตามเวลาสำรอง"
                        if not allow_fallback:
                            return False, "แถบพลังไม่ขยับ — พักแล้วตรวจจับใหม่"
                else:
                    self._event("metrics", charge=None)
                    if elapsed >= grace:
                        if allow_fallback and elapsed >= fallback:
                            self.log.warning("charge meter unreadable; timed fallback at %.2fs", elapsed)
                            self._release()
                            return True, "อ่านแถบพลังไม่ได้ — ปล่อยตามเวลาสำรอง"
                        if not allow_fallback:
                            return False, "ไม่พบแถบพลังในพื้นที่ B — พักแล้วตรวจจับใหม่"
                if now - last_ui > 0.5:
                    self._event("phase", text="กำลังอ่านแถบพลัง")
                    last_ui = now
                time.sleep(max(0.02, poll))
        finally:
            self._release()
        return False, "ถูกหยุดระหว่างชาร์จ"

    def _wait_for_minigame(self, sct: mss.mss, timeout: float | None = None) -> tuple[bool, str]:
        timeout = float(timeout if timeout is not None else self.settings.get("bite_wait_seconds", 45.0))
        poll = max(0.04, float(self.settings.get("poll_interval", 0.035)))
        started = time.monotonic()
        stable_frames = 0
        self._event("phase", text="รอปลา / รอมินิเกมแบบ Fisch")
        while not self.stop_event.is_set() and time.monotonic() - started < timeout:
            self._check_active()
            slider, _ = self._grab_roi(sct, "slider")
            progress, _ = self._grab_roi(sct, "progress")
            control_bar = detect_control_bar(slider)
            fish_marker = detect_fish_marker(slider)
            progress_value = detect_progress(progress)
            if control_bar is not None and fish_marker is not None:
                stable_frames += 1
                self._event(
                    "metrics",
                    bar_center=control_bar[0],
                    bar_width=control_bar[1],
                    fish_x=fish_marker[0],
                    progress=progress_value,
                )
                if stable_frames >= 2:
                    self.log.info(
                        "Fisch-style minigame detected; control_bar center=%.1f width=%.1f fish=%.1f",
                        control_bar[0], control_bar[1], fish_marker[0],
                    )
                    return True, "พบแถบควบคุมและตัวบอกตำแหน่งปลา"
            else:
                stable_frames = 0
            time.sleep(poll * 2)
        if self.stop_event.is_set():
            return False, "ผู้ใช้สั่งหยุดขณะรอมินิเกม"
        return False, "ไม่พบแถบควบคุม/ตัวบอกตำแหน่งปลา — ตรวจพื้นที่ C และจะลองใหม่อัตโนมัติ"

    def _play_minigame(self, sct: mss.mss) -> tuple[bool, str]:
        """Play the reel minigame using Fisch's hold-right / release-left model."""
        finish = float(self.settings.get("minigame_finish", 0.985))
        timeout = float(self.settings.get("minigame_timeout", 120.0))
        poll = max(0.02, float(self.settings.get("poll_interval", 0.035)))
        lookahead = max(0.0, float(self.settings.get("tracking_lookahead_seconds", 0.10)))
        deadband_ratio = float(self.settings.get("tracking_deadband_ratio", 0.10))
        bar_lost_limit = float(self.settings.get("bar_lost_seconds", 1.5))
        fish_lost_limit = float(self.settings.get("fish_lost_seconds", 1.5))
        disappear_progress = float(self.settings.get("minigame_disappear_success_progress", 0.78))
        disappear_confirm = float(self.settings.get("minigame_disappear_confirm_seconds", 0.55))

        slider, slider_rect = self._grab_roi(sct, "slider")
        control_bar = detect_control_bar(slider)
        fish_marker = detect_fish_marker(slider)
        if control_bar is None or fish_marker is None:
            return False, "ไม่พบแถบควบคุมสีขาวหรือตัวบอกตำแหน่งปลา — ตรวจพื้นที่ C"

        cursor_x = float(slider_rect.left) + control_bar[0]
        cursor_y = float(slider_rect.top) + fish_marker[1]
        self._check_active(force=True)
        self._release()
        self.mouse.move(round(cursor_x), round(cursor_y))
        self._event("phase", text="มินิเกมแบบ Fisch — กดค้างให้แถบขาวไปขวา / ปล่อยให้กลับซ้าย")

        started = time.monotonic()
        last_bar_seen = started
        last_fish_seen = started
        previous_fish_x: float | None = None
        previous_time = started
        fish_velocity = 0.0
        last_ui = 0.0
        complete_frames = 0
        last_progress: float | None = None
        progress_high_water = 0.0
        both_missing_since: float | None = None
        current_held = False
        last_inside: bool | None = None
        try:
            while not self.stop_event.is_set():
                self._check_active()
                now = time.monotonic()
                if now - started >= timeout:
                    return False, "มินิเกมเกินเวลาสูงสุด — พักแล้วตรวจใหม่"

                slider, slider_rect = self._grab_roi(sct, "slider")
                progress_frame, _ = self._grab_roi(sct, "progress")
                control_bar = detect_control_bar(slider)
                fish_marker = detect_fish_marker(slider)
                progress = detect_progress(progress_frame)

                if progress is not None:
                    last_progress = progress
                    progress_high_water = max(progress_high_water, progress)
                    if progress >= finish:
                        complete_frames += 1
                    else:
                        complete_frames = 0
                else:
                    complete_frames = 0

                bar_center = control_bar[0] if control_bar else None
                bar_width = control_bar[1] if control_bar else None
                fish_x = fish_marker[0] if fish_marker else None
                fish_inside = None
                if control_bar is not None and fish_marker is not None:
                    half = control_bar[1] / 2.0
                    fish_inside = (control_bar[0] - half <= fish_marker[0] <= control_bar[0] + half)

                self._event(
                    "metrics",
                    bar_center=bar_center,
                    bar_width=bar_width,
                    fish_x=fish_x,
                    fish_inside=fish_inside,
                    progress=progress,
                )

                if complete_frames >= 2:
                    self.log.info("minigame complete by progress %.3f", last_progress or 0.0)
                    self._release()
                    self._event("phase", text=f"จับปลาแล้ว — Progress {((last_progress or 0.0) * 100):.1f}%")
                    return True, f"จับปลาสำเร็จ {((last_progress or 0.0) * 100):.1f}%"

                reel_objects_missing = control_bar is None and fish_marker is None
                fish_and_progress_missing = fish_marker is None and progress is None
                completion_transition = progress_high_water >= disappear_progress and fish_and_progress_missing
                if reel_objects_missing or completion_transition:
                    if both_missing_since is None:
                        both_missing_since = now
                    absent_for = now - both_missing_since
                    if progress is not None:
                        if absent_for >= max(bar_lost_limit, fish_lost_limit):
                            return False, "ไม่พบรางและตัวบอกปลา แต่ Progress ยังแสดงอยู่ — พักแล้วตรวจใหม่"
                        time.sleep(poll)
                        continue
                    if progress_high_water >= disappear_progress and absent_for <= poll * 2.0:
                        self._release()
                        current_held = False
                        self.log.info("reel UI completion transition detected; progress_high_water=%.3f", progress_high_water)
                    if absent_for >= disappear_confirm:
                        if progress_high_water >= disappear_progress:
                            self._release()
                            current_held = False
                            self._event("phase", text=f"จับปลาแล้ว ({progress_high_water * 100:.1f}%) — เริ่มรอบใหม่อัตโนมัติ")
                            return True, f"มินิเกมจบแล้ว {progress_high_water * 100:.1f}%"
                        if absent_for >= max(bar_lost_limit, fish_lost_limit):
                            return False, "หน้ามินิเกมหายไปก่อน Progress ถึงระดับยืนยัน — พัก ตรวจสถานะ แล้วลองใหม่"
                    if now - last_ui >= 1.0:
                        self.log.info("reel UI absent; progress_high_water=%.3f absent_for=%.2fs", progress_high_water, absent_for)
                        last_ui = now
                    time.sleep(poll)
                    continue
                else:
                    both_missing_since = None

                if control_bar is None:
                    if now - last_bar_seen > bar_lost_limit:
                        return False, "ตรวจไม่พบแถบควบคุมสีขาวต่อเนื่อง — พักแล้วตรวจใหม่"
                    time.sleep(poll)
                    continue
                last_bar_seen = now

                if fish_marker is None:
                    if now - last_fish_seen > fish_lost_limit:
                        return False, "ตรวจไม่พบเส้นบอกตำแหน่งปลาต่อเนื่อง — พักแล้วตรวจใหม่"
                    time.sleep(poll)
                    continue
                last_fish_seen = now

                fish_x_now = float(fish_marker[0])
                if previous_fish_x is not None:
                    dt = max(0.001, now - previous_time)
                    raw_velocity = (fish_x_now - previous_fish_x) / dt
                    raw_velocity = float(np.clip(raw_velocity, -1100.0, 1100.0))
                    fish_velocity = 0.60 * fish_velocity + 0.40 * raw_velocity
                prediction_px = float(np.clip(fish_velocity * lookahead, -42.0, 42.0))
                previous_fish_x = fish_x_now
                previous_time = now

                desired_held = fisch_should_hold(
                    fish_x_now,
                    float(control_bar[0]),
                    float(control_bar[1]),
                    current_held,
                    prediction_px=prediction_px,
                    deadband_ratio=deadband_ratio,
                )
                if desired_held != current_held:
                    self._check_active(force=True)
                    if desired_held:
                        self.mouse.down()
                        self.log.debug("Fisch reel input: HOLD (push bar right)")
                    else:
                        self.mouse.release()
                        self.log.debug("Fisch reel input: RELEASE (let bar move left)")
                    current_held = desired_held

                if fish_inside is not None:
                    if last_inside is not None and fish_inside != last_inside:
                        self.log.debug("fish entered control bar: %s", fish_inside)
                    last_inside = fish_inside

                if now - last_ui >= 0.8:
                    self.log.info(
                        "Fisch reel bar=%.1f width=%.1f fish=%.1f predicted=%.1f input=%s inside=%s progress=%s high_water=%.3f",
                        control_bar[0], control_bar[1], fish_x_now, fish_x_now + prediction_px,
                        "HOLD" if current_held else "RELEASE", fish_inside, progress, progress_high_water,
                    )
                    self._event(
                        "phase",
                        text=("กำลังตามปลาแบบ Fisch — " + ("กดค้าง/เลื่อนไปขวา" if current_held else "ปล่อย/เลื่อนไปซ้าย")
                              + (" — ปลาอยู่ในแถบ" if fish_inside else " — กำลังปรับตำแหน่ง")),
                    )
                    last_ui = now
                time.sleep(poll)
        finally:
            self._release()
        return False, "ผู้ใช้สั่งหยุดระหว่างมินิเกม"
