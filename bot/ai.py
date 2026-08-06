"""Claude (Anthropic) AI — asosiy mutaxassis miyasi.

Arxitektura:
  • chat()             — Asosiy bosh AI: rahbar bilan muloqot, tahlil, maslahat
  • classify_message() — Yordamchi: xabar topshiriqmi yoki yo'qligini aniqlaydi
  • read_image()       — Yordamchi: rasm/fotodagi jadval va matnni o'qiydi
  • analyze_table()    — Yordamchi: jadval ma'lumotlarini tahlil qiladi
  • consolidate()      — Yordamchi: matn hisobotlarni umumlashtiradi
"""
from __future__ import annotations

import base64
import json
import logging
from typing import Any, Optional

from anthropic import AsyncAnthropic

logger = logging.getLogger(__name__)


# ── System promptlar ─────────────────────────────────────────────

BRAIN_SYSTEM = """Sen "Robot Mutaxassis" — O'zbekistondagi tashkilotning aqlli xodim boshqarish \
yordamchisan. Rahbar va xodimlariga topshiriqlarni boshqarishda yordam berasan.

QOIDALAR:
- Har doim O'ZBEK tilida, samimiy, aniq va qisqa javob ber.
- Rahbarga: topshiriq tahlili, xodimlar unumdorligi, muddat nazorati, tavsiyalar ber.
- Xodimga: muddatlar, topshiriqlar tafsiloti, bajarish yo'llari haqida yordam ber.
- Haqiqiy mutaxassis kabi gapir — aniq raqam, aniq ism, aniq holat ayt.
- HECH QACHON salbiy yoki haqoratli fikr bildirma.

Bot imkoniyatlari (kerak bo'lsa eslatib qo'y):
- /svodka — kimlar bajardi/bajarmagani (rasm+matn)
- /reyting — xodimlar samaradorligi
- /umumlashtir N — barcha fayllarni birlashtirib ZIP
- /eslatma N — bajarmaganlarga eslatma
- /excel — svodkani Excel fayl"""

# ai_ollama.py ham shu konstantani import qiladi
CHAT_SYSTEM = BRAIN_SYSTEM

CLASSIFY_SYSTEM = """Sen topshiriq klassifikatorisan. Senga Telegram guruhidagi xabar beriladi.

TOPSHIRIQ belgilari (is_task: true):
- Xodimlardan biror narsa qilishni so'raydi (hisobot, jadval, ma'lumot tayyorlash)
- Muddat, deadline, sanа yoki vaqt ko'rsatilgan
- "bajarish", "tayyorlash", "yuboring", "to'ldiring", "kerak" kabi so'zlar bor
- Namuna fayl (Excel/Word/PPT) biriktirilib yuborilgan
- Rasmiy vazifa yoki topshiriq tarzida yozilgan

ODDIY XABAR belgilari (is_task: false):
- Salomlashish: "Salom", "Xayrli kun", "OK", "Tushundim", "Rahmat"
- Qisqa tasdiqlash: "Ha", "Yo'q", "Ko'rdim", "Bo'ladi", "Yaxshi"
- Bot komandalar: /svodka, /help, /menu va h.k.
- Faqat emoji yoki bitta-ikki so'z
- Savol-javob (ish topshiriq emas)
- Shaxsiy muloqot

FAQAT JSON qaytarasan (boshqa matn yozma):
{"is_task": true/false, "confidence": 0.0-1.0, "title": "sarlavha (qisqa)", "deadline": "DD.MM.YYYY HH:MM yoki bo'sh", "description": "qo'shimcha tavsif yoki bo'sh"}"""

IMAGE_SYSTEM = """Sen rasmlardagi ma'lumotlarni o'quvchi mutaxassissan.
Senga rasm beriladi. Rasmdagi BARCHA matn, jadval, raqam, sarlavha va muhim ma'lumotlarni o'qi.

Agar jadval bo'lsa — ustunlar va qatorlarni aniq ko'rsat:
Sarlavha1 | Sarlavha2 | Sarlavha3
Qiymat1   | Qiymat2   | Qiymat3

O'zbek, rus yoki ingliz tilida bo'lishi mumkin — barchasini qaytargin.
Faqat rasmdagi haqiqiy ma'lumotlarni yoz, hech narsa qo'shma."""

TABLE_ANALYSIS_SYSTEM = """Sen ish tahlilchisan. Senga birlashtirilgan xodimlar jadvali beriladi.
Jadvalning mazmuniga qarab CHUQUR tahlil qil.

FAQAT JSON qaytarasan:
{
  "summary": "Umumiy xulosa — nima maqsadda, qanday natija chiqdi (3-5 gap, o'zbek tilida)",
  "top_performers": ["eng yaxshi ishlagan xodimlar ismi (aniq raqamlar bilan)"],
  "low_performers": ["kam yoki noto'g'ri to'ldirgan xodimlar ismi"],
  "insights": ["diqqatga sazovor topilmalar, tendensiyalar, pattern-lar"],
  "anomalies": ["noto'g'ri to'ldirishlar, bo'sh qoldirilgan muhim ustunlar, g'ayrioddiy qiymatlar"],
  "recommendation": "Rahbarga tavsiya — nima qilish kerak"
}"""

CONSOLIDATE_SYSTEM = """Sen hisobotlarni umumlashtiruvchi tahlilchisan. Senga topshiriq va \
xodimlar hisobotlari beriladi.

Barcha hisobotlarni tahlil qilib, FAQAT JSON qaytarasan:
{
  "summary": "Barcha hisobotlar bo'yicha 3-6 gaplik xulosa (o'zbek tilida)",
  "key_points": ["asosiy natija 1", "asosiy natija 2", "asosiy natija 3"],
  "columns": ["Xodim", "ustun2", "ustun3"],
  "rows": [["xodim ismi", "qiymat", "qiymat"]]
}
- "columns" — taqqoslash jadvali ustunlari (birinchisi doim "Xodim")
- Jadval ustunlarini topshiriq mazmuniga qarab o'zing tanla
- Barcha matn o'zbek tilida"""


def _text_of(resp) -> str:
    return "".join(b.text for b in resp.content if b.type == "text").strip()


def _parse_json(text: str) -> Optional[dict[str, Any]]:
    if not text:
        return None
    start = text.find("{")
    end   = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        return None
    try:
        return json.loads(text[start: end + 1])
    except json.JSONDecodeError:
        return None


