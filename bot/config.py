"""Bot sozlamalari — muhit o'zgaruvchilaridan (.env) o'qiladi."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv()


def _parse_ids(raw: str | None) -> list[int]:
    if not raw:
        return []
    ids: list[int] = []
    for part in raw.replace(";", ",").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            ids.append(int(part))
        except ValueError:
            continue
    return ids


def _parse_int(raw: str | None) -> int | None:
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


@dataclass
class Config:
    bot_token: str
    manager_ids: list[int]
    tasks_group_id: int | None
    execution_group_id: int | None
    tasks_channel_id: int | None          # Alohida kanal (ixtiyoriy)
    timezone_name: str
    db_path: str
    reminder_minutes: list[int] = field(default_factory=list)

    # Claude AI
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-opus-5"

    # Ollama mahalliy AI
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3"
    ollama_vision_model: str = ""   # Rasm o'qish modeli (masalan llava). Bo'sh = ollama_model
    use_ollama: bool = False

    # Userbot (Telethon)
    tg_api_id: int | None = None
    tg_api_hash: str = ""
    tg_userbot_session: str = ""

    @property
    def ai_enabled(self) -> bool:
        if self.use_ollama:
            return bool(self.ollama_base_url)
        return bool(self.anthropic_api_key)

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone_name)

    def is_manager(self, user_id: int) -> bool:
        return user_id in self.manager_ids

    @property
    def userbot_enabled(self) -> bool:
        return bool(self.tg_api_id and self.tg_api_hash and self.tg_userbot_session)

    def is_tasks_source(self, chat_id: int) -> bool:
        """Ushbu chat topshiriqlar manbai ekanligini tekshiradi."""
        if self.tasks_channel_id and chat_id == self.tasks_channel_id:
            return True
        if self.tasks_group_id and chat_id == self.tasks_group_id:
            return True
        return False


def load_config() -> Config:
    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError(
            "BOT_TOKEN topilmadi. .env faylida BOT_TOKEN ni to'ldiring "
            "(namuna: .env.example)."
        )

    reminders_raw = os.getenv("REMINDER_MINUTES", "120,30")
    reminders = sorted(
        {m for m in (_parse_int(x) for x in reminders_raw.split(",")) if m and m > 0},
        reverse=True,
    )

    return Config(
        bot_token=token,
        manager_ids=_parse_ids(os.getenv("MANAGER_IDS")),
        tasks_group_id=_parse_int(os.getenv("TASKS_GROUP_ID")),
        execution_group_id=_parse_int(os.getenv("EXECUTION_GROUP_ID")),
        tasks_channel_id=_parse_int(os.getenv("TASKS_CHANNEL_ID")),
        timezone_name=os.getenv("TIMEZONE", "Asia/Tashkent"),
        db_path=os.getenv("DB_PATH", "topshriq.db"),
        reminder_minutes=reminders,
        anthropic_api_key=os.getenv("ANTHROPIC_API_KEY", "").strip(),
        anthropic_model=os.getenv("ANTHROPIC_MODEL", "claude-opus-5").strip() or "claude-opus-5",
        ollama_base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").strip(),
        ollama_model=os.getenv("OLLAMA_MODEL", "llama3").strip() or "llama3",
        ollama_vision_model=os.getenv("OLLAMA_VISION_MODEL", "").strip(),
        use_ollama=os.getenv("USE_OLLAMA", "").strip().lower() in ("1", "true", "yes"),
        tg_api_id=_parse_int(os.getenv("TG_API_ID")),
        tg_api_hash=os.getenv("TG_API_HASH", "").strip(),
        tg_userbot_session=os.getenv("TG_USERBOT_SESSION", "").strip(),
    )
