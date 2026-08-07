"""Yagona AI xizmati.

Foydalanish:

    from .ai_pkg import create_ai_client

    ai = create_ai_client(config)     # None — AI o'chirilgan bo'lsa
    if ai:
        javob = await ai.chat([{"role": "user", "content": "Salom"}])

Provayder `.env` dagi sozlamalar bo'yicha avtomatik tanlanadi:
  USE_OLLAMA=true       → mahalliy Ollama (bepul)
  ANTHROPIC_API_KEY=... → Claude (pullik)
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Optional

from .base import AIProvider

if TYPE_CHECKING:
    from ..config import Config

logger = logging.getLogger(__name__)

__all__ = ["AIProvider", "create_ai_client"]


def create_ai_client(config: "Config") -> Optional[AIProvider]:
    """Sozlamalarga qarab AI provayderini yaratadi. AI o'chiq bo'lsa None."""
    if config.use_ollama:
        from .ollama import OllamaProvider
        vision = config.ollama_vision_model or config.ollama_model
        logger.info(
            "Mahalliy AI (Ollama) yoqildi: %s / %s (rasm modeli: %s)",
            config.ollama_base_url, config.ollama_model, vision,
        )
        return OllamaProvider(config.ollama_base_url, config.ollama_model, vision)

    if config.anthropic_api_key:
        from .claude import ClaudeProvider
        logger.info("Claude AI yoqildi (model: %s)", config.anthropic_model)
        return ClaudeProvider(config.anthropic_api_key, config.anthropic_model)

    logger.info("AI o'chirilgan (API kalit yo'q va USE_OLLAMA=false).")
    return None
