"""Svodkani PNG rasm ko'rinishida yaratish.

Katta jadvallar uchun avtomatik miqyoslash:
  • 41 xodim × 15+ topshiriq — ustun kengligini kamaytiradi
  • Tasvirni 3200px dan oshirmaydi (Telegram limiti)
  • Agar 20+ topshiriq bo'lsa — ortiqchalari keyingi rasmlarga bo'linmaydi,
    faqat 20 ta ko'rsatiladi va izoh qo'shiladi.
"""
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
COL_HEADER_BG = (31, 78, 120)
COL_HEADER_FG = (255, 255, 255)
COL_DONE_BG   = (198, 239, 206)
COL_MISS_BG   = (255, 199, 206)
COL_ALT_BG    = (242, 242, 242)
COL_WHITE     = (255, 255, 255)
COL_BORDER    = (180, 180, 180)
COL_TEXT      = (30, 30, 30)
COL_TITLE_BG  = (13, 55, 92)
COL_NOTE_BG   = (255, 248, 220)

MAX_IMG_W = 3000   # px, Telegram foto limiti uchun
MAX_TASKS = 20     # Bir rasmda ko'rsatiladigan max topshiriqlar soni


def _find_font(size: int):
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


def _text_bbox(draw, text: str, font) -> tuple[int, int]:
    try:
        bbox = draw.textbbox((0, 0), text, font=font)
        return bbox[2] - bbox[0], bbox[3] - bbox[1]
    except Exception:
        return len(text) * 8, 14


def _centered_text(draw, rect: tuple, text: str, font, color: tuple) -> None:
    x0, y0, x1, y1 = rect
    tw, th = _text_bbox(draw, text, font)
    tx = x0 + max(0, (x1 - x0 - tw) // 2)
    ty = y0 + max(0, (y1 - y0 - th) // 2)
    draw.text((tx, ty), text, fill=color, font=font)


def _calc_sizes(n_tasks: int, n_emp: int) -> dict:
    """Jadval o'lchamlarini avtomatik hisoblaydi."""
    # Asosiy o'lchamlar
    col_w_emp = 200
    title_h   = 46
    header_h  = 48
    stats_h   = 38
    pad       = 8

    # Miqyoslash: ko'p topshiriq bo'lsa ustunlarni toraytirish
    if n_tasks <= 6:
        col_w_tsk = 90
    elif n_tasks <= 10:
        col_w_tsk = 80
    elif n_tasks <= 15:
        col_w_tsk = 68
    else:
        col_w_tsk = 58
    col_w_sum = 65

    # Miqyoslash: ko'p xodim bo'lsa qator balandligini kamaytirish
    if n_emp <= 15:
        row_h = 38
    elif n_emp <= 25:
        row_h = 32
    elif n_emp <= 40:
        row_h = 28
    else:
        row_h = 24

    img_w = col_w_emp + n_tasks * col_w_tsk + col_w_sum
    img_h = title_h + header_h + n_emp * row_h + stats_h + 2

    # MAX_IMG_W ni oshirmaslik
    if img_w > MAX_IMG_W:
        # Ustun kengligini proporsional kamaytirish
        available   = MAX_IMG_W - col_w_emp - col_w_sum
        col_w_tsk   = max(45, available // max(n_tasks, 1))
        img_w       = col_w_emp + n_tasks * col_w_tsk + col_w_sum

    return dict(
        col_w_emp=col_w_emp, col_w_tsk=col_w_tsk, col_w_sum=col_w_sum,
        title_h=title_h, header_h=header_h, stats_h=stats_h,
        row_h=row_h, pad=pad, img_w=img_w, img_h=img_h,
    )


def build_svodka_image(
    tasks: list[aiosqlite.Row],
    employees: list[aiosqlite.Row],
    submitted_map: dict[int, set[int]],
    tz: ZoneInfo,
) -> bytes | None:
    """Svodka jadvalini PNG baytlar sifatida yaratadi."""
    if not PIL_AVAILABLE:
        return None

    n_emp = len(employees)
    if n_emp == 0:
        return None

    # Max 20 ta topshiriq ko'rsatiladi
    tasks_shown = list(tasks[:MAX_TASKS])
    hidden_cnt  = len(tasks) - len(tasks_shown)
    n_tasks     = len(tasks_shown)

    if n_tasks == 0:
        return None

    s = _calc_sizes(n_tasks, n_emp)

    # Izoh qatori (agar yashirilgan topshiriqlar bo'lsa)
    note_h    = 30 if hidden_cnt > 0 else 0
    total_h   = s["img_h"] + note_h
    font_size_title  = max(11, min(14, 15 - n_tasks // 5))
    font_size_header = max(9,  min(12, 12 - n_tasks // 6))
    font_size_cell   = max(8,  min(11, 11 - n_tasks // 8))

    img  = Image.new("RGB", (s["img_w"], total_h), COL_WHITE)
    draw = ImageDraw.Draw(img)

    f_title  = _find_font(font_size_title)
    f_header = _find_font(font_size_header)
    f_cell   = _find_font(font_size_cell)

    now_str = datetime.now(tz).strftime("%d.%m.%Y  %H:%M")

    # Sarlavha
    draw.rectangle([(0, 0), (s["img_w"], s["title_h"])], fill=COL_TITLE_BG)
    _centered_text(
        draw, (0, 0, s["img_w"], s["title_h"]),
        f"TOPSHIRIQLAR SVODKASI  —  {now_str}",
        f_title, COL_HEADER_FG,
    )

    y = s["title_h"]

    # Ustun sarlavhalari
    draw.rectangle([(0, y), (s["img_w"], y + s["header_h"])], fill=COL_HEADER_BG)
    draw.line([(s["col_w_emp"], y), (s["col_w_emp"], y + s["header_h"])],
              fill=COL_BORDER, width=1)
    _centered_text(
        draw, (0, y, s["col_w_emp"], y + s["header_h"]),
        "Xodim", f_header, COL_HEADER_FG,
    )

    x = s["col_w_emp"]
    for t in tasks_shown:
        x1 = x + s["col_w_tsk"]
        draw.line([(x1, y), (x1, y + s["header_h"])], fill=COL_BORDER, width=1)
        _centered_text(
            draw, (x, y, x1, y + s["header_h"]),
            f"#{t['id']}", f_header, COL_HEADER_FG,
        )
        x = x1
    draw.line([(x, y), (x, y + s["header_h"])], fill=COL_BORDER, width=1)
    _centered_text(
        draw, (x, y, s["img_w"], y + s["header_h"]),
        "Jami", f_header, COL_HEADER_FG,
    )

    y += s["header_h"]

    # Xodimlar qatorlari
    task_done_counts = {t["id"]: 0 for t in tasks_shown}

    for i, emp in enumerate(employees):
        row_bg = COL_WHITE if i % 2 == 0 else COL_ALT_BG
        draw.rectangle([(0, y), (s["img_w"], y + s["row_h"])], fill=row_bg)

        # Ism
        draw.line([(s["col_w_emp"], y), (s["col_w_emp"], y + s["row_h"])],
                  fill=COL_BORDER, width=1)
        max_chars = max(10, s["col_w_emp"] // 9)
        name = emp["full_name"][:max_chars]
        _, th = _text_bbox(draw, name, f_cell)
        draw.text(
            (s["pad"], y + max(0, (s["row_h"] - th) // 2)),
            name, fill=COL_TEXT, font=f_cell,
        )

        done_count = 0
        x = s["col_w_emp"]
        for t in tasks_shown:
            x1       = x + s["col_w_tsk"]
            is_done  = emp["tg_id"] in submitted_map.get(t["id"], set())
            cell_bg  = COL_DONE_BG if is_done else COL_MISS_BG
            cell_ch  = "✓" if is_done else "✗"
            draw.rectangle([(x + 1, y + 1), (x1 - 1, y + s["row_h"] - 1)], fill=cell_bg)
            draw.line([(x1, y), (x1, y + s["row_h"])], fill=COL_BORDER, width=1)
            _centered_text(draw, (x, y, x1, y + s["row_h"]), cell_ch, f_cell, COL_TEXT)
            if is_done:
                done_count += 1
                task_done_counts[t["id"]] += 1
            x = x1

        draw.line([(x, y), (x, y + s["row_h"])], fill=COL_BORDER, width=1)
        _centered_text(
            draw, (x, y, s["img_w"], y + s["row_h"]),
            f"{done_count}/{n_tasks}", f_cell, COL_TEXT,
        )
        draw.line([(0, y + s["row_h"]), (s["img_w"], y + s["row_h"])],
                  fill=COL_BORDER, width=1)
        y += s["row_h"]

    # Statistika qatori
    draw.rectangle([(0, y), (s["img_w"], y + s["stats_h"])], fill=COL_HEADER_BG)
    _centered_text(
        draw, (0, y, s["col_w_emp"], y + s["stats_h"]),
        "JAMI", f_header, COL_HEADER_FG,
    )
    x = s["col_w_emp"]
    for t in tasks_shown:
        x1  = x + s["col_w_tsk"]
        cnt = task_done_counts[t["id"]]
        _centered_text(
            draw, (x, y, x1, y + s["stats_h"]),
            f"{cnt}/{n_emp}", f_header, COL_HEADER_FG,
        )
        x = x1
    y += s["stats_h"]

    # Yashirilgan topshiriqlar haqida izoh
    if hidden_cnt > 0:
        draw.rectangle([(0, y), (s["img_w"], y + note_h)], fill=COL_NOTE_BG)
        _centered_text(
            draw, (0, y, s["img_w"], y + note_h),
            f"+ yana {hidden_cnt} ta topshiriq ko'rsatilmadi. /svodka N — batafsil ko'rish.",
            f_cell, (100, 80, 0),
        )

    draw.rectangle(
        [(0, 0), (s["img_w"] - 1, total_h - 1)],
        outline=COL_BORDER, width=1,
    )

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()
