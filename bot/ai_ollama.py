"""Ollama (mahalliy bepul AI) bilan ishlash — Claude AIClient bilan bir xil interfeys."""
from __future__ import annotations

import json
import logging
from typing import Any, Optional

import httpx

from .ai import CHAT_SYSTEM, CONSOLIDATE_SYSTEM, _parse_json

logger = logging.getLogger(__name__)


class OllamaClient:
    """Ollama HTTP API orqali mahalliy modellar bilan ishlash."""

    def __init__(self, base_url: str, model: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.model    = model
        self._http    = httpx.AsyncClient(timeout=180.0)

    async def _chat_raw(self, system: str, messages: list[dict[str, Any]]) -> str:
        """Ollama /api/chat endpointiga so'rov yuboradi."""
        payload_messages = [{"role": "system", "content": system}] + messages
        try:
            r = await self._http.post(
                f"{self.base_url}/api/chat",
                json={"model": self.model, "messages": payload_messages, "stream": False},
            )
            r.raise_for_status()
            data = r.json()
            return data.get("message", {}).get("content", "").strip()
        except httpx.ConnectError:
            logger.error("Ollama ulanmadi: %s (ishga tushirilganmi?)", self.base_url)
            return ""
        except Exception as exc:
            logger.warning("Ollama xatolik: %s", exc)
            return ""

    async def chat(
        self, messages: list[dict[str, Any]], extra_context: str = ""
    ) -> str:
        system = CHAT_SYSTEM
        if extra_context:
            system = f"{CHAT_SYSTEM}\n\n--- JORIY HOLAT ---\n{extra_context}"
        text = await self._chat_raw(system, messages)
        return text or "⚠️ Mahalliy AI javob bermadi. Ollama ishga tushirilganligini tekshiring."

    async def consolidate(
        self, task_title: str, task_desc: str, reports: list[tuple[str, str]]
    ) -> Optional[dict[str, Any]]:
        parts = [f"TOPSHIRIQ: {task_title}"]
        if task_desc:
            parts.append(f"TAVSIF: {task_desc}")
        parts.append(f"\nXODIMLAR HISOBOTLARI ({len(reports)} ta):")
        for i, (name, text) in enumerate(reports, 1):
            parts.append(f"\n═══ {i}. {name} ═══\n{text}")
        user_content = "\n".join(parts)

        text = await self._chat_raw(
            CONSOLIDATE_SYSTEM,
            [{"role": "user", "content": user_content}],
        )
        return _parse_json(text)

    async def classify_task(self, message_text: str) -> dict[str, Any]:
        """Xabar topshiriqmi yoki yo'qligini aniqlaydi."""
        system = (
            "Sen Telegram kanalida topshiriqlarni aniqlovchi tahlilchisan. "
            "Faqat JSON qaytarasan, boshqa hech narsa yozma.\n"
            "Qayt: {\"is_task\": true/false, \"title\": \"...\", "
            "\"deadline\": \"...\", \"description\": \"...\"}"
        )
        text = await self._chat_raw(
            system,
            [{"role": "user", "content": f"Bu xabar topshiriqmi?\n\n{message_text[:2000]}"}],
        )
        result = _parse_json(text)
        if result and isinstance(result.get("is_task"), bool):
            return result
        # Fallback
        return {"is_task": True, "title": "", "deadline": "", "description": ""}

    async def close(self) -> None:
        await self._http.aclose()
