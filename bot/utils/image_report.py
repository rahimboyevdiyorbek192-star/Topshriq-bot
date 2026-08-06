"""Svodkani PNG rasm ko'rinishida yaratish (Pillow)."""
from __future__ import annotations

import io
import os
from datetime import datetime
from zoneinfo import ZoneInfo

import aiosqlite

try:
    from PIL import Image, ImageDraw, ImageFont
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False


# Ranglar
COL_HEADER_BG = (31, 78, 120)    # Ko'k
COL_HEADER_FG = (255, 255, 255)
COL_DONE_BG   = (198, 239, 206)  # Yashil
COL_MISS_BG   = (255, 199, 206)  # Qizil
COL_ALT_BG    = (242, 242, 242)  # Kul rang (alternating row)
COL_WHITE     = (255, 255, 255)
COL_BORDER    = (180, 180, 180)
COL_TEXT      = (30, 30, 30)
COL_TITLE_BG  = (13, 55, 92)

# O'lchamlar
ROW_H     = 38
HEADER_H  = 50
TITLE_H   = 48
STATS_H   = 40
COL_W_EMP = 220
COL_W_TSK = 90
COL_W_SUM = 70
PAD       = 10


def _find_font(size: int):
    """Kirill/O'zbek alifbosini qo'llab-quvvatlaydigan shrift izlaydi."""
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/TTF/DejaVuSans.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans.ttf",
        "C:/Windows/Fonts/arial.ttf",
        "C:/Windows/Fonts/calibri.ttf",
        "C:/Windows/Fonts/tahoma.ttf",
        "/Library/Fonts/Arial.ttf",
    ]
    if not PIL_AVAILABLE:
        return None
    for path in candidates:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    try:
        return ImageFont.load_default(size=size)
    except Exception:
        return ImageFont.load_default()


def _text_bbox(draw: "ImageDraw.ImageDraw", text: str, font) -> tuple[int, int]:
    """Matn kengligi va balandligini qaytaradi."""
    try:
        bbox = draw.textbbox((0, 0), text, font=font)
        return bbox[2] - bbox[0], bbox[3] - bbox[1]
    except Exception:
        return len(text) * 8, 14


def _centered_text(
    draw: "ImageDraw.ImageDraw",
    rect: tuple[int, int, int, int],
    text: str,
    font,
    color: tuple,
) -> None:
    x0, y0, x1, y1 = rect
    tw, th = _text_bbox(draw, text, font)
    tx = x0 + (x1 - x0 - tw) // 2
    ty = y0 + (y1 - y0 - th) // 2
    draw.text((tx, ty), text, fill=color, font=font)


