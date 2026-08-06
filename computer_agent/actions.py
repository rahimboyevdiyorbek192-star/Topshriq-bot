"""Kompyuter harakatlari: click, type, key, scroll — pyautogui orqali."""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Optional

logger = logging.getLogger(__name__)

try:
    import pyautogui
    pyautogui.FAILSAFE = True     # Sichqonchani burchakka olib borsa — to'xtatadi
    pyautogui.PAUSE   = 0.25     # Har harakatdan keyin 0.25s kutish
    PYAUTOGUI_OK = True
except Exception:
    PYAUTOGUI_OK = False


def _check() -> bool:
    if not PYAUTOGUI_OK:
        logger.error("pyautogui o'rnatilmagan")
        return False
    return True


def _scale_coord(x: int, y: int, ratio_x: float = 1.0, ratio_y: float = 1.0) -> tuple[int, int]:
    """AI tomonidan berilgan koordinatalarni haqiqiy ekran koordinatalariga aylantiradi."""
    return int(x * ratio_x), int(y * ratio_y)


async def do_click(
    x: int, y: int,
    ratio_x: float = 1.0, ratio_y: float = 1.0,
) -> bool:
    if not _check():
        return False
    rx, ry = _scale_coord(x, y, ratio_x, ratio_y)
    try:
        await asyncio.to_thread(pyautogui.click, rx, ry)
        logger.info("click(%d, %d) → real(%d, %d)", x, y, rx, ry)
        return True
    except Exception as e:
        logger.warning("click xato: %s", e)
        return False


async def do_double_click(
    x: int, y: int,
    ratio_x: float = 1.0, ratio_y: float = 1.0,
) -> bool:
    if not _check():
        return False
    rx, ry = _scale_coord(x, y, ratio_x, ratio_y)
    try:
        await asyncio.to_thread(pyautogui.doubleClick, rx, ry)
        logger.info("doubleClick(%d, %d)", rx, ry)
        return True
    except Exception as e:
        logger.warning("doubleClick xato: %s", e)
        return False


async def do_right_click(
    x: int, y: int,
    ratio_x: float = 1.0, ratio_y: float = 1.0,
) -> bool:
    if not _check():
        return False
    rx, ry = _scale_coord(x, y, ratio_x, ratio_y)
    try:
        await asyncio.to_thread(pyautogui.rightClick, rx, ry)
        return True
    except Exception as e:
        logger.warning("rightClick xato: %s", e)
        return False


async def do_type(text: str) -> bool:
    if not _check():
        return False
    try:
        await asyncio.to_thread(pyautogui.typewrite, text, interval=0.05)
        logger.info("type: %r", text[:50])
        return True
    except Exception as e:
        # typewrite latin harflar uchun, unicode uchun pyperclip + hotkey
        try:
            import pyperclip
            pyperclip.copy(text)
            await asyncio.to_thread(pyautogui.hotkey, "ctrl", "v")
            return True
        except Exception as e2:
            logger.warning("type xato: %s / %s", e, e2)
            return False


async def do_key(key_combo: str) -> bool:
    """Misol: 'enter', 'ctrl+a', 'win', 'alt+f4'."""
    if not _check():
        return False
    try:
        parts = [k.strip() for k in key_combo.split("+")]
        if len(parts) > 1:
            await asyncio.to_thread(pyautogui.hotkey, *parts)
        else:
            await asyncio.to_thread(pyautogui.press, parts[0])
        logger.info("key: %s", key_combo)
        return True
    except Exception as e:
        logger.warning("key xato: %s", e)
        return False


async def do_scroll(
    x: int, y: int,
    amount: int = -3,
    ratio_x: float = 1.0, ratio_y: float = 1.0,
) -> bool:
    if not _check():
        return False
    rx, ry = _scale_coord(x, y, ratio_x, ratio_y)
    try:
        await asyncio.to_thread(pyautogui.scroll, amount, rx, ry)
        return True
    except Exception as e:
        logger.warning("scroll xato: %s", e)
        return False


async def do_move(
    x: int, y: int,
    ratio_x: float = 1.0, ratio_y: float = 1.0,
    duration: float = 0.3,
) -> bool:
    if not _check():
        return False
    rx, ry = _scale_coord(x, y, ratio_x, ratio_y)
    try:
        await asyncio.to_thread(pyautogui.moveTo, rx, ry, duration)
        return True
    except Exception as e:
        logger.warning("move xato: %s", e)
        return False
