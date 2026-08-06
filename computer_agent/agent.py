"""Avtonom kompyuter agentining asosiy sikli."""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable, Optional

from .actions import (
    do_click, do_double_click, do_key,
    do_move, do_right_click, do_scroll, do_type,
)
from .ollama_vision import OllamaVision
from .screen import screenshot_b64, screenshot_bytes, scale_ratio

logger = logging.getLogger(__name__)

MAX_STEPS   = 25      # Bir vazifada maksimal qadam soni
STEP_DELAY  = 1.5     # Harakatdan keyin kutish (sekund) — UI yangilanishi uchun

# Callback turlari
OnStepCallback = Callable[[int, str, bytes | None], Awaitable[None]]
OnDoneCallback = Callable[[str, bool, bytes | None], Awaitable[None]]


class ComputerAgent:
    """
    Avtonom kompyuter boshqaruv agenti.

    Ishlatish:
        agent = ComputerAgent(ollama_url="http://localhost:11434", vision_model="llava")
        await agent.run(task="Chrome ochib google.com ga kir", on_step=..., on_done=...)
    """

    def __init__(
        self,
        ollama_url:   str = "http://localhost:11434",
        vision_model: str = "llava",
        max_steps:    int = MAX_STEPS,
        step_delay:   float = STEP_DELAY,
    ) -> None:
        self.vision     = OllamaVision(ollama_url, vision_model)
        self.max_steps  = max_steps
        self.step_delay = step_delay
        self._stop      = False

    def stop(self) -> None:
        """Tashqaridan agentni to'xtatish."""
        self._stop = True

    async def run(
        self,
        task: str,
        on_step: Optional[OnStepCallback] = None,
        on_done: Optional[OnDoneCallback] = None,
    ) -> None:
        """
        Vazifani bajaradi.

        on_step(step, message, screenshot_bytes) — har qadamdan keyin chaqiriladi
        on_done(message, success, screenshot_bytes) — tugaganda chaqiriladi
        """
        self._stop  = False
        history:    list[str] = []
        ratio_x, ratio_y = scale_ratio()
        success     = False
        final_msg   = "Vazifa bajarildi."

        for step in range(1, self.max_steps + 1):
            if self._stop:
                final_msg = "⛔ Foydalanuvchi to'xtatdi."
                break

            # 1. Ekran rasmini ol
            b64 = screenshot_b64()
            if b64 is None:
                final_msg = "❌ Ekran rasmini ololmadim. pyautogui/PIL o'rnatilganmi?"
                break

            # 2. AI qaror
            decision = await self.vision.decide_action(
                task=task,
                history=history,
                screenshot_b64=b64,
                step=step,
                max_steps=self.max_steps,
            )

            action  = decision.get("action", "done")
            msg     = decision.get("message", "")
            done    = decision.get("done", False) or action == "done"
            thought = decision.get("thought", "")

            logger.info("Qadam %d | %s | %s", step, action, thought[:80])

            history.append(f"{action}: {msg}")

            # 3. Screenshot (harakatdan OLDIN, foydalanuvchi nima ko'rayotganini bilsin)
            scr_bytes = screenshot_bytes()

            # 4. on_step callback
            if on_step:
                await on_step(step, f"[{step}] {msg}", scr_bytes)

            # 5. Agar done — tugatish
            if done:
                success   = True
                final_msg = msg or "✅ Vazifa bajarildi!"
                break

            # 6. Harakatni bajarish
            ok = await self._execute(decision, ratio_x, ratio_y)
            if not ok:
                logger.warning("Qadam %d bajarilmadi: %s", step, action)

            # 7. UI yangilanishi uchun kutish
            await asyncio.sleep(self.step_delay)

        else:
            final_msg = f"⏱ {self.max_steps} qadamdan keyin vazifa tugadirlmadi."

        # Yakuniy screenshot
        final_scr = screenshot_bytes()
        if on_done:
            await on_done(final_msg, success, final_scr)

    async def _execute(
        self,
        decision: dict[str, Any],
        ratio_x: float,
        ratio_y: float,
    ) -> bool:
        """Bir harakatni bajaradi, True = muvaffaqiyatli."""
        action = decision.get("action", "")
        x      = decision.get("x") or 0
        y      = decision.get("y") or 0

        match action:
            case "click":
                return await do_click(x, y, ratio_x, ratio_y)
            case "double_click":
                return await do_double_click(x, y, ratio_x, ratio_y)
            case "right_click":
                return await do_right_click(x, y, ratio_x, ratio_y)
            case "type":
                text = decision.get("text") or ""
                return await do_type(text)
            case "key":
                key = decision.get("key") or ""
                return await do_key(key)
            case "scroll":
                amt = int(decision.get("scroll_amount") or -3)
                return await do_scroll(x, y, amt, ratio_x, ratio_y)
            case "move":
                return await do_move(x, y, ratio_x, ratio_y)
            case _:
                return True   # done yoki noma'lum — skip
