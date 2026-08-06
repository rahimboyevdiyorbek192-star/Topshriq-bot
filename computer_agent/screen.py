"""Ekran rasmini olish va Ollama uchun moslash."""
from __future__ import annotations

import io
import base64
from typing import Optional

try:
    import pyautogui
    PYAUTOGUI_OK = True
except Exception:
    PYAUTOGUI_OK = False

try:
    from PIL import Image
    PIL_OK = True
except ImportError:
    PIL_OK = False

# Ollama uchun max o'lcham (llava model limiti)
MAX_W = 1280
MAX_H = 960


def screenshot_bytes(max_w: int = MAX_W, max_h: int = MAX_H) -> Optional[bytes]:
    """Screenshot oladi va PNG baytlar qaytaradi. None — kutubxona yo'q."""
    if not PYAUTOGUI_OK or not PIL_OK:
        return None

    try:
        img = pyautogui.screenshot()           # PIL Image
        w, h = img.size

        # Miqyoslash — agar katta bo'lsa kamaytirish
        if w > max_w or h > max_h:
            ratio = min(max_w / w, max_h / h)
            new_w = int(w * ratio)
            new_h = int(h * ratio)
            img = img.resize((new_w, new_h), Image.LANCZOS)

        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
        return buf.getvalue()
    except Exception:
        return None


def screenshot_b64(max_w: int = MAX_W, max_h: int = MAX_H) -> Optional[str]:
    """Screenshot → base64 string (Ollama API uchun)."""
    data = screenshot_bytes(max_w, max_h)
    if data is None:
        return None
    return base64.b64encode(data).decode()


def scale_ratio() -> tuple[float, float]:
    """Haqiqiy ekran o'lchami / miqyoslangan o'lcham nisbati."""
    if not PYAUTOGUI_OK:
        return 1.0, 1.0
    try:
        real_w, real_h = pyautogui.size()
        ratio_x = real_w / min(real_w, MAX_W)
        ratio_y = real_h / min(real_h, MAX_H)
        return ratio_x, ratio_y
    except Exception:
        return 1.0, 1.0