class AIClient:
    """Claude AI — asosiy bosh va yordamchi funksiyalar."""

    def __init__(self, api_key: str, model: str) -> None:
        self._client = AsyncAnthropic(api_key=api_key)
        self.model   = model

    # ── 1. BOSH AI: erkin muloqot ─────────────────────────────

    async def chat(
        self, messages: list[dict[str, Any]], extra_context: str = ""
    ) -> str:
        system = BRAIN_SYSTEM
        if extra_context:
            system = f"{BRAIN_SYSTEM}\n\n--- JORIY HOLAT ---\n{extra_context}"
        try:
            resp = await self._client.messages.create(
                model=self.model, max_tokens=4096,
                system=system, messages=messages,
            )
        except Exception as exc:
            logger.warning("AI chat xatolik: %s", exc)
            return "⚠️ AI bilan bog'lanishda xatolik. Keyinroq urinib ko'ring."
        if getattr(resp, "stop_reason", None) == "refusal":
            return "Kechirasiz, bu so'rovga javob bera olmayman."
        return _text_of(resp) or "…"

    # ── 2. YORDAMCHI: topshiriq klassifikatsiyasi ─────────────

    async def classify_message(
        self, text: str, has_files: bool = False
    ) -> dict[str, Any]:
        """Xabar topshiriqmi? → {is_task, confidence, title, deadline, description}"""
        prompt = text[:3000]
        if has_files:
            prompt += "\n\n[Xabarga fayl biriktirilgan]"
        try:
            resp = await self._client.messages.create(
                model=self.model, max_tokens=512,
                system=CLASSIFY_SYSTEM,
                messages=[{"role": "user", "content": prompt}],
            )
            result = _parse_json(_text_of(resp))
            if result and isinstance(result.get("is_task"), bool):
                return result
        except Exception as exc:
            logger.warning("classify_message xatolik: %s", exc)
        # Fallback: fayl bo'lsa topshiriq, aks holda heuristik
        return {
            "is_task": has_files or len(text.strip()) >= 20,
            "confidence": 0.4,
            "title": "", "deadline": "", "description": "",
        }

    # ── 3. YORDAMCHI: rasm o'qish (vision) ───────────────────

    async def read_image(
        self, image_bytes: bytes, hint: str = "", media_type: str = "image/jpeg"
    ) -> str:
        """Rasmdagi matn, jadval va raqamlarni o'qiydi."""
        b64 = base64.standard_b64encode(image_bytes).decode()
        prompt = hint or "Bu rasmdagi barcha jadval, matn va raqamlarni o'qib ber."
        try:
            resp = await self._client.messages.create(
                model=self.model, max_tokens=2048,
                system=IMAGE_SYSTEM,
                messages=[{
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": media_type,
                                "data": b64,
                            },
                        },
                        {"type": "text", "text": prompt},
                    ],
                }],
            )
            return _text_of(resp) or ""
        except Exception as exc:
            logger.warning("read_image xatolik: %s", exc)
            return ""

    # ── 4. YORDAMCHI: jadval tahlili ─────────────────────────

    async def analyze_table(
        self,
        headers: list[str],
        rows: list[dict[str, str]],
        task_context: str = "",
    ) -> dict[str, Any]:
        """Birlashtirilgan jadvaldan AI xulosasi."""
        # Jadvalni matn ko'rinishiga o'tkazish
        hdr_line = " | ".join(headers)
        data_lines = []
        for row in rows[:80]:  # Max 80 qator
            data_lines.append(" | ".join(str(row.get(h, "")) for h in headers))
        table_txt = hdr_line + "\n" + "\n".join(data_lines)

        prompt = ""
        if task_context:
            prompt = f"TOPSHIRIQ: {task_context}\n\n"
        prompt += f"JADVAL ({len(rows)} qator):\n{table_txt}"

        try:
            resp = await self._client.messages.create(
                model=self.model, max_tokens=2048,
                system=TABLE_ANALYSIS_SYSTEM,
                messages=[{"role": "user", "content": prompt}],
            )
            return _parse_json(_text_of(resp)) or {}
        except Exception as exc:
            logger.warning("analyze_table xatolik: %s", exc)
            return {}

    # ── 5. YORDAMCHI: matn hisobotlarni birlashtirish ─────────

    async def consolidate(
        self,
        task_title: str,
        task_desc: str,
        reports: list[tuple[str, str]],
    ) -> Optional[dict[str, Any]]:
        """Xodimlar matn hisobotlarini umumlashtiradi."""
        parts = [f"TOPSHIRIQ: {task_title}"]
        if task_desc:
            parts.append(f"TAVSIF: {task_desc}")
        parts.append(f"\nXODIMLAR HISOBOTLARI ({len(reports)} ta):")
        for i, (name, text) in enumerate(reports, 1):
            parts.append(f"\n═══ {i}. {name} ═══\n{text[:2500]}")

        try:
            resp = await self._client.messages.create(
                model=self.model, max_tokens=8192,
                system=CONSOLIDATE_SYSTEM,
                messages=[{"role": "user", "content": "\n".join(parts)}],
            )
            return _parse_json(_text_of(resp))
        except Exception as exc:
            logger.warning("AI consolidate xatolik: %s", exc)
            return None

    # ── Eski nom (backwards compat) ───────────────────────────
    async def classify_task(self, message_text: str) -> dict[str, Any]:
        return await self.classify_message(message_text)
