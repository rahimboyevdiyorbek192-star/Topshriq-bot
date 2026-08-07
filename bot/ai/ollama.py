"""Ollama (mahalliy, bepul) provayderi."""
from __future__ import annotations

import base64
import logging
from typing import Any

import httpx

from .base import AIProvider

logger = logging.getLogger(__name__)


class OllamaProvider(AIProvider):
    """Mahalliy Ollama serveri orqali ishlaydi (bepul, internetsiz)."""

    name = "ollama"

    def __init__(self, base_url: str, model: str, vision_model: str | None = None) -> None:
        self.base_url     = base_url.rstrip("/")
        self.model        = model
        self.vision_model = vision_model or model   # masalan: llava
        self._http        = httpx.AsyncClient(timeout=240.0)

    async def _post_chat(self, payload: dict[str, Any], model_label: str) -> str:
        try:
            r = await self._http.post(f"{self.base_url}/api/chat", json=payload)
            r.raise_for_status()
            return r.json().get("message", {}).get("content", "").strip()
        except httpx.ConnectError:
            logger.error(
                "Ollama ulanmadi: %s — 'ollama serve' ishga tushirilganmi?", self.base_url
            )
            return ""
        except Exception as exc:
            logger.warning("Ollama xatolik (%s): %s", model_label, exc)
            return ""

    async def _complete(
        self, system: str, messages: list[dict[str, Any]], max_tokens: int = 4096
    ) -> str:
        # Ollama max_tokens'ni num_predict deb ataydi
        return await self._post_chat({
            "model":    self.model,
            "messages": [{"role": "system", "content": system}] + messages,
            "stream":   False,
            "options":  {"num_predict": max_tokens},
        }, self.model)

    async def _complete_vision(
        self, system: str, prompt: str, image_bytes: bytes, media_type: str
    ) -> str:
        return await self._post_chat({
            "model": self.vision_model,
            "messages": [
                {"role": "system", "content": system},
                {
                    "role": "user",
                    "content": prompt,
                    "images": [base64.standard_b64encode(image_bytes).decode()],
                },
            ],
            "stream": False,
        }, self.vision_model)

    async def close(self) -> None:
        await self._http.aclose()
