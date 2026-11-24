from __future__ import annotations

import logging
import os
import json
import queue
import sys
import threading
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

import mss
from PIL import Image, ImageTk

from core.config import ConfigStore, DEFAULT_CONFIG, TRACKING_FPS_OPTIONS, _merge
from core.debug import save_debug_snapshot, test_vision
from core.engine import FishingEngine
from core.input_win import MouseController
from core.win32 import (
    Rect,
    client_rect,
    enable_dpi_awareness,
    find_roblox_window,
    focus_window,
    screen_to_relative_point,
    screen_to_relative_rect,
    virtual_desktop_rect,
)
from ui.overlay import SelectionOverlay

APP_VERSION = "V5.5"
APP_DIR = Path(__file__).resolve().parent
DEBUG_DIR = APP_DIR / "debug"
LOG_DIR = APP_DIR / "logs"
LOG_PATH = LOG_DIR / "fishing_auto_v5_5.log"


def setup_logging() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("FishingAutoBotV5")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        handler = RotatingFileHandler(LOG_PATH, maxBytes=1_500_000, backupCount=3, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
        logger.addHandler(handler)


class FishingAutoBotV5:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.store = ConfigStore(APP_DIR)
        self.cfg = self.store.load()
        self.events: queue.Queue[tuple[str, dict]] = queue.Queue()
        self.stop_event = threading.Event()
        self.worker: threading.Thread | None = None
        self.running = False
        self.hwnd: int | None = None
        self.game_title = ""
        self.overlay: SelectionOverlay | None = None
        self.hotkey_available = False
        self._preview_refs = []

        self.status_var = tk.StringVar(value="พร้อม — ตรวจจับหน้าต่าง Roblox อัตโนมัติ")
        self.phase_var = tk.StringVar(value="สถานะ: รอเริ่ม")
        self.game_var = tk.StringVar(value="Roblox: ยังไม่ได้ตรวจพบ")
        self.charge_var = tk.StringVar(value="Charge: --")
        self.target_var = tk.StringVar(value="แถบควบคุม: --")
        self.handle_var = tk.StringVar(value="ตำแหน่งปลา: --")
        self.progress_var = tk.StringVar(value="Progress: --")
        self.tracking_fps_status_var = tk.StringVar(value="Tracking: -- FPS")
        self.tracking_latency_status_var = tk.StringVar(value="Frame: -- ms")
        self.round_var = tk.StringVar(value="สำเร็จ 0 รอบ")
        self.calibration_vars = {
            "cast_point": tk.StringVar(),
            "charge": tk.StringVar(),
            "slider": tk.StringVar(),
            "progress": tk.StringVar(),
        }
        self.charge_target_var = tk.StringVar(value="94")
        self.finish_var = tk.StringVar(value="98.5")
        self.fallback_enabled_var = tk.BooleanVar(value=False)
        self.fallback_var = tk.StringVar(value="1.5")
        self.charge_timeout_var = tk.StringVar(value="8")
        self.bite_wait_var = tk.StringVar(value="45")
        self.minigame_timeout_var = tk.StringVar(value="120")
        self.deadband_var = tk.StringVar(value="78")
        self.lookahead_var = tk.StringVar(value="0.10")
        self.poll_var = tk.StringVar(value="35")
        self.tracking_fps_var = tk.StringVar(value="120")
        self.tracking_auto_scale_var = tk.BooleanVar(value=True)
        self.recovery_enabled_var = tk.BooleanVar(value=True)
        self.wait_for_focus_var = tk.BooleanVar(value=True)
        self.recovery_initial_var = tk.StringVar(value="2.5")
        self.recovery_max_var = tk.StringVar(value="15")

        self._apply_dark_theme()
        self._build_ui()
        self._sync_form_from_config()
        self._refresh_calibration_labels()
        self._install_hotkeys()
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.after(60, self._drain_events)
        self.root.after(1000, self._refresh_game_status)

    # ------------------------------- UI ----------------------------------
    def _apply_dark_theme(self) -> None:
        """Apply a consistent dark NOXEN theme to all ttk controls."""
        colors = {
            "bg": "#0b1020",
            "surface": "#111a2b",
            "surface_alt": "#172338",
            "panel": "#131f33",
            "input": "#0a1425",
            "border": "#2a3a54",
            "text": "#e8eef8",
            "muted": "#91a1b8",
            "accent": "#48dfc1",
            "accent_hover": "#70f0d5",
            "danger": "#fb7185",
            "danger_hover": "#fda4af",
            "warning": "#fbbf24",
        }
        self.colors = colors
        self.root.configure(background=colors["bg"])
        self.root.option_add("*Font", ("Segoe UI", 9))
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        style.configure(".", background=colors["bg"], foreground=colors["text"],
                        font=("Segoe UI", 9), bordercolor=colors["border"],
                        lightcolor=colors["border"], darkcolor=colors["border"])
        style.configure("TFrame", background=colors["surface"])
        style.configure("TLabel", background=colors["surface"], foreground=colors["text"],
                        font=("Segoe UI", 9))
        style.configure("Title.TLabel", background=colors["surface"], foreground=colors["text"],
                        font=("Segoe UI Semibold", 17, "bold"))
        style.configure("Brand.TLabel", background=colors["surface"], foreground=colors["accent"],
                        font=("Segoe UI Semibold", 17, "bold"))
        style.configure("BrandName.TLabel", background=colors["surface"], foreground=colors["text"],
                        font=("Segoe UI Semibold", 15, "bold"))
        style.configure("Subtitle.TLabel", background=colors["surface"], foreground=colors["muted"],
                        font=("Segoe UI", 8))
        style.configure("Muted.TLabel", background=colors["surface"], foreground=colors["muted"])
        style.configure("Success.TLabel", background=colors["surface"], foreground=colors["accent"])
        style.configure("Warning.TLabel", background=colors["surface"], foreground=colors["warning"])
        style.configure("Status.TLabel", background=colors["surface_alt"], foreground=colors["accent"],
                        padding=(8, 4), font=("Segoe UI", 8, "bold"))
        style.configure("TLabelframe", background=colors["surface"], foreground=colors["text"],
                        bordercolor=colors["border"], lightcolor=colors["border"],
                        darkcolor=colors["border"], relief="solid", borderwidth=1,
                        padding=8)
        style.configure("TLabelframe.Label", background=colors["surface"],
                        foreground=colors["accent"], font=("Segoe UI Semibold", 9, "bold"))
        style.configure("Version.TLabel", background=colors["surface_alt"], foreground=colors["accent"], padding=(9, 4), font=("Segoe UI", 8, "bold"))
        style.configure("TNotebook", background=colors["bg"], borderwidth=0,
                        tabmargins=(2, 5, 2, 0))
        style.configure("TNotebook.Tab", background=colors["surface_alt"],
                        foreground=colors["muted"], padding=(14, 7),
                        font=("Segoe UI", 8, "bold"), borderwidth=0)
        style.map("TNotebook.Tab",
                  background=[("selected", colors["panel"]), ("active", colors["surface"])],
                  foreground=[("selected", colors["accent"]), ("active", colors["text"])])
        style.configure("TEntry", fieldbackground=colors["input"], foreground=colors["text"],
                        insertcolor=colors["text"], bordercolor=colors["border"],
                        lightcolor=colors["border"], darkcolor=colors["border"],
                        padding=(7, 4), relief="flat")
        style.map("TEntry", fieldbackground=[("focus", "#101d32")],
                  bordercolor=[("focus", colors["accent"])])
        style.configure("TButton", background=colors["surface_alt"], foreground=colors["text"],
                        bordercolor=colors["border"], lightcolor=colors["border"],
                        darkcolor=colors["border"], padding=(10, 6),
                        font=("Segoe UI", 9, "bold"), relief="flat")
        style.map("TButton",
                  background=[("disabled", "#182235"), ("pressed", colors["panel"]),
                              ("active", "#22334e")],
                  foreground=[("disabled", "#65758d"), ("active", colors["accent"])],
                  bordercolor=[("focus", colors["accent"])])
        style.configure("Primary.TButton", background="#147d70", foreground="#f4fffc",
                        bordercolor="#249e8d", padding=(11, 8),
                        font=("Segoe UI Semibold", 10, "bold"))
        style.map("Primary.TButton", background=[("disabled", "#243a48"),
                                                  ("pressed", "#0c655b"),
                                                  ("active", "#199887")],
                  foreground=[("disabled", "#8195a5"), ("active", "#ffffff")])
        style.configure("Danger.TButton", background="#572638", foreground="#ffdce3",
                        bordercolor="#8c3b55", padding=(11, 8),
                        font=("Segoe UI Semibold", 10, "bold"))
        style.map("Danger.TButton", background=[("disabled", "#252333"),
                                                 ("pressed", "#66263c"),
                                                 ("active", "#783149")],
                  foreground=[("disabled", "#7d7888"), ("active", "#ffffff")])
        style.configure("TCheckbutton", background=colors["surface"], foreground=colors["text"],
                        padding=(2, 4), font=("Segoe UI", 9))
        style.map("TCheckbutton", background=[("active", colors["surface"])],
                  foreground=[("active", colors["accent"])],
                  indicatorcolor=[("selected", colors["accent"]), ("!selected", colors["input"])])
        style.configure("TSeparator", background=colors["border"])

    def _make_scrollable_tab(self, tab: ttk.Frame) -> ttk.Frame:
        """Create a compact tab page that remains usable on smaller screens."""
        shell = ttk.Frame(tab)
        shell.pack(fill="both", expand=True)

        canvas = tk.Canvas(shell, background=self.colors["surface"], highlightthickness=0, bd=0)
        scrollbar = ttk.Scrollbar(shell, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        content = ttk.Frame(canvas, padding=9)
        window_id = canvas.create_window((0, 0), window=content, anchor="nw")
        content.bind(
            "<Configure>",
            lambda _event: canvas.configure(scrollregion=canvas.bbox("all")),
        )
        canvas.bind(
            "<Configure>",
            lambda event: canvas.itemconfigure(window_id, width=event.width),
        )

        def on_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        canvas.bind("<Enter>", lambda _event: canvas.bind_all("<MouseWheel>", on_mousewheel))
        canvas.bind("<Leave>", lambda _event: canvas.unbind_all("<MouseWheel>"))
        return content

    def _build_ui(self) -> None:
        app_name = "[ NOXEN ] - Fishing Auto JOODPHAKJAI"
        self.root.title(f"{app_name} | {APP_VERSION}")
        self.root.geometry("880x680")
        self.root.minsize(760, 580)

        outer = ttk.Frame(self.root, padding=12)
        outer.pack(fill="both", expand=True)

        header = ttk.Frame(outer)
        header.pack(fill="x", pady=(0, 7))
        brand_row = ttk.Frame(header)
        brand_row.pack(fill="x")
        ttk.Label(brand_row, text="[ NOXEN ]", style="Brand.TLabel").pack(side="left")
        ttk.Label(
            brand_row,
            text="  Fishing Auto JOODPHAKJAI",
            style="BrandName.TLabel",
        ).pack(side="left")
        ttk.Label(brand_row, text=f"{APP_VERSION}  •  COMPACT UI", style="Version.TLabel").pack(side="right")

        status_row = ttk.Frame(header)
        status_row.pack(fill="x", pady=(3, 0))
        ttk.Label(
            status_row,
            text="AUTO CHARGE  •  CAST  •  FISCH REEL  •  AUTO REPEAT  •  SMART RECOVERY",
            style="Subtitle.TLabel",
        ).pack(side="left", anchor="w")
        ttk.Label(status_row, textvariable=self.game_var, style="Status.TLabel").pack(side="right")

        ttk.Separator(outer, orient="horizontal").pack(fill="x", pady=(0, 7))

        self.tabs = ttk.Notebook(outer)
        self.tabs.pack(fill="both", expand=True)

        self.control_tab = ttk.Frame(self.tabs)
        self.calibration_tab = ttk.Frame(self.tabs)
        self.advanced_tab = ttk.Frame(self.tabs)
        self.help_tab = ttk.Frame(self.tabs)
        self.tabs.add(self.control_tab, text="ควบคุม")
        self.tabs.add(self.calibration_tab, text="ตั้งค่าพื้นที่")
        self.tabs.add(self.advanced_tab, text="ขั้นสูง")
        self.tabs.add(self.help_tab, text="วิธีใช้")

        self.control_content = self._make_scrollable_tab(self.control_tab)
        self.calibration_content = self._make_scrollable_tab(self.calibration_tab)
        self.advanced_content = self._make_scrollable_tab(self.advanced_tab)
        self.help_content = self._make_scrollable_tab(self.help_tab)

        self._build_control_tab(self.control_content)
        self._build_calibration_tab(self.calibration_content)
        self._build_advanced_tab(self.advanced_content)
        self._build_help_tab(self.help_content)

        footer = ttk.Frame(outer)
        footer.pack(fill="x", pady=(6, 0))
        ttk.Label(
            footer,
            textvariable=self.phase_var,
            font=("Segoe UI Semibold", 9, "bold"),
            style="Brand.TLabel",
        ).pack(anchor="w")
        ttk.Label(
            footer,
            textvariable=self.status_var,
            wraplength=680,
            style="Muted.TLabel",
        ).pack(anchor="w", pady=(2, 0))

    def _build_control_tab(self, parent: ttk.Frame) -> None:
        status = ttk.LabelFrame(parent, text="สถานะการทำงาน", padding=8)
        status.pack(fill="x")

        metrics = (
            self.charge_var,
            self.target_var,
            self.handle_var,
            self.progress_var,
            self.tracking_fps_status_var,
            self.tracking_latency_status_var,
        )
        for index, variable in enumerate(metrics):
            ttk.Label(
                status,
                textvariable=variable,
                font=("Segoe UI", 9),
            ).grid(
                row=index // 2,
                column=index % 2,
                sticky="w",
                padx=(5, 12),
                pady=3,
            )
        status.columnconfigure(0, weight=1)
        status.columnconfigure(1, weight=1)
        ttk.Label(status, textvariable=self.round_var, style="Success.TLabel").grid(
            row=3, column=0, columnspan=2, sticky="w", padx=5, pady=(4, 0)
        )

        settings = ttk.LabelFrame(parent, text="ตั้งค่าหลัก", padding=8)
        settings.pack(fill="x", pady=(8, 0))
        fields = ttk.Frame(settings)
        fields.pack(fill="x")
        fields.columnconfigure(0, weight=1)
        fields.columnconfigure(1, weight=1)

        for column, (label, variable) in enumerate((
            ("ปล่อยเบ็ดเมื่อ Charge ถึง", self.charge_target_var),
            ("จบมินิเกมเมื่อ Progress ถึง", self.finish_var),
        )):
            field = ttk.Frame(fields)
            field.grid(row=0, column=column, sticky="ew", padx=(3, 8) if column == 0 else (8, 3))
            ttk.Label(field, text=label, style="Muted.TLabel").pack(anchor="w", pady=(0, 3))
            entry_row = ttk.Frame(field)
            entry_row.pack(anchor="w")
            ttk.Entry(entry_row, textvariable=variable, width=8).pack(side="left")
            ttk.Label(entry_row, text="%", padding=(5, 0)).pack(side="left")

        ttk.Label(
            settings,
            text="Auto Repeat เปิดตลอด: จบรอบแล้วเริ่มตกปลาใหม่เอง • F6 เริ่ม  |  F7 หยุด  |  F8 เปิดแผงควบคุม",
            style="Success.TLabel",
            wraplength=680,
        ).pack(anchor="w", pady=(7, 0))

        actions = ttk.LabelFrame(parent, text="ควบคุมบอท", padding=8)
        actions.pack(fill="x", pady=(8, 0))
        action_row = ttk.Frame(actions)
        action_row.pack(fill="x")
        self.start_btn = ttk.Button(
            action_row,
            text="▶  เริ่มตกปลาอัตโนมัติ  [F6]",
            command=self.start,
            style="Primary.TButton",
        )
        self.start_btn.pack(side="left", fill="x", expand=True, padx=(0, 4), ipady=4)
        self.stop_btn = ttk.Button(
            action_row,
            text="■  หยุดฉุกเฉิน  [F7]",
            command=self.stop,
            state="disabled",
            style="Danger.TButton",
        )
        self.stop_btn.pack(side="left", fill="x", expand=True, padx=(4, 0), ipady=4)

        tools_row = ttk.Frame(actions)
        tools_row.pack(fill="x", pady=(7, 0))
        for column in range(3):
            tools_row.columnconfigure(column, weight=1)
        ttk.Button(
            tools_row, text="ซ่อนแผงควบคุม [F8]", command=self.hide_panel
        ).grid(row=0, column=0, sticky="ew", padx=(0, 3))
        ttk.Button(
            tools_row, text="บันทึกการตั้งค่า", command=self.save_settings
        ).grid(row=0, column=1, sticky="ew", padx=3)
        ttk.Button(
            tools_row, text="เปิด Log", command=self.open_log
        ).grid(row=0, column=2, sticky="ew", padx=(3, 0))

        ttk.Label(
            parent,
            text="หมายเหตุ: ต้องเปิด Roblox ให้มองเห็นบนหน้าจอและอยู่หน้าสุดระหว่างบอททำงาน ไม่รองรับการควบคุมเกมเบื้องหลัง",
            style="Warning.TLabel",
            wraplength=680,
        ).pack(anchor="w", pady=(8, 0))

    def _build_calibration_tab(self, parent: ttk.Frame) -> None:
        ttk.Label(
            parent,
            text="ตั้งค่าพื้นที่ครั้งแรกเพียงครั้งเดียว ระบบจะจำตำแหน่งแบบสัดส่วนของหน้าต่าง Roblox",
            style="Muted.TLabel",
            wraplength=680,
        ).pack(anchor="w", pady=(0, 7))

        box = ttk.LabelFrame(parent, text="เลือกตำแหน่งบนหน้าจอเกม", padding=8)
        box.pack(fill="x")
        self._calibration_row(box, "A. จุดคลิกชาร์จและเหวี่ยงเบ็ด", "cast_point", "เลือกจุด")
        self._calibration_row(box, "B. แถบพลังแนวตั้งสีเขียว/ขาว", "charge", "เลือกกรอบ")
        self._calibration_row(box, "C. รางมินิเกมและแท่งบอกปลา", "slider", "เลือกกรอบ")
        self._calibration_row(box, "D. แถบ Progress ด้านล่าง", "progress", "เลือกกรอบ")

        tests = ttk.LabelFrame(parent, text="ทดสอบและจัดการข้อมูล", padding=8)
        tests.pack(fill="x", pady=(8, 0))
        first_row = ttk.Frame(tests)
        first_row.pack(fill="x")
        ttk.Button(
            first_row, text="ทดสอบการอ่านแถบ", command=self.test_vision_now
        ).pack(side="left", fill="x", expand=True, padx=(0, 3))
        ttk.Button(
            first_row, text="บันทึก Debug Snapshot", command=self.snapshot_now
        ).pack(side="left", fill="x", expand=True, padx=(3, 0))

        second_row = ttk.Frame(tests)
        second_row.pack(fill="x", pady=(6, 0))
        for column in range(3):
            second_row.columnconfigure(column, weight=1)
        ttk.Button(
            second_row, text="เปิดโฟลเดอร์ Debug", command=self.open_debug_folder
        ).grid(row=0, column=0, sticky="ew", padx=(0, 3))
        ttk.Button(
            second_row, text="ส่งออก/สำรองค่า", command=self.export_config
        ).grid(row=0, column=1, sticky="ew", padx=3)
        ttk.Button(
            second_row, text="นำเข้าค่าที่สำรอง", command=self.import_config
        ).grid(row=0, column=2, sticky="ew", padx=(3, 0))

        ttk.Label(
            tests,
            text="ทดสอบขณะ UI ที่ต้องการอ่านกำลังแสดงอยู่ หากหน้ามินิเกมยังไม่เปิด ค่าแถบควบคุม/ปลา/Progress อาจขึ้นว่าไม่พบได้ตามปกติ",
            style="Muted.TLabel",
            wraplength=680,
        ).pack(anchor="w", pady=(7, 0))

    def _calibration_row(self, parent: ttk.Frame, label: str, key: str, button_text: str) -> None:
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=3)
        ttk.Label(row, text=label, width=30).pack(side="left")
        ttk.Label(
            row,
            textvariable=self.calibration_vars[key],
            width=22,
            style="Muted.TLabel",
        ).pack(side="left", padx=5)
        ttk.Button(
            row,
            text=button_text,
            command=lambda selected=key: self.pick_region(selected),
        ).pack(side="right")

    def _build_advanced_tab(self, parent: ttk.Frame) -> None:
        box = ttk.LabelFrame(parent, text="การชาร์จและเวลาสำรอง", padding=8)
        box.pack(fill="x")
        self._entry_row(box, "เวลาสำรองเมื่ออ่านแถบไม่ได้ (วินาที)", self.fallback_var)
        ttk.Checkbutton(
            box,
            text="อนุญาตให้ปล่อยเบ็ดตามเวลาสำรอง (เสี่ยงปล่อยไม่ตรงพลัง)",
            variable=self.fallback_enabled_var,
        ).pack(anchor="w", pady=(3, 2))
        self._entry_row(box, "เวลาสูงสุดในการชาร์จ (วินาที)", self.charge_timeout_var)
        self._entry_row(box, "เวลารอปลา/มินิเกม (วินาที)", self.bite_wait_var)
        self._entry_row(box, "เวลาสูงสุดต่อมินิเกม (วินาที)", self.minigame_timeout_var)

        control = ttk.LabelFrame(parent, text="การควบคุมเมาส์และภาพ", padding=8)
        control.pack(fill="x", pady=(8, 0))
        self._entry_row(control, "จุดสลับทิศเมื่อปลาเข้าใกล้ขอบ (% ของครึ่งแถบ)", self.deadband_var)
        self._entry_row(control, "คาดการณ์การเคลื่อนที่ล่วงหน้า (วินาที)", self.lookahead_var)
        self._entry_row(control, "ช่วงตรวจจับงานทั่วไป (มิลลิวินาที)", self.poll_var)
        tracking_row = ttk.Frame(control)
        tracking_row.pack(fill="x", pady=3)
        ttk.Label(tracking_row, text="Tracking FPS (เฉพาะมินิเกม)", width=38).pack(side="left")
        ttk.Combobox(
            tracking_row,
            textvariable=self.tracking_fps_var,
            values=tuple(str(rate) for rate in TRACKING_FPS_OPTIONS),
            width=8,
            state="readonly",
        ).pack(side="left")
        ttk.Label(
            control,
            text="120 FPS = รอบอ่านเป้าหมายทุก 8.33 ms • Progress แยกอ่านประมาณ 20 FPS",
            style="Muted.TLabel",
            wraplength=680,
        ).pack(anchor="w", pady=(2, 0))
        ttk.Checkbutton(
            control,
            text="ปรับ FPS อัตโนมัติเมื่อเครื่องประมวลผลไม่ทัน และเพิ่มกลับเมื่อพร้อม",
            variable=self.tracking_auto_scale_var,
        ).pack(anchor="w", pady=(3, 0))

        recovery = ttk.LabelFrame(parent, text="ระบบกู้คืนอัตโนมัติ (Recovery)", padding=8)
        recovery.pack(fill="x", pady=(8, 0))
        ttk.Checkbutton(
            recovery,
            text="เมื่ออ่านแถบไม่พบ / มินิเกมหาย / ตรวจจับปลาขาดช่วง ให้พักแล้วลองตรวจใหม่อัตโนมัติ",
            variable=self.recovery_enabled_var,
        ).pack(anchor="w", pady=3)
        self._entry_row(recovery, "เวลาพักเริ่มต้นเมื่อพบข้อผิดพลาด (วินาที)", self.recovery_initial_var)
        self._entry_row(recovery, "เวลาพักสูงสุดเมื่อผิดพลาดซ้ำ (วินาที)", self.recovery_max_var)
        ttk.Checkbutton(
            recovery,
            text="ถ้า Roblox ถูกย่อหรือเสียโฟกัส ให้ปล่อยเมาส์และรอจนกลับมาอยู่หน้าสุด แล้วทำต่อ",
            variable=self.wait_for_focus_var,
        ).pack(anchor="w", pady=(3, 2))
        ttk.Label(
            recovery,
            text="เมื่อเปิด Recovery จะลองใหม่ไม่จำกัดครั้ง (หยุดได้ด้วย F7) • เวลาพักเพิ่มตามจำนวนปัญหา และสแกนหามินิเกมเดิมได้ถึง 8 วินาที",
            style="Success.TLabel",
            wraplength=680,
        ).pack(anchor="w", pady=(3, 0))
        ttk.Button(
            parent,
            text="บันทึกการตั้งค่าขั้นสูง",
            command=self.save_settings,
        ).pack(anchor="e", pady=(8, 0))

    def _entry_row(self, parent: ttk.Frame, label: str, variable: tk.StringVar) -> None:
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=2)
        ttk.Label(row, text=label, width=38).pack(side="left")
        ttk.Entry(row, textvariable=variable, width=10).pack(side="left")

    def _build_help_tab(self, parent: ttk.Frame) -> None:
        text = (
            f"[ NOXEN ] - Fishing Auto JOODPHAKJAI / {APP_VERSION} Compact UI — Fisch-style Reel\n\n"
            "1. เปิด Roblox และให้หน้าต่างเกมอยู่บนหน้าจอ ห้ามย่อเกม\n"
            "2. พื้นที่ A: เลือกจุดบนผิวน้ำที่ต้องการเหวี่ยงเบ็ด\n"
            "3. พื้นที่ B: ครอบแถบชาร์จแนวตั้งทั้งแท่ง โดยต้องเห็นส่วนสีเขียว/เหลืองด้านบนและส่วนเติมสีขาวด้านล่าง\n"
            "4. พื้นที่ C: ครอบรางมินิเกมแนวนอนทั้งหมด รวมบล็อกควบคุมสีขาวและตัวบอกตำแหน่งปลาสีม่วง/เทา\n"
            "5. พื้นที่ D: ครอบแถบ Progress ด้านล่างทั้งราง โดยสีเติมอาจเป็นส้มอมชมพูหรือสีขาว\n"
            "6. กด ‘ทดสอบการอ่านแถบ’ ระหว่างที่หน้าจอแสดงแต่ละสถานะ แล้วตรวจ Charge, แถบควบคุม, ตำแหน่งปลา และ Progress\n"
            "7. กด F6 เพียงครั้งเดียวเพื่อเริ่มตกปลาอัตโนมัติ ระบบจะวนเหวี่ยงเบ็ดและเล่นมินิเกมรอบถัดไปเองจนกด F7 หรือปิดโปรแกรม\n\n"
            "กลไกมินิเกมแบบ Fisch\n"
            "• กดเมาส์ซ้ายค้าง: บล็อกควบคุมสีขาวเคลื่อนไปทางขวา\n"
            "• ปล่อยเมาส์: บล็อกควบคุมไหลกลับไปทางซ้าย\n"
            "• บอทใช้ Edge Tracking รักษาปลาให้อยู่ในพื้นที่บล็อก และคาดการณ์ความเร็วทั้งปลาและบล็อกเพื่อลดการแกว่ง\n"
            "• เลือก Tracking ได้ 30/60/90/120 FPS; ที่ 120 FPS ตั้งเป้ารอบละ 8.33 ms และ Progress อ่านแยกประมาณ 20 FPS\n"
            "• ค่า Tracking FPS ที่แสดงเป็นค่าที่วัดได้จริง ไม่ใช่แค่ค่าที่เลือก และอาจต่ำกว่าเป้าหมายตามประสิทธิภาพเครื่อง\n\n"
            "ข้อสำคัญ\n"
            "• ใช้สีตามภาพจริง: Charge เขียว/เหลือง + ขาว; บล็อกควบคุมเทาอ่อน/ขาว; ตัวบอกปลาม่วง/เทาอมฟ้า; Progress ส้มอมชมพูหรือขาว\n"
            "• หากอ่าน Charge/Progress/ตำแหน่งปลาไม่พบ บอทจะปล่อยเมาส์ พักตามเวลาที่ตั้ง และลองตรวจใหม่โดยอัตโนมัติ ไม่ต้องกด F6 ซ้ำ\n"
            "• หากสลับหน้าต่างหรือย่อ Roblox บอทจะปล่อยเมาส์และรอจนผู้ใช้กลับมาเปิด Roblox ไว้หน้าสุด จากนั้นตรวจ UI เดิมก่อนตัดสินใจชาร์จใหม่\n"
            "• F7 หยุดทันที; F8 เปิดแผงควบคุมและหยุดบอท\n"
        )
        ttk.Label(
            parent,
            text=text,
            justify="left",
            wraplength=680,
        ).pack(anchor="nw", fill="both", expand=True)
    def _sync_form_from_config(self) -> None:
        s = self.cfg["settings"]
        self.charge_target_var.set(str(round(float(s["charge_target"]) * 100, 1)))
        self.finish_var.set(str(round(float(s["minigame_finish"]) * 100, 1)))
        self.fallback_enabled_var.set(bool(s["use_timed_fallback"]))
        self.fallback_var.set(str(s["charge_fallback_seconds"]))
        self.charge_timeout_var.set(str(s["charge_timeout"]))
        self.bite_wait_var.set(str(s["bite_wait_seconds"]))
        self.minigame_timeout_var.set(str(s["minigame_timeout"]))
        self.deadband_var.set(str(round(float(s.get("tracking_edge_guard_ratio", 0.78)) * 100)))
        self.lookahead_var.set(str(s.get("tracking_lookahead_seconds", 0.10)))
        self.poll_var.set(str(round(float(s["poll_interval"]) * 1000)))
        self.tracking_fps_var.set(str(s.get("tracking_fps", 120)))
        self.tracking_auto_scale_var.set(bool(s.get("tracking_auto_scale", True)))
        self.recovery_enabled_var.set(bool(s.get("recovery_enabled", True)))
        self.wait_for_focus_var.set(bool(s.get("wait_for_focus_recovery", True)))
        self.recovery_initial_var.set(str(s.get("recovery_initial_seconds", 2.5)))
        self.recovery_max_var.set(str(s.get("recovery_max_seconds", 15.0)))

    def _apply_form(self) -> None:
        s = self.cfg["settings"]
        try:
            charge_target = float(self.charge_target_var.get()) / 100.0
            finish = float(self.finish_var.get()) / 100.0
            fallback = float(self.fallback_var.get())
            charge_timeout = float(self.charge_timeout_var.get())
            bite_wait = float(self.bite_wait_var.get())
            minigame_timeout = float(self.minigame_timeout_var.get())
            edge_guard_percent = float(self.deadband_var.get())
            lookahead = float(self.lookahead_var.get())
            poll_ms = int(self.poll_var.get())
            tracking_fps = int(self.tracking_fps_var.get())
            recovery_initial = float(self.recovery_initial_var.get())
            recovery_max = float(self.recovery_max_var.get())
        except ValueError as exc:
            raise ValueError("กรุณากรอกค่าตัวเลขให้ถูกต้องทุกช่อง") from exc
        if not 0.10 <= charge_target <= 1.0:
            raise ValueError("Charge ต้องอยู่ระหว่าง 10–100%")
        if not 0.80 <= finish <= 1.0:
            raise ValueError("Progress ต้องอยู่ระหว่าง 80–100%")
        if not 0.2 <= fallback <= 10:
            raise ValueError("เวลาสำรองต้องอยู่ระหว่าง 0.2–10 วินาที")
        if not 1 <= charge_timeout <= 30 or not 5 <= bite_wait <= 180 or not 10 <= minigame_timeout <= 240:
            raise ValueError("ตรวจสอบช่วงเวลาที่ตั้งค่า: Charge 1–30s, รอปลา 5–180s, มินิเกม 10–240s")
        if not 55 <= edge_guard_percent <= 92 or not 0 <= lookahead <= 0.35 or not 15 <= poll_ms <= 100:
            raise ValueError("ตรวจสอบจุดสลับทิศ 55–92%/คาดการณ์ 0–0.35s/ช่วงตรวจจับ 15–100ms")
        if tracking_fps not in TRACKING_FPS_OPTIONS:
            raise ValueError("Tracking FPS เลือกได้เฉพาะ 30, 60, 90 หรือ 120")
        if not 0.5 <= recovery_initial <= 10 or not 2 <= recovery_max <= 60 or recovery_max < recovery_initial:
            raise ValueError("เวลาพัก Recovery ต้องเริ่ม 0.5–10 วินาที และเวลาสูงสุด 2–60 วินาที โดยต้องไม่น้อยกว่าเวลาเริ่มต้น")
        s.update({
            "charge_target": charge_target,
            "minigame_finish": finish,
            "use_timed_fallback": bool(self.fallback_enabled_var.get()),
            "charge_fallback_seconds": fallback,
            "charge_timeout": charge_timeout,
            "bite_wait_seconds": bite_wait,
            "minigame_timeout": minigame_timeout,
            "max_run_minutes": 0,
            "repeat_fishing": True,
            "tracking_edge_guard_ratio": edge_guard_percent / 100.0,
            "tracking_lookahead_seconds": lookahead,
            "tracking_fps": tracking_fps,
            "tracking_auto_scale": bool(self.tracking_auto_scale_var.get()),
            "progress_poll_interval": 0.05,
            "poll_interval": poll_ms / 1000.0,
            "recovery_enabled": bool(self.recovery_enabled_var.get()),
            "recovery_initial_seconds": recovery_initial,
            "recovery_max_seconds": recovery_max,
            "recovery_max_attempts": 0,
            "wait_for_focus_recovery": bool(self.wait_for_focus_var.get()),
        })

    def save_settings(self) -> None:
        try:
            self._apply_form()
            self.store.save(self.cfg)
            self.status_var.set("บันทึกการตั้งค่าแล้ว")
        except Exception as exc:
            messagebox.showerror("บันทึกการตั้งค่าไม่ได้", str(exc), parent=self.root)

    def _refresh_calibration_labels(self) -> None:
        regions = self.cfg["regions"]
        for key, var in self.calibration_vars.items():
            value = regions.get(key)
            try:
                if not isinstance(value, dict):
                    var.set("ยังไม่ได้เลือก")
                elif key == "cast_point":
                    var.set(f"X {float(value['x']) * 100:.1f}% / Y {float(value['y']) * 100:.1f}%")
                else:
                    var.set(f"{float(value['w']) * 100:.1f}% × {float(value['h']) * 100:.1f}%")
            except (KeyError, TypeError, ValueError):
                var.set("ค่าตั้งค่าไม่ถูกต้อง")

    def _validate_regions(self) -> list[str]:
        regions = self.cfg.get("regions", {})
        errors = []
        point = regions.get("cast_point")
        if not isinstance(point, dict):
            errors.append("A จุดเหวี่ยงเบ็ด")
        else:
            try:
                x, y = float(point["x"]), float(point["y"])
                if not (0.0 <= x <= 1.0 and 0.0 <= y <= 1.0):
                    errors.append("A จุดเหวี่ยงเบ็ด (พิกัดผิดช่วง)")
            except (KeyError, TypeError, ValueError):
                errors.append("A จุดเหวี่ยงเบ็ด (ข้อมูลไม่ครบ)")
        for key, label in (("charge", "B แถบพลัง"), ("slider", "C รางมินิเกม"), ("progress", "D Progress")):
            rect = regions.get(key)
            if not isinstance(rect, dict):
                errors.append(label)
                continue
            try:
                x, y, w, h = (float(rect[k]) for k in ("x", "y", "w", "h"))
                if x < 0 or y < 0 or w <= 0 or h <= 0 or x + w > 1.001 or y + h > 1.001:
                    errors.append(label + " (กรอบผิดช่วง)")
            except (KeyError, TypeError, ValueError):
                errors.append(label + " (ข้อมูลไม่ครบ)")
        return errors

    # --------------------------- Calibration -----------------------------
    def _locate_game(self) -> tuple[int, Rect] | None:
        hwnd, title = find_roblox_window()
        if hwnd is None:
            messagebox.showerror("ไม่พบ Roblox", "เปิด Roblox ให้เรียบร้อยก่อน แล้วลองอีกครั้ง", parent=self.root)
            return None
        bounds = client_rect(hwnd)
        if bounds is None:
            messagebox.showerror("หน้าต่าง Roblox ไม่พร้อม", "ขยายหน้าต่าง Roblox ให้มองเห็นบนหน้าจอก่อน", parent=self.root)
            return None
        self.hwnd, self.game_title = hwnd, title or "Roblox"
        self.game_var.set(f"Roblox: พบหน้าต่างแล้ว ({bounds.width} × {bounds.height})")
        return hwnd, bounds

    def pick_region(self, key: str) -> None:
        if self.running:
            messagebox.showwarning("กำลังทำงาน", "หยุดบอทก่อนเปลี่ยนพื้นที่ตรวจจับ", parent=self.root)
            return
        found = self._locate_game()
        if not found:
            return
        hwnd, bounds = found
        ok, title = focus_window(hwnd)
        if not ok:
            messagebox.showerror("โฟกัส Roblox ไม่ได้", title, parent=self.root)
            return
        self.root.withdraw()
        self.root.after(250, lambda: self._open_selector(key, bounds))

    def _open_selector(self, key: str, bounds: Rect) -> None:
        def done(value):
            try:
                if key == "cast_point":
                    self.cfg["regions"][key] = screen_to_relative_point(value, bounds)
                else:
                    self.cfg["regions"][key] = screen_to_relative_rect(value, bounds)
                self.store.save(self.cfg)
                self._refresh_calibration_labels()
                self.status_var.set(f"บันทึกพื้นที่ {key} แล้ว")
            except Exception as exc:
                messagebox.showerror("เลือกพื้นที่ไม่ได้", str(exc), parent=self.root)
            self.root.deiconify()
            self.root.lift()

        def cancel():
            self.root.deiconify()
            self.root.lift()
            self.status_var.set("ยกเลิกการเลือกพื้นที่")

        desktop = virtual_desktop_rect()
        self.overlay = SelectionOverlay(self.root, key, desktop, done, cancel)

    # ------------------------------ Capture ------------------------------
    def _begin_capture_task(self, mode: str) -> None:
        if self.running:
            messagebox.showwarning("กำลังทำงาน", "หยุดบอทก่อนทดสอบภาพ", parent=self.root)
            return
        found = self._locate_game()
        if not found:
            return
        hwnd, _bounds = found
        ok, title = focus_window(hwnd)
        if not ok:
            messagebox.showerror("โฟกัส Roblox ไม่ได้", title, parent=self.root)
            return
        self.root.withdraw()
        self.root.after(400, lambda: self._capture_task(mode, hwnd))

    def test_vision_now(self) -> None:
        self._begin_capture_task("test")

    def snapshot_now(self) -> None:
        self._begin_capture_task("snapshot")

    def _capture_task(self, mode: str, hwnd: int) -> None:
        try:
            bounds = client_rect(hwnd)
            if bounds is None:
                raise RuntimeError("อ่านพื้นที่หน้าต่าง Roblox ไม่ได้")
            with mss.mss() as sct:
                metrics, crops, full = test_vision(sct, hwnd, self.cfg, bounds)
            image_path = save_debug_snapshot(DEBUG_DIR, self.cfg, bounds, metrics, crops, full)
            self._show_metrics(metrics)
            if mode == "test":
                self.status_var.set("ทดสอบภาพเสร็จแล้ว — แสดงภาพตัวอย่างและบันทึก Debug แล้ว")
                self._show_preview(crops, metrics, image_path)
            else:
                self.status_var.set(f"บันทึก Debug Snapshot แล้ว: {image_path.name}")
                messagebox.showinfo("บันทึก Debug แล้ว", f"บันทึกภาพและข้อมูลไว้ที่\n{image_path}", parent=self.root)
        except Exception as exc:
            self.status_var.set(f"ทดสอบภาพไม่สำเร็จ: {exc}")
            messagebox.showerror("ทดสอบภาพไม่สำเร็จ", str(exc), parent=self.root)
        finally:
            self.root.deiconify()
            self.root.lift()

    def _show_metrics(self, metrics: dict) -> None:
        value = metrics.get("charge")
        self.charge_var.set("Charge: ไม่พบ" if value is None else f"Charge: {value * 100:.1f}%")
        value = metrics.get("bar_center")
        self.target_var.set("แถบควบคุม: ไม่พบ" if value is None else f"แถบควบคุม: x={value:.1f}px")
        value = metrics.get("fish_x")
        self.handle_var.set("ตำแหน่งปลา: ไม่พบ" if value is None else f"ตำแหน่งปลา: x={value:.1f}px")
        value = metrics.get("progress")
        self.progress_var.set("Progress: ไม่พบ" if value is None else f"Progress: {value * 100:.1f}%")

    def _show_preview(self, crops: dict, metrics: dict, snapshot_path: Path) -> None:
        win = tk.Toplevel(self.root)
        win.title("[ NOXEN ] - Debug Preview")
        win.geometry("700x550")
        win.transient(self.root)
        win.configure(background=self.colors["bg"])
        ttk.Label(win, text="ผลตรวจจับจากภาพปัจจุบัน", font=("Segoe UI", 13, "bold")).pack(anchor="w", padx=12, pady=10)
        self._preview_refs = []
        body = ttk.Frame(win, padding=10)
        body.pack(fill="both", expand=True)
        keys = ["charge", "slider", "progress"]
        for idx, key in enumerate(keys):
            card = ttk.LabelFrame(body, text=key.upper(), padding=6)
            card.grid(row=idx, column=0, sticky="ew", pady=5)
            if key in crops:
                crop = Image.fromarray(crops[key])
                crop.thumbnail((630, 105))
                photo = ImageTk.PhotoImage(crop)
                self._preview_refs.append(photo)
                ttk.Label(card, image=photo).pack(anchor="w")
            else:
                ttk.Label(card, text="ยังไม่ได้เลือกพื้นที่").pack(anchor="w")
            val = metrics.get(key)
            if key == "charge" or key == "progress":
                summary = "ไม่พบ" if val is None else f"{float(val) * 100:.1f}%"
            elif key == "slider":
                summary = f"แถบควบคุม={metrics.get('bar_center')} / ตำแหน่งปลา={metrics.get('fish_x')}"
            else:
                summary = str(val)
            ttk.Label(card, text=summary, style="Muted.TLabel").pack(anchor="w")
        ttk.Button(win, text=f"เปิดภาพ Snapshot ({snapshot_path.name})", command=lambda: os.startfile(str(snapshot_path))).pack(anchor="e", padx=12, pady=8)

    # ------------------------------- Worker ------------------------------
    def start(self) -> None:
        if self.running:
            return
        try:
            self._apply_form()
            self.store.save(self.cfg)
        except Exception as exc:
            messagebox.showerror("ตั้งค่าไม่ถูกต้อง", str(exc), parent=self.root)
            return
        region_errors = self._validate_regions()
        if region_errors:
            messagebox.showwarning("ตั้งค่าพื้นที่ไม่ครบ/ไม่ถูกต้อง", "กรุณาตั้งค่าให้ถูกต้อง:\n• " + "\n• ".join(region_errors), parent=self.root)
            self.tabs.select(self.calibration_tab)
            return
        found = self._locate_game()
        if not found:
            return
        hwnd, _bounds = found
        ok, title = focus_window(hwnd)
        if not ok:
            messagebox.showerror("เริ่มเกมไม่ได้", title, parent=self.root)
            return
        self.hwnd = hwnd
        self.game_title = title or "Roblox"
        self.stop_event.clear()
        self.running = True
        self.start_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        self.phase_var.set("สถานะ: กำลังเริ่ม")
        self.status_var.set("บอทกำลังทำงาน — วนตกปลาและกู้คืนอัตโนมัติเมื่อผิดพลาด กด F7 เพื่อหยุด")
        self.root.withdraw()
        engine = FishingEngine(self.hwnd, self.cfg, self.stop_event, self._emit_from_worker)

        def worker_main():
            result = engine.run()
            self.events.put(("done", {"result": result}))

        self.worker = threading.Thread(target=worker_main, name="FishingBotV55WideBarRecoveryWorker", daemon=True)
        self.worker.start()
        logging.getLogger("FishingAutoBotV5").info("Start clicked; window=%s", self.game_title)

    def _emit_from_worker(self, kind: str, payload: dict) -> None:
        self.events.put((kind, payload))

    def stop(self) -> None:
        # Always send a mouse-up, even if the UI state already says idle.
        self.stop_event.set()
        try:
            MouseController().release()
        except Exception:
            pass
        if self.running:
            self.events.put(("status", {"text": "รับคำสั่งหยุดแล้ว — ปล่อยเมาส์และกำลังหยุดบอท"}))

    def hide_panel(self) -> None:
        self.root.withdraw()

    def show_panel(self) -> None:
        if self.running:
            self.stop()
        self.root.deiconify()
        self.root.lift()
        self.status_var.set("เปิดแผงควบคุมแล้ว")

    def _install_hotkeys(self) -> None:
        try:
            import keyboard
            keyboard.add_hotkey("F6", lambda: self.events.put(("hotkey", {"key": "F6"})))
            keyboard.add_hotkey("F7", lambda: self.events.put(("hotkey", {"key": "F7"})))
            keyboard.add_hotkey("F8", lambda: self.events.put(("hotkey", {"key": "F8"})))
            self.hotkey_available = True
        except Exception as exc:
            logging.getLogger("FishingAutoBotV5").warning("global hotkeys unavailable: %s", exc)
            self.status_var.set("ไม่สามารถติดตั้งปุ่มลัดได้ — ใช้ปุ่มบนหน้าต่างแทน")

    def _drain_events(self) -> None:
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == "phase":
                    self.phase_var.set(f"สถานะ: {payload.get('text', '')}")
                elif kind == "metrics":
                    if "charge" in payload:
                        value = payload["charge"]
                        self.charge_var.set("Charge: ไม่พบ" if value is None else f"Charge: {value * 100:.1f}%")
                    if "bar_center" in payload:
                        value = payload["bar_center"]
                        self.target_var.set("แถบควบคุม: ไม่พบ" if value is None else f"แถบควบคุม: x={value:.1f}px")
                    if "fish_x" in payload:
                        value = payload["fish_x"]
                        self.handle_var.set("ตำแหน่งปลา: ไม่พบ" if value is None else f"ตำแหน่งปลา: x={value:.1f}px")
                    if "progress" in payload:
                        value = payload["progress"]
                        self.progress_var.set("Progress: ไม่พบ" if value is None else f"Progress: {value * 100:.1f}%")
                    if "tracking_fps" in payload:
                        value = float(payload["tracking_fps"])
                        target = int(payload.get("tracking_target_fps", 120))
                        effective = int(payload.get("tracking_effective_fps", target))
                        self.tracking_fps_status_var.set(f"Tracking: {value:.1f} FPS (auto {effective}, cap {target})")
                    if "tracking_ms" in payload:
                        latency_ms = float(payload["tracking_ms"])
                        self.tracking_latency_status_var.set(f"Frame: {latency_ms:.2f} ms")
                elif kind == "round":
                    self.round_var.set(f"สำเร็จ {payload.get('count', 0)} รอบ")
                elif kind == "status":
                    self.status_var.set(payload.get("text", ""))
                elif kind == "done":
                    self.running = False
                    self.start_btn.configure(state="normal")
                    self.stop_btn.configure(state="disabled")
                    self.phase_var.set("สถานะ: จบการทำงาน")
                    self.status_var.set(payload.get("result", "หยุดแล้ว"))
                    self.root.deiconify()
                    self.root.lift()
                    logging.getLogger("FishingAutoBotV5").info("Worker finished: %s", payload.get("result"))
                elif kind == "hotkey":
                    key = payload.get("key")
                    if key == "F6":
                        self.start()
                    elif key == "F7":
                        self.stop()
                    elif key == "F8":
                        self.show_panel()
        except queue.Empty:
            pass
        except Exception as exc:
            logging.getLogger("FishingAutoBotV5").exception("UI event error: %s", exc)
        try:
            self.root.after(60, self._drain_events)
        except tk.TclError:
            pass

    def _refresh_game_status(self) -> None:
        if not self.running:
            hwnd, title = find_roblox_window()
            if hwnd:
                bounds = client_rect(hwnd)
                if bounds:
                    self.game_var.set(f"Roblox: {title or 'พบหน้าต่าง'} — {bounds.width} × {bounds.height}")
            else:
                self.game_var.set("Roblox: ยังไม่ได้ตรวจพบ")
        try:
            self.root.after(1500, self._refresh_game_status)
        except tk.TclError:
            pass

    # -------------------------------- Files ------------------------------
    def export_config(self) -> None:
        try:
            self._apply_form()
            path = filedialog.asksaveasfilename(
                parent=self.root, title="สำรองการตั้งค่า [ NOXEN ] - Fishing Auto JOODPHAKJAI",
                defaultextension=".json", filetypes=[("JSON config", "*.json")],
                initialfile="noxen_fishing_auto_v5_5_backup.json")
            if not path:
                return
            Path(path).write_text(json.dumps(self.cfg, ensure_ascii=False, indent=2), encoding="utf-8")
            self.status_var.set(f"สำรองการตั้งค่าแล้ว: {Path(path).name}")
        except Exception as exc:
            messagebox.showerror("สำรองการตั้งค่าไม่ได้", str(exc), parent=self.root)

    def import_config(self) -> None:
        path = filedialog.askopenfilename(
            parent=self.root, title="เลือกไฟล์สำรอง V5",
            filetypes=[("JSON config", "*.json"), ("All files", "*.*")])
        if not path:
            return
        try:
            loaded = json.loads(Path(path).read_text(encoding="utf-8"))
            if not isinstance(loaded, dict):
                raise ValueError("ไฟล์ตั้งค่าไม่ใช่ JSON object")
            if loaded.get("version") != 5:
                raise ValueError("ไฟล์นี้ไม่ใช่ไฟล์สำรอง V5 (พิกัดรุ่นก่อนหน้าใช้รูปแบบต่างกัน)")
            imported = _merge(DEFAULT_CONFIG, loaded)
            imported["version"] = 5
            self.cfg = imported
            self.store.save(self.cfg)
            self._sync_form_from_config()
            self._refresh_calibration_labels()
            self.status_var.set(f"นำเข้าการตั้งค่าแล้ว: {Path(path).name}")
        except Exception as exc:
            messagebox.showerror("นำเข้าการตั้งค่าไม่ได้", str(exc), parent=self.root)

    def open_log(self) -> None:
        LOG_DIR.mkdir(exist_ok=True)
        if not LOG_PATH.exists():
            LOG_PATH.write_text(f"[ NOXEN ] - Fishing Auto JOODPHAKJAI / {APP_VERSION} Recovery log\n", encoding="utf-8")
        try:
            os.startfile(str(LOG_PATH))
        except Exception as exc:
            messagebox.showerror("เปิด Log ไม่ได้", str(exc), parent=self.root)

    def open_debug_folder(self) -> None:
        DEBUG_DIR.mkdir(exist_ok=True)
        try:
            os.startfile(str(DEBUG_DIR))
        except Exception as exc:
            messagebox.showerror("เปิดโฟลเดอร์ไม่ได้", str(exc), parent=self.root)

    def close(self) -> None:
        if self.running and not messagebox.askyesno("ปิดโปรแกรม", "ต้องการหยุดบอทและปิดโปรแกรมหรือไม่?", parent=self.root):
            return
        self.stop_event.set()
        try:
            MouseController().release()
        except Exception:
            pass
        try:
            import keyboard
            keyboard.unhook_all_hotkeys()
        except Exception:
            pass
        self.root.destroy()


def main() -> None:
    enable_dpi_awareness()
    setup_logging()
    root = tk.Tk()
    app = FishingAutoBotV5(root)
    root.mainloop()


if __name__ == "__main__":
    main()
