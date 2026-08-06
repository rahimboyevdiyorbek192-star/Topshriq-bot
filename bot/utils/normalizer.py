"""O'zbek matni normalizatsiyasi: Kirill/Lotin, katta/kichik harf, o'xshash belgilar."""
from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

# Tashqi ko'rinishi bir xil lekin turli kod nuqtali belgilar
# Lotin → Kirill
_LAT_TO_CYR: dict[str, str] = {
    'a': 'а', 'c': 'с', 'e': 'е', 'o': 'о', 'p': 'р', 'x': 'х',
    'A': 'А', 'B': 'В', 'C': 'С', 'E': 'Е', 'H': 'Н', 'K': 'К',
    'M': 'М', 'O': 'О', 'P': 'Р', 'T': 'Т', 'X': 'Х', 'Y': 'У',
}
_CYR_TO_LAT: dict[str, str] = {v: k for k, v in _LAT_TO_CYR.items()}

# O'zbek Lotin → Kirill to'liq jadval
_UZB_LAT_CYR: list[tuple[str, str]] = [
    ("sh", "ш"), ("ch", "ч"), ("ng", "нг"),
    ("o'", "ў"), ("O'", "Ў"), ("g'", "ғ"), ("G'", "Ғ"),
    ("yo", "ё"), ("ya", "я"), ("yu", "ю"),
    ("a", "а"), ("b", "б"), ("v", "в"), ("g", "г"), ("d", "д"),
    ("e", "е"), ("z", "з"), ("i", "и"), ("y", "й"), ("k", "к"),
    ("l", "л"), ("m", "м"), ("n", "н"), ("o", "о"), ("p", "п"),
    ("r", "р"), ("s", "с"), ("t", "т"), ("u", "у"), ("f", "ф"),
    ("x", "х"), ("q", "қ"), ("h", "ҳ"), ("j", "ж"),
]


def _count_script(text: str) -> tuple[int, int]:
    """Matndagi Kirill va Lotin harflar sonini qaytaradi."""
    cyr = sum(1 for c in text if 'Ѐ' <= c <= 'ӿ')
    lat = sum(1 for c in text if ('A' <= c <= 'Z') or ('a' <= c <= 'z'))
    return cyr, lat


def detect_script(text: str) -> str:
    """Asosiy alifboni aniqlaydi: 'cyr' | 'lat' | 'mixed' | 'other'."""
    cyr, lat = _count_script(text)
    if cyr == 0 and lat == 0:
        return 'other'
    if cyr > lat * 1.5:
        return 'cyr'
    if lat > cyr * 1.5:
        return 'lat'
    return 'mixed'


def to_uniform(text: str) -> str:
    """O'xshash ko'rinishli Lotin va Kirill belgilarni Lotinga o'tkazadi (taqqoslash uchun)."""
    result = []
    for ch in text:
        if ch in _CYR_TO_LAT:
            result.append(_CYR_TO_LAT[ch])
        else:
            result.append(ch)
    return ''.join(result)


def normalize_for_compare(text: str) -> str:
    """Taqqoslash uchun normalizatsiya: kichik harf + bir xil alifbo + bo'shliq."""
    text = str(text).strip()
    text = unicodedata.normalize('NFC', text)
    text = to_uniform(text)
    text = text.lower()
    text = re.sub(r'\s+', ' ', text)
    return text


def normalize_cell(value) -> str:
    """Jadval yacheykasi qiymatini tozalaydi."""
    if value is None:
        return ''
    text = str(value).strip()
    text = re.sub(r'\s+', ' ', text)
    return text


def similarity(a: str, b: str) -> float:
    """Ikki ustun nomi orasidagi o'xshashlik (0.0–1.0)."""
    na = normalize_for_compare(a)
    nb = normalize_for_compare(b)
    return SequenceMatcher(None, na, nb).ratio()


def find_best_match(
    query: str, candidates: list[str], threshold: float = 0.70
) -> str | None:
    """candidates ichidan eng o'xshashini qaytaradi yoki None."""
    best_score = 0.0
    best: str | None = None
    for c in candidates:
        s = similarity(query, c)
        if s > best_score:
            best_score = s
            best = c
    return best if best_score >= threshold else None


def build_column_mapping(
    source_headers: list[str], canonical: list[str]
) -> dict[str, str]:
    """source_headers → canonical mapping. Mos bo'lmasa: as-is."""
    mapping: dict[str, str] = {}
    for h in source_headers:
        match = find_best_match(h, canonical)
        mapping[h] = match if match else h
    return mapping


def find_canonical_headers(
    all_header_sets: list[list[str]],
    reference: list[str] | None = None,
) -> list[str]:
    """Barcha fayllarning ustun nomlari ichidan kanonik ro'yxat tuzadi."""
    if reference:
        return list(reference)
    if not all_header_sets:
        return []

    # Eng ko'p ustunli faylni asos qilamiz
    base = max(all_header_sets, key=len)
    canonical: list[str] = list(base)
    seen_norms = [normalize_for_compare(h) for h in canonical]

    for headers in all_header_sets:
        for h in headers:
            norm = normalize_for_compare(h)
            match_norm = find_best_match(norm, seen_norms, threshold=0.80)
            if match_norm is None:
                canonical.append(h)
                seen_norms.append(norm)

    return canonical
