from __future__ import annotations

import tkinter as tk
from tkinter import messagebox
from typing import Callable

from core.win32 import Rect


class SelectionOverlay:
    def __init__(self, root: tk.Tk, mode: str, desktop: Rect,
                 on_done: Callable, on_cancel: Callable):
        self.root = root
        self.mode = mode
        self.desktop = desktop
        self.on_done = on_done
        self.on_cancel = on_cancel
        self.start: tuple[int, int] | None = None
        self.shape = None

        prompts = {
            "cast_point": "คลิกจุดบนผิวน้ำที่ต้องการเหวี่ยงเบ็ด | Esc = ยกเลิก",
            "charge": "ลากกรอบครอบแท่งพลังแนวตั้งสีขาว/เหลืองให้ครบ | Esc = ยกเลิก",
            "slider": "ลากกรอบครอบราง Click & Hold รวมแท่งสีม่วงและบล็อกสว่าง | Esc = ยกเลิก",
            "progress": "ลากกรอบครอบแถบ Progress ด้านล่างทั้งเส้น | Esc = ยกเลิก",
        }
        self.win = tk.Toplevel(root)
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        try:
            self.win.attributes("-alpha", 0.28)
        except tk.TclError:
            pass
        self.win.geometry(f"{desktop.width}x{desktop.height}{desktop.left:+d}{desktop.top:+d}")
        self.canvas = tk.Canvas(self.win, bg="#101820", highlightthickness=0, cursor="crosshair")
        self.canvas.pack(fill="both", expand=True)
        self.canvas.create_text(24, 24, anchor="nw", text=prompts[mode], fill="white",
                                font=("Segoe UI", 14, "bold"))
        self.canvas.bind("<Button-1>", self._down)
        self.canvas.bind("<B1-Motion>", self._move)
        self.canvas.bind("<ButtonRelease-1>", self._up)
        self.win.bind("<Escape>", lambda _event: self._cancel())
        self.win.focus_force()

    def _coords(self, x_root: int, y_root: int) -> tuple[int, int]:
        return (x_root - self.desktop.left, y_root - self.desktop.top)

    def _down(self, event):
        point = (int(event.x_root), int(event.y_root))
        self.start = point
        if self.mode == "cast_point":
            self._finish(point)
        else:
            x, y = self._coords(*point)
            self.shape = self.canvas.create_rectangle(x, y, x, y, outline="#36e0a1", width=3)

    def _move(self, event):
        if self.mode == "cast_point" or self.start is None or self.shape is None:
            return
        x0, y0 = self._coords(*self.start)
        x1, y1 = self._coords(int(event.x_root), int(event.y_root))
        self.canvas.coords(self.shape, x0, y0, x1, y1)

    def _up(self, event):
        if self.mode == "cast_point" or self.start is None:
            return
        x0, y0 = self.start
        x1, y1 = int(event.x_root), int(event.y_root)
        rect = Rect(min(x0, x1), min(y0, y1), abs(x1 - x0), abs(y1 - y0))
        min_width, min_height = {
            "charge": (7, 35),
            "slider": (120, 26),
            "progress": (50, 7),
        }[self.mode]
        if rect.width < min_width or rect.height < min_height:
            messagebox.showwarning("พื้นที่เล็กเกินไป", "กรุณาลากกรอบให้ครอบแถบควบคุมทั้งหมด", parent=self.win)
            if self.shape is not None:
                self.canvas.delete(self.shape)
                self.shape = None
            self.start = None
            return
        self._finish(rect)

    def _finish(self, value):
        try:
            self.win.destroy()
        except tk.TclError:
            pass
        self.on_done(value)

    def _cancel(self):
        try:
            self.win.destroy()
        except tk.TclError:
            pass
        self.on_cancel()
