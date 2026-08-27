import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import aiosqlite


class Database:
    def __init__(self, db_path: str) -> None:
        self.db_path = Path(db_path)
        self._conn: aiosqlite.Connection | None = None
        self._download_request_lock = asyncio.Lock()

    async def connect(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(self.db_path)
        self._conn.row_factory = aiosqlite.Row
        await self.conn.execute("PRAGMA journal_mode=WAL;")
        await self.conn.execute("PRAGMA foreign_keys=ON;")
        await self.conn.execute("PRAGMA busy_timeout=5000;")
        await self.conn.commit()

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    @property
    def conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("Database is not connected")
        return self._conn

    async def init_schema(self) -> None:
        await self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                telegram_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS groups (
                chat_id INTEGER PRIMARY KEY,
                title TEXT NOT NULL,
                chat_type TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS user_groups (
                user_id INTEGER NOT NULL,
                chat_id INTEGER NOT NULL,
                relation TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (user_id, chat_id)
            );

            CREATE TABLE IF NOT EXISTS settings (
                scope TEXT NOT NULL,
                owner_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (scope, owner_id, name)
            );

            CREATE TABLE IF NOT EXISTS translation_settings (
                scope TEXT NOT NULL,
                owner_id INTEGER NOT NULL,
                language TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (scope, owner_id)
            );

            CREATE TABLE IF NOT EXISTS download_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER NOT NULL,
                video_id TEXT NOT NULL,
                source_chat_id INTEGER NOT NULL,
                source_message_id INTEGER NOT NULL,
                selected_quality TEXT,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS downloads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                request_id INTEGER NOT NULL,
                file_path TEXT NOT NULL,
                final_size INTEGER NOT NULL,
                format_note TEXT,
                sent_at TEXT NOT NULL,
                FOREIGN KEY(request_id) REFERENCES download_requests(id)
            );

            CREATE TABLE IF NOT EXISTS media_cache (
                source_url TEXT PRIMARY KEY,
                media_type TEXT NOT NULL,
                file_id TEXT NOT NULL,
                file_unique_id TEXT,
                width INTEGER,
                height INTEGER,
                duration INTEGER,
                cached_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS deliveries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                source_message_id INTEGER NOT NULL,
                requester_user_id INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(chat_id, source_message_id)
            );

            CREATE TABLE IF NOT EXISTS delivery_messages (
                delivery_id INTEGER NOT NULL,
                message_id INTEGER NOT NULL,
                PRIMARY KEY (delivery_id, message_id),
                FOREIGN KEY(delivery_id) REFERENCES deliveries(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_download_requests_user_status
                ON download_requests(telegram_id, status);
            CREATE INDEX IF NOT EXISTS idx_downloads_request
                ON downloads(request_id);
            CREATE INDEX IF NOT EXISTS idx_groups_updated
                ON groups(updated_at);
            CREATE INDEX IF NOT EXISTS idx_media_cache_cached_at
                ON media_cache(cached_at);
            CREATE INDEX IF NOT EXISTS idx_delivery_messages_message
                ON delivery_messages(message_id);
            """
        )
        await self.conn.commit()

    async def upsert_user(self, telegram_id: int, username: str | None, first_name: str | None) -> None:
        now = _utc_now()
        await self.conn.execute(
            """
            INSERT INTO users (telegram_id, username, first_name, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(telegram_id) DO UPDATE SET
                username = excluded.username,
                first_name = excluded.first_name,
                updated_at = excluded.updated_at
            """,
            (telegram_id, username, first_name, now),
        )
        await self.conn.commit()

    async def get_user(self, telegram_id: int) -> aiosqlite.Row | None:
        cursor = await self.conn.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,))
        return await cursor.fetchone()

    async def upsert_group(self, chat_id: int, title: str, chat_type: str) -> None:
        now = _utc_now()
        await self.conn.execute(
            """
            INSERT INTO groups (chat_id, title, chat_type, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(chat_id) DO UPDATE SET
                title = excluded.title,
                chat_type = excluded.chat_type,
                updated_at = excluded.updated_at
            """,
            (chat_id, title, chat_type, now),
        )
        await self.conn.commit()

    async def list_groups(self) -> list[aiosqlite.Row]:
        cursor = await self.conn.execute("SELECT * FROM groups ORDER BY updated_at DESC, title ASC")
        return list(await cursor.fetchall())

    async def link_user_group(self, user_id: int, chat_id: int, relation: str = "adder") -> None:
        now = _utc_now()
        await self.conn.execute(
            """
            INSERT INTO user_groups (user_id, chat_id, relation, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id, chat_id) DO UPDATE SET
                relation = excluded.relation,
                updated_at = excluded.updated_at
            """,
            (user_id, chat_id, relation, now),
        )
        await self.conn.commit()

    async def unlink_group_users(self, chat_id: int) -> None:
        await self.conn.execute("DELETE FROM user_groups WHERE chat_id = ?", (chat_id,))
        await self.conn.commit()

    async def list_groups_for_user(self, user_id: int) -> list[aiosqlite.Row]:
        cursor = await self.conn.execute(
            """
            SELECT groups.*
            FROM groups
            JOIN user_groups ON user_groups.chat_id = groups.chat_id
            WHERE user_groups.user_id = ?
            ORDER BY groups.updated_at DESC, groups.title ASC
            """,
            (user_id,),
        )
        return list(await cursor.fetchall())

    async def user_can_manage_group(self, user_id: int, chat_id: int) -> bool:
        cursor = await self.conn.execute(
            "SELECT 1 FROM user_groups WHERE user_id = ? AND chat_id = ?",
            (user_id, chat_id),
        )
        return await cursor.fetchone() is not None

    async def get_group(self, chat_id: int) -> aiosqlite.Row | None:
        cursor = await self.conn.execute("SELECT * FROM groups WHERE chat_id = ?", (chat_id,))
        return await cursor.fetchone()

    async def set_setting(self, scope: str, owner_id: int, name: str, value: str) -> None:
        now = _utc_now()
        await self.conn.execute(
            """
            INSERT INTO settings (scope, owner_id, name, value, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(scope, owner_id, name) DO UPDATE SET
                value = excluded.value,
                updated_at = excluded.updated_at
            """,
            (scope, owner_id, name, value, now),
        )
        await self.conn.commit()

    async def get_setting(self, scope: str, owner_id: int, name: str) -> str | None:
        cursor = await self.conn.execute(
            "SELECT value FROM settings WHERE scope = ? AND owner_id = ? AND name = ?",
            (scope, owner_id, name),
        )
        row = await cursor.fetchone()
        return str(row["value"]) if row else None

    async def delete_setting(self, scope: str, owner_id: int, name: str) -> None:
        await self.conn.execute(
            "DELETE FROM settings WHERE scope = ? AND owner_id = ? AND name = ?",
            (scope, owner_id, name),
        )
        await self.conn.commit()

    async def get_cached_media(self, source_url: str) -> aiosqlite.Row | None:
        cursor = await self.conn.execute("SELECT * FROM media_cache WHERE source_url = ?", (source_url,))
        return await cursor.fetchone()

    async def upsert_cached_media(
        self,
        source_url: str,
        media_type: str,
        file_id: str,
        file_unique_id: str | None = None,
        width: int | None = None,
        height: int | None = None,
        duration: int | None = None,
    ) -> None:
        await self.conn.execute(
            """
            INSERT INTO media_cache (
                source_url, media_type, file_id, file_unique_id,
                width, height, duration, cached_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(source_url) DO UPDATE SET
                media_type = excluded.media_type,
                file_id = excluded.file_id,
                file_unique_id = excluded.file_unique_id,
                width = excluded.width,
                height = excluded.height,
                duration = excluded.duration,
                cached_at = excluded.cached_at
            """,
            (source_url, media_type, file_id, file_unique_id, width, height, duration, _utc_now()),
        )
        await self.conn.commit()

    async def delete_cached_media(self, source_urls: list[str]) -> None:
        if not source_urls:
            return
        await self.conn.executemany(
            "DELETE FROM media_cache WHERE source_url = ?",
            [(source_url,) for source_url in source_urls],
        )
        await self.conn.commit()

    async def record_delivery_message(
        self,
        chat_id: int,
        source_message_id: int,
        requester_user_id: int,
        output_message_id: int,
    ) -> None:
        now = _utc_now()
        await self.conn.execute(
            """
            INSERT INTO deliveries (chat_id, source_message_id, requester_user_id, created_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(chat_id, source_message_id) DO UPDATE SET
                requester_user_id = excluded.requester_user_id
            """,
            (chat_id, source_message_id, requester_user_id, now),
        )
        cursor = await self.conn.execute(
            "SELECT id FROM deliveries WHERE chat_id = ? AND source_message_id = ?",
            (chat_id, source_message_id),
        )
        row = await cursor.fetchone()
        if row is not None:
            await self.conn.execute(
                "INSERT OR IGNORE INTO delivery_messages (delivery_id, message_id) VALUES (?, ?)",
                (int(row["id"]), output_message_id),
            )
        await self.conn.commit()

    async def get_delivery_for_message(self, chat_id: int, output_message_id: int) -> dict[str, Any] | None:
        cursor = await self.conn.execute(
            """
            SELECT deliveries.*
            FROM deliveries
            JOIN delivery_messages ON delivery_messages.delivery_id = deliveries.id
            WHERE deliveries.chat_id = ? AND delivery_messages.message_id = ?
            """,
            (chat_id, output_message_id),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        message_cursor = await self.conn.execute(
            "SELECT message_id FROM delivery_messages WHERE delivery_id = ? ORDER BY message_id",
            (int(row["id"]),),
        )
        message_rows = await message_cursor.fetchall()
        return {
            "id": int(row["id"]),
            "chat_id": int(row["chat_id"]),
            "source_message_id": int(row["source_message_id"]),
            "requester_user_id": int(row["requester_user_id"]),
            "message_ids": [int(item["message_id"]) for item in message_rows],
            "created_at": str(row["created_at"]),
        }

    async def delete_delivery(self, delivery_id: int) -> None:
        await self.conn.execute("DELETE FROM deliveries WHERE id = ?", (delivery_id,))
        await self.conn.commit()

    async def prune_deliveries(self, max_age_hours: int = 48) -> int:
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=max(1, max_age_hours))).isoformat()
        cursor = await self.conn.execute("DELETE FROM deliveries WHERE created_at < ?", (cutoff,))
        await self.conn.commit()
        return max(cursor.rowcount, 0)

    async def get_settings(self, scope: str, owner_id: int) -> dict[str, str]:
        cursor = await self.conn.execute(
            "SELECT name, value FROM settings WHERE scope = ? AND owner_id = ?",
            (scope, owner_id),
        )
        rows = await cursor.fetchall()
        return {str(row["name"]): str(row["value"]) for row in rows}

    async def reset_scope_settings(self, scope: str, owner_id: int) -> None:
        await self.conn.execute("DELETE FROM settings WHERE scope = ? AND owner_id = ?", (scope, owner_id))
        await self.conn.execute(
            "DELETE FROM translation_settings WHERE scope = ? AND owner_id = ?",
            (scope, owner_id),
        )
        await self.conn.commit()

    async def set_translation_language(self, scope: str, owner_id: int, language: str) -> None:
        now = _utc_now()
        await self.conn.execute(
            """
            INSERT INTO translation_settings (scope, owner_id, language, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(scope, owner_id) DO UPDATE SET
                language = excluded.language,
                updated_at = excluded.updated_at
            """,
            (scope, owner_id, language, now),
        )
        await self.conn.commit()

    async def get_translation_language(self, scope: str, owner_id: int) -> str | None:
        cursor = await self.conn.execute(
            "SELECT language FROM translation_settings WHERE scope = ? AND owner_id = ?",
            (scope, owner_id),
        )
        row = await cursor.fetchone()
        if not row:
            return None
        language = str(row["language"])
        return None if language == "off" else language

    async def create_download_request(
        self,
        telegram_id: int,
        video_id: str,
        source_chat_id: int,
        source_message_id: int,
        status: str = "pending",
    ) -> int:
        now = _utc_now()
        cursor = await self.conn.execute(
            """
            INSERT INTO download_requests (
                telegram_id, video_id, source_chat_id, source_message_id,
                selected_quality, status, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, NULL, ?, ?, ?)
            """,
            (telegram_id, video_id, source_chat_id, source_message_id, status, now, now),
        )
        await self.conn.commit()
        return int(cursor.lastrowid)

    async def reserve_download_request(
        self,
        telegram_id: int,
        video_id: str,
        source_chat_id: int,
        source_message_id: int,
        max_active: int,
    ) -> tuple[int | None, str | None]:
        """Atomically reserve a pending download for one bot process."""
        async with self._download_request_lock:
            if await self.find_active_download_request(telegram_id, video_id) is not None:
                return None, "duplicate"
            if await self.count_active_download_requests(telegram_id) >= max(1, int(max_active)):
                return None, "limit"
            request_id = await self.create_download_request(
                telegram_id=telegram_id,
                video_id=video_id,
                source_chat_id=source_chat_id,
                source_message_id=source_message_id,
                status="pending",
            )
            return request_id, None

    async def fail_interrupted_downloads(self) -> int:
        """Release requests whose in-memory jobs disappeared during a restart."""
        cursor = await self.conn.execute(
            """
            UPDATE download_requests
            SET status = 'failed', updated_at = ?
            WHERE status IN ('pending', 'queued', 'downloading')
            """,
            (_utc_now(),),
        )
        await self.conn.commit()
        return max(cursor.rowcount, 0)

    async def count_active_download_requests(self, telegram_id: int) -> int:
        cursor = await self.conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM download_requests
            WHERE telegram_id = ? AND status IN ('pending', 'queued', 'downloading')
            """,
            (telegram_id,),
        )
        row = await cursor.fetchone()
        return int(row["count"]) if row else 0

    async def get_download_request(self, request_id: int) -> aiosqlite.Row | None:
        cursor = await self.conn.execute("SELECT * FROM download_requests WHERE id = ?", (request_id,))
        return await cursor.fetchone()

    async def find_active_download_request(self, telegram_id: int, video_id: str) -> aiosqlite.Row | None:
        cursor = await self.conn.execute(
            """
            SELECT * FROM download_requests
            WHERE telegram_id = ? AND video_id = ?
              AND status IN ('pending', 'queued', 'downloading')
            ORDER BY id DESC
            LIMIT 1
            """,
            (telegram_id, video_id),
        )
        return await cursor.fetchone()

    async def claim_download_request(self, request_id: int, telegram_id: int, quality: str) -> bool:
        now = _utc_now()
        cursor = await self.conn.execute(
            """
            UPDATE download_requests
            SET selected_quality = ?, status = 'queued', updated_at = ?
            WHERE id = ? AND telegram_id = ? AND status = 'pending'
            """,
            (quality, now, request_id, telegram_id),
        )
        await self.conn.commit()
        return cursor.rowcount == 1

    async def update_download_request(self, request_id: int, **fields: Any) -> None:
        selected_quality = fields.get("selected_quality")
        status = fields.get("status")
        if selected_quality is None and status is None:
            return

        updated_at = _utc_now()
        if selected_quality is not None and status is not None:
            await self.conn.execute(
                "UPDATE download_requests SET selected_quality = ?, status = ?, updated_at = ? WHERE id = ?",
                (selected_quality, status, updated_at, request_id),
            )
        elif selected_quality is not None:
            await self.conn.execute(
                "UPDATE download_requests SET selected_quality = ?, updated_at = ? WHERE id = ?",
                (selected_quality, updated_at, request_id),
            )
        else:
            await self.conn.execute(
                "UPDATE download_requests SET status = ?, updated_at = ? WHERE id = ?",
                (status, updated_at, request_id),
            )
        await self.conn.commit()

    async def create_download(self, request_id: int, file_path: str, final_size: int, format_note: str | None) -> None:
        sent_at = _utc_now()
        await self.conn.execute(
            """
            INSERT INTO downloads (request_id, file_path, final_size, format_note, sent_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (request_id, file_path, final_size, format_note, sent_at),
        )
        await self.conn.commit()

    async def list_recent_downloads_for_user(self, telegram_id: int, limit: int = 10) -> list[aiosqlite.Row]:
        cursor = await self.conn.execute(
            """
            SELECT downloads.id, downloads.file_path, downloads.final_size,
                   downloads.format_note, downloads.sent_at, download_requests.video_id
            FROM downloads
            JOIN download_requests ON download_requests.id = downloads.request_id
            WHERE download_requests.telegram_id = ?
            ORDER BY downloads.id DESC
            LIMIT ?
            """,
            (telegram_id, max(1, min(limit, 20))),
        )
        return list(await cursor.fetchall())

    async def get_runtime_stats(self) -> dict[str, int]:
        result: dict[str, int] = {}
        for name, query in {
            "users": "SELECT COUNT(*) AS count FROM users",
            "groups": "SELECT COUNT(*) AS count FROM groups",
            "downloads": "SELECT COUNT(*) AS count FROM downloads",
        }.items():
            cursor = await self.conn.execute(query)
            row = await cursor.fetchone()
            result[name] = int(row["count"]) if row else 0
        cursor = await self.conn.execute(
            "SELECT COUNT(*) AS count FROM download_requests WHERE status IN ('pending', 'queued', 'downloading')"
        )
        row = await cursor.fetchone()
        result["active_downloads"] = int(row["count"]) if row else 0
        return result


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
