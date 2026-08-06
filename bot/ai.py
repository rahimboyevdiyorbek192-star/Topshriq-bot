"""Claude (Anthropic) sun'iy intellekt bilan ishlash — muloqot va umumlashtirish."""
from __future__ import annotations

import json
import logging
from typing import Any, Optional

from anthropic import AsyncAnthropic

logger = logging.getLogger(__name__)

CHAT_SYSTEM = """Sen "Topshiriq Mutaxassisi" nomli aqlli yordamchisan — rahbar va uning \
xodimlariga topshiriqlarni boshqarishda yordam berasan. Telegram bot ichida ishlaysan.

QOIDALAR:
- Har doim O'ZBEK tilida, samimiy va tushunarli javob ber.
- Qisqa va aniq javob ber, ortiqcha gaplashma.
- Rahbarga topshiriq matnini tuzishga, muddat belgilashga, xodimlar ishini \
tahlil qilishga yordam ber.
- Xodimga o'z topshiriqlari, muddatlari va ularni qanday bajarish bo'yicha yordam ber.
- Agar foydalanuvchi topshiriq yozishni so'rasa, tayyor namuna matn taklif qil \
(sarlavha, muddat, tavsif ko'rinishida).

Bot imkoniyatlari (kerak bo'lsa eslatib qo'y):
- Rahbar topshiriqlar guruhiga #topshiriq bilan topshiriq yozadi.
- Xodimlar ijro guruhiga reply qilib yoki #T3 yozib ishni topshiradi.
- /svodka, /excel, /eslatma, /umumlashtir komandalar mavjud."""

CONSOLIDATE_SYSTEM = """Sen hisobotlarni umumlashtiruvchi tahlilchisan. Senga bitta topshiriq \
va uni bajargan bir nechta xodimning hisoboti (fayl matni) beriladi.

Vazifang: barcha hisobotlarni tahlil qilib, quyidagi JSON formatida NATIJA qaytar. \
FAQAT JSON qaytar, boshqa hech qanday matn yozma:

{
  "summary": "Barcha hisobotlar bo'yicha 3-6 gaplik umumiy xulosa (o'zbek tilida)",
  "key_points": ["asosiy natija 1", "asosiy natija 2", "..."],
  "columns": ["Xodim", "ustun2", "ustun3"],
  "rows": [["xodim ismi", "qiymat", "qiymat"], ["...", "...", "..."]]
}

- "columns" — taqqoslash jadvalining ustun nomlari (birinchisi doim "Xodim").
- "rows" — har bir xodim uchun bitta qator, ustunlarga mos qiymatlar.
- Jadval ustunlarini topshiriq mazmuniga qarab o'zing tanla (masalan: bajarilgan ish, \
raqamlar, holat, izoh).
- Barcha matn o'zbek tilida bo'lsin."""


class AIClient:
    def __init__(self, api_key: str, model: str) -> None:
        self._client = AsyncAnthropic(api_key=api_key)
        self.model = model

    async def chat(
        self, messages: list[dict[str, Any]], extra_context: str = ""
    ) -> str:
        """Foydalanuvchi bilan erkin muloqot."""
        system = CHAT_SYSTEM
        if extra_context:
            system = f"{CHAT_SYSTEM}\n\n--- JORIY HOLAT ---\n{extra_context}"
        try:
            resp = await self._client.messages.create(
                model=self.model,
                max_tokens=6000,
                system=system,
                messages=messages,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("AI chat xatolik: %s", exc)
            return "⚠️ AI bilan bog'lanishда xatolik yuz berdi. Keyinroq urinib ko'ring."
        if resp.stop_reason == "refusal":
            return "Kechirasiz, bu so'rovga javob bera olmayman."
        return _text_of(resp) or "…"

    async def consolidate(
        self, task_title: str, task_desc: str, reports: list[tuple[str, str]]
    ) -> Optional[dict[str, Any]]:
        """Xodimlar hisobotlarini umumlashtiradi. Natija dict yoki None."""
        parts = [f"TOPSHIRIQ: {task_title}"]
        if task_desc:
            parts.append(f"TAVSIF: {task_desc}")
        parts.append(f"\nXODIMLAR HISOBOTLARI ({len(reports)} ta):")
        for i, (name, text) in enumerate(reports, 1):
            parts.append(f"\n═══ {i}. {name} ═══\n{text}")
        user_content = "\n".join(parts)

        try:
            resp = await self._client.messages.create(
                model=self.model,
                max_tokens=12000,
                system=CONSOLIDATE_SYSTEM,
                messages=[{"role": "user", "content": user_content}],
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("AI umumlashtirish xatolik: %s", exc)
            return None
        if resp.stop_reason == "refusal":
            return None
        return _parse_json(_text_of(resp))


def _text_of(resp) -> str:
    return "".join(b.text for b in resp.content if b.type == "text").strip()


def _parse_json(text: str) -> Optional[dict[str, Any]]:
    if not text:
        return None
    # Modeldan kelgan matndan birinchi { ... } bloknи ajratib olamiz
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        return None
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None
