"""Ollama llava orqali ekran tahlili va keyingi harakatni aniqlash."""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)

AGENT_SYSTEM = """\
Sen avtonom kompyuter boshqaruv agentisar. Senga ekran rasmi va foydalanuvchi vazifasi beriladi.
Har qadam uchun bir harakat tanlay va JSON formatida javob ber.

JSON formatting qoidalar:
- Faqat JSON chiqar, boshqa hech narsa yozma
- "thought": nima ko'ryapsan va nima qilish kerakligi haqida qisqa o'ylaming
- "action": quyidagilardan biri: click, double_click, right_click, type, key, scroll, move, done
- "x", "y": rasm koordinatalari (faqat click/double_click/right_click/scroll/move uchun)
- "text": yoziladigan matn (faqat type uchun)
- "key": tugma kombinatsiyasi (faqat key uchun), masalan: "enter", "ctrl+a", "win", "alt+f4"
- "scroll_amount": skroll miqdori (manfiy = pastga, musbat = yuqoriga), masalan: -3
- "done": true — vazifa bajarildi
- "message": foydalanuvchiga o'zbek tilida qisqa xabar

Muhim qoidalar:
1. Har doim faqat bitta harakatni bajara — navbatdagi eng mantiqli qadam
2. Agar vazifa bajarilgan bo'lsa done=true qo'y
3. Agar 3 marta urinib bajarolmasang done=true + xato xabar
4. Koordinatalar berilgan rasm o'lchamiga mos bo'lishi kerak

Javob namunasi:
{"thought": "Ekranda Chrome ko'rinmoqda, URL qatorini bosishim kerak", "action": "click", "x": 640, "y": 45, "text": null, "key": null, "scroll_amount": null, "done": false, "message": "URL qatorini bosyapman"}
"""


class OllamaVision:
    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        vision_model: str = "llava",
        timeout: int = 60,
    ) -> None:
        self.base_url   = base_url.rstrip("/")
        self.model      = vision_model
        self.timeout    = timeout

    async def decide_action(
        self,
        task: str,
        history: list[str],
        screenshot_b64: str,
        step: int,
        max_steps: int,
    ) -> dict[str, Any]:
        """Ekran rasmini ko'rib, keyingi harakatni JSON sifatida qaytaradi."""

        hist_text = ""
        if history:
            recent = history[-5:]          # oxirgi 5 qadam
            hist_text = "Oldingi qadamlar:\n" + "\n".join(
                f"  {i+1}. {h}" for i, h in enumerate(recent)
            )

        user_prompt = (
            f"Vazifa: {task}\n\n"
            f"Qadam: {step}/{max_steps}\n"
            f"{hist_text}\n\n"
            "Ekran rasmiga qarab, vazifani bajarish uchun KEYINGI bitta harakatni JSON formatida yoz."
        )

        payload = {
            "model":  self.model,
            "stream": False,
            "messages": [
                {"role": "system",  "content": AGENT_SYSTEM},
                {
                    "role":    "user",
                    "content": user_prompt,
                    "images":  [screenshot_b64],
                },
            ],
            "options": {
                "temperature": 0.1,
                "num_predict": 512,
            },
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(
                    f"{self.base_url}/api/chat",
                    json=payload,
                )
                resp.raise_for_status()
                raw = resp.json()["message"]["content"].strip()

            return self._parse(raw)

        except httpx.ConnectError:
            logger.error("Ollama server topilmadi: %s", self.base_url)
            return self._error("Ollama server ishlamayapti. Avval 'ollama serve' buyrug'ini ishga tushiring.")
        except Exception as exc:
            logger.error("Ollama xato: %s", exc)
            return self._error(f"AI xato: {exc}")

    @staticmethod
    def _parse(raw: str) -> dict[str, Any]:
        """JSON ni raw matndan ajratib oladi."""
        # Markdown code block ichida bo'lsa tozalash
        raw = re.sub(r"^```(?:json)?\s*", "", raw.strip(), flags=re.IGNORECASE)
        raw = re.sub(r"\s*```$", "", raw.strip())

        # JSON topish
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if m:
            try:
                data = json.loads(m.group())
                # Majburiy maydonlarni tekshirish
                action = data.get("action", "done")
                return {
                    "thought":       data.get("thought", ""),
                    "action":        action,
                    "x":             data.get("x"),
                    "y":             data.get("y"),
                    "text":          data.get("text"),
                    "key":           data.get("key"),
                    "scroll_amount": data.get("scroll_amount", -3),
                    "done":          bool(data.get("done", action == "done")),
                    "message":       data.get("message", ""),
                }
            except json.JSONDecodeError:
                pass

        logger.warning("JSON parse xato: %r", raw[:200])
        return OllamaVision._error("AI javobini tushunmadim, qayta urinaman...")

    @staticmethod
    def _error(msg: str) -> dict[str, Any]:
        return {
            "thought":       "",
            "action":        "done",
            "x":             None, "y": None,
            "text":          None, "key": None,
            "scroll_amount": None,
            "done":          True,
            "message":       msg,
        }
