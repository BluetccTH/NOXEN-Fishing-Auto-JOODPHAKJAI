from __future__ import annotations

import ctypes
import time
from ctypes import wintypes
from dataclasses import dataclass

if __import__("sys").platform != "win32":
    raise RuntimeError("[ NOXEN ] - Fishing Auto JOODPHAKJAI รองรับ Windows 10/11 เท่านั้น")

user32 = ctypes.windll.user32


def enable_dpi_awareness() -> None:
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # per-monitor DPI aware
    except Exception:
        try:
            user32.SetProcessDPIAware()
        except Exception:
            pass


@dataclass(frozen=True)
class Rect:
    left: int
    top: int
    width: int
    height: int

    @property
    def right(self) -> int:
        return self.left + self.width

    @property
    def bottom(self) -> int:
        return self.top + self.height

    def as_mss(self) -> dict[str, int]:
        return {"left": self.left, "top": self.top, "width": self.width, "height": self.height}


class POINT(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


class RECT(ctypes.Structure):
    _fields_ = [("left", wintypes.LONG), ("top", wintypes.LONG), ("right", wintypes.LONG), ("bottom", wintypes.LONG)]


EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

# Declare Win32 signatures explicitly so HWND pointers are not truncated on 64-bit Windows.
user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
user32.GetWindowTextLengthW.restype = ctypes.c_int
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetWindowTextW.restype = ctypes.c_int
user32.IsWindow.argtypes = [wintypes.HWND]
user32.IsWindow.restype = wintypes.BOOL
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.IsWindowVisible.restype = wintypes.BOOL
user32.IsIconic.argtypes = [wintypes.HWND]
user32.IsIconic.restype = wintypes.BOOL
user32.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(RECT)]
user32.GetClientRect.restype = wintypes.BOOL
user32.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(POINT)]
user32.ClientToScreen.restype = wintypes.BOOL
user32.GetForegroundWindow.restype = wintypes.HWND
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.ShowWindow.restype = wintypes.BOOL
user32.BringWindowToTop.argtypes = [wintypes.HWND]
user32.BringWindowToTop.restype = wintypes.BOOL
user32.SetForegroundWindow.argtypes = [wintypes.HWND]
user32.SetForegroundWindow.restype = wintypes.BOOL
user32.EnumWindows.argtypes = [EnumWindowsProc, wintypes.LPARAM]
user32.EnumWindows.restype = wintypes.BOOL
user32.GetSystemMetrics.argtypes = [ctypes.c_int]
user32.GetSystemMetrics.restype = ctypes.c_int


def window_title(hwnd: int) -> str:
    length = user32.GetWindowTextLengthW(hwnd)
    if length <= 0:
        return ""
    buffer = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buffer, length + 1)
    return buffer.value


def find_roblox_window() -> tuple[int | None, str | None]:
    candidates: list[tuple[int, str]] = []

    def callback(hwnd: int, _param: int) -> bool:
        if not user32.IsWindowVisible(hwnd) or user32.IsIconic(hwnd):
            return True
        title = window_title(hwnd)
        if title and "roblox" in title.casefold():
            candidates.append((int(hwnd), title))
        return True

    callback_ref = EnumWindowsProc(callback)
    user32.EnumWindows(callback_ref, 0)
    if not candidates:
        return None, None
    candidates.sort(key=lambda entry: (entry[1].casefold() != "roblox", len(entry[1])))
    return candidates[0]


def client_rect(hwnd: int) -> Rect | None:
    rect = RECT()
    if not user32.GetClientRect(hwnd, ctypes.byref(rect)):
        return None
    origin = POINT(0, 0)
    if not user32.ClientToScreen(hwnd, ctypes.byref(origin)):
        return None
    width = int(rect.right - rect.left)
    height = int(rect.bottom - rect.top)
    if width < 100 or height < 100:
        return None
    return Rect(int(origin.x), int(origin.y), width, height)


def virtual_desktop_rect() -> Rect:
    # SM_X/Y/CX/CYVIRTUALSCREEN; handles monitors placed left/up of primary.
    x = int(user32.GetSystemMetrics(76))
    y = int(user32.GetSystemMetrics(77))
    w = int(user32.GetSystemMetrics(78))
    h = int(user32.GetSystemMetrics(79))
    if w <= 0 or h <= 0:
        return Rect(0, 0, int(user32.GetSystemMetrics(0)), int(user32.GetSystemMetrics(1)))
    return Rect(x, y, w, h)


def focus_window(hwnd: int) -> tuple[bool, str]:
    if not user32.IsWindow(hwnd):
        return False, "หน้าต่าง Roblox ไม่อยู่แล้ว"
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE
        time.sleep(0.25)
    user32.BringWindowToTop(hwnd)
    user32.SetForegroundWindow(hwnd)
    time.sleep(0.25)
    foreground = int(user32.GetForegroundWindow())
    if foreground != int(hwnd):
        return False, f"โฟกัส Roblox ไม่สำเร็จ (หน้าต่างด้านหน้า: {window_title(foreground) or 'ไม่ทราบชื่อ'})"
    return True, window_title(hwnd) or "Roblox"


def is_window(hwnd: int) -> bool:
    """Return whether the HWND still exists (minimized windows still exist)."""
    return bool(user32.IsWindow(hwnd))


def is_foreground(hwnd: int) -> bool:
    return int(user32.GetForegroundWindow()) == int(hwnd)


def screen_to_relative_point(point: tuple[int, int], bounds: Rect) -> dict[str, float]:
    x, y = point
    if not (bounds.left <= x < bounds.right and bounds.top <= y < bounds.bottom):
        raise ValueError("จุดที่เลือกอยู่นอกพื้นที่หน้าต่าง Roblox")
    return {"x": (x - bounds.left) / bounds.width, "y": (y - bounds.top) / bounds.height}


def screen_to_relative_rect(rect: Rect, bounds: Rect) -> dict[str, float]:
    if rect.width <= 0 or rect.height <= 0:
        raise ValueError("กรอบพื้นที่ไม่ถูกต้อง")
    if rect.left < bounds.left or rect.top < bounds.top or rect.right > bounds.right or rect.bottom > bounds.bottom:
        raise ValueError("กรอบที่เลือกต้องอยู่ภายในพื้นที่เกม Roblox ทั้งหมด")
    return {
        "x": (rect.left - bounds.left) / bounds.width,
        "y": (rect.top - bounds.top) / bounds.height,
        "w": rect.width / bounds.width,
        "h": rect.height / bounds.height,
    }


def relative_point_to_screen(point: dict, bounds: Rect) -> tuple[int, int]:
    return (round(bounds.left + float(point["x"]) * bounds.width),
            round(bounds.top + float(point["y"]) * bounds.height))


def relative_rect_to_screen(rect: dict, bounds: Rect) -> Rect:
    x = round(bounds.left + float(rect["x"]) * bounds.width)
    y = round(bounds.top + float(rect["y"]) * bounds.height)
    w = max(1, round(float(rect["w"]) * bounds.width))
    h = max(1, round(float(rect["h"]) * bounds.height))
    return Rect(x, y, w, h)
