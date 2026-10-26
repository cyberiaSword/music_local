"""
Тесты для core.migrations.
"""

import sqlite3

import pytest

from core.migrations import (
    SCHEMA_VERSION,
    MIGRATIONS,
    apply_migrations,
    get_current_version,
    ensure_schema_version_table,
    set_version,
)


@pytest.fixture
def fresh_db():
    """Новая пустая БД в памяти."""
    conn = sqlite3.connect(':memory:')
    yield conn
    conn.close()


class TestGetCurrentVersion:
    """Тесты get_current_version."""

    def test_no_table(self, fresh_db):
        """Без таблицы schema_version — версия 0."""
        assert get_current_version(fresh_db) == 0

    def test_with_table(self, fresh_db):
        """С таблицей и записью — версия из записи."""
        ensure_schema_version_table(fresh_db)
        set_version(fresh_db, 5)
        assert get_current_version(fresh_db) == 5


class TestApplyMigrations:
    """Тесты применения миграций."""

    def test_fresh_db(self, fresh_db):
        """Новая БД получает SCHEMA_VERSION."""
        result = apply_migrations(fresh_db)
        assert result == SCHEMA_VERSION
        assert get_current_version(fresh_db) == SCHEMA_VERSION

    def test_idempotent(self, fresh_db):
        """Повторный вызов не ломает."""
        apply_migrations(fresh_db)
        apply_migrations(fresh_db)  # второй раз
        assert get_current_version(fresh_db) == SCHEMA_VERSION

    def test_creates_tracks_table(self, fresh_db):
        """После миграции есть таблица tracks."""
        apply_migrations(fresh_db)
        tables = fresh_db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        table_names = [t[0] for t in tables]
        assert 'tracks' in table_names
        assert 'track_plays' in table_names
        assert 'schema_version' in table_names

    def test_tracks_columns(self, fresh_db):
        """У tracks есть нужные колонки."""
        apply_migrations(fresh_db)
        columns = fresh_db.execute("PRAGMA table_info(tracks)").fetchall()
        col_names = [c[1] for c in columns]
        assert 'id' in col_names
        assert 'video_id' in col_names
        assert 'title' in col_names
        assert 'download_status' in col_names
        assert 'added_at' in col_names
        assert 'downloaded_at' in col_names

    @pytest.mark.parametrize('legacy_version', [1, 2, 3, 4])
    @pytest.mark.parametrize('existing_dates', [False, True])
    def test_legacy_upgrade(self, fresh_db, legacy_version, existing_dates):
        ensure_schema_version_table(fresh_db)
        for version in range(1, min(legacy_version, 3) + 1):
            MIGRATIONS[version](fresh_db)
        fresh_db.execute("""
            INSERT INTO tracks (video_id, title, first_played, last_played,
                                download_status)
            VALUES ('legacy', 'Legacy', '2020-01-02', '2025-06-07', 'done')
        """)
        if existing_dates:
            fresh_db.execute('ALTER TABLE tracks ADD COLUMN added_at TIMESTAMP')
            fresh_db.execute('ALTER TABLE tracks ADD COLUMN downloaded_at TIMESTAMP')
            fresh_db.execute("""UPDATE tracks SET added_at = '2021-02-03',
                                downloaded_at = '2022-03-04'""")
        set_version(fresh_db, legacy_version)
        fresh_db.commit()

        assert apply_migrations(fresh_db) == SCHEMA_VERSION
        assert apply_migrations(fresh_db) == SCHEMA_VERSION
        dates = fresh_db.execute('SELECT added_at, downloaded_at FROM tracks').fetchone()
        assert dates == (('2021-02-03', '2022-03-04') if existing_dates
                         else ('2020-01-02', None))
        assert fresh_db.execute('SELECT * FROM playback_state').fetchall() == []
        assert fresh_db.execute('SELECT COUNT(*) FROM tracks').fetchone()[0] == 1

    def test_playback_state_constraints(self, fresh_db):
        apply_migrations(fresh_db)
        with pytest.raises(sqlite3.IntegrityError):
            fresh_db.execute('INSERT INTO playback_state VALUES (2, 1, 0)')
        with pytest.raises(sqlite3.IntegrityError):
            fresh_db.execute('INSERT INTO playback_state VALUES (1, 1, -1)')


class TestPlaylistMigration:
    def test_v5_upgrade_preserves_integer_track_ids(self, fresh_db):
        fresh_db.execute('PRAGMA foreign_keys = ON')
        ensure_schema_version_table(fresh_db)
        for version in range(1, 6):
            MIGRATIONS[version](fresh_db)
        fresh_db.execute("""INSERT INTO tracks (id, video_id, title)
                            VALUES (42, 'legacy-playlist', 'Legacy')""")
        fresh_db.execute('INSERT INTO playback_state VALUES (1, 42, 1234)')
        set_version(fresh_db, 5)
        fresh_db.commit()
        before = fresh_db.execute('SELECT * FROM tracks').fetchall()

        assert apply_migrations(fresh_db) == 6
        assert get_current_version(fresh_db) == 6
        assert fresh_db.execute('SELECT * FROM tracks').fetchall() == before
        assert fresh_db.execute('SELECT * FROM playback_state').fetchall() == [(1, 42, 1234)]
        assert fresh_db.execute('SELECT * FROM playlists').fetchall() == []
        assert fresh_db.execute('SELECT * FROM playlist_tracks').fetchall() == []
        fresh_db.execute("INSERT INTO playlists VALUES ('mix', 'Music', 100, 100)")
        fresh_db.execute("INSERT INTO playlist_tracks VALUES ('mix', 42, 0, 100)")
        fresh_db.commit()
        assert apply_migrations(fresh_db) == 6
        assert fresh_db.execute('SELECT * FROM playlist_tracks').fetchall() == [('mix', 42, 0, 100)]
        assert fresh_db.execute('PRAGMA foreign_key_check').fetchall() == []

    def test_v6_schema_and_constraints(self, fresh_db):
        fresh_db.execute('PRAGMA foreign_keys = ON')
        apply_migrations(fresh_db)
        columns = {row[1]: row for row in fresh_db.execute('PRAGMA table_info(playlists)')}
        assert columns['id'][2] == 'TEXT'
        assert columns['id'][5] == 1
        assert columns['name'][3] == 1
        assert columns['created_at'][2] == columns['updated_at'][2] == 'INTEGER'
        columns = {row[1]: row for row in fresh_db.execute('PRAGMA table_info(playlist_tracks)')}
        assert columns['playlist_id'][2] == 'TEXT'
        assert columns['track_id'][2] == 'INTEGER'
        assert columns['playlist_id'][5] == 1
        assert columns['track_id'][5] == 2
        assert columns['position'][2] == columns['added_at'][2] == 'INTEGER'
        foreign_keys = fresh_db.execute('PRAGMA foreign_key_list(playlist_tracks)').fetchall()
        assert {(row[2], row[3], row[4], row[6]) for row in foreign_keys} == {
            ('playlists', 'playlist_id', 'id', 'CASCADE'),
            ('tracks', 'track_id', 'id', 'CASCADE'),
        }
        with pytest.raises(sqlite3.IntegrityError):
            fresh_db.execute("INSERT INTO playlists VALUES ('bad', NULL, 0, 0)")
        fresh_db.execute("INSERT INTO playlists VALUES ('mix', 'Music', 0, 0)")
        fresh_db.execute("INSERT INTO tracks (id, video_id, title) VALUES (42, 'v', 'Title')")
        fresh_db.execute("INSERT INTO playlist_tracks VALUES ('mix', 42, 0, 0)")
        with pytest.raises(sqlite3.IntegrityError):
            fresh_db.execute("INSERT INTO playlist_tracks VALUES ('mix', 42, 1, 0)")


class TestMigrationsRegistry:
    """Тесты реестра миграций."""

    def test_all_versions_present(self):
        """Все версии от 1 до SCHEMA_VERSION есть в MIGRATIONS."""
        for version in range(1, SCHEMA_VERSION + 1):
            assert version in MIGRATIONS, f"Миграция v{version} отсутствует"