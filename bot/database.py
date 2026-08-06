"""SQLite ma'lumotlar bazasi bilan ishlash (aiosqlite)."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

import aiosqlite

SCHEMA = """
CREATE TABLE IF NOT EXISTS employees (
    tg_id      INTEGER PRIMARY KEY,
    full_name  TEXT NOT NULL,
    username   TEXT,
    active     INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tasks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    title       TEXT NOT NULL,
    description TEXT,
    deadline    TEXT,                 -- ISO format, mahalliy vaqt mintaqasida
    created_by  INTEGER,
    src_chat_id INTEGER,
    src_msg_id  INTEGER,
    announce_msg_id INTEGER,          -- ijro guruhidagi e'lon xabari id
    status      TEXT NOT NULL DEFAULT 'open',  -- open | closed
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS task_files (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id   INTEGER NOT NULL,
    file_id   TEXT NOT NULL,
    file_name TEXT,
    file_kind TEXT,                   -- document | photo | video ...
    FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS submissions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id      INTEGER NOT NULL,
    employee_id  INTEGER NOT NULL,
    message_id   INTEGER,
    note         TEXT,
    file_id      TEXT,
    file_name    TEXT,
    submitted_at TEXT NOT NULL,
    UNIQUE (task_id, employee_id),
    FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS reminders_sent (
    task_id  INTEGER NOT NULL,
    minutes  INTEGER NOT NULL,
    PRIMARY KEY (task_id, minutes)
);
"""


class Database:
    def __init__(self, path: str) -> None:
        self.path = path
        self._conn: Optional[aiosqlite.Connection] = None

    async def connect(self) -> None:
        self._conn = await aiosqlite.connect(self.path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA foreign_keys = ON")
        await self._conn.executescript(SCHEMA)
        await self._conn.commit()

    async def close(self) -> None:
        if self._conn:
            await self._conn.close()
            self._conn = None

    @property
    def conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("Ma'lumotlar bazasi ulanmagan. connect() ni chaqiring.")
        return self._conn

    # ---------- Xodimlar ----------
    async def add_employee(
        self, tg_id: int, full_name: str, username: str | None
    ) -> None:
        await self.conn.execute(
            """
            INSERT INTO employees (tg_id, full_name, username, active, created_at)
            VALUES (?, ?, ?, 1, ?)
            ON CONFLICT(tg_id) DO UPDATE SET
                full_name = excluded.full_name,
                username  = excluded.username,
                active    = 1
            """,
            (tg_id, full_name, username, datetime.now().isoformat()),
        )
        await self.conn.commit()

    async def remove_employee(self, tg_id: int) -> bool:
        cur = await self.conn.execute(
            "UPDATE employees SET active = 0 WHERE tg_id = ?", (tg_id,)
        )
        await self.conn.commit()
        return cur.rowcount > 0

    async def get_employee(self, tg_id: int) -> Optional[aiosqlite.Row]:
        cur = await self.conn.execute(
            "SELECT * FROM employees WHERE tg_id = ?", (tg_id,)
        )
        return await cur.fetchone()

    async def list_employees(self, active_only: bool = True) -> list[aiosqlite.Row]:
        q = "SELECT * FROM employees"
        if active_only:
            q += " WHERE active = 1"
        q += " ORDER BY full_name COLLATE NOCASE"
        cur = await self.conn.execute(q)
        return list(await cur.fetchall())

    async def count_employees(self) -> int:
        cur = await self.conn.execute(
            "SELECT COUNT(*) AS c FROM employees WHERE active = 1"
        )
        row = await cur.fetchone()
        return row["c"] if row else 0

    # ---------- Topshiriqlar ----------
    async def create_task(
        self,
        title: str,
        description: str | None,
        deadline: str | None,
        created_by: int | None,
        src_chat_id: int | None,
        src_msg_id: int | None,
    ) -> int:
        cur = await self.conn.execute(
            """
            INSERT INTO tasks
                (title, description, deadline, created_by, src_chat_id, src_msg_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                title,
                description,
                deadline,
                created_by,
                src_chat_id,
                src_msg_id,
                datetime.now().isoformat(),
            ),
        )
        await self.conn.commit()
        return cur.lastrowid

    async def add_task_file(
        self, task_id: int, file_id: str, file_name: str | None, file_kind: str
    ) -> None:
        await self.conn.execute(
            "INSERT INTO task_files (task_id, file_id, file_name, file_kind) VALUES (?, ?, ?, ?)",
            (task_id, file_id, file_name, file_kind),
        )
        await self.conn.commit()

    async def set_announce_msg(self, task_id: int, msg_id: int) -> None:
        await self.conn.execute(
            "UPDATE tasks SET announce_msg_id = ? WHERE id = ?", (msg_id, task_id)
        )
        await self.conn.commit()

    async def get_task(self, task_id: int) -> Optional[aiosqlite.Row]:
        cur = await self.conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
        return await cur.fetchone()

    async def get_task_files(self, task_id: int) -> list[aiosqlite.Row]:
        cur = await self.conn.execute(
            "SELECT * FROM task_files WHERE task_id = ?", (task_id,)
        )
        return list(await cur.fetchall())

    async def get_task_by_announce(self, announce_msg_id: int) -> Optional[aiosqlite.Row]:
        cur = await self.conn.execute(
            "SELECT * FROM tasks WHERE announce_msg_id = ?", (announce_msg_id,)
        )
        return await cur.fetchone()

    async def list_open_tasks(self) -> list[aiosqlite.Row]:
        cur = await self.conn.execute(
            "SELECT * FROM tasks WHERE status = 'open' ORDER BY id DESC"
        )
        return list(await cur.fetchall())

    async def latest_open_task(self) -> Optional[aiosqlite.Row]:
        cur = await self.conn.execute(
            "SELECT * FROM tasks WHERE status = 'open' ORDER BY id DESC LIMIT 1"
        )
        return await cur.fetchone()

    async def close_task(self, task_id: int) -> None:
        await self.conn.execute(
            "UPDATE tasks SET status = 'closed' WHERE id = ?", (task_id,)
        )
        await self.conn.commit()

    async def reopen_task(self, task_id: int) -> None:
        await self.conn.execute(
            "UPDATE tasks SET status = 'open' WHERE id = ?", (task_id,)
        )
        await self.conn.commit()

    async def tasks_due_between(
        self, start_iso: str, end_iso: str
    ) -> list[aiosqlite.Row]:
        cur = await self.conn.execute(
            """
            SELECT * FROM tasks
            WHERE status = 'open' AND deadline IS NOT NULL
              AND deadline > ? AND deadline <= ?
            """,
            (start_iso, end_iso),
        )
        return list(await cur.fetchall())

    # ---------- Topshiriqlarni bajarish (submissions) ----------
    async def add_submission(
        self,
        task_id: int,
        employee_id: int,
        message_id: int | None,
        note: str | None,
        file_id: str | None,
        file_name: str | None,
    ) -> bool:
        """Yangi topshirilgan ish qo'shadi. Agar allaqachon topshirilgan bo'lsa yangilaydi.
        Yangi topshiriq bo'lsa True qaytaradi."""
        cur = await self.conn.execute(
            "SELECT id FROM submissions WHERE task_id = ? AND employee_id = ?",
            (task_id, employee_id),
        )
        existing = await cur.fetchone()
        now = datetime.now().isoformat()
        if existing:
            await self.conn.execute(
                """
                UPDATE submissions
                SET message_id = ?, note = ?, file_id = ?, file_name = ?, submitted_at = ?
                WHERE id = ?
                """,
                (message_id, note, file_id, file_name, now, existing["id"]),
            )
            await self.conn.commit()
            return False
        await self.conn.execute(
            """
            INSERT INTO submissions
                (task_id, employee_id, message_id, note, file_id, file_name, submitted_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (task_id, employee_id, message_id, note, file_id, file_name, now),
        )
        await self.conn.commit()
        return True

    async def get_submissions(self, task_id: int) -> list[aiosqlite.Row]:
        cur = await self.conn.execute(
            "SELECT * FROM submissions WHERE task_id = ?", (task_id,)
        )
        return list(await cur.fetchall())

    async def submitted_employee_ids(self, task_id: int) -> set[int]:
        cur = await self.conn.execute(
            "SELECT employee_id FROM submissions WHERE task_id = ?", (task_id,)
        )
        return {row["employee_id"] for row in await cur.fetchall()}

    async def employee_stats(self, employee_id: int) -> dict[str, int]:
        cur = await self.conn.execute(
            "SELECT COUNT(*) AS c FROM submissions WHERE employee_id = ?",
            (employee_id,),
        )
        done = (await cur.fetchone())["c"]
        cur = await self.conn.execute("SELECT COUNT(*) AS c FROM tasks")
        total = (await cur.fetchone())["c"]
        return {"done": done, "total": total}

    async def employee_ranking(self) -> list[aiosqlite.Row]:
        """Xodimlarni bajarilgan topshiriqlar soni bo'yicha tartiblaydi."""
        cur = await self.conn.execute(
            """
            SELECT e.tg_id, e.full_name, e.username,
                   COUNT(s.id) AS done_count
            FROM employees e
            LEFT JOIN submissions s ON s.employee_id = e.tg_id
            WHERE e.active = 1
            GROUP BY e.tg_id
            ORDER BY done_count DESC, e.full_name
            """
        )
        return list(await cur.fetchall())

    async def employee_open_task_stats(self) -> list[aiosqlite.Row]:
        """Faqat ochiq topshiriqlar bo'yicha statistika."""
        cur = await self.conn.execute(
            """
            SELECT e.tg_id, e.full_name, e.username,
                   COUNT(s.id) AS done_count,
                   (SELECT COUNT(*) FROM tasks WHERE status='open') AS open_count
            FROM employees e
            LEFT JOIN submissions s
                   ON s.employee_id = e.tg_id
                   AND s.task_id IN (SELECT id FROM tasks WHERE status='open')
            WHERE e.active = 1
            GROUP BY e.tg_id
            ORDER BY done_count DESC, e.full_name
            """
        )
        return list(await cur.fetchall())

    async def get_submission(self, task_id: int, employee_id: int) -> Optional[aiosqlite.Row]:
        cur = await self.conn.execute(
            "SELECT * FROM submissions WHERE task_id=? AND employee_id=?",
            (task_id, employee_id),
        )
        return await cur.fetchone()

    # ---------- Eslatmalar ----------
    async def was_reminder_sent(self, task_id: int, minutes: int) -> bool:
        cur = await self.conn.execute(
            "SELECT 1 FROM reminders_sent WHERE task_id = ? AND minutes = ?",
            (task_id, minutes),
        )
        return await cur.fetchone() is not None

    async def mark_reminder_sent(self, task_id: int, minutes: int) -> None:
        await self.conn.execute(
            "INSERT OR IGNORE INTO reminders_sent (task_id, minutes) VALUES (?, ?)",
            (task_id, minutes),
        )
        await self.conn.commit()
