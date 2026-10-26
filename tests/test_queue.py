"""Интеграционные проверки очереди без native audio и декодирования."""

import os
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import Mock

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PyQt6")
from PyQt6.QtWidgets import QApplication

from core import player as player_module
from core.database import Database, Track
from core.settings import Settings
from ui.controllers.player_controller import PlayerController
from .test_player_resume import FakeAudio, FakeMedia


@dataclass
class QueueRig:
    db: Database
    player: player_module.Player
    controller: PlayerController
    settings: Settings
    tracks: list[Track]

    def ids(self, *rows: int) -> list[int]:
        return [self.tracks[row].id for row in rows]

    def queue(self, *rows: int, current: int = -1) -> None:
        self.player.set_queue([self.tracks[row] for row in rows], current)

    def play(self, row: int) -> None:
        assert self.player.play_queue_index(row)

    def finish(self) -> None:
        media = self.player._player
        media.load()
        media.setPosition(media.duration())
        media._change_state(FakeMedia.PlaybackState.StoppedState)


@pytest.fixture(scope="module")
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


@pytest.fixture
def rig(app: QApplication, tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch) -> Iterator[QueueRig]:
    monkeypatch.setattr("core.paths.get_data_dir", lambda: tmp_path)
    monkeypatch.setattr(player_module, "QMediaPlayer", FakeMedia)
    monkeypatch.setattr(player_module, "QAudioOutput", FakeAudio)
    db = Database(tmp_path / "tracks.db")
    settings = Settings(tmp_path / "settings.json")
    tracks: list[Track] = []
    for row in range(4):
        path = tmp_path / f"track-{row}.mp3"
        path.write_bytes(b"fake audio")
        track_id = db.upsert_from_play({
            "videoId": f"video-{row}", "title": f"Track {row}", "url": "u",
        })
        db.set_download_status(track_id, "done", str(path))
        track = db.get_track(track_id)
        assert isinstance(track, Track)
        tracks.append(track)
    player = player_module.Player(db)
    track_controller = Mock()
    track_controller.build_queue.return_value = tracks
    controller = PlayerController(player, track_controller, Mock(), settings=settings)
    yield QueueRig(db, player, controller, settings, tracks)
    player.shutdown()


def test_enqueue_next_end_and_duplicate_occurrences(rig: QueueRig) -> None:
    controller = rig.controller
    rig.queue(0, 1)
    rig.play(0)
    controller.enqueue(rig.tracks[0].id)
    controller.enqueue(rig.tracks[2].id, "next")
    controller.enqueue(rig.tracks[2].id, "next")
    assert controller.queue_ids == rig.ids(0, 2, 2, 1, 0)
    assert controller.current_index == 0
    assert rig.player.current_track().id == rig.tracks[0].id
    snapshot = controller.queue_ids
    snapshot.clear()
    assert len(controller.queue_ids) == 5
    controller.queue_tracks.clear()
    assert len(controller.queue_tracks) == 5


def test_enqueue_empty_missing_id_and_invalid_position(rig: QueueRig) -> None:
    rig.controller.enqueue(rig.tracks[0].id, "next")
    assert rig.controller.queue_ids == rig.ids(0)
    assert rig.controller.current_index == -1
    rig.controller.enqueue(999999)
    assert rig.controller.queue_ids == rig.ids(0)
    with pytest.raises(ValueError):
        rig.controller.enqueue(rig.tracks[0].id, "invalid")


@pytest.mark.parametrize("source,target,expected,current", [
    (0, 3, (1, 0, 2, 0), 1),
    (3, 0, (2, 0, 1, 0), 3),
    (2, 0, (0, 0, 1, 2), 0),
    (2, 2, (0, 1, 0, 2), 2),
])
def test_move_tracks_occurrence_not_id(rig: QueueRig, source: int, target: int,
                                     expected: tuple[int, ...], current: int) -> None:
    rig.queue(0, 1, 0, 2)
    rig.play(2)
    rig.controller.move_in_queue(source, target)
    assert rig.controller.queue_ids == rig.ids(*expected)
    assert rig.controller.current_index == rig.player.queue_index == current
    assert rig.player.current_track().id == rig.tracks[0].id


@pytest.mark.parametrize("source,target", [(-1, 0), (0, -1), (4, 0), (0, 4)])
def test_move_out_of_bounds_is_noop(rig: QueueRig, source: int, target: int) -> None:
    rig.queue(0, 1, 0, 2)
    rig.play(2)
    rig.controller.move_in_queue(source, target)
    assert rig.controller.queue_ids == rig.ids(0, 1, 0, 2)
    assert rig.controller.current_index == 2


