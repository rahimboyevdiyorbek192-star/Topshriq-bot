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
    timezone_name: str
    db_path: str
    reminder_minutes: list[int] = field(default_factory=list)

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone_name)

    def is_manager(self, user_id: int) -> bool:
        return user_id in self.manager_ids


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
        timezone_name=os.getenv("TIMEZONE", "Asia/Tashkent"),
        db_path=os.getenv("DB_PATH", "topshriq.db"),
        reminder_minutes=reminders,
    )
