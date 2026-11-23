from __future__ import annotations

import ctypes
from ctypes import wintypes

user32 = ctypes.windll.user32

INPUT_MOUSE = 0
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
ULONG_PTR = wintypes.WPARAM


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class INPUT_UNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("u", INPUT_UNION)]


user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
user32.SetCursorPos.restype = wintypes.BOOL
user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
user32.SendInput.restype = wintypes.UINT


class MouseController:
    def __init__(self):
        self.is_down = False

    @staticmethod
    def move(x: int, y: int) -> None:
        if not user32.SetCursorPos(int(x), int(y)):
            raise ctypes.WinError()

    @staticmethod
    def _send(flags: int) -> None:
        mouse = MOUSEINPUT(0, 0, 0, flags, 0, ULONG_PTR(0))
        packet = INPUT(INPUT_MOUSE, INPUT_UNION(mi=mouse))
        sent = user32.SendInput(1, ctypes.byref(packet), ctypes.sizeof(INPUT))
        if sent != 1:
            raise ctypes.WinError()

    def down(self) -> None:
        if not self.is_down:
            self._send(MOUSEEVENTF_LEFTDOWN)
            self.is_down = True

    def up(self) -> None:
        # Always send UP, even if local state is uncertain, as a safety release.
        try:
            self._send(MOUSEEVENTF_LEFTUP)
        finally:
            self.is_down = False

    def release(self) -> None:
        self.up()