@pytest.mark.parametrize("removed,expected,current,playing", [
    (0, (1, 0, 2), 1, True), (1, (0, 0, 2), 1, True),
    (2, (0, 1, 2), -1, False), (3, (0, 1, 0), 2, True),
    (-1, (0, 1, 0, 2), 2, True), (4, (0, 1, 0, 2), 2, True),
])
def test_remove_bounds_and_current(rig: QueueRig, removed: int,
                                  expected: tuple[int, ...], current: int,
                                  playing: bool) -> None:
    rig.queue(0, 1, 0, 2)
    rig.play(2)
    rig.controller.remove_from_queue(removed)
    assert rig.controller.queue_ids == rig.ids(*expected)
    assert rig.controller.current_index == current
    assert rig.player.is_playing() is playing
    assert (rig.player.current_track() is not None) is playing


def test_clear_is_idempotent_and_persisted(rig: QueueRig) -> None:
    rig.queue(0, 0, 1)
    rig.play(1)
    for _ in range(2):
        rig.controller.clear_queue()
        assert rig.controller.queue_ids == []
        assert rig.controller.current_index == rig.player.queue_index == -1
        assert rig.player.current_track() is None
    saved = Settings(rig.settings.path)
    assert saved.get("queue_track_ids") == []
    assert saved.get("queue_current_index") == -1


def test_playback_by_duplicate_index_and_invalid_bounds(rig: QueueRig) -> None:
    rig.queue(0, 1, 0)
    emitted: list[int] = []
    rig.player.queue_index_changed.connect(emitted.append)
    rig.controller.play_queue_index(2)
    assert rig.controller.current_index == 2
    assert rig.player.current_track().id == rig.tracks[0].id
    for row in (-1, 3):
        assert rig.player.play_queue_index(row) is False
    assert emitted == [2]
    assert rig.controller.current_index == 2


@pytest.mark.parametrize("direction,start,expected", [("next", 0, 2), ("prev", 2, 0)])
def test_navigation_skips_missing_file(rig: QueueRig, direction: str,
                                      start: int, expected: int) -> None:
    rig.queue(0, 1, 2)
    rig.play(start)
    Path(rig.tracks[1].file_path).unlink()
    errors: list[str] = []
    rig.player.error_occurred.connect(errors.append)
    getattr(rig.controller, f"{direction}_track")()
    assert rig.controller.current_index == expected
    assert rig.player.current_track().id == rig.tracks[expected].id
    assert len(errors) == 1


def test_failed_index_preserves_current_and_prev_restarts(rig: QueueRig) -> None:
    rig.queue(0, 1)
    rig.play(0)
    Path(rig.tracks[1].file_path).unlink()
    assert not rig.player.play_queue_index(1)
    assert rig.controller.current_index == 0
    rig.player._player.load()
    rig.player.seek(4000)
    rig.controller.prev_track()
    assert rig.player.position() == 0
    assert rig.player.queue_index == 0


@pytest.mark.parametrize("enabled,expected", [(True, 2), (False, 0)])
def test_autoplay_missing_and_disabled(rig: QueueRig, enabled: bool,
                                     expected: int) -> None:
    rig.queue(0, 1, 2)
    rig.play(0)
    Path(rig.tracks[1].file_path).unlink()
    rig.player.set_autoplay_next(enabled)
    rig.finish()
    assert rig.controller.current_index == expected
    assert rig.player.current_track().id == rig.tracks[expected].id
    assert rig.player.is_playing() is enabled


@pytest.mark.parametrize("mode,expected", [("off", None), ("all", 0), ("one", 1)])
def test_repeat_at_end(rig: QueueRig, mode: str, expected: int | None) -> None:
    rig.queue(0, 1)
    rig.play(1)
    changes: list[str] = []
    rig.player.repeat_changed.connect(changes.append)
    while rig.player.get_repeat_mode() != mode:
        rig.player.cycle_repeat()
    assert changes == {"off": [], "all": ["all"], "one": ["all", "one"]}[mode]
    rig.finish()
    if expected is None:
        assert rig.player.current_track() is None
        assert not rig.player.is_playing()
    else:
        assert rig.controller.current_index == expected
        assert rig.player.current_track().id == rig.tracks[expected].id
        assert rig.player.is_playing()


def test_repeat_cycle_and_previous_wrap(rig: QueueRig) -> None:
    rig.queue(0, 1)
    rig.play(0)
    rig.controller.prev_track()
    assert rig.controller.current_index == 0
    assert rig.player.cycle_repeat() == "all"
    rig.controller.prev_track()
    assert rig.controller.current_index == 1
    assert rig.player.cycle_repeat() == "one"
    assert rig.player.cycle_repeat() == "off"


