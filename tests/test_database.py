"""
Тесты для core.database.
"""

import pytest

from core.database import Database


@pytest.fixture
def db(tmp_db_path, monkeypatch):
    """Создаёт БД и изолирует все обращения к data/."""
    monkeypatch.setattr('core.paths.get_data_dir', lambda: tmp_db_path.parent)
    return Database(tmp_db_path)


class TestUpsert:
    """Тесты upsert_from_play."""

    def test_insert_new(self, db):
        """Новый трек вставляется."""
        track_id = db.upsert_from_play({
            'videoId': 'abc123',
            'title': 'Test Track',
            'channel': 'Test Channel',
            'url': 'https://youtube.com/watch?v=abc123',
        })
        assert track_id > 0

        track = db.get_track(track_id)
        assert track.title == 'Test Track'
        assert track.video_id == 'abc123'
        assert track.play_count == 1

    def test_update_existing(self, db):
        """Повторный play увеличивает play_count."""
        id1 = db.upsert_from_play({
            'videoId': 'abc123',
            'title': 'Test',
            'url': 'https://youtube.com/watch?v=abc123',
        })
        id2 = db.upsert_from_play({
            'videoId': 'abc123',
            'title': 'Test Updated',
            'url': 'https://youtube.com/watch?v=abc123',
        })
        assert id1 == id2  # тот же трек

        track = db.get_track(id1)
        assert track.play_count == 2
        assert track.title == 'Test Updated'


class TestGetAll:
    """Тесты get_all."""

    def test_empty(self, db):
        """Пустая БД возвращает пустой список."""
        assert db.get_all() == []

    def test_filter_by_status(self, db):
        """Фильтр по статусу работает."""
        db.upsert_from_play({'videoId': 'a', 'title': 'A', 'url': 'u1'})
        db.upsert_from_play({'videoId': 'b', 'title': 'B', 'url': 'u2'})

        pending = db.get_all(filter_status='pending')
        assert len(pending) == 2

        done = db.get_all(filter_status='done')
        assert len(done) == 0

    def test_search(self, db):
        """Поиск по title/channel работает."""
        db.upsert_from_play({
            'videoId': 'a', 'title': 'Nightcore Song', 'url': 'u1',
        })
        db.upsert_from_play({
            'videoId': 'b', 'title': 'Rock Song', 'url': 'u2',
        })

        results = db.get_all(search='Nightcore')
        assert len(results) == 1
        assert results[0].title == 'Nightcore Song'


class TestStats:
    """Тесты stats."""

    def test_empty(self, db):
        """Пустая БД — все счётчики 0."""
        s = db.stats()
        assert s['total'] == 0
        assert s['done'] == 0
        assert s['pending'] == 0

    def test_with_tracks(self, db):
        """Счётчики отражают реальность."""
        db.upsert_from_play({'videoId': 'a', 'title': 'A', 'url': 'u1'})
        db.upsert_from_play({'videoId': 'b', 'title': 'B', 'url': 'u2'})

        s = db.stats()
        assert s['total'] == 2
        assert s['pending'] == 2


class TestStatus:
    """Тесты статусов."""

    def test_set_status(self, db):
        """Статус меняется."""
        track_id = db.upsert_from_play({
            'videoId': 'a', 'title': 'A', 'url': 'u1',
        })
        db.set_download_status(track_id, 'done', file_path='test.mp3')

        track = db.get_track(track_id)
        assert track.download_status == 'done'
        assert track.file_path == 'test.mp3'


class TestOverviewQueries:
    def test_top_week_counts_only_recent_play_events(self, db):
        track_id = db.upsert_from_play({
            'videoId': 'weekly-track', 'title': 'Недельный трек', 'url': 'url',
        })
        db.upsert_from_play({
            'videoId': 'weekly-track', 'title': 'Недельный трек', 'url': 'url',
        })

        ranking = db.get_top_week()
        assert len(ranking) == 1
        assert ranking[0][0].id == track_id
        assert ranking[0][1] == 2

        with db._connect() as connection:
            connection.execute(
                "UPDATE track_plays SET played_at = datetime('now', '-8 days')"
            )
            connection.commit()

        assert db.get_top_week() == []

    def test_recent_tracks_uses_added_at_order(self, db):
        ids = [db.upsert_from_play({'videoId': str(i), 'title': str(i), 'url': 'u'})
               for i in range(3)]
        assert all(db.get_track(track_id).added_at for track_id in ids)
        with db._connect() as conn:
            conn.execute("UPDATE tracks SET added_at = '2020-01-01'")
            conn.execute("""UPDATE tracks SET added_at = '2021-01-01',
                            first_played = '1999-01-01' WHERE id = ?""", (ids[0],))
        db.upsert_from_play({'videoId': '1', 'title': 'Updated', 'url': 'u'})
        assert [t.id for t in db.get_recent_tracks()] == [ids[0], ids[2], ids[1]]
        assert db.get_track(ids[1]).added_at == '2020-01-01'
        assert len(db.get_recent_tracks(limit=1)) == 1
        assert db.get_recent_tracks(limit=0) == []


@pytest.fixture
def add_track(db):
    def add(video_id, path=None, date=None, status='done'):
        track_id = db.upsert_from_play({'videoId': video_id, 'title': video_id, 'url': 'u'})
        with db._connect() as conn:
            conn.execute('''UPDATE tracks SET file_path = ?, downloaded_at = ?,
                            download_status = ? WHERE id = ?''',
                         (str(path) if path is not None else None, date, status, track_id))
        return track_id
    return add


