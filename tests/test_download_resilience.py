import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest
from PyQt6.QtCore import QCoreApplication
from PyQt6.QtMultimedia import QMediaPlayer

from core.download_manager import DownloadManager
from core.downloader import _friendly_download_error, _try_clients
from core.player import _friendly_media_error


def test_try_clients_falls_back_from_cookies_to_other_client(monkeypatch):
    attempts = []

    class FakeYoutubeDL:
        def __init__(self, options):
            self.options = options
            attempts.append(options)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def extract_info(self, url, download=True):
            if len(attempts) < 4:
                raise RuntimeError("ошибка временной попытки")
            return {"title": "Тестовый трек"}

    fake_ytdlp = ModuleType("yt_dlp")
    fake_ytdlp.YoutubeDL = FakeYoutubeDL
    monkeypatch.setitem(sys.modules, "yt_dlp", fake_ytdlp)

    result = _try_clients(
        "https://example.invalid/video",
        {
            "cookiefile": "cookies.txt",
            "extractor_args": {"youtube": {"lang": ["ru"]}},
        },
        ["ios", "mweb"],
    )

    assert result["title"] == "Тестовый трек"
    assert ["cookiefile" in options for options in attempts] == [
        True, False, True, False
    ]
    assert [
        options["extractor_args"]["youtube"]["player_client"][0]
        for options in attempts
    ] == ["ios", "ios", "mweb", "mweb"]
    assert all(
        options["extractor_args"]["youtube"]["lang"] == ["ru"]
        for options in attempts
    )


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        ("Please sign in to confirm", "YouTube требует авторизацию"),
        ("HTTP Error 400: Bad Request", "YouTube отклонил запрос"),
        ("HTTP Error 429: Too Many Requests", "временно ограничил загрузки"),
    ],
)
def test_download_errors_are_localized(error, expected):
    assert expected in _friendly_download_error(error)


def test_media_errors_distinguish_corrupt_file_and_codec():
    damaged = _friendly_media_error(QMediaPlayer.Error.ResourceError, "corrupt input")
    unsupported = _friendly_media_error(QMediaPlayer.Error.FormatError, "")

    assert "повреждён" in damaged
    assert "кодек" in unsupported


def test_download_queue_continues_after_track_exception(monkeypatch, tmp_path):
    QCoreApplication.instance() or QCoreApplication([])
    tracks = [
        SimpleNamespace(id=1, title="Первый трек"),
        SimpleNamespace(id=2, title="Второй трек"),
    ]

    class FakeDatabase:
        def __init__(self):
            self.statuses = {}

        def get_all(self, filter_status=None):
            return tracks

        def set_download_status(self, track_id, status):
            self.statuses[track_id] = status

    database = FakeDatabase()
    manager = DownloadManager(database, tmp_path, tmp_path)
    handled = []

    def process_track(track):
        handled.append(track.id)
        if track.id == 1:
            raise RuntimeError("сбой тестового трека")
        manager._stop = True

    monkeypatch.setattr("core.download_manager.is_ytdlp_available", lambda: True)
    manager._process_track = process_track
    manager.run()

    assert handled == [1, 2]
    assert database.statuses[1] == "failed"
