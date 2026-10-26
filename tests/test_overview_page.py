"""Offscreen-проверки обзора без pytest-qt и установки зависимостей."""

import os
import threading
import time
from dataclasses import replace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PyQt6")
from PyQt6.QtCore import QCoreApplication, QEvent, QPoint, Qt
from PyQt6.QtTest import QSignalSpy, QTest
from PyQt6.QtWidgets import QApplication, QLabel, QPushButton, QScrollArea

from core.database import Track
from ui import overview_page as overview
from ui.styles import build_stylesheet


@pytest.fixture(scope="module")
def app():
    application = QApplication.instance() or QApplication([])
    application.setStyleSheet(build_stylesheet())
    yield application


def wait_until(app, predicate, timeout=3):
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        app.processEvents()
        QTest.qWait(10)
    assert predicate(), "Истекло ожидание Qt"
    app.processEvents()


def make_track(**changes):
    track = Track(1, "video", "<b>Полный title</b>", "<i>Артист</i>",
                  "https://example.invalid", "", "", 1, "done")
    return replace(track, **changes)


class FakeDatabase:
    def __init__(self):
        self.recent = []
        self.downloads = []
        self.weekly = []
        self.state = None
        self.stats = dict(total=0, downloaded=0, downloads_bytes=0, free_bytes=None)
        self.calls = []
        self.thread_ids = []
        self.entered = threading.Event()
        self.release = threading.Event()
        self.release.set()

    def get_recent_tracks(self, limit):
        self.calls.append(("recent", limit))
        self.thread_ids.append(threading.get_ident())
        self.entered.set()
        assert self.release.wait(3), "Worker не освобождён"
        return self.recent[:limit]

    def get_recent_downloads(self, limit):
        self.calls.append(("downloads", limit))
        self.thread_ids.append(threading.get_ident())
        return self.downloads[:limit]

    def get_top_week(self, limit):
        self.calls.append(("weekly", limit))
        self.thread_ids.append(threading.get_ident())
        return self.weekly[:limit]

    def get_overview_stats(self):
        self.thread_ids.append(threading.get_ident())
        return self.stats.copy()

    def get_playback_state(self):
        self.thread_ids.append(threading.get_ident())
        return self.state


@pytest.fixture
def page_factory(app, monkeypatch, tmp_path):
    monkeypatch.setattr(overview, "get_data_dir", lambda: tmp_path)
    pages = []

    def create(db=None):
        page = overview.OverviewPage(db or FakeDatabase())
        pages.append(page)
        return page

    yield create
    for page in pages:
        page.db.release.set()
        page.shutdown()
        app.processEvents()
        page.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def cards(row):
    return [row.itemAt(i).widget() for i in range(row.count() - 1)
            if isinstance(row.itemAt(i).widget(), overview.OverviewTrackCard)]


def test_empty_stats_and_messages(app, page_factory):
    page = page_factory()
    assert page._resume_section.isHidden()
    wait_until(app, lambda: page._worker is None)
    assert page._resume_section.isHidden()
    assert page._stats_labels["total"].text() == "0"
    assert page._stats_labels["downloaded"].text() == "0"
    assert page._stats_labels["downloads_bytes"].text() == "0.0 МБ"
    assert page._stats_labels["free_bytes"].text() == "Нет данных"
    for row in (page._recent_layout, page._downloads_layout, page._weekly_layout):
        assert isinstance(row.itemAt(0).widget(), QLabel)
        assert row.itemAt(0).widget().text()


def test_rows_small_window_and_plain_text(app, page_factory):
    db = FakeDatabase()
    db.recent = [make_track(id=i, title=f"<b>Трек {i}</b>") for i in range(10)]
    db.downloads = list(reversed(db.recent))
    db.weekly = [(db.recent[0], 12)]
    page = page_factory(db)
    page.resize(320, 360)
    page.show()
    wait_until(app, lambda: page._worker is None)
    QTest.qWait(50)
    assert [c.track.id for c in cards(page._recent_layout)] == list(range(8))
    assert [c.track.id for c in cards(page._downloads_layout)] == list(range(9, 1, -1))
    assert len(cards(page._weekly_layout)) == 1
    assert ("recent", 8) in db.calls and ("downloads", 8) in db.calls
    assert ("weekly", 6) in db.calls
    assert page._scroll.verticalScrollBar().maximum() > 0
    assert page.minimumSizeHint().width() <= 320
    for scroll in page.findChildren(QScrollArea, "OverviewRowScroll"):
        assert scroll.height() == 230
        assert scroll.horizontalScrollBar().maximum() > 0 or scroll.widget().layout().count() == 2
    card = cards(page._recent_layout)[0]
    title = card.findChild(QLabel, "OverviewCardTitle")
    subtitle = card.findChild(QLabel, "OverviewCardSubtitle")
    assert title.textFormat() == Qt.TextFormat.PlainText
    assert subtitle.textFormat() == Qt.TextFormat.PlainText
    assert title.toolTip() == card.track.title
    spy = QSignalSpy(page.track_play_requested)
    QTest.keyClick(card, Qt.Key.Key_Return)
    QTest.keyClick(card, Qt.Key.Key_Space)
    QTest.mouseClick(card, Qt.MouseButton.LeftButton, pos=QPoint(4, 4))
    assert len(spy) == 3
    assert all(args[0] is card.track for args in spy)
    assert all(tid != threading.get_ident() for tid in db.thread_ids)


def test_resume_signals_and_background_visibility(app, page_factory, tmp_path):
    (tmp_path / "last.mp3").write_bytes(b"local mp3")
    db = FakeDatabase()
    db.state = (make_track(file_path="last.mp3"), 1200)
    page = page_factory(db)
    page.show()
    wait_until(app, lambda: page._worker is None)
    card = cards(page._resume_layout)[0]
    resume = QSignalSpy(page.resume_play_requested)
    play = QSignalSpy(page.track_play_requested)
    QTest.mouseClick(card.findChild(QPushButton), Qt.MouseButton.LeftButton)
    assert len(resume) == 1 and list(resume[0]) == []
    QTest.mouseClick(card, Qt.MouseButton.LeftButton, pos=QPoint(4, 4))
    QTest.keyClick(card, Qt.Key.Key_Space)
    assert len(resume) == 3 and len(play) == 0
    db.release.clear()
    page.refresh()
    assert not page._resume_section.isHidden()
    page._on_loaded(page._request_id - 1, {}, "устаревший ответ")
    assert not page._resume_section.isHidden()
    db.release.set()
    wait_until(app, lambda: page._worker is None)
    db.state = None
    page.refresh()
    wait_until(app, lambda: page._worker is None)
    assert page._resume_section.isHidden()


def test_coalescing_stale_results_and_deletion(app, page_factory):
    db = FakeDatabase()
    db.release.clear()
    page = page_factory(db)
    first = page._worker
    deleted = QSignalSpy(first.destroyed)
    wait_until(app, db.entered.is_set)
    for _ in range(30):
        page.refresh()
    assert page._worker is first and page._pending
    assert len(db.calls) == 1
    page._on_loaded(first.request_id, {}, "Старый ответ")
    assert page._message.text() == "Загружаем подборки…"
    db.release.set()
    wait_until(app, lambda: page._worker is None)
    assert [call for call in db.calls if call[0] == "recent"] == [("recent", 8)] * 2
    assert not page._pending
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert len(deleted) == 1


def test_shutdown_drops_pending_and_late_answers(app, page_factory):
    db = FakeDatabase()
    db.release.clear()
    page = page_factory(db)
    first = page._worker
    deleted = QSignalSpy(first.destroyed)
    wait_until(app, db.entered.is_set)
    page.refresh()
    db.release.set()
    page.shutdown()
    page.shutdown()
    assert not first.isRunning()
    assert page._closed and not page._pending
    page.refresh()
    page._on_loaded(page._request_id, {}, "Поздний ответ")
    app.processEvents()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert len(deleted) == 1
    assert len([call for call in db.calls if call[0] == "recent"]) == 1
    assert page._message.text() == "Загружаем подборки…"


@pytest.mark.parametrize("file_path", [None, "missing.mp3", "not-mp3.txt"])
def test_resume_requires_existing_mp3(app, page_factory, tmp_path, file_path):
    (tmp_path / "not-mp3.txt").write_text("not audio")
    db = FakeDatabase()
    db.state = (make_track(file_path=file_path), 0)
    page = page_factory(db)
    wait_until(app, lambda: page._worker is None)
    assert page._resume_section.isHidden()


def test_covers_are_read_in_worker_and_errors_keep_content(app, page_factory, monkeypatch, tmp_path):
    from PyQt6.QtGui import QImage

    image = QImage(8, 8, QImage.Format.Format_RGB32)
    image.fill(0)
    assert image.save(str(tmp_path / "cover.png"))
    (tmp_path / "last.mp3").write_bytes(b"mp3")
    reader = overview.QImageReader
    threads = []

    def recording_reader(path):
        threads.append(threading.get_ident())
        return reader(path)

    monkeypatch.setattr(overview, "QImageReader", recording_reader)
    db = FakeDatabase()
    track = make_track(file_path="last.mp3", cover_path="cover.png")
    db.recent = [track]
    db.state = (track, 1)
    db.stats = dict(total=9, downloaded=2, downloads_bytes=2 * 1024 ** 3,
                    free_bytes=512 * 1024 ** 2)
    page = page_factory(db)
    wait_until(app, lambda: page._worker is None)
    assert threads and all(tid != threading.get_ident() for tid in threads)
    assert not page._covers["cover.png"].isNull()
    assert page._stats_labels["downloads_bytes"].text() == "2.0 ГБ"
    assert page._stats_labels["free_bytes"].text() == "512.0 МБ"
    original = cards(page._resume_layout)[0]
    page._on_loaded(page._request_id, {}, "Ошибка БД")
    assert cards(page._resume_layout)[0] is original
    assert not page._resume_section.isHidden()
    assert not page._message.isHidden()
    assert page._stats_labels["total"].text() == "9"
