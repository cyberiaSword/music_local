import sqlite3
from uuid import UUID

import pytest

from core.database import Database, Playlist, Track


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr('core.paths.get_data_dir', lambda: tmp_path)
    return Database(tmp_path / 'playlists.db')


@pytest.fixture
def tracks(db):
    return [db.upsert_from_play({
        'videoId': f'video-{index}', 'title': title,
        'channel': channel, 'url': f'https://example.test/{index}',
    }) for index, (title, channel) in enumerate([
        ('Alpha', 'One'), ('Beta', 'Two'), ('Gamma', 'One'),
    ])]


def entries(db, playlist_id):
    with db._connect() as conn:
        return [tuple(row) for row in conn.execute(
            'SELECT track_id, position, added_at FROM playlist_tracks '
            'WHERE playlist_id = ? ORDER BY position', (playlist_id,),
        )]


def populate(db, tracks):
    playlist_id = db.create_playlist('Music')
    for track_id in tracks:
        db.add_to_playlist(playlist_id, track_id)
    return playlist_id


def test_crud_and_timestamps(db, tracks, monkeypatch):
    monkeypatch.setattr('core.database.time.time', lambda: 100)
    name = "Mix'); DROP TABLE tracks; --"
    playlist_id = db.create_playlist(name)
    assert str(UUID(playlist_id)) == playlist_id
    assert db.list_playlists() == [Playlist(playlist_id, name, 100, 100)]
    monkeypatch.setattr('core.database.time.time', lambda: 200)
    assert db.rename_playlist(playlist_id, 'Renamed') is None
    assert db.list_playlists() == [Playlist(playlist_id, 'Renamed', 100, 200)]
    db.add_to_playlist(playlist_id, tracks[0])
    assert db.list_playlists()[0].track_count == 1
    assert isinstance(db.get_playlist_tracks(playlist_id)[0], Track)
    assert db.delete_playlist(playlist_id) is None
    assert db.list_playlists() == []
    assert db.get_track(tracks[0]) is not None
    db.delete_playlist(playlist_id)


@pytest.mark.parametrize('name', ['', ' ', '\t\n'])
def test_blank_names_rejected(db, name):
    with pytest.raises(ValueError):
        db.create_playlist(name)
    playlist_id = db.create_playlist('Original')
    before = db.list_playlists()
    with pytest.raises(ValueError):
        db.rename_playlist(playlist_id, name)
    assert db.list_playlists() == before


def test_duplicate_add_is_noop(db, tracks, monkeypatch):
    playlist_id = populate(db, tracks)
    before = entries(db, playlist_id)
    playlists = db.list_playlists()
    monkeypatch.setattr('core.database.time.time', lambda: 9999999999)
    assert db.add_to_playlist(playlist_id, tracks[1]) is None
    assert entries(db, playlist_id) == before
    assert db.list_playlists() == playlists
    assert [row[1] for row in before] == [0, 1, 2]
    assert all(isinstance(row[2], int) for row in before)


def test_unknown_foreign_keys_rejected(db, tracks):
    playlist_id = db.create_playlist('Music')
    for unknown_playlist, unknown_track in [
        ('missing', tracks[0]), (playlist_id, 999999), ('missing', 999999),
    ]:
        with pytest.raises(ValueError):
            db.add_to_playlist(unknown_playlist, unknown_track)
    assert entries(db, playlist_id) == []
    with db._connect() as conn:
        assert conn.execute('SELECT COUNT(*) FROM playlist_tracks').fetchone()[0] == 0


def test_remove_compacts_and_append_uses_last_position(db, tracks):
    playlist_id = populate(db, tracks)
    assert db.remove_from_playlist(playlist_id, tracks[1]) is None
    assert [(row[0], row[1]) for row in entries(db, playlist_id)] == [
        (tracks[0], 0), (tracks[2], 1),
    ]
    db.remove_from_playlist(playlist_id, tracks[1])
    db.add_to_playlist(playlist_id, tracks[1])
    assert [row[0] for row in entries(db, playlist_id)] == [tracks[0], tracks[2], tracks[1]]
    assert [row[1] for row in entries(db, playlist_id)] == [0, 1, 2]


def test_reorder_preserves_membership_and_added_at(db, tracks):
    playlist_id = populate(db, tracks)
    other_id = populate(db, tracks)
    before = {row[0]: row[2] for row in entries(db, playlist_id)}
    order = [tracks[2], tracks[0], tracks[1]]
    assert db.reorder_playlist(playlist_id, order) is None
    assert [track.id for track in db.get_playlist_tracks(playlist_id)] == order
    assert [row[1] for row in entries(db, playlist_id)] == [0, 1, 2]
    assert {row[0]: row[2] for row in entries(db, playlist_id)} == before
    assert [track.id for track in db.get_playlist_tracks(other_id)] == tracks


