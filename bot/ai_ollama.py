"""Ollama (mahalliy bepul AI) — AIClient bilan bir xil interfeys.

Arxitektura:
  • chat()             — Bosh AI muloqot (llama3 yoki boshqa model)
  • classify_message() — Xabar topshiriqmi? (kichik, tez)
  • read_image()       — Rasm o'qish (llava yoki vision model kerak)
  • analyze_table()    — Jadval tahlili
  • consolidate()      — Matn hisobotlarni birlashtirish
"""
from __future__ import annotations

import base64
import json
import logging
from typing import Any, Optional

import httpx

from .ai import (
    CLASSIFY_SYSTEM,
    CONSOLIDATE_SYSTEM,
    IMAGE_SYSTEM,
    TABLE_ANALYSIS_SYSTEM,
    BRAIN_SYSTEM,
    _parse_json,
)

# backwards-compat: ai_ollama exports CHAT_SYSTEM uchun
CHAT_SYSTEM = BRAIN_SYSTEM

logger = logging.getLogger(__name__)


class OllamaClient:
    """Ollama HTTP API orqali mahalliy modellar."""

    def __init__(
        self,
        base_url: str,
        model: str,
        vision_model: str | None = None,
    ) -> None:
        self.base_url     = base_url.rstrip("/")
        self.model        = model
        self.vision_model = vision_model or model  # Vision uchun alohida model (masalan llava)
        self._http        = httpx.AsyncClient(timeout=240.0)

    # ── Ichki HTTP so'rovi ────────────────────────────────────

    async def _chat_raw(
        self,
        system: str,
        messages: list[dict[str, Any]],
        model: str | None = None,
    ) -> str:
        payload_msgs = [{"role": "system", "content": system}] + messages
        used_model   = model or self.model
        try:
            r = await self._http.post(
                f"{self.base_url}/api/chat",
                json={"model": used_model, "messages": payload_msgs, "stream": False},
            )
            r.raise_for_status()
            return r.json().get("message", {}).get("content", "").strip()
        except httpx.ConnectError:
            logger.error(
                "Ollama ulanmadi: %s — ollama serve ishga tushirilganmi?",
                self.base_url,
            )
            return ""
        except Exception as exc:
            logger.warning("Ollama xatolik (%s): %s", used_model, exc)
            return ""

    async def _vision_raw(self, system: str, prompt: str, image_b64: str) -> str:
        """Rasm bilan so'rov (multimodal model kerak)."""
        payload = {
            "model": self.vision_model,
            "messages": [
                {"role": "system", "content": system},
                {
                    "role": "user",
                    "content": prompt,
                    "images": [image_b64],
                },
            ],
            "stream": False,
        }
        try:
            r = await self._http.post(f"{self.base_url}/api/chat", json=payload)
            r.raise_for_status()
            return r.json().get("message", {}).get("content", "").strip()
        except httpx.ConnectError:
            logger.error("Ollama (vision) ulanmadi: %s", self.base_url)
            return ""
        except Exception as exc:
            logger.warning("Ollama vision xatolik (%s): %s", self.vision_model, exc)
            return ""

    # ── 1. BOSH AI: erkin muloqot ─────────────────────────────

    async def chat(
        self, messages: list[dict[str, Any]], extra_context: str = ""
    ) -> str:
        system = BRAIN_SYSTEM
        if extra_context:
            system = f"{BRAIN_SYSTEM}\n\n--- JORIY HOLAT ---\n{extra_context}"
        text = await self._chat_raw(system, messages)
        return text or "⚠️ Mahalliy AI javob bermadi. Ollama ishga tushirilganligini tekshiring."

    # ── 2. YORDAMCHI: topshiriq klassifikatsiyasi ─────────────

    async def classify_message(
        self, text: str, has_files: bool = False
    ) -> dict[str, Any]:
        """Xabar topshiriqmi? → {is_task, confidence, title, deadline, description}"""
        prompt = text[:3000]
        if has_files:
            prompt += "\n\n[Xabarga fayl biriktirilgan]"
        raw = await self._chat_raw(
            CLASSIFY_SYSTEM,
            [{"role": "user", "content": prompt}],
        )
        result = _parse_json(raw)
        if result and isinstance(result.get("is_task"), bool):
            return result
        return {
            "is_task": has_files or len(text.strip()) >= 20,
            "confidence": 0.4,
            "title": "", "deadline": "", "description": "",
        }

    # ── 3. YORDAMCHI: rasm o'qish ─────────────────────────────

    async def read_image(
        self, image_bytes: bytes, hint: str = "", media_type: str = "image/jpeg"
    ) -> str:
        """Rasmdagi matn/jadvallarni o'qiydi (multimodal Ollama modeli kerak)."""
        b64    = base64.standard_b64encode(image_bytes).decode()
        prompt = hint or "Bu rasmdagi barcha jadval, matn va raqamlarni o'qib ber."
        text   = await self._vision_raw(IMAGE_SYSTEM, prompt, b64)
        return text

    # ── 4. YORDAMCHI: jadval tahlili ─────────────────────────

    async def analyze_table(
        self,
        headers: list[str],
        rows: list[dict[str, str]],
        task_context: str = "",
    ) -> dict[str, Any]:
        hdr_line   = " | ".join(headers)
        data_lines = [
            " | ".join(str(row.get(h, "")) for h in headers)
            for row in rows[:80]
        ]
        table_txt = hdr_line + "\n" + "\n".join(data_lines)

        prompt = ""
        if task_context:
            prompt = f"TOPSHIRIQ: {task_context}\n\n"
        prompt += f"JADVAL ({len(rows)} qator):\n{table_txt}"

        raw = await self._chat_raw(
            TABLE_ANALYSIS_SYSTEM,
            [{"role": "user", "content": prompt}],
        )
        return _parse_json(raw) or {}

    # ── 5. YORDAMCHI: matn hisobotlarni birlashtirish ─────────

    async def consolidate(
        self,
        task_title: str,
        task_desc: str,
        reports: list[tuple[str, str]],
    ) -> Optional[dict[str, Any]]:
        parts = [f"TOPSHIRIQ: {task_title}"]
        if task_desc:
            parts.append(f"TAVSIF: {task_desc}")
        parts.append(f"\nXODIMLAR HISOBOTLARI ({len(reports)} ta):")
        for i, (name, text) in enumerate(reports, 1):
            parts.append(f"\n═══ {i}. {name} ═══\n{text[:2000]}")

        raw = await self._chat_raw(
            CONSOLIDATE_SYSTEM,
            [{"role": "user", "content": "\n".join(parts)}],
        )
        return _parse_json(raw)

    # ── Eski nom (backwards compat) ───────────────────────────
    async def classify_task(self, message_text: str) -> dict[str, Any]:
        return await self.classify_message(message_text)

    async def close(self) -> None:
        await self._http.aclose()
