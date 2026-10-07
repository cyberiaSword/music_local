"""
Обёртка над SQLite для треков.
"""

import logging
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

logger = logging.getLogger('yt-local.db')


@dataclass
class Track:
    """Одна запись трека."""
    id: int
    video_id: str
    title: str
    channel: str
    url: str
    first_played: str
    last_played: str
    play_count: int
    download_status: str
    file_path: str | None = None
    cover_path: str | None = None
    duration: int | None = None


class Database:
    """Синхронный доступ к SQLite. Вызывается из главного потока Qt."""

    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS tracks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    video_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    channel TEXT,
                    url TEXT,
                    first_played TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_played TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    play_count INTEGER DEFAULT 1,
                    download_status TEXT DEFAULT 'pending',
                    file_path TEXT,
                    cover_path TEXT,
                    duration INTEGER,
                    UNIQUE(video_id)
                );

                CREATE INDEX IF NOT EXISTS idx_tracks_last_played
                    ON tracks(last_played DESC);
                CREATE INDEX IF NOT EXISTS idx_tracks_status
                    ON tracks(download_status);
            """)
            self._migrate(conn)
            conn.commit()
        logger.info(f"Схема БД готова: {self.path}")

    def _migrate(self, conn: sqlite3.Connection) -> None:
        """
        Миграции для баз, созданных в старых версиях приложения.
        Проверяет, что колонка url допускает NULL, и при необходимости
        пересоздаёт таблицу.
        """
        try:
            columns = conn.execute("PRAGMA table_info(tracks)").fetchall()
        except sqlite3.Error as e:
            logger.warning(f"Не удалось получить схему таблицы: {e}")
            return

        url_col = next((c for c in columns if c[1] == 'url'), None)
        if url_col is None:
            return

        # notnull = 1 означает, что url NOT NULL — это мешает псевдо-id записям
        # row[3] в PRAGMA table_info — это notnull
        is_notnull = url_col[3] == 1
        if not is_notnull:
            return

        logger.info("Миграция: url NOT NULL → url NULL")

        try:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS tracks_new (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    video_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    channel TEXT,
                    url TEXT,
                    first_played TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_played TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    play_count INTEGER DEFAULT 1,
                    download_status TEXT DEFAULT 'pending',
                    file_path TEXT,
                    cover_path TEXT,
                    duration INTEGER,
                    UNIQUE(video_id)
                );
                INSERT INTO tracks_new (
                    id, video_id, title, channel, url,
                    first_played, last_played, play_count,
                    download_status, file_path, cover_path, duration
                )
                SELECT
                    id, video_id, title, channel, url,
                    first_played, last_played, play_count,
                    download_status, file_path, cover_path, duration
                FROM tracks;
                DROP TABLE tracks;
                ALTER TABLE tracks_new RENAME TO tracks;
            """)
        except sqlite3.Error as e:
            logger.error(f"Ошибка миграции: {e}")
    # ---------------- Запись ----------------

    def upsert_from_play(self, data: dict) -> int:
        """
        Вставляет или обновляет трек по данным из WebSocket-скрипта.
        Возвращает id записи.
        """
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id, play_count FROM tracks WHERE video_id = ?",
                (data['videoId'],)
            ).fetchone()

            if row:
                conn.execute("""
                    UPDATE tracks
                    SET last_played = CURRENT_TIMESTAMP,
                        play_count = play_count + 1,
                        title = ?,
                        channel = ?
                    WHERE id = ?
                """, (data['title'], data.get('channel', ''), row['id']))
                conn.commit()
                return row['id']

            cursor = conn.execute("""
                INSERT INTO tracks (video_id, title, channel, url, duration)
                VALUES (?, ?, ?, ?, ?)
            """, (
                data['videoId'],
                data['title'],
                data.get('channel', ''),
                data['url'],
                int(data.get('duration') or 0) or None,
            ))
            conn.commit()
            return cursor.lastrowid

    def set_download_status(self, track_id: int, status: str, file_path: str | None = None) -> None:
        with self._connect() as conn:
            if file_path is not None:
                conn.execute(
                    "UPDATE tracks SET download_status = ?, file_path = ? WHERE id = ?",
                    (status, file_path, track_id)
                )
            else:
                conn.execute(
                    "UPDATE tracks SET download_status = ? WHERE id = ?",
                    (status, track_id)
                )
            conn.commit()

    def set_cover_path(self, track_id: int, cover_path: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE tracks SET cover_path = ? WHERE id = ?",
                (cover_path, track_id)
            )
            conn.commit()

    # ---------------- Чтение ----------------

    def get_track(self, track_id: int) -> Track | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM tracks WHERE id = ?", (track_id,)
            ).fetchone()
            return self._row_to_track(row) if row else None

    def get_by_video_id(self, video_id: str) -> Track | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM tracks WHERE video_id = ?", (video_id,)
            ).fetchone()
            return self._row_to_track(row) if row else None

    def get_all(
        self,
        search: str = '',
        sort_by: str = 'last_played',
        sort_desc: bool = True,
        filter_status: str | None = None,
    ) -> list[Track]:
        """
        Возвращает список треков с фильтрацией и сортировкой.

        sort_by: last_played | first_played | title | channel | play_count
        filter_status: pending | downloading | done | failed | None
        """
        allowed_sort = {'last_played', 'first_played', 'title', 'channel', 'play_count'}
        if sort_by not in allowed_sort:
            sort_by = 'last_played'

        order = 'DESC' if sort_desc else 'ASC'
        sql = "SELECT * FROM tracks WHERE 1=1"
        params: list = []

        if search:
            sql += " AND (title LIKE ? OR channel LIKE ?)"
            params.extend([f'%{search}%', f'%{search}%'])

        if filter_status:
            sql += " AND download_status = ?"
            params.append(filter_status)

        sql += f" ORDER BY {sort_by} {order}"

        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
            return [self._row_to_track(r) for r in rows]

    def count_pending(self) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM tracks WHERE download_status = 'pending'"
            ).fetchone()
            return row['n']

    def stats(self) -> dict:
        with self._connect() as conn:
            total = conn.execute("SELECT COUNT(*) AS n FROM tracks").fetchone()['n']
            done = conn.execute(
                "SELECT COUNT(*) AS n FROM tracks WHERE download_status = 'done'"
            ).fetchone()['n']
            pending = conn.execute(
                "SELECT COUNT(*) AS n FROM tracks WHERE download_status = 'pending'"
            ).fetchone()['n']
            failed = conn.execute(
                "SELECT COUNT(*) AS n FROM tracks WHERE download_status = 'failed'"
            ).fetchone()['n']
        return {'total': total, 'done': done, 'pending': pending, 'failed': failed}

    def verify_files(self) -> int:
        """
        Проходит по всем done-записям, проверяет наличие MP3.
        Если файла нет — сбрасывает в pending.
        Возвращает количество «восстановленных» записей.
        """
        from pathlib import Path

        base = Path(__file__).resolve().parent.parent / 'data'
        fixed = 0

        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, file_path FROM tracks WHERE download_status = 'done'"
            ).fetchall()

            for r in rows:
                if not r['file_path']:
                    continue
                p = Path(r['file_path'])
                if not p.is_absolute():
                    p = base / p
                if not p.exists():
                    conn.execute(
                        "UPDATE tracks SET download_status = 'pending', file_path = NULL WHERE id = ?",
                        (r['id'],)
                    )
                    fixed += 1

            conn.commit()

        if fixed:
            logger.info(f"Восстановлено в очередь: {fixed} треков (файлы отсутствуют)")
        return fixed

    def reset_stuck_statuses(self) -> int:
        """
        Сбрасывает в pending записи со статусами downloading и failed,
        которые остались с прошлой сессии.
        Возвращает количество сброшенных.
        """
        with self._connect() as conn:
            cursor = conn.execute("""
                UPDATE tracks
                SET download_status = 'pending', file_path = NULL
                WHERE download_status IN ('downloading', 'failed')
            """)
            conn.commit()
            n = cursor.rowcount
        if n:
            logger.info(f"Сброшено в pending (залипшие/ошибочные): {n}")
        return n

    # ---------------- Утилиты ----------------

    @staticmethod
    def _row_to_track(row: sqlite3.Row) -> Track:
        return Track(
            id=row['id'],
            video_id=row['video_id'],
            title=row['title'],
            channel=row['channel'] or '',
            url=row['url'],
            first_played=row['first_played'],
            last_played=row['last_played'],
            play_count=row['play_count'],
            download_status=row['download_status'],
            file_path=row['file_path'],
            cover_path=row['cover_path'],
            duration=row['duration'],
        )
    