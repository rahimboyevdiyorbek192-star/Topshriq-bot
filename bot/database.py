"""SQLite ma'lumotlar bazasi bilan ishlash (aiosqlite)."""
from __future__ import annotations

import hashlib
import hmac as _hmac
import secrets
from datetime import datetime, timedelta
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
    exif_date    TEXT,                   -- EXIF DateTimeOriginal (faqat JPG/JPEG uchun)
    submitted_at TEXT NOT NULL,
    UNIQUE (task_id, employee_id),
    FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS submission_files (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id     INTEGER NOT NULL,
    employee_id INTEGER NOT NULL,
    file_id     TEXT NOT NULL,
    file_name   TEXT,
    file_kind   TEXT,
    exif_date   TEXT,                    -- EXIF DateTimeOriginal (faqat JPG/JPEG uchun)
    added_at    TEXT NOT NULL,
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
        await self._migrate()

    async def _migrate(self) -> None:
        """Yangi ustunlar va jadvallarni qo'shadi (migratsiya)."""
        for sql in [
            "ALTER TABLE employees ADD COLUMN login_phone TEXT",
            "ALTER TABLE employees ADD COLUMN password_hash TEXT",
            "ALTER TABLE employees ADD COLUMN position TEXT",
            "ALTER TABLE submissions ADD COLUMN exif_date TEXT",
            "ALTER TABLE submission_files ADD COLUMN exif_date TEXT",
            "ALTER TABLE employees ADD COLUMN last_bot_msg_id INTEGER",
            "ALTER TABLE employees ADD COLUMN last_lat REAL",
            "ALTER TABLE employees ADD COLUMN last_lon REAL",
            "ALTER TABLE employees ADD COLUMN last_location_at TEXT",
            "ALTER TABLE submissions ADD COLUMN submit_lat REAL",
            "ALTER TABLE submissions ADD COLUMN submit_lon REAL",
        ]:
            try:
                await self._conn.execute(sql)
            except Exception:
                pass
        await self._conn.execute("""
            CREATE TABLE IF NOT EXISTS web_sessions (
                token      TEXT PRIMARY KEY,
                tg_id      INTEGER NOT NULL,
                is_manager INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL
            )
        """)
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

    async def get_employee_bot_msg(self, tg_id: int) -> int | None:
        cur = await self.conn.execute(
            "SELECT last_bot_msg_id FROM employees WHERE tg_id = ?", (tg_id,)
        )
        row = await cur.fetchone()
        return row["last_bot_msg_id"] if row else None

    async def set_employee_bot_msg(self, tg_id: int, msg_id: int | None) -> None:
        await self.conn.execute(
            "UPDATE employees SET last_bot_msg_id = ? WHERE tg_id = ?", (msg_id, tg_id)
        )
        await self.conn.commit()

    async def update_employee_location(
        self, tg_id: int, lat: float, lon: float
    ) -> None:
        await self.conn.execute(
            """UPDATE employees
               SET last_lat = ?, last_lon = ?, last_location_at = ?
               WHERE tg_id = ?""",
            (lat, lon, datetime.now().isoformat(), tg_id),
        )
        await self.conn.commit()

    async def get_all_employees_location_status(self) -> list[aiosqlite.Row]:
        """Barcha faol xodimlarni joylashuv ma'lumoti bilan qaytaradi (yo'q bo'lsa ham)."""
        cur = await self.conn.execute(
            """SELECT tg_id, full_name, login_phone, position,
                      last_lat, last_lon, last_location_at, active
               FROM employees
               WHERE active = 1
               ORDER BY last_location_at DESC NULLS LAST, full_name COLLATE NOCASE"""
        )
        return list(await cur.fetchall())

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

    async def close_task(self, task_id: int) -> None:
        await self.conn.execute(
            "UPDATE tasks SET status = 'closed' WHERE id = ?", (task_id,)
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
        exif_date: str | None = None,
        submit_lat: float | None = None,
        submit_lon: float | None = None,
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
                SET message_id=?, note=?, file_id=?, file_name=?, exif_date=?,
                    submit_lat=?, submit_lon=?, submitted_at=?
                WHERE id=?
                """,
                (message_id, note, file_id, file_name, exif_date,
                 submit_lat, submit_lon, now, existing["id"]),
            )
            await self.conn.commit()
            return False
        await self.conn.execute(
            """
            INSERT INTO submissions
                (task_id, employee_id, message_id, note, file_id, file_name,
                 exif_date, submit_lat, submit_lon, submitted_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (task_id, employee_id, message_id, note, file_id, file_name,
             exif_date, submit_lat, submit_lon, now),
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

    async def add_submission_file(
        self, task_id: int, employee_id: int, file_id: str, file_name: str | None,
        file_kind: str = "document", exif_date: str | None = None
    ) -> None:
        """Topshiriqning qo'shimcha faylini saqlaydi."""
        await self.conn.execute(
            """
            INSERT INTO submission_files (task_id, employee_id, file_id, file_name, file_kind, exif_date, added_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (task_id, employee_id, file_id, file_name, file_kind, exif_date, datetime.now().isoformat()),
        )
        await self.conn.commit()

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

    # ---------- Parol xeshlash (pbkdf2) ----------
    @staticmethod
    def hash_password(password: str) -> str:
        salt = secrets.token_hex(16)
        key = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100_000)
        return f"{salt}:{key.hex()}"

    @staticmethod
    def verify_password(password: str, stored: str) -> bool:
        try:
            salt, key_hex = stored.split(":", 1)
            key = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100_000)
            return _hmac.compare_digest(key.hex(), key_hex)
        except Exception:
            return False

    # ---------- Web sessiyalar ----------
    async def create_web_session(
        self, tg_id: int, is_manager: bool, hours: int = 168
    ) -> str:
        token = secrets.token_urlsafe(32)
        now = datetime.now()
        expires = (now + timedelta(hours=hours)).isoformat()
        await self.conn.execute(
            "INSERT INTO web_sessions (token, tg_id, is_manager, created_at, expires_at) VALUES (?,?,?,?,?)",
            (token, tg_id, 1 if is_manager else 0, now.isoformat(), expires),
        )
        await self.conn.commit()
        return token

    async def get_web_session(self, token: str) -> Optional[aiosqlite.Row]:
        cur = await self.conn.execute(
            "SELECT * FROM web_sessions WHERE token=? AND expires_at>?",
            (token, datetime.now().isoformat()),
        )
        return await cur.fetchone()

    async def delete_web_session(self, token: str) -> None:
        await self.conn.execute("DELETE FROM web_sessions WHERE token=?", (token,))
        await self.conn.commit()

    async def cleanup_sessions(self) -> None:
        await self.conn.execute(
            "DELETE FROM web_sessions WHERE expires_at<?", (datetime.now().isoformat(),)
        )
        await self.conn.commit()

    # ---------- Web xodimlar boshqaruvi ----------
    async def _next_web_id(self) -> int:
        """Web xodimlarga manfiy ID beradi (Telegram ID lar bilan to'qnashmaydi)."""
        cur = await self.conn.execute(
            "SELECT MIN(tg_id) AS m FROM employees WHERE tg_id < 0"
        )
        row = await cur.fetchone()
        return (row["m"] or 0) - 1

    async def get_employee_by_login_phone(self, phone: str) -> Optional[aiosqlite.Row]:
        norm = phone.replace(" ", "").replace("-", "")
        cur = await self.conn.execute(
            "SELECT * FROM employees WHERE REPLACE(REPLACE(login_phone,' ',''),'-','')=?",
            (norm,),
        )
        return await cur.fetchone()

    async def add_employee_web(
        self, full_name: str, position: str, login_phone: str, password_hash: str
    ) -> int:
        tg_id = await self._next_web_id()
        await self.conn.execute(
            """INSERT INTO employees
               (tg_id, full_name, username, active, created_at, position, login_phone, password_hash)
               VALUES (?,?,NULL,1,?,?,?,?)""",
            (tg_id, full_name, datetime.now().isoformat(), position, login_phone, password_hash),
        )
        await self.conn.commit()
        return tg_id

    async def update_employee_web(
        self,
        tg_id: int,
        full_name: str,
        position: str,
        login_phone: str,
        password_hash: Optional[str],
        active: int,
    ) -> None:
        if password_hash:
            await self.conn.execute(
                """UPDATE employees SET full_name=?,position=?,login_phone=?,
                   password_hash=?,active=? WHERE tg_id=?""",
                (full_name, position, login_phone, password_hash, active, tg_id),
            )
        else:
            await self.conn.execute(
                "UPDATE employees SET full_name=?,position=?,login_phone=?,active=? WHERE tg_id=?",
                (full_name, position, login_phone, active, tg_id),
            )
        await self.conn.commit()

    async def delete_employee_web(self, tg_id: int) -> None:
        await self.conn.execute("DELETE FROM employees WHERE tg_id=?", (tg_id,))
        await self.conn.commit()

    async def list_employees_web(self) -> list[aiosqlite.Row]:
        cur = await self.conn.execute(
            "SELECT * FROM employees ORDER BY full_name COLLATE NOCASE"
        )
        return list(await cur.fetchall())

    # ---------- Faylga kirish huquqi ----------
    async def file_access_owner(self, file_id: str) -> tuple[str, Optional[int]]:
        """Fayl kimga tegishli ekanini aniqlaydi.

        Qaytaradi:
          ("task",       None)         — rahbar biriktirgan namuna fayl (hammaga ochiq)
          ("submission", employee_id)  — xodim topshirgan fayl (faqat egasi + rahbar)
          ("unknown",    None)         — bazada bunday fayl yo'q
        """
        cur = await self.conn.execute(
            "SELECT 1 FROM task_files WHERE file_id = ? LIMIT 1", (file_id,)
        )
        if await cur.fetchone():
            return "task", None

        cur = await self.conn.execute(
            "SELECT employee_id FROM submissions WHERE file_id = ? LIMIT 1", (file_id,)
        )
        row = await cur.fetchone()
        if row:
            return "submission", row["employee_id"]

        cur = await self.conn.execute(
            "SELECT employee_id FROM submission_files WHERE file_id = ? LIMIT 1", (file_id,)
        )
        row = await cur.fetchone()
        if row:
            return "submission", row["employee_id"]

        return "unknown", None

    # ---------- ZIP uchun ma'lumotlar ----------
    async def get_all_task_submissions(self, task_id: int) -> list[aiosqlite.Row]:
        cur = await self.conn.execute(
            """SELECT s.*, e.full_name, e.username
               FROM submissions s
               LEFT JOIN employees e ON e.tg_id = s.employee_id
               WHERE s.task_id=?
               ORDER BY e.full_name COLLATE NOCASE""",
            (task_id,),
        )
        return list(await cur.fetchall())

    async def get_all_submission_files_for_task(self, task_id: int) -> list[aiosqlite.Row]:
        cur = await self.conn.execute(
            """SELECT sf.*, e.full_name
               FROM submission_files sf
               LEFT JOIN employees e ON e.tg_id = sf.employee_id
               WHERE sf.task_id=?""",
            (task_id,),
        )
        return list(await cur.fetchall())
