"""Проверки сохранения позиции без аудиоустройства и реального декодирования."""

import os
from unittest.mock import Mock

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PyQt6")
from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtMultimedia import QMediaPlayer
from PyQt6.QtWidgets import QApplication

from core import player as player_module
from core.database import Database
from ui.controllers.player_controller import PlayerController


class FakeMedia(QObject):
    PlaybackState = QMediaPlayer.PlaybackState
    MediaStatus = QMediaPlayer.MediaStatus
    Error = QMediaPlayer.Error
    positionChanged = pyqtSignal(int)
    durationChanged = pyqtSignal(int)
    playbackStateChanged = pyqtSignal(object)
    errorOccurred = pyqtSignal(object, str)
    seekableChanged = pyqtSignal(bool)
    mediaStatusChanged = pyqtSignal(object)

    def __init__(self):
        super().__init__()
        self._position = 0
        self._duration = 0
        self._seekable = False
        self._status = self.MediaStatus.NoMedia
        self._state = self.PlaybackState.StoppedState
        self.seeks = []

    def setAudioOutput(self, audio):
        self.audio = audio

    def setSource(self, source):
        self.source = source
        self._duration = 0
        self._seekable = False
        self._status = self.MediaStatus.LoadingMedia
        self.setPosition(0)
        self._change_state(self.PlaybackState.StoppedState)

    def _change_state(self, state):
        self._state = state
        self.playbackStateChanged.emit(state)

    def load(self, duration=60000):
        self._duration = duration
        self._status = self.MediaStatus.LoadedMedia
        self.durationChanged.emit(duration)
        self._seekable = True
        self.seekableChanged.emit(True)
        self.mediaStatusChanged.emit(self._status)

    def setPosition(self, position):
        self._position = position
        self.seeks.append(position)
        self.positionChanged.emit(position)

    def position(self):
        return self._position

    def duration(self):
        return self._duration

    def isSeekable(self):
        return self._seekable

    def mediaStatus(self):
        return self._status

    def playbackState(self):
        return self._state

    def play(self):
        self._change_state(self.PlaybackState.PlayingState)

    def pause(self):
        self._change_state(self.PlaybackState.PausedState)

    def stop(self):
        self.setPosition(0)
        self._change_state(self.PlaybackState.StoppedState)


class FakeAudio:
    def setVolume(self, volume):
        self._volume = volume

    def volume(self):
        return self._volume


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def setup(app, tmp_path, monkeypatch):
    monkeypatch.setattr("core.paths.get_data_dir", lambda: tmp_path)
    monkeypatch.setattr(player_module, "QMediaPlayer", FakeMedia)
    monkeypatch.setattr(player_module, "QAudioOutput", FakeAudio)
    db = Database(tmp_path / "tracks.db")
    player = player_module.Player(db)

    def track(video_id):
        path = tmp_path / f"{video_id}.mp3"
        path.write_bytes(b"fake audio")
        track_id = db.upsert_from_play({"videoId": video_id, "title": video_id, "url": "u"})
        db.set_download_status(track_id, "done", str(path))
        return db.get_track(track_id)

    yield db, player, track
    player.shutdown()


def test_new_play_and_saved_position(setup):
    db, player, track = setup
    assert db.get_playback_state() is None
    song = track("song")
    assert player.play_track(song)
    assert db.get_playback_state()[0].id == song.id
    player._player.load()
    player._player.setPosition(12345)
    player._save_timer.timeout.emit()
    assert db.get_playback_state()[1] == 12345
    player._player.setPosition(15123)
    player.pause()
    assert db.get_playback_state()[1] == 15123
    player.stop()
    assert player.current_track() is None
    assert db.get_playback_state()[1] == 15123


@pytest.mark.parametrize("position, expected", [(12000, 12000), (-10, 0), (60000, 0), (90000, 0)])
def test_restore_waits_for_media_and_clamps_position(setup, position, expected):
    db, player, track = setup
    assert player.play_track(track("resume"), position_ms=position)
    assert player._pending_seek_ms == max(0, position)
    assert db.get_playback_state()[1] == max(0, position)
    player._player.positionChanged.emit(0)
    assert player._last_position_ms == max(0, position)
    player._player.load()
    assert player._pending_seek_ms is None
    assert player.position() == expected
    player.save_playback_state()
    assert db.get_playback_state()[1] == expected


def test_shutdown_preserves_position_and_stops_timer(setup):
    db, player, track = setup
    player.play_track(track("shutdown"))
    player._player.load()
    player._player.setPosition(24680)
    player.shutdown()
    assert db.get_playback_state()[1] == 24680
    assert not player._save_timer.isActive()
    assert player.current_track() is None


def test_switch_and_missing_file_keep_valid_state(setup):
    db, player, track = setup
    first, second = track("first"), track("second")
    player.play_track(first, queue=[first, second])
    player._player.load()
    player._player.setPosition(10000)
    player.play_track(second, queue=[first, second], position_ms=23000)
    assert player.current_track().id == second.id
    assert db.get_playback_state()[1] == 23000
    player._player.load()
    missing = track("missing")
    from pathlib import Path
    Path(missing.file_path).unlink()
    assert not player.play_track(missing)
    assert db.get_playback_state()[0].id == second.id
    assert db.get_playback_state()[1] == 23000
    player.play_track(second)
    player._player.load()
    assert player.position() == 0


def test_end_resets_position_and_autoplays_next(setup):
    db, player, track = setup
    first, second = track("first"), track("second")
    player.play_track(first, queue=[first, second])
    player._player.load()
    player._player.setPosition(60000)
    player._player._change_state(FakeMedia.PlaybackState.StoppedState)
    assert player.current_track().id == second.id
    assert db.get_playback_state()[0].id == second.id
    assert db.get_playback_state()[1] == 0
    player.set_autoplay_next(False)
    player._player.load()
    player._player.setPosition(60000)
    player._player._change_state(FakeMedia.PlaybackState.StoppedState)
    assert db.get_playback_state()[1] == 0


def test_resume_controller_uses_saved_position_and_queue(setup):
    db, player, track = setup
    first, second = track("first"), track("second")
    db.save_playback_state(first.id, 32100)
    tracks = Mock()
    tracks.build_queue.return_value = [second]
    controller = PlayerController(player, tracks, Mock())
    controller.resume_track()
    assert player.current_track().id == first.id
    assert player._pending_seek_ms == 32100
    assert player._queue_index == 0
    player._player.load()
    player._player.setPosition(34100)
    controller.resume_track()
    assert db.get_playback_state()[1] == 34100
    tracks.set_playing.assert_called_with(first.video_id)


def test_resume_no_state_does_nothing(setup):
    _, player, _ = setup
    tracks = Mock()
    controller = PlayerController(player, tracks, Mock())
    controller.resume_track()
    tracks.build_queue.assert_not_called()
    assert player.current_track() is None


def test_queue_uses_id_when_track_metadata_changed(setup):
    from dataclasses import replace
    _, player, track = setup
    song, other = track("song"), track("other")
    stale = replace(song, title="Old title", play_count=0)
    player.play_track(song, queue=[other, stale], position_ms=10000)
    assert player._queue_index == 1
