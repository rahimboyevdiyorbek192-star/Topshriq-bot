"""
Xodimlar fayllarini birlashtirish.
Asosiy qoida: topshiriq qanday formatda berilgan bo'lsa, umumiy ham SHU formatda chiqadi.
  • Excel topshiriq → barcha xodim Excel lari → bitta Excel
  • Word topshiriq  → barcha xodim Word lari  → bitta Word
  • PPT topshiriq   → barcha xodim PPT lari   → bitta PPT
  • Aralash         → Excel ga majburlaydi
"""
from __future__ import annotations

import io
import zipfile
from datetime import datetime
from zoneinfo import ZoneInfo

from .normalizer import (
    build_column_mapping,
    find_canonical_headers,
    normalize_cell,
)


# ── Fayldan jadval ma'lumotlarini ajratish ────────────────────

def _from_xlsx(data: bytes) -> tuple[list[str], list[list[str]]]:
    from openpyxl import load_workbook

    wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    for ws in wb.worksheets:
        all_rows = list(ws.iter_rows(values_only=True))
        for row_idx, row in enumerate(all_rows):
            cells = [normalize_cell(c) for c in row]
            non_empty = [c for c in cells if c]
            if non_empty:
                headers = [c for c in cells if c]
                rows = []
                for data_row in all_rows[row_idx + 1:]:
                    dc = [normalize_cell(c) for c in data_row]
                    if any(dc):
                        rows.append(dc[: len(headers)])
                wb.close()
                return headers, rows
    wb.close()
    return [], []


def _from_docx(data: bytes) -> tuple[list[str], list[list[str]]]:
    from docx import Document

    doc = Document(io.BytesIO(data))
    for table in doc.tables:
        table_rows = []
        for row in table.rows:
            cells = [normalize_cell(c.text) for c in row.cells]
            if any(cells):
                table_rows.append(cells)
        if len(table_rows) >= 2:
            headers = [c for c in table_rows[0] if c]
            rows = [r[: len(headers)] for r in table_rows[1:] if any(r)]
            return headers, rows
    return [], []


def _from_pptx(data: bytes) -> tuple[list[str], list[list[str]]]:
    from pptx import Presentation

    prs = Presentation(io.BytesIO(data))
    for slide in prs.slides:
        for shape in slide.shapes:
            if not shape.has_table:
                continue
            tbl = shape.table
            table_rows = []
            for row in tbl.rows:
                cells = [normalize_cell(c.text_frame.text) for c in row.cells]
                if any(cells):
                    table_rows.append(cells)
            if len(table_rows) >= 2:
                headers = [c for c in table_rows[0] if c]
                rows = [r[: len(headers)] for r in table_rows[1:] if any(r)]
                return headers, rows
    return [], []


def extract_table_from_xlsx(data: bytes) -> tuple[list[str], list[list[str]]]:
    return _from_xlsx(data)


def extract_table_from_file(data: bytes, filename: str) -> tuple[list[str], list[list[str]]]:
    name = (filename or "").lower()
    if name.endswith((".xlsx", ".xls")):
        return _from_xlsx(data)
    if name.endswith((".docx", ".doc")):
        return _from_docx(data)
    if name.endswith((".pptx", ".ppt")):
        return _from_pptx(data)
    return [], []


# ── Topshiriq shablonining formatini aniqlash ─────────────────

def detect_template_format(task_file_names: list[str]) -> str | None:
    """
    Topshiriq bilan biriktiriilgan fayllar nomiga qarab formatni aniqlaydi.
    Qaytaradi: 'xlsx' | 'docx' | 'pptx' | None
    """
    for fname in task_file_names:
        name = (fname or "").lower()
        if name.endswith(".xlsx") or name.endswith(".xls"):
            return "xlsx"
        if name.endswith(".docx") or name.endswith(".doc"):
            return "docx"
        if name.endswith(".pptx") or name.endswith(".ppt"):
            return "pptx"
    return None


# ── Jadvallarni birlashtirish (format-agnostik) ───────────────

def consolidate(
    reports: list[tuple[str, bytes, str]],  # (emp_name, file_bytes, file_name)
    reference_headers: list[str] | None = None,
) -> tuple[list[str], list[dict[str, str]]]:
    """
    Barcha xodim fayllarini o'qib kanonik headers va unified qatorlar qaytaradi.
    """
    all_headers: list[list[str]] = []
    parsed: list[tuple[str, list[str], list[list[str]]]] = []

    for emp_name, file_bytes, file_name in reports:
        try:
            hdrs, rows = extract_table_from_file(file_bytes, file_name)
        except Exception:
            hdrs, rows = [], []
        parsed.append((emp_name, hdrs, rows))
        if hdrs:
            all_headers.append(hdrs)

    canonical = find_canonical_headers(all_headers, reference=reference_headers)
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
                        canon = mapping.get(hdrs[j], hdrs[j])
                        row_dict[canon] = val
                unified.append(row_dict)
        else:
            unified.append({"Xodim": emp_name})

    return canonical, unified