@pytest.mark.parametrize('order', [[], [0, 1], [0, 0, 2], [0, 1, 3], [0, 1, 2, 2]])
def test_invalid_reorder_leaves_everything_unchanged(db, tracks, order):
    playlist_id = populate(db, tracks)
    before = entries(db, playlist_id)
    playlists = db.list_playlists()
    ids = [tracks[index] if index < 3 else 999999 for index in order]
    with pytest.raises(ValueError):
        db.reorder_playlist(playlist_id, ids)
    assert entries(db, playlist_id) == before
    assert db.list_playlists() == playlists


def test_empty_reorder_and_unknown_playlist(db):
    playlist_id = db.create_playlist('Empty')
    db.reorder_playlist(playlist_id, [])
    assert db.get_playlist_tracks(playlist_id) == []
    with pytest.raises(ValueError):
        db.reorder_playlist('missing', [])


def test_reorder_rolls_back_after_partial_sql_failure(db, tracks):
    playlist_id = populate(db, tracks)
    before = entries(db, playlist_id)
    playlists = db.list_playlists()
    with db._connect() as conn:
        conn.execute("""CREATE TRIGGER fail_reorder BEFORE UPDATE OF position
                        ON playlist_tracks WHEN NEW.position = 1
                        BEGIN SELECT RAISE(ABORT, 'test failure'); END""")
    with pytest.raises(sqlite3.IntegrityError, match='test failure'):
        db.reorder_playlist(playlist_id, tracks[::-1])
    assert entries(db, playlist_id) == before
    assert db.list_playlists() == playlists


def test_search_pagination_and_playlist_isolation(db, tracks):
    playlist_id = populate(db, tracks)
    empty_id = db.create_playlist('Empty')
    assert [t.id for t in db.get_playlist_tracks(playlist_id, search='One')] == tracks[::2]
    assert [t.id for t in db.get_playlist_tracks(playlist_id, search='Beta')] == tracks[1:2]
    assert [t.id for t in db.get_playlist_tracks(playlist_id, limit=1, offset=1)] == tracks[1:2]
    assert [t.id for t in db.get_playlist_tracks(playlist_id, offset=1)] == tracks[1:]
    assert db.get_playlist_tracks(playlist_id, limit=0) == []
    assert db.get_playlist_tracks(playlist_id, offset=99) == []
    assert db.get_playlist_tracks(playlist_id, search="' OR 1=1 --") == []
    assert db.get_playlist_tracks(empty_id) == []
    assert db.get_playlist_tracks('missing') == []
    db.set_download_status(tracks[0], 'done')
    db.set_download_status(tracks[2], 'done')
    assert [track.id for track in db.get_playlist_tracks(
        playlist_id, filter_status='done', limit=1, offset=1)] == tracks[2:3]
    assert db.get_playlist_tracks(playlist_id, filter_status="' OR 1=1 --") == []


def test_foreign_keys_enabled_on_every_connection(db, tracks):
    playlist_id = db.create_playlist('Music')
    for _ in range(2):
        with db._connect() as conn:
            assert conn.execute('PRAGMA foreign_keys').fetchone()[0] == 1
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute(
                    'INSERT INTO playlist_tracks VALUES (?, ?, ?, ?)',
                    ('missing', tracks[0], 0, 100),
                )
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute(
                    'INSERT INTO playlist_tracks VALUES (?, ?, ?, ?)',
                    (playlist_id, 999999, 0, 100),
                )


def test_cascade_playlist_and_track_deletion(db, tracks):
    first = populate(db, tracks)
    second = populate(db, tracks)
    db.delete_playlist(first)
    assert entries(db, first) == []
    assert len(entries(db, second)) == 3
    assert all(db.get_track(track_id) is not None for track_id in tracks)
    with db._connect() as conn:
        conn.execute('DELETE FROM tracks WHERE id = ?', (tracks[1],))
    assert [t.id for t in db.get_playlist_tracks(second)] == [tracks[0], tracks[2]]
    assert db.list_playlists()[0].track_count == 2
    with db._connect() as conn:
        assert conn.execute('PRAGMA foreign_key_check').fetchall() == []


def test_remove_rolls_back_if_compaction_fails(db, tracks):
    playlist_id = populate(db, tracks)
    before = entries(db, playlist_id)
    with db._connect() as conn:
        conn.execute("""CREATE TRIGGER fail_compaction BEFORE UPDATE OF position
                        ON playlist_tracks
                        BEGIN SELECT RAISE(ABORT, 'test failure'); END""")
    with pytest.raises(sqlite3.IntegrityError, match='test failure'):
        db.remove_from_playlist(playlist_id, tracks[1])
    assert entries(db, playlist_id) == before
