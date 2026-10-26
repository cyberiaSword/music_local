"""
Обёртка над SQLite для треков.
"""

import logging
import os
import shutil
import sqlite3
import stat
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from uuid import uuid4

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
    download_updated_at: str | None = None
    download_error: str | None = None
    added_at: str | None = None
    downloaded_at: str | None = None


@dataclass
class Playlist:
    """Плейлист с временными метками Unix в секундах."""
    id: str
    name: str
    created_at: int
    updated_at: int
    track_count: int = 0


class Database:
    """Синхронный доступ к SQLite; сканирование ФС вызывается из UI worker."""

    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA foreign_keys = ON')
        return conn

    def _init_schema(self) -> None:
        """Инициализирует схему БД и применяет миграции."""
        from core.migrations import apply_migrations
        from core.paths import get_data_dir

        with self._connect() as conn:
            # Папка для бэкапов
            backup_dir = get_data_dir() / 'backups'

            # Применяем миграции
            apply_migrations(
                conn,
                backup_dir=backup_dir,
                db_path=self.path,
            )

        logger.info(f"Схема БД готова: {self.path}")

    # ---------------- Плейлисты ----------------

    @staticmethod
    def _validate_playlist_name(name: str) -> str:
        name = name.strip()
        if not name:
            raise ValueError('Имя плейлиста не должно быть пустым')
        return name

    def create_playlist(self, name: str) -> str:
        name = self._validate_playlist_name(name)
        playlist_id = str(uuid4())
        now = int(time.time())
        with self._connect() as conn:
            conn.execute(
                'INSERT INTO playlists (id, name, created_at, updated_at) VALUES (?, ?, ?, ?)',
                (playlist_id, name, now, now),
            )
        return playlist_id

    def rename_playlist(self, playlist_id: str, name: str) -> None:
        name = self._validate_playlist_name(name)
        with self._connect() as conn:
            conn.execute(
                'UPDATE playlists SET name = ?, updated_at = ? WHERE id = ?',
                (name, int(time.time()), playlist_id),
            )

    def delete_playlist(self, playlist_id: str) -> None:
        with self._connect() as conn:
            conn.execute('DELETE FROM playlists WHERE id = ?', (playlist_id,))

    def list_playlists(self) -> list[Playlist]:
        with self._connect() as conn:
            rows = conn.execute("""
                SELECT p.*, COUNT(pt.track_id) AS track_count
                FROM playlists AS p
                LEFT JOIN playlist_tracks AS pt ON pt.playlist_id = p.id
                GROUP BY p.id ORDER BY p.created_at, p.id
            """).fetchall()
        return [Playlist(**dict(row)) for row in rows]

    def add_to_playlist(self, playlist_id: str, track_id: int) -> None:
        """Добавляет в конец; неизвестные внешние ключи дают ValueError."""
        with self._connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            if conn.execute('SELECT 1 FROM playlists WHERE id = ?', (playlist_id,)).fetchone() is None:
                raise ValueError('Неизвестный плейлист')
            if conn.execute('SELECT 1 FROM tracks WHERE id = ?', (track_id,)).fetchone() is None:
                raise ValueError('Неизвестный трек')
            now = int(time.time())
            cursor = conn.execute("""
                INSERT INTO playlist_tracks (playlist_id, track_id, position, added_at)
                SELECT ?, ?, COALESCE(MAX(position), -1) + 1, ?
                FROM playlist_tracks WHERE playlist_id = ?
                ON CONFLICT(playlist_id, track_id) DO NOTHING
            """, (playlist_id, track_id, now, playlist_id))
            if cursor.rowcount:
                conn.execute('UPDATE playlists SET updated_at = ? WHERE id = ?', (now, playlist_id))

    def remove_from_playlist(self, playlist_id: str, track_id: int) -> None:
        with self._connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            cursor = conn.execute(
                'DELETE FROM playlist_tracks WHERE playlist_id = ? AND track_id = ?',
                (playlist_id, track_id),
            )
            if not cursor.rowcount:
                return
            rows = conn.execute(
                'SELECT track_id FROM playlist_tracks WHERE playlist_id = ? ORDER BY position, track_id',
                (playlist_id,),
            ).fetchall()
            conn.executemany(
                'UPDATE playlist_tracks SET position = ? WHERE playlist_id = ? AND track_id = ?',
                [(position, playlist_id, row['track_id']) for position, row in enumerate(rows)],
            )
            conn.execute(
                'UPDATE playlists SET updated_at = ? WHERE id = ?',
                (int(time.time()), playlist_id),
            )

    def reorder_playlist(self, playlist_id: str, track_ids: list[int]) -> None:
        """Атомарная точная перестановка; состав и added_at не меняются."""
        with self._connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            if conn.execute('SELECT 1 FROM playlists WHERE id = ?', (playlist_id,)).fetchone() is None:
                raise ValueError('Неизвестный плейлист')
            current = {row['track_id'] for row in conn.execute(
                'SELECT track_id FROM playlist_tracks WHERE playlist_id = ?', (playlist_id,),
            )}
            if len(track_ids) != len(current) or set(track_ids) != current:
                raise ValueError('Требуется точная перестановка треков плейлиста')
            conn.executemany(
                'UPDATE playlist_tracks SET position = ? WHERE playlist_id = ? AND track_id = ?',
                [(position, playlist_id, track_id) for position, track_id in enumerate(track_ids)],
            )
            conn.execute(
                'UPDATE playlists SET updated_at = ? WHERE id = ?',
                (int(time.time()), playlist_id),
            )

    def get_playlist_tracks(
        self, playlist_id: str, search: str = '', limit: int | None = None, offset: int = 0,
        *, filter_status: str | None = None,
    ) -> list[Track]:
        sql = """SELECT t.* FROM tracks AS t
                 JOIN playlist_tracks AS pt ON pt.track_id = t.id
                 WHERE pt.playlist_id = ?"""
        params: list = [playlist_id]
        if search:
            sql += ' AND (t.title LIKE ? OR t.channel LIKE ?)'
            params.extend([f'%{search}%', f'%{search}%'])
        if filter_status is not None:
            sql += ' AND t.download_status = ?'
            params.append(filter_status)
        sql += ' ORDER BY pt.position, pt.track_id LIMIT ? OFFSET ?'
        params.extend([-1 if limit is None else max(0, int(limit)), max(0, int(offset))])
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [self._row_to_track(row) for row in rows]

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
                track_id = row['id']
                conn.execute("""
                    UPDATE tracks
                    SET last_played = CURRENT_TIMESTAMP,
                        play_count = play_count + 1,
                        title = ?,
                        channel = ?
                    WHERE id = ?
                """, (data['title'], data.get('channel', ''), track_id))
            else:
                cursor = conn.execute("""
                    INSERT INTO tracks (video_id, title, channel, url, duration, added_at)
                    VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """, (
                    data['videoId'],
                    data['title'],
                    data.get('channel', ''),
                    data['url'],
                    int(data.get('duration') or 0) or None,
                ))
                track_id = cursor.lastrowid

            conn.execute(
                "INSERT INTO track_plays (track_id) VALUES (?)",
                (track_id,),
            )
            conn.commit()
            return track_id

    def set_download_status(
        self,
        track_id: int,
        status: str,
        file_path: str | None = None,
        error: str | None = None,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """UPDATE tracks
                   SET download_status = ?, file_path = COALESCE(?, file_path),
                       download_updated_at = CASE WHEN ? = 'downloading'
                           THEN CURRENT_TIMESTAMP ELSE NULL END,
                       download_error = CASE WHEN ? = 'failed' THEN ? ELSE NULL END,
                       downloaded_at = CASE WHEN ? = 'done'
                           THEN CURRENT_TIMESTAMP ELSE downloaded_at END
                   WHERE id = ?""",
                (status, file_path, status, status, error, status, track_id),
            )
            conn.commit()

    def touch_download_activity(self, track_id: int) -> None:
        with self._connect() as conn:
            conn.execute(
                """UPDATE tracks SET download_updated_at = CURRENT_TIMESTAMP
                   WHERE id = ? AND download_status = 'downloading'""",
                (track_id,),
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
        limit: int | None = None,
        offset: int = 0,
    ) -> list[Track]:
        """Возвращает треки с фильтрацией, сортировкой и необязательной страницей."""
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

        sql += f" ORDER BY {sort_by} {order}, id {order}"
        if limit is not None:
            params.extend([max(1, min(int(limit), 500)), max(0, int(offset))])
            sql += " LIMIT ? OFFSET ?"

        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
            return [self._row_to_track(row) for row in rows]

    def get_recent_tracks(self, limit: int = 8) -> list[Track]:
        """Возвращает недавно добавленные треки для страницы обзора."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM tracks ORDER BY added_at DESC, id DESC LIMIT ?",
                (max(0, int(limit)),),
            ).fetchall()
        return [self._row_to_track(row) for row in rows]

    @staticmethod
    def _is_local_mp3(file_path: str | None, data_dir: Path) -> bool:
        if not file_path:
            return False
        path = Path(file_path)
        if path.suffix.lower() != '.mp3':
            return False
        if not path.is_absolute():
            path = data_dir / path
        try:
            return path.is_file()
        except (OSError, ValueError):
            return False

    def get_recent_downloads(self, limit: int = 8) -> list[Track]:
        """Фильтрует реальные MP3 до применения лимита, неизвестные даты — в конце."""
        from core.paths import get_data_dir

        limit = max(0, int(limit))
        if not limit:
            return []
        data_dir = get_data_dir()
        tracks = []
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM tracks ORDER BY downloaded_at DESC, id DESC"
            )
            for row in rows:
                if self._is_local_mp3(row['file_path'], data_dir):
                    tracks.append(self._row_to_track(row))
                    if len(tracks) == limit:
                        break
        return tracks

    def get_overview_stats(self) -> dict[str, int | None]:
        """Сканирует ФС синхронно; вызывается рабочим потоком UI."""
        from core.paths import get_data_dir

        with self._connect() as conn:
            rows = conn.execute("SELECT file_path FROM tracks").fetchall()
        result: dict[str, int | None] = {
            'total': len(rows), 'downloaded': 0,
            'downloads_bytes': None, 'free_bytes': None,
        }
        try:
            data_dir = get_data_dir()
        except OSError:
            return result
        result['downloaded'] = sum(
            self._is_local_mp3(row['file_path'], data_dir) for row in rows
        )
        try:
            result['free_bytes'] = shutil.disk_usage(data_dir).free
        except OSError:
            pass

        def raise_walk_error(error: OSError) -> None:
            raise error

        try:
            downloads_dir = data_dir / 'downloads'
            try:
                mode = downloads_dir.stat().st_mode
            except FileNotFoundError:
                result['downloads_bytes'] = 0
                return result
            if not stat.S_ISDIR(mode):
                return result
            total_bytes = 0
            for directory, _, filenames in os.walk(
                downloads_dir, onerror=raise_walk_error
            ):
                for filename in filenames:
                    info = (Path(directory) / filename).stat()
                    if stat.S_ISREG(info.st_mode):
                        total_bytes += info.st_size
            result['downloads_bytes'] = total_bytes
        except OSError:
            pass
        return result

    def save_playback_state(self, track_id: int, position_ms: int) -> None:
        """Сохраняет только явно переданный локальным плеером трек."""
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO playback_state (id, track_id, position_ms)
                   VALUES (1, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET
                       track_id = excluded.track_id, position_ms = excluded.position_ms""",
                (track_id, max(0, position_ms)),
            )
            conn.commit()

    def get_playback_state(self) -> tuple[Track, int] | None:
        with self._connect() as conn:
            row = conn.execute(
                """SELECT tracks.*, playback_state.position_ms
                   FROM playback_state JOIN tracks ON tracks.id = playback_state.track_id
                   WHERE playback_state.id = 1"""
            ).fetchone()
        return (self._row_to_track(row), row['position_ms']) if row else None

    def get_top_week(self, limit: int = 8) -> list[tuple[Track, int]]:
        """Возвращает треки с наибольшим числом запусков за семь дней."""
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT tracks.*, COUNT(track_plays.id) AS weekly_plays
                   FROM track_plays
                   JOIN tracks ON tracks.id = track_plays.track_id
                   WHERE track_plays.played_at >= datetime('now', '-7 days')
                   GROUP BY tracks.id
                   ORDER BY weekly_plays DESC,
                            MAX(track_plays.played_at) DESC, tracks.id DESC
                   LIMIT ?""",
                (max(1, min(int(limit), 50)),),
            ).fetchall()
            return [
                (self._row_to_track(row), row["weekly_plays"])
                for row in rows
            ]

    def get_downloads_page(self, limit: int = 100, offset: int = 0) -> list[Track]:
        """Возвращает страницу очереди с приоритетом активных ошибок и загрузок."""
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT * FROM tracks
                   ORDER BY CASE download_status
                       WHEN 'downloading' THEN 0
                       WHEN 'pending' THEN 1
                       WHEN 'failed' THEN 2
                       WHEN 'done' THEN 3 ELSE 4 END, id
                   LIMIT ? OFFSET ?""",
                (max(1, min(int(limit), 500)), max(0, int(offset))),
            ).fetchall()
            return [self._row_to_track(row) for row in rows]

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
        """Помечает как ошибочные загрузки без прогресса более десяти минут."""
        with self._connect() as conn:
            cursor = conn.execute("""
                UPDATE tracks
                SET download_status = 'failed',
                    download_error = 'Загрузка не обновлялась более 10 минут',
                    download_updated_at = NULL
                WHERE download_status = 'downloading'
                  AND (
                      download_updated_at IS NULL
                      OR datetime(download_updated_at) < datetime('now', '-10 minutes')
                  )
            """)
            conn.commit()
            count = cursor.rowcount
        if count:
            logger.warning("Сброшено в ошибку зависших загрузок: %s", count)
        return count

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
            download_updated_at=row['download_updated_at'],
            download_error=row['download_error'],
            added_at=row['added_at'],
            downloaded_at=row['downloaded_at'],
        )
    