"""Topshiriq matnidan muddat (deadline) va sarlavhani ajratib olish."""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

# "Muddat:", "Muddati:", "muddat -", "срок:" kabi qatorlar
_DEADLINE_LABEL = re.compile(
    r"(?:muddat(?:i)?|срок|deadline)\s*[:\-–]?\s*(.+)", re.IGNORECASE
)

# Sana + vaqt: 07.08.2026 17:00 | 7.8 17:00 | 2026-08-07 17:00
_DATETIME_PATTERNS = [
    (re.compile(r"(\d{4})[.\-/](\d{1,2})[.\-/](\d{1,2})[ tT]+(\d{1,2})[:.](\d{2})"), "ymd"),
    (re.compile(r"(\d{1,2})[.\-/](\d{1,2})[.\-/](\d{4})\s+(\d{1,2})[:.](\d{2})"), "dmy"),
    (re.compile(r"(\d{1,2})[.\-/](\d{1,2})\s+(\d{1,2})[:.](\d{2})"), "dm"),
]

# Faqat vaqt: "soat 17:00", "17:00", "17.00"
_TIME_ONLY = re.compile(r"(?:soat\s*)?(\d{1,2})[:.](\d{2})", re.IGNORECASE)


def _clamp_time(h: int, m: int) -> tuple[int, int] | None:
    if 0 <= h <= 23 and 0 <= m <= 59:
        return h, m
    return None


def parse_deadline(text: str, tz: ZoneInfo, now: datetime | None = None) -> datetime | None:
    """Matndan muddatni topib, mahalliy vaqt mintaqasidagi datetime qaytaradi.

    Topilmasa None qaytaradi. "Muddat:" belgisidan keyingi qism ustuvor.
    """
    if not text:
        return None
    now = now or datetime.now(tz)

    # Avval "Muddat:" belgili qatorni izlaymiz, keyin butun matnni.
    candidates: list[str] = []
    for line in text.splitlines():
        m = _DEADLINE_LABEL.search(line)
        if m:
            candidates.append(m.group(1).strip())
    candidates.append(text)

    for chunk in candidates:
        dt = _extract_datetime(chunk, tz, now)
        if dt:
            return dt
    return None


def _extract_datetime(chunk: str, tz: ZoneInfo, now: datetime) -> datetime | None:
    for pattern, kind in _DATETIME_PATTERNS:
        m = pattern.search(chunk)
        if not m:
            continue
        try:
            if kind == "ymd":
                y, mo, d, h, mi = (int(x) for x in m.groups())
            elif kind == "dmy":
                d, mo, y, h, mi = (int(x) for x in m.groups())
            else:  # dm — yil joriy yildan olinadi
                d, mo, h, mi = (int(x) for x in m.groups())
                y = now.year
            hm = _clamp_time(h, mi)
            if hm is None:
                continue
            dt = datetime(y, mo, d, hm[0], hm[1], tzinfo=tz)
            # "dm" da o'tgan sana bo'lsa kelasi yilga o'tkazamiz
            if kind == "dm" and dt < now - timedelta(hours=1):
                dt = dt.replace(year=y + 1)
            return dt
        except ValueError:
            continue

    # Faqat vaqt topilsa — bugungi kun (o'tgan bo'lsa ertaga)
    m = _TIME_ONLY.search(chunk)
    if m:
        hm = _clamp_time(int(m.group(1)), int(m.group(2)))
        if hm:
            dt = now.replace(hour=hm[0], minute=hm[1], second=0, microsecond=0)
            if dt < now:
                dt += timedelta(days=1)
            return dt
    return None


_WEEKDAYS_UZ = ["Dushanba", "Seshanba", "Chorshanba", "Payshanba", "Juma", "Shanba", "Yakshanba"]


def format_deadline(deadline_iso: str | None, tz: ZoneInfo) -> str:
    if not deadline_iso:
        return "muddatsiz"
    try:
        dt = datetime.fromisoformat(deadline_iso)
    except ValueError:
        return deadline_iso
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=tz)
    else:
        # Web orqali kelgan muddat UTC bo'lishi mumkin — mahalliy vaqtga o'giramiz
        dt = dt.astimezone(tz)
    wd = _WEEKDAYS_UZ[dt.weekday()]
    return f"{dt.strftime('%d.%m.%Y %H:%M')} ({wd})"


def humanize_left(deadline_iso: str | None, tz: ZoneInfo, now: datetime | None = None) -> str:
    """Muddatgacha qolgan vaqtni matn ko'rinishida qaytaradi."""
    if not deadline_iso:
        return ""
    try:
        dt = datetime.fromisoformat(deadline_iso)
    except ValueError:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=tz)
    now = now or datetime.now(tz)
    delta = dt - now
    total_min = int(delta.total_seconds() // 60)
    if total_min < 0:
        past = -total_min
        d, h, m = past // 1440, (past % 1440) // 60, past % 60
        parts = []
        if d:
            parts.append(f"{d} kun")
        if h:
            parts.append(f"{h} soat")
        if m and not d:
            parts.append(f"{m} daqiqa")
        return "⏱ " + " ".join(parts) + " kechikdi"
    d, h, m = total_min // 1440, (total_min % 1440) // 60, total_min % 60
    parts = []
    if d:
        parts.append(f"{d} kun")
    if h:
        parts.append(f"{h} soat")
    if m and not d:
        parts.append(f"{m} daqiqa")
    return "⏳ " + " ".join(parts) + " qoldi" if parts else "⏳ vaqt tugadi"