class TestRecentDownloads:
    def test_default_limit_and_distinct_dates(self, db, add_track, tmp_db_path):
        song = tmp_db_path.parent / 'song.mp3'
        song.write_bytes(b'a')
        ids = [add_track(str(i), song, f'2020-01-{10 - i:02d}') for i in range(10)]
        assert [track.id for track in db.get_recent_downloads()] == ids[:8]

    def test_filter_order_limit(self, db, add_track, tmp_db_path):
        base = tmp_db_path.parent
        (base / 'downloads').mkdir()
        (base / 'downloads/song.MP3').write_bytes(b'abc')
        absolute = base / 'absolute.mp3'
        absolute.write_bytes(b'ab')
        directory = base / 'directory.mp3'
        directory.mkdir()
        wrong = base / 'song.wav'
        wrong.write_bytes(b'not mp3')
        old = add_track('old', absolute)
        first = add_track('first', 'downloads/song.MP3', '2022-01-01')
        second = add_track('second', absolute, '2022-01-01', status='pending')
        add_track('missing', 'missing.mp3', '2025-01-01')
        add_track('directory', directory, '2025-01-01')
        add_track('wrong', wrong, '2025-01-01')
        add_track('empty', None, '2025-01-01')
        assert [t.id for t in db.get_recent_downloads(2)] == [second, first]
        assert [t.id for t in db.get_recent_downloads()] == [second, first, old]
        assert db.get_recent_downloads(0) == []

    def test_download_date_only_on_done(self, db, add_track):
        track_id = add_track('date', status='pending')
        db.set_download_status(track_id, 'downloading')
        db.touch_download_activity(track_id)
        assert db.get_track(track_id).downloaded_at is None
        db.set_download_status(track_id, 'done', 'song.mp3')
        assert db.get_track(track_id).downloaded_at
        with db._connect() as conn:
            conn.execute("UPDATE tracks SET downloaded_at = '2000-01-01' WHERE id = ?",
                         (track_id,))
        db.set_download_status(track_id, 'downloading')
        db.touch_download_activity(track_id)
        assert db.get_track(track_id).downloaded_at == '2000-01-01'
        assert db.get_track(track_id).file_path == 'song.mp3'
        db.set_download_status(track_id, 'done')
        assert db.get_track(track_id).downloaded_at != '2000-01-01'


class TestOverviewStats:
    def test_sizes_and_real_mp3_count(self, db, add_track, tmp_db_path, monkeypatch):
        from collections import namedtuple
        downloads = tmp_db_path.parent / 'downloads'
        nested = downloads / 'nested'
        nested.mkdir(parents=True)
        song = downloads / 'song.MP3'
        song.write_bytes(b'12345')
        (nested / 'other.bin').write_bytes(b'1234567')
        (downloads / 'directory.mp3').mkdir()
        add_track('real', 'downloads/song.MP3', status='pending')
        add_track('missing', 'downloads/missing.mp3')
        add_track('directory', downloads / 'directory.mp3')
        add_track('not-mp3', nested / 'other.bin')
        usage = namedtuple('Usage', 'total used free')(100, 40, 60)
        calls = []
        def disk_usage(path):
            calls.append(path)
            return usage
        monkeypatch.setattr('core.database.shutil.disk_usage', disk_usage)
        assert db.get_overview_stats() == {
            'total': 4, 'downloaded': 1, 'downloads_bytes': 12, 'free_bytes': 60,
        }
        assert calls == [tmp_db_path.parent]

    def test_missing_downloads(self, db):
        result = db.get_overview_stats()
        assert result['total'] == result['downloaded'] == result['downloads_bytes'] == 0
        assert isinstance(result['free_bytes'], int)
        assert db.get_recent_downloads() == []

    def test_scan_errors_do_not_return_partial_size(self, db, tmp_db_path, monkeypatch):
        downloads = tmp_db_path.parent / 'downloads'
        downloads.mkdir()
        (downloads / 'ok.mp3').write_bytes(b'123')
        def broken_walk(path, onerror):
            yield str(path), [], ['ok.mp3']
            onerror(PermissionError('denied'))
        def broken_usage(path):
            raise OSError('disk unavailable')
        monkeypatch.setattr('core.database.os.walk', broken_walk)
        monkeypatch.setattr('core.database.shutil.disk_usage', broken_usage)
        result = db.get_overview_stats()
        assert result['downloads_bytes'] is None
        assert result['free_bytes'] is None

    def test_unavailable_data_dir(self, db, monkeypatch):
        def unavailable():
            raise PermissionError('denied')
        monkeypatch.setattr('core.paths.get_data_dir', unavailable)
        result = db.get_overview_stats()
        assert result['downloads_bytes'] is None
        assert result['free_bytes'] is None


class TestPlaybackState:
    def test_empty_and_browser_play(self, db, add_track):
        assert db.get_playback_state() is None
        add_track('browser')
        assert db.get_playback_state() is None

    def test_singleton_persistence_and_join(self, db, add_track):
        first = add_track('local-first')
        second = add_track('local-second')
        db.save_playback_state(first, 1234)
        state = Database(db.path).get_playback_state()
        assert state[0].id == first
        assert state[1] == 1234
        db.upsert_from_play({'videoId': 'browser', 'title': 'Browser', 'url': 'u'})
        assert db.get_playback_state()[0].id == first
        db.save_playback_state(second, -100)
        assert db.get_playback_state()[0].id == second
        assert db.get_playback_state()[1] == 0
        with db._connect() as conn:
            assert conn.execute('SELECT COUNT(*) FROM playback_state').fetchone()[0] == 1
            conn.execute('DELETE FROM tracks WHERE id = ?', (second,))
        assert db.get_playback_state() is None