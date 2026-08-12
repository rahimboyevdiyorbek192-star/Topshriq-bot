"""AI provayderlar uchun umumiy asos.

Barcha yuqori darajadagi mantiq (prompt qurish, JSON tahlili, fallback'lar)
shu yerda bir marta yozilgan. Har bir provayder faqat ikkita ibtidoiy
amalni bajaradi:

  • _complete()        — matnli so'rov  → matn
  • _complete_vision() — rasmli so'rov  → matn

Shu tufayli Claude va Ollama o'rtasida kod takrorlanmaydi va yangi
provayder qo'shish uchun 30 qatordan kam kod yetarli.
"""
from __future__ import annotations

import abc
import json
import logging
from typing import Any, Optional

from .prompts import (
    BRAIN_SYSTEM,
    CLASSIFY_SYSTEM,
    CONSOLIDATE_SYSTEM,
    IMAGE_SYSTEM,
    TABLE_ANALYSIS_SYSTEM,
)

logger = logging.getLogger(__name__)

MAX_TABLE_ROWS   = 80      # Tahlilga yuboriladigan maksimal qator
MAX_REPORT_CHARS = 2500    # Bitta xodim hisobotidan olinadigan belgi


def parse_json(text: str) -> Optional[dict[str, Any]]:
    """Model javobidan birinchi JSON obyektini ajratib oladi."""
    if not text:
        return None
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1 or end < start:
        return None
    try:
        return json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return None


class AIProvider(abc.ABC):
    """Barcha AI provayderlari uchun umumiy interfeys."""

    name = "ai"

    # ── Provayder amalga oshiradigan ibtidoiy amallar ─────────

    @abc.abstractmethod
    async def _complete(
        self, system: str, messages: list[dict[str, Any]], max_tokens: int = 4096
    ) -> str:
        """Matnli so'rov yuboradi. Xato bo'lsa bo'sh satr qaytaradi."""

    @abc.abstractmethod
    async def _complete_vision(
        self, system: str, prompt: str, image_bytes: bytes, media_type: str
    ) -> str:
        """Rasmli so'rov yuboradi. Xato bo'lsa bo'sh satr qaytaradi."""

    async def close(self) -> None:
        """Ochiq ulanishlarni yopadi (kerak bo'lsa qayta aniqlanadi)."""

    # ── 1. Erkin muloqot ──────────────────────────────────────

    async def chat(self, messages: list[dict[str, Any]], extra_context: str = "") -> str:
        system = BRAIN_SYSTEM
        if extra_context:
            system = f"{BRAIN_SYSTEM}\n\n--- JORIY HOLAT ---\n{extra_context}"
        return await self._complete(system, messages) or (
            "⚠️ AI javob bermadi. Keyinroq urinib ko'ring."
        )

    # ── 2. Xabar topshiriqmi? ─────────────────────────────────

    async def classify_message(self, text: str, has_files: bool = False) -> dict[str, Any]:
        """→ {is_task, confidence, title, deadline, description}"""
        prompt = text[:3000]
        if has_files:
            prompt += "\n\n[Xabarga fayl biriktirilgan]"

        raw    = await self._complete(
            CLASSIFY_SYSTEM, [{"role": "user", "content": prompt}], max_tokens=512
        )
        result = parse_json(raw)
        if result and isinstance(result.get("is_task"), bool):
            return result

        # AI ishlamasa — oddiy heuristika
        return {
            "is_task":    has_files or len(text.strip()) >= 20,
            "confidence": 0.4,
            "title": "", "deadline": "", "description": "",
        }

    # ── 3. Rasmdagi matn va jadvalni o'qish ───────────────────

    async def read_image(
        self, image_bytes: bytes, hint: str = "", media_type: str = "image/jpeg"
    ) -> str:
        prompt = hint or "Bu rasmdagi barcha jadval, matn va raqamlarni o'qib ber."
        return await self._complete_vision(IMAGE_SYSTEM, prompt, image_bytes, media_type)

    # ── 4. Jadval tahlili ─────────────────────────────────────

    async def analyze_table(
        self, headers: list[str], rows: list[dict[str, str]], task_context: str = ""
    ) -> dict[str, Any]:
        lines = [" | ".join(headers)]
        for row in rows[:MAX_TABLE_ROWS]:
            lines.append(" | ".join(str(row.get(h, "")) for h in headers))

        prompt = f"TOPSHIRIQ: {task_context}\n\n" if task_context else ""
        prompt += f"JADVAL ({len(rows)} qator):\n" + "\n".join(lines)

        raw = await self._complete(
            TABLE_ANALYSIS_SYSTEM, [{"role": "user", "content": prompt}], max_tokens=2048
        )
        return parse_json(raw) or {}

    # ── 5. Hisobotlarni umumlashtirish ────────────────────────

    async def consolidate(
        self, task_title: str, task_desc: str, reports: list[tuple[str, str]]
    ) -> Optional[dict[str, Any]]:
        parts = [f"TOPSHIRIQ: {task_title}"]
        if task_desc:
            parts.append(f"TAVSIF: {task_desc}")
        parts.append(f"\nXODIMLAR HISOBOTLARI ({len(reports)} ta):")
        for i, (name, text) in enumerate(reports, 1):
            parts.append(f"\n═══ {i}. {name} ═══\n{text[:MAX_REPORT_CHARS]}")

        raw = await self._complete(
            CONSOLIDATE_SYSTEM, [{"role": "user", "content": "\n".join(parts)}],
            max_tokens=8192,
        )
        return parse_json(raw)
