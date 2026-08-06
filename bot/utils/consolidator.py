"""Xodimlar fayllarini birlashtirib umumiy jadval va ZIP yaratish."""
from __future__ import annotations

import io
import zipfile
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from .normalizer import (
    build_column_mapping,
    find_canonical_headers,
    normalize_cell,
    normalize_for_compare,
)


# ── Fayldan jadval ma'lumotlarini olish ──────────────────────

def extract_table_from_xlsx(data: bytes) -> tuple[list[str], list[list[str]]]:
    """Excel faylidan sarlavhalar va qatorlarni qaytaradi."""
    from openpyxl import load_workbook

    wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    headers: list[str] = []
    rows: list[list[str]] = []

    for ws in wb.worksheets:
        all_rows = list(ws.iter_rows(values_only=True))
        if not all_rows:
            continue
        # Sarlavha qatori — birinchi bo'sh bo'lmagan qator
        for row_idx, row in enumerate(all_rows):
            cells = [normalize_cell(c) for c in row]
            non_empty = [c for c in cells if c]
            if non_empty:
                headers = [c for c in cells if c]
                # Qolgan qatorlar — ma'lumotlar
                for data_row in all_rows[row_idx + 1:]:
                    dc = [normalize_cell(c) for c in data_row]
                    if any(dc):
                        rows.append(dc[:len(headers)])
                break
        if headers:
            break

    wb.close()
    return headers, rows


def extract_table_from_docx(data: bytes) -> tuple[list[str], list[list[str]]]:
    """Word faylidan jadval sarlavhalar va qatorlarni qaytaradi."""
    from docx import Document

    doc = Document(io.BytesIO(data))
    headers: list[str] = []
    rows: list[list[str]] = []

    for table in doc.tables:
        table_rows = []
        for row in table.rows:
            cells = [normalize_cell(c.text) for c in row.cells]
            if any(cells):
                table_rows.append(cells)
        if len(table_rows) >= 2:
            headers = [c for c in table_rows[0] if c]
            for row in table_rows[1:]:
                if any(row):
                    rows.append(row[:len(headers)])
            break  # Birinchi jadval yetarli

    return headers, rows


def extract_table_from_file(data: bytes, filename: str) -> tuple[list[str], list[list[str]]]:
    """Fayl nomiga qarab to'g'ri funksiyani chaqiradi."""
    name = (filename or "").lower()
    if name.endswith(".xlsx") or name.endswith(".xls"):
        return extract_table_from_xlsx(data)
    if name.endswith(".docx") or name.endswith(".doc"):
        return extract_table_from_docx(data)
    return [], []


# ── Umumiy jadval tuzish ─────────────────────────────────────

def consolidate(
    reports: list[tuple[str, bytes, str]],   # (emp_name, file_bytes, file_name)
    reference_headers: list[str] | None = None,
) -> tuple[list[str], list[dict[str, str]]]:
    """
    Barcha xodimlar fayllarini umumlashtiradi.
    Qaytaradi: (canonical_headers, unified_rows)
    unified_rows — har bir qatorda 'Xodim' ham bor.
    """
    all_file_headers: list[list[str]] = []
    parsed: list[tuple[str, list[str], list[list[str]]]] = []

    for emp_name, file_bytes, file_name in reports:
        try:
            hdrs, rows = extract_table_from_file(file_bytes, file_name)
        except Exception:
            hdrs, rows = [], []
        parsed.append((emp_name, hdrs, rows))
        if hdrs:
            all_file_headers.append(hdrs)

    canonical = find_canonical_headers(all_file_headers, reference=reference_headers)
    if not canonical:
        canonical = ["Ma'lumot"]

    unified: list[dict[str, str]] = []
    for emp_name, hdrs, rows in parsed:
        mapping = build_column_mapping(hdrs, canonical) if hdrs else {}
        if rows:
            for row in rows:
                row_dict: dict[str, str] = {"Xodim": emp_name}
                for j, val in enumerate(row):
                    if j < len(hdrs):
                        canon_col = mapping.get(hdrs[j], hdrs[j])
                        row_dict[canon_col] = val
                unified.append(row_dict)
        else:
            # Fayl bo'sh yoki jadval yo'q: faqat xodim ismi
            unified.append({"Xodim": emp_name})

    return canonical, unified


# ── Umumiy Excel yaratish ────────────────────────────────────

def build_unified_excel(
    canonical_headers: list[str],
    unified_rows: list[dict[str, str]],
    task_title: str,
    tz: ZoneInfo,
) -> bytes:
    """Umumlashtirilgan Excel faylini yaratadi."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill

    wb = Workbook()
    ws = wb.active
    ws.title = "Umumiy"

    header_fill = PatternFill("solid", fgColor="1F4E78")
    header_font = Font(bold=True, color="FFFFFF", size=11)
    center      = Alignment(horizontal="center", vertical="center", wrap_text=True)
    left        = Alignment(vertical="center", wrap_text=True)
    alt_fill    = PatternFill("solid", fgColor="EBF3FB")

    all_cols = ["Xodim"] + [h for h in canonical_headers if h != "Xodim"]

    # Sarlavha
    for j, col in enumerate(all_cols, 1):
        c = ws.cell(row=1, column=j, value=col)
        c.fill   = header_fill
        c.font   = header_font
        c.alignment = center

    # Ma'lumotlar
    for i, row_dict in enumerate(unified_rows, 2):
        fill = PatternFill("solid", fgColor="FFFFFF") if i % 2 == 0 else alt_fill
        for j, col in enumerate(all_cols, 1):
            c = ws.cell(row=i, column=j, value=row_dict.get(col, ""))
            c.fill      = fill
            c.alignment = left

    # Ustun kengligi
    ws.column_dimensions["A"].width = 28
    for j in range(2, len(all_cols) + 1):
        from openpyxl.utils import get_column_letter
        ws.column_dimensions[get_column_letter(j)].width = 18
    ws.freeze_panes = "B2"
    ws.row_dimensions[1].height = 30

    # Meta
    ws2 = wb.create_sheet("Ma'lumot")
    ws2["A1"] = "Topshiriq:"
    ws2["B1"] = task_title
    ws2["A2"] = "Yaratilgan:"
    ws2["B2"] = datetime.now(tz).strftime("%d.%m.%Y %H:%M")
    ws2["A3"] = "Xodimlar soni:"
    ws2["B3"] = len({r.get("Xodim", "") for r in unified_rows})

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ── ZIP arxiv yaratish ───────────────────────────────────────

def build_zip(
    employee_files: list[tuple[str, bytes, str]],  # (emp_name, bytes, filename)
    unified_excel: bytes,
    task_id: int,
    task_title: str,
) -> bytes:
    """Barcha xodim fayllarini + umumiy jadvalni ZIP ga yig'adi."""
    buf = io.BytesIO()
    safe_title = "".join(c for c in task_title[:30] if c.isalnum() or c in " _-").strip()

    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for emp_name, file_bytes, file_name in employee_files:
            safe_emp = "".join(c for c in emp_name[:20] if c.isalnum() or c in " _-").strip()
            ext = file_name.rsplit(".", 1)[-1] if "." in file_name else "bin"
            arcname = f"xodimlar/{safe_emp}.{ext}"
            zf.writestr(arcname, file_bytes)

        zf.writestr(f"UMUMIY_{safe_title or task_id}.xlsx", unified_excel)

    return buf.getvalue()
