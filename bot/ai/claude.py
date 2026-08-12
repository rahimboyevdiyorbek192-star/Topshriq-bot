"""Claude (Anthropic) provayderi."""
from __future__ import annotations

import base64
import logging
from typing import Any

from anthropic import AsyncAnthropic

from .base import AIProvider

logger = logging.getLogger(__name__)


def _text_of(resp) -> str:
    return "".join(b.text for b in resp.content if b.type == "text").strip()


class ClaudeProvider(AIProvider):
    """Anthropic Claude API orqali ishlaydi (pullik, internet kerak)."""

    name = "claude"

    def __init__(self, api_key: str, model: str) -> None:
        self._client = AsyncAnthropic(api_key=api_key)
        self.model   = model

    async def _complete(
        self, system: str, messages: list[dict[str, Any]], max_tokens: int = 4096
    ) -> str:
        try:
            resp = await self._client.messages.create(
                model=self.model, max_tokens=max_tokens,
                system=system, messages=messages,
            )
        except Exception as exc:
            logger.warning("Claude so'rovi muvaffaqiyatsiz: %s", exc)
            return ""
        if getattr(resp, "stop_reason", None) == "refusal":
            return "Kechirasiz, bu so'rovga javob bera olmayman."
        return _text_of(resp)

    async def _complete_vision(
        self, system: str, prompt: str, image_bytes: bytes, media_type: str
    ) -> str:
        content = [
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": media_type,
                    "data": base64.standard_b64encode(image_bytes).decode(),
                },
            },
            {"type": "text", "text": prompt},
        ]
        try:
            resp = await self._client.messages.create(
                model=self.model, max_tokens=2048,
                system=system, messages=[{"role": "user", "content": content}],
            )
            return _text_of(resp)
        except Exception as exc:
            logger.warning("Claude rasm o'qishda xatolik: %s", exc)
            return ""
