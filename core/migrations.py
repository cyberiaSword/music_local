"""
Реестр миграций схемы БД.

Каждая миграция — функция, которая получает соединение SQLite
и выполняет SQL-команды для перехода на новую версию.

Правила:
1. Миграции НЕОБРАТИМЫ. Откат делается через бэкап.
2. Миграции применяются по порядку: 1 → 2 → 3 → ...
3. Каждая миграция ДОЛЖНА увеличивать SCHEMA_VERSION.
4. Не удаляйте старые миграции — они нужны для баз, которые ещё не обновлены.
5. Не меняйте существующие миграции — добавляйте новые.
"""

import logging
import sqlite3
from pathlib import Path
from typing import Callable

logger = logging.getLogger('yt-local.migrations')


# ============================================================
# ТЕКУЩАЯ ВЕРСИЯ СХЕМЫ
# ============================================================
# Увеличивайте при добавлении новой миграции
SCHEMA_VERSION = 6


# ============================================================
# МИГРАЦИИ
# ============================================================
# Формат: {версия: функция}
# Функция принимает sqlite3.Connection и выполняет изменения.


def _migrate_to_v1(conn: sqlite3.Connection) -> None:
    """
    Версия 1 — базовая схема.

    Создаёт таблицы:
    - tracks: основные треки
    - schema_version: версия схемы (управляется из database.py)
    """
    logger.info("Применяю миграцию v1 (базовая схема)")

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

    logger.info("Миграция v1 применена")


def _migrate_to_v2(conn: sqlite3.Connection) -> None:
    """Добавляет время активности загрузки, причину ошибки и индексы."""
    columns = {
        row[1] for row in conn.execute("PRAGMA table_info(tracks)").fetchall()
    }
    if "download_updated_at" not in columns:
        conn.execute("ALTER TABLE tracks ADD COLUMN download_updated_at TIMESTAMP")
    if "download_error" not in columns:
        conn.execute("ALTER TABLE tracks ADD COLUMN download_error TEXT")

    conn.executescript("""
        CREATE INDEX IF NOT EXISTS idx_tracks_title
            ON tracks(title);
        CREATE INDEX IF NOT EXISTS idx_tracks_status_last_played
            ON tracks(download_status, last_played DESC, id DESC);
    """)
    logger.info("Миграция v2 применена")


def _migrate_to_v3(conn: sqlite3.Connection) -> None:
    """Создаёт журнал прослушиваний для расчёта недельного рейтинга."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS track_plays (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            track_id INTEGER NOT NULL REFERENCES tracks(id) ON DELETE CASCADE,
            played_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_track_plays_played_at_track
            ON track_plays(played_at DESC, track_id);
    """)
    logger.info("Миграция v3 применена")


# ============================================================
# РЕЕСТР
# ============================================================

def _migrate_to_v4(conn: sqlite3.Connection) -> None:
    """Добавляет даты обзора, не подменяя неизвестное время скачивания."""
    columns = {row[1] for row in conn.execute("PRAGMA table_info(tracks)")}
    if 'added_at' not in columns:
        conn.execute("ALTER TABLE tracks ADD COLUMN added_at TIMESTAMP")
    if 'downloaded_at' not in columns:
        conn.execute("ALTER TABLE tracks ADD COLUMN downloaded_at TIMESTAMP")
    conn.execute("UPDATE tracks SET added_at = first_played WHERE added_at IS NULL")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_tracks_added_at ON tracks(added_at DESC, id DESC)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_tracks_downloaded_at "
        "ON tracks(downloaded_at DESC, id DESC)"
    )


def _migrate_to_v5(conn: sqlite3.Connection) -> None:
    """Восстанавливает пропущенную v4 и хранит последнее локальное воспроизведение."""
    _migrate_to_v4(conn)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS playback_state (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            track_id INTEGER NOT NULL REFERENCES tracks(id) ON DELETE CASCADE,
            position_ms INTEGER NOT NULL CHECK (position_ms >= 0)
        )
    """)


def _migrate_to_v6(conn: sqlite3.Connection) -> None:
    """Добавляет плейлисты с целочисленными ссылками на существующие треки."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS playlists (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            created_at INTEGER,
            updated_at INTEGER
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS playlist_tracks (
            playlist_id TEXT NOT NULL REFERENCES playlists(id) ON DELETE CASCADE,
            track_id INTEGER NOT NULL REFERENCES tracks(id) ON DELETE CASCADE,
            position INTEGER NOT NULL,
            added_at INTEGER,
            PRIMARY KEY (playlist_id, track_id)
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_playlist_tracks_position
        ON playlist_tracks(playlist_id, position)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_playlist_tracks_track_id
        ON playlist_tracks(track_id)
    """)


MIGRATIONS: dict[int, Callable[[sqlite3.Connection], None]] = {
    1: _migrate_to_v1,
    2: _migrate_to_v2,
    3: _migrate_to_v3,
    4: _migrate_to_v4,
    5: _migrate_to_v5,
    6: _migrate_to_v6,
}


# ============================================================
# ПРИМЕНЕНИЕ
# ============================================================

def get_current_version(conn: sqlite3.Connection) -> int:
    """
    Возвращает текущую версию схемы БД.
    Если таблицы schema_version нет — возвращает 0.
    """
    try:
        row = conn.execute(
            "SELECT version FROM schema_version LIMIT 1"
        ).fetchone()
        return row[0] if row else 0
    except sqlite3.OperationalError:
        # Таблицы ещё нет — база новая
        return 0


def ensure_schema_version_table(conn: sqlite3.Connection) -> None:
    """Создаёт таблицу schema_version, если её нет."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS schema_version (
            version INTEGER NOT NULL,
            applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)


def set_version(conn: sqlite3.Connection, version: int) -> None:
    """Записывает версию в таблицу schema_version."""
    # Удаляем старую запись, вставляем новую
    conn.execute("DELETE FROM schema_version")
    conn.execute(
        "INSERT INTO schema_version (version) VALUES (?)",
        (version,),
    )


def apply_migrations(
    conn: sqlite3.Connection,
    backup_dir: Path | None = None,
    db_path: Path | None = None,
) -> int:
    """
    Применяет все недостающие миграции.

    Args:
        conn: соединение SQLite.
        backup_dir: папка для бэкапов (опционально).
        db_path: путь к БД для бэкапа (опционально).

    Returns:
        Новая версия схемы.
    """
    ensure_schema_version_table(conn)
    current = get_current_version(conn)

    if current >= SCHEMA_VERSION:
        logger.info(f"Схема БД актуальна: v{current}")
        return current

    logger.info(f"Обновление схемы БД: v{current} → v{SCHEMA_VERSION}")

    # Бэкап перед миграцией
    if backup_dir and db_path and db_path.exists():
        _make_backup(db_path, backup_dir, current)

    # Применяем по порядку
    for version in range(current + 1, SCHEMA_VERSION + 1):
        migration = MIGRATIONS.get(version)
        if migration is None:
            logger.error(f"Миграция v{version} не найдена в реестре!")
            raise RuntimeError(f"Отсутствует миграция v{version}")

        try:
            migration(conn)
            set_version(conn, version)
            conn.commit()
            logger.info(f"Миграция v{version} применена успешно")
        except Exception as e:
            conn.rollback()
            logger.exception(f"Ошибка миграции v{version}: {e}")
            raise

    logger.info(f"Схема БД обновлена до v{SCHEMA_VERSION}")
    return SCHEMA_VERSION


def _make_backup(db_path: Path, backup_dir: Path, version: int) -> None:
    """Создаёт бэкап БД перед миграцией."""
    import shutil
    from datetime import datetime

    try:
        backup_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_path = backup_dir / f'tracks_v{version}_{timestamp}.db'
        shutil.copy2(db_path, backup_path)
        logger.info(f"Бэкап БД создан: {backup_path}")
    except Exception as e:
        logger.warning(f"Не удалось создать бэкап: {e}")