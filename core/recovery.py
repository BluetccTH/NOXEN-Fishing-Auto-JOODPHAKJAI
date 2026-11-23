"""Portable retry classification and back-off helpers for Fishing Auto Bot."""
from __future__ import annotations


def classify_failure(reason: str) -> str:
    """Return one of: stop, focus, fatal, retry."""
    text = str(reason or "").casefold()
    if any(token in text for token in ("ผู้ใช้สั่งหยุด", "ถูกหยุดระหว่าง", "stop requested")):
        return "stop"
    if any(token in text for token in ("หน้าต่าง roblox ถูกปิด", "roblox window was closed")):
        return "fatal"
    if any(token in text for token in (
        "ยังไม่ได้ตั้งค่าพื้นที่", "ยังไม่ได้ตั้งค่าจุด", "พื้นที่ไม่ถูกต้อง",
        "จุดเหวี่ยงเบ็ด", "ข้อมูลไม่ครบ", "อยู่นอกพื้นที่หน้าต่าง",
    )):
        return "fatal"
    if any(token in text for token in (
        "ไม่ได้อยู่หน้าสุด", "ถูกย่อ", "ไม่พร้อมใช้งาน", "อ่านขนาดหน้าต่าง roblox ไม่ได้",
        "not foreground", "minimized", "window is not ready",
    )):
        return "focus"
    return "retry"


def recovery_delay(attempt: int, initial_seconds: float = 2.0, max_seconds: float = 15.0) -> float:
    """Exponential back-off capped at max_seconds; attempt numbers start at 1."""
    attempt = max(1, int(attempt))
    initial = max(0.1, float(initial_seconds))
    maximum = max(initial, float(max_seconds))
    return min(maximum, initial * (2 ** min(attempt - 1, 10)))