def build_svodka_image(
    tasks: list[aiosqlite.Row],
    employees: list[aiosqlite.Row],
    submitted_map: dict[int, set[int]],  # {task_id: {emp_tg_id, ...}}
    tz: ZoneInfo,
) -> bytes | None:
    """Svodka jadvalini PNG baytlar sifatida yaratadi. Pillow bo'lmasa None."""
    if not PIL_AVAILABLE:
        return None

    n_tasks = len(tasks)
    n_emp   = len(employees)

    img_w = COL_W_EMP + n_tasks * COL_W_TSK + COL_W_SUM + 2
    img_h = TITLE_H + HEADER_H + n_emp * ROW_H + STATS_H + 2

    img  = Image.new("RGB", (img_w, img_h), COL_WHITE)
    draw = ImageDraw.Draw(img)

    font_title  = _find_font(15)
    font_header = _find_font(12)
    font_cell   = _find_font(11)
    font_bold   = _find_font(12)

    now_str = datetime.now(tz).strftime("%d.%m.%Y  %H:%M")

    # ── Sarlavha qatori ──────────────────────────────────────
    draw.rectangle([(0, 0), (img_w, TITLE_H)], fill=COL_TITLE_BG)
    _centered_text(
        draw, (0, 0, img_w, TITLE_H),
        f"TOPSHIRIQLAR SVODKASI  —  {now_str}",
        font_title, COL_HEADER_FG,
    )

    y = TITLE_H

    # ── Ustun sarlavhalari ───────────────────────────────────
    draw.rectangle([(0, y), (img_w, y + HEADER_H)], fill=COL_HEADER_BG)

    # Xodim ustuni
    draw.line([(COL_W_EMP, y), (COL_W_EMP, y + HEADER_H)], fill=COL_BORDER, width=1)
    _centered_text(draw, (0, y, COL_W_EMP, y + HEADER_H), "Xodim", font_header, COL_HEADER_FG)

    # Topshiriq ustunlari
    x = COL_W_EMP
    for t in tasks:
        label = f"#{t['id']}\n{t['title'][:12]}"
        x1 = x + COL_W_TSK
        draw.line([(x1, y), (x1, y + HEADER_H)], fill=COL_BORDER, width=1)
        _centered_text(draw, (x, y, x1, y + HEADER_H), f"#{t['id']}", font_header, COL_HEADER_FG)
        x = x1

    # Jami ustuni
    draw.line([(x, y), (x, y + HEADER_H)], fill=COL_BORDER, width=1)
    _centered_text(draw, (x, y, img_w, y + HEADER_H), "Jami", font_header, COL_HEADER_FG)

    y += HEADER_H

    # ── Xodimlar qatorlari ───────────────────────────────────
    task_done_counts = {t['id']: 0 for t in tasks}

    for i, emp in enumerate(employees):
        row_bg = COL_WHITE if i % 2 == 0 else COL_ALT_BG
        draw.rectangle([(0, y), (img_w, y + ROW_H)], fill=row_bg)

        # Xodim ismi
        draw.line([(COL_W_EMP, y), (COL_W_EMP, y + ROW_H)], fill=COL_BORDER, width=1)
        name = emp['full_name'][:28]
        tw, th = _text_bbox(draw, name, font_cell)
        draw.text((PAD, y + (ROW_H - th) // 2), name, fill=COL_TEXT, font=font_cell)

        done_count = 0
        x = COL_W_EMP
        for t in tasks:
            x1 = x + COL_W_TSK
            submitted = submitted_map.get(t['id'], set())
            is_done = emp['tg_id'] in submitted
            cell_bg = COL_DONE_BG if is_done else COL_MISS_BG
            cell_ch = "✓" if is_done else "✗"
            draw.rectangle([(x + 1, y + 1), (x1 - 1, y + ROW_H - 1)], fill=cell_bg)
            draw.line([(x1, y), (x1, y + ROW_H)], fill=COL_BORDER, width=1)
            _centered_text(draw, (x, y, x1, y + ROW_H), cell_ch, font_bold, COL_TEXT)
            if is_done:
                done_count += 1
                task_done_counts[t['id']] += 1
            x = x1

        # Jami
        draw.line([(x, y), (x, y + ROW_H)], fill=COL_BORDER, width=1)
        _centered_text(
            draw, (x, y, img_w, y + ROW_H),
            f"{done_count}/{n_tasks}", font_cell, COL_TEXT,
        )

        draw.line([(0, y + ROW_H), (img_w, y + ROW_H)], fill=COL_BORDER, width=1)
        y += ROW_H

    # ── Statistika qatori ────────────────────────────────────
    draw.rectangle([(0, y), (img_w, y + STATS_H)], fill=COL_HEADER_BG)
    x = COL_W_EMP
    _centered_text(draw, (0, y, COL_W_EMP, y + STATS_H), "JAMI", font_header, COL_HEADER_FG)
    for t in tasks:
        x1 = x + COL_W_TSK
        cnt = task_done_counts[t['id']]
        _centered_text(
            draw, (x, y, x1, y + STATS_H),
            f"{cnt}/{n_emp}", font_header, COL_HEADER_FG,
        )
        x = x1

    # Qator chegarasi
    draw.line([(0, y), (img_w, y)], fill=COL_BORDER, width=1)
    draw.rectangle([(0, 0), (img_w - 1, img_h - 1)], outline=COL_BORDER, width=1)

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()