@pytest.mark.parametrize("command", ["enqueue", "play_next"])
def test_shuffle_keeps_visible_order_and_next_priority(
        rig: QueueRig, monkeypatch: pytest.MonkeyPatch, command: str) -> None:
    monkeypatch.setattr(player_module.random, "shuffle", lambda rows: rows.reverse())
    rig.queue(0, 1, 0, 2)
    rig.play(2)
    visible = rig.controller.queue_ids
    assert rig.player.toggle_shuffle()
    assert rig.controller.queue_ids == visible
    assert rig.player._shuffle_order == [2, 3, 1, 0]
    if command == "enqueue":
        rig.controller.enqueue(rig.tracks[3].id, "next")
        expected = rig.ids(0, 1, 0, 3, 2)
    else:
        rig.controller.play_next(1)
        expected = rig.ids(0, 0, 1, 2)
    assert rig.controller.queue_ids == expected
    target = rig.controller.current_index + 1
    rig.controller.next_track()
    assert rig.controller.current_index == target
    assert rig.player.current_track().id == expected[target]
    assert rig.controller.queue_ids == expected
    assert not rig.player.toggle_shuffle()
    assert rig.controller.queue_ids == expected


@pytest.mark.parametrize("selected,restored", [(0, -1), (5, 0), (204, 199)])
def test_persistence_last_200_adjusts_current(rig: QueueRig, selected: int,
                                            restored: int) -> None:
    tracks = [rig.tracks[row % 4] for row in range(205)]
    rig.player.set_queue(tracks, selected)
    saved = Settings(rig.settings.path)
    assert saved.get("queue_track_ids") == [track.id for track in tracks[-200:]]
    assert saved.get("queue_current_index") == restored
    other = player_module.Player(rig.db)
    try:
        controller = PlayerController(other, Mock(), Mock(), settings=saved)
        assert controller.queue_ids == [track.id for track in tracks[-200:]]
        assert controller.current_index == other.queue_index == restored
        assert other.current_track() is None
        assert not other.is_playing()
    finally:
        other.shutdown()


@pytest.mark.parametrize("selected,restored", [(0, -1), (2, 1), (3, -1), (4, 2)])
def test_restore_drops_missing_db_ids_and_adjusts_current(
        rig: QueueRig, selected: int, restored: int) -> None:
    saved = Settings(rig.settings.path.parent / "restore.json")
    saved.set("queue_track_ids", [999999, *rig.ids(0, 0), 999998, rig.tracks[1].id])
    saved.set("queue_current_index", selected)
    saved.save()
    other = player_module.Player(rig.db)
    try:
        controller = PlayerController(other, Mock(), Mock(), settings=Settings(saved.path))
        assert controller.queue_ids == rig.ids(0, 0, 1)
        assert controller.current_index == restored
        persisted = Settings(saved.path)
        assert persisted.get("queue_track_ids") == rig.ids(0, 0, 1)
        assert persisted.get("queue_current_index") == restored
    finally:
        other.shutdown()


def test_exhausted_missing_next_keeps_last_valid_index(rig: QueueRig) -> None:
    rig.queue(0, 1, 2)
    rig.play(0)
    for track in rig.tracks[1:3]:
        Path(track.file_path).unlink()
    rig.controller.next_track()
    assert rig.player.current_track() is None
    assert rig.player.queue_index == rig.controller.current_index == 0


def test_shuffle_repeat_all_advances_at_wrap(
        rig: QueueRig, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(player_module.random, "shuffle", lambda rows: None)
    rig.queue(0, 1, 2)
    rig.play(0)
    rig.player.toggle_shuffle()
    rig.player.cycle_repeat()
    rig.controller.next_track()
    rig.controller.next_track()
    assert rig.controller.current_index == 2
    rig.controller.next_track()
    assert rig.controller.current_index != 2


def test_pending_track_refreshes_file_path_before_playback(rig: QueueRig) -> None:
    track_id = rig.db.upsert_from_play({'videoId': 'later', 'title': 'Later', 'url': 'u'})
    rig.controller.enqueue(track_id)
    assert rig.controller.queue_tracks[0].file_path is None
    path = rig.settings.path.parent / 'later.mp3'
    path.write_bytes(b'fake audio')
    rig.db.set_download_status(track_id, 'done', str(path))
    rig.controller.play_queue_index(0)
    assert rig.player.current_track().id == track_id
    assert rig.controller.queue_tracks[0].file_path == str(path)
    assert rig.player.is_playing()


def test_shuffle_previous_respects_repeat_boundary(rig: QueueRig) -> None:
    rig.queue(0, 1, 2)
    rig.play(0)
    rig.player.toggle_shuffle()
    rig.controller.prev_track()
    assert rig.controller.current_index == 0
    assert rig.player._shuffle_pos == 0
    rig.player.cycle_repeat()
    rig.controller.prev_track()
    assert rig.controller.current_index != 0