# ── Format-ga qarab umumiy fayl yaratish ─────────────────────

def build_unified_xlsx(
    canonical: list[str],
    rows: list[dict[str, str]],
    task_title: str,
    tz: ZoneInfo,
) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    wb  = Workbook()
    ws  = wb.active
    ws.title = "Umumiy"

    header_fill = PatternFill("solid", fgColor="1F4E78")
    header_font = Font(bold=True, color="FFFFFF", size=11)
    center      = Alignment(horizontal="center", vertical="center", wrap_text=True)
    left        = Alignment(vertical="center", wrap_text=True)
    alt_fill    = PatternFill("solid", fgColor="EBF3FB")

    all_cols = ["Xodim"] + [h for h in canonical if h != "Xodim"]

    for j, col in enumerate(all_cols, 1):
        c = ws.cell(row=1, column=j, value=col)
        c.fill = header_fill
        c.font = header_font
        c.alignment = center

    for i, row_dict in enumerate(rows, 2):
        bg = PatternFill("solid", fgColor="FFFFFF" if i % 2 == 0 else "EBF3FB")
        for j, col in enumerate(all_cols, 1):
            c = ws.cell(row=i, column=j, value=row_dict.get(col, ""))
            c.fill = bg
            c.alignment = left

    ws.column_dimensions["A"].width = 28
    for j in range(2, len(all_cols) + 1):
        ws.column_dimensions[get_column_letter(j)].width = 18
    ws.freeze_panes = "B2"
    ws.row_dimensions[1].height = 30

    meta = wb.create_sheet("Ma'lumot")
    meta["A1"], meta["B1"] = "Topshiriq:", task_title
    meta["A2"], meta["B2"] = "Yaratilgan:", datetime.now(tz).strftime("%d.%m.%Y %H:%M")
    meta["A3"], meta["B3"] = "Xodimlar soni:", len({r.get("Xodim", "") for r in rows})

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def build_unified_docx(
    canonical: list[str],
    rows: list[dict[str, str]],
    task_title: str,
) -> bytes:
    from docx import Document
    from docx.oxml.ns import qn
    from docx.oxml import OxmlElement
    from docx.shared import Pt, RGBColor

    doc = Document()

    # Sarlavha
    heading = doc.add_heading(f"Umumiy hisobot: {task_title}", level=1)
    heading.runs[0].font.size = Pt(14)
    doc.add_paragraph(
        f"Yig'ilgan: {datetime.now().strftime('%d.%m.%Y %H:%M')}  |  "
        f"Xodimlar soni: {len({r.get('Xodim', '') for r in rows})}"
    )
    doc.add_paragraph()

    all_cols = ["Xodim"] + [h for h in canonical if h != "Xodim"]
    n_cols   = len(all_cols)
    n_rows   = len(rows)

    table = doc.add_table(rows=1 + n_rows, cols=n_cols)
    table.style = "Table Grid"

    # Sarlavha qatori
    hdr_row = table.rows[0]
    for j, col in enumerate(all_cols):
        cell = hdr_row.cells[j]
        cell.text = col
        # Ko'k fon
        tc_pr = cell._tc.get_or_add_tcPr()
        shd   = OxmlElement("w:shd")
        shd.set(qn("w:fill"), "1F4E78")
        shd.set(qn("w:color"), "auto")
        shd.set(qn("w:val"),   "clear")
        tc_pr.append(shd)
        # Oq qo'yruq matn
        for para in cell.paragraphs:
            for run in para.runs:
                run.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
                run.font.bold      = True
                run.font.size      = Pt(10)

    # Ma'lumot qatorlari
    for i, row_dict in enumerate(rows, 1):
        tbl_row = table.rows[i]
        for j, col in enumerate(all_cols):
            tbl_row.cells[j].text = row_dict.get(col, "")
            for para in tbl_row.cells[j].paragraphs:
                for run in para.runs:
                    run.font.size = Pt(9)

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def build_unified_pptx(
    canonical: list[str],
    rows: list[dict[str, str]],
    task_title: str,
) -> bytes:
    from pptx import Presentation
    from pptx.dml.color import RGBColor
    from pptx.util import Inches, Pt

    prs = Presentation()
    prs.slide_width  = Inches(13.33)
    prs.slide_height = Inches(7.5)

    # Muqova slayd
    title_layout = prs.slide_layouts[0]
    sld = prs.slides.add_slide(title_layout)
    sld.shapes.title.text = "Umumiy hisobot"
    if len(sld.placeholders) > 1:
        sld.placeholders[1].text = (
            f"{task_title}\n"
            f"{datetime.now().strftime('%d.%m.%Y %H:%M')}  |  "
            f"{len({r.get('Xodim', '') for r in rows})} xodim"
        )

    all_cols   = ["Xodim"] + [h for h in canonical if h != "Xodim"]
    n_cols     = len(all_cols)
    blank_lay  = prs.slide_layouts[6]
    chunk_size = 18  # har slaydda max qatorlar

    chunks = [rows[i: i + chunk_size] for i in range(0, max(1, len(rows)), chunk_size)]

    for c_idx, chunk in enumerate(chunks):
        sld    = prs.slides.add_slide(blank_lay)
        n_data = len(chunk)
        n_tot  = 1 + n_data

        left   = Inches(0.3)
        top    = Inches(0.5)
        width  = Inches(12.7)
        height = Inches(min(6.5, 0.35 * n_tot + 0.5))

        shape = sld.shapes.add_table(n_tot, n_cols, left, top, width, height)
        tbl   = shape.table

        # Sarlavha
        for j, col in enumerate(all_cols):
            cell = tbl.cell(0, j)
            cell.text = col
            cell.fill.solid()
            cell.fill.fore_color.rgb = RGBColor(0x1F, 0x4E, 0x78)
            for para in cell.text_frame.paragraphs:
                para.alignment = 1  # CENTER
                for run in para.runs:
                    run.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
                    run.font.bold      = True
                    run.font.size      = Pt(9)

        # Ma'lumotlar
        for i, row_dict in enumerate(chunk, 1):
            fill_color = RGBColor(0xEB, 0xF3, 0xFB) if i % 2 == 0 else RGBColor(0xFF, 0xFF, 0xFF)
            for j, col in enumerate(all_cols):
                cell = tbl.cell(i, j)
                cell.text = row_dict.get(col, "")
                cell.fill.solid()
                cell.fill.fore_color.rgb = fill_color
                for para in cell.text_frame.paragraphs:
                    for run in para.runs:
                        run.font.size = Pt(8)

        # Slayd raqami
        if len(chunks) > 1:
            txb = sld.shapes.add_textbox(Inches(12.5), Inches(7.0), Inches(0.8), Inches(0.4))
            txb.text_frame.text = f"{c_idx + 2}/{len(chunks) + 1}"

    buf = io.BytesIO()
    prs.save(buf)
    return buf.getvalue()


# ── Asosiy entry point ────────────────────────────────────────

def auto_consolidate(
    reports: list[tuple[str, bytes, str]],  # (emp_name, file_bytes, file_name)
    template_format: str | None,
    reference_headers: list[str] | None,
    task_title: str,
    tz: ZoneInfo,
) -> tuple[bytes, str]:
    """
    Barcha xodim fayllarini birlashtiradi.
    template_format: 'xlsx' | 'docx' | 'pptx' | None (None bo'lsa xlsx)
    Qaytaradi: (unified_file_bytes, file_extension)
    """
    canonical, unified_rows = consolidate(reports, reference_headers=reference_headers)

    fmt = template_format or "xlsx"

    if fmt == "docx":
        return build_unified_docx(canonical, unified_rows, task_title), "docx"
    if fmt == "pptx":
        return build_unified_pptx(canonical, unified_rows, task_title), "pptx"
    # default: xlsx
    return build_unified_xlsx(canonical, unified_rows, task_title, tz), "xlsx"


# ── ZIP arxiv ────────────────────────────────────────────────

def build_zip(
    employee_files: list[tuple[str, bytes, str]],  # (emp_name, bytes, filename)
    unified_file: bytes,
    unified_ext: str,
    task_id: int,
    task_title: str,
) -> bytes:
    safe_title = "".join(c for c in task_title[:30] if c.isalnum() or c in " _-").strip()
    buf = io.BytesIO()

    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for emp_name, file_bytes, file_name in employee_files:
            safe_emp = "".join(c for c in emp_name[:20] if c.isalnum() or c in " _-").strip()
            ext      = file_name.rsplit(".", 1)[-1] if "." in file_name else "bin"
            zf.writestr(f"xodimlar/{safe_emp}.{ext}", file_bytes)

        unified_name = f"UMUMIY_{safe_title or task_id}.{unified_ext}"
        zf.writestr(unified_name, unified_file)

    return buf.getvalue()


# Backwards-compat alias
build_unified_excel = build_unified_xlsx
