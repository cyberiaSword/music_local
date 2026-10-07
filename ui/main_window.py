"""
Главное окно: TitleBar + sidebar + стек разделов + плеер + панель текста + трей.
"""

import logging
from core.paths import get_data_dir

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QStackedWidget,
    QLabel, QStatusBar, QSystemTrayIcon, QApplication
)

from core.database import Database, Track
from core.settings import Settings
from core.ws_server import WebSocketServer
from core.download_manager import DownloadManager
from core.player import Player
from core.lyrics import fetch_lyrics
from ui.title_bar import TitleBar
from ui.sidebar import Sidebar
from ui.track_list import TrackListWidget
from ui.player import PlayerWidget
from ui.downloads_page import DownloadsPage
from ui.lyrics_panel import LyricsPanel
from ui.settings_dialog import SettingsDialog
from ui.tray import Tray
from ui.styles import COLORS

logger = logging.getLogger('yt-local.ui')


class MainWindow(QMainWindow):
    def __init__(self, db: Database, settings: Settings, ws: WebSocketServer):
        super().__init__()
        self.db = db
        self.settings = settings
        self.ws = ws

        self.setWindowTitle("YT Music Local")
        self.resize(1200, 800)
        self.setMinimumSize(900, 600)

        # Пути к данным (рядом с main.py)
        self.data_dir = get_data_dir()
        self.downloads_dir = self.data_dir / 'downloads'
        self.covers_dir = self.data_dir / 'covers'
        self.lyrics_dir = self.data_dir / 'lyrics'

        # Состояние синхронизации текста
        self._lyrics_synced = False
        self._lyrics_loader = None

        # ============================================================
        # Центральный виджет: вертикально TitleBar + остальное
        # ============================================================
        central = QWidget()
        outer = QVBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ---- TitleBar ----
        self.title_bar = TitleBar()
        self.title_bar.minimize_clicked.connect(self.showMinimized)
        self.title_bar.maximize_clicked.connect(self._toggle_maximize)
        self.title_bar.close_clicked.connect(self.close)
        self.title_bar.search_changed.connect(self._on_global_search)
        outer.addWidget(self.title_bar)

        # ---- Нижняя часть: sidebar + контент ----
        content = QWidget()
        root = QHBoxLayout(content)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ---- Sidebar ----
        self.sidebar = Sidebar()
        self.sidebar.section_changed.connect(self._on_section_changed)
        root.addWidget(self.sidebar)

        # ---- Правая колонка ----
        right_column = QWidget()
        right_layout = QVBoxLayout(right_column)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)

        # ===== Стек разделов =====
        self.stack = QStackedWidget()

        # Библиотека
        self.track_list = TrackListWidget(db)
        self.track_list.track_activated.connect(self._on_track_activated)
        self.track_list.track_play_requested.connect(self._on_play_requested)
        self.stack.addWidget(self.track_list)

        # Загрузки
        self.downloads_page = DownloadsPage(db)
        self.stack.addWidget(self.downloads_page)

        # ---- Панель текста ----
        self.lyrics_panel = LyricsPanel()
        self.lyrics_panel.setVisible(False)
        self.lyrics_panel.closed.connect(self._on_lyrics_closed)

        # ---- Контейнер: стек + панель текста ----
        content_row = QWidget()
        content_row_layout = QHBoxLayout(content_row)
        content_row_layout.setContentsMargins(0, 0, 0, 0)
        content_row_layout.setSpacing(0)

        content_row_layout.addWidget(self.stack, stretch=1)
        content_row_layout.addWidget(self.lyrics_panel)

        right_layout.addWidget(content_row, stretch=1)

        # ---- Плеер ----
        self.player = Player(db)
        self.player_widget = PlayerWidget(self.player)
        right_layout.addWidget(self.player_widget)

        root.addWidget(right_column, stretch=1)

        outer.addWidget(content, stretch=1)

        self.setCentralWidget(central)

        # ============================================================
        # Статусбар
        # ============================================================
        self.setStatusBar(QStatusBar())
        self.statusBar().showMessage("Готово")

        self._stats_label = QLabel("—")
        from core.version import __version__
        version_label = QLabel(f"v{__version__}")
        version_label.setStyleSheet("color: #6a6a6a; padding-right: 12px;")
        self.statusBar().addPermanentWidget(version_label)
        self._stats_label.setStyleSheet("color: #b3b3b3; padding-right: 12px;")
        self.statusBar().addPermanentWidget(self._stats_label)

        # ============================================================
        # DownloadManager
        # ============================================================
        self.download_manager = DownloadManager(
            db=db,
            downloads_dir=self.downloads_dir,
            covers_dir=self.covers_dir,
            quality_v0=settings.get('audio_quality_v0', True),
            cover_mode=settings.get('cover_mode', 'auto'),
            video_frame_second=settings.get('video_frame_second', 15),
            proxy=settings.get('proxy', 'http://127.0.0.1:7897'),
        )
        self.download_manager.download_started.connect(self._on_download_started)
        self.download_manager.download_progress.connect(self._on_download_progress)
        self.download_manager.download_finished.connect(self._on_download_finished)
        self.download_manager.download_failed.connect(self._on_download_failed)
        self.download_manager.queue_changed.connect(self._on_queue_changed)

        if settings.get('auto_download', True):
            self.download_manager.start()

        # ============================================================
        # Трей
        # ============================================================
        self.tray = Tray(self)
        self.tray.show_window_requested.connect(self._restore_from_tray)
        self.tray.play_pause_requested.connect(self.player.play_pause)
        self.tray.next_requested.connect(self.player.next_track)
        self.tray.prev_requested.connect(self.player.prev_track)
        self.tray.quit_requested.connect(self._quit_from_tray)

        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray.show()
        else:
            logger.warning("Системный трей недоступен")

        # ============================================================
        # Подписки
        # ============================================================
        # WebSocket
        self.ws.track_played.connect(self._on_track_played)
        self.ws.client_connected.connect(self._on_client_connected)
        self.ws.client_disconnected.connect(self._on_client_disconnected)

        # Плеер
        self.player.track_changed.connect(self._on_player_track_changed)
        self.player.position_changed.connect(self._on_player_position)
        self.player.error_occurred.connect(
            lambda msg: self.statusBar().showMessage(f"⚠ {msg}", 5000)
        )

        # Кнопка текста в плеере
        self.player_widget.lyrics_toggled.connect(self._on_lyrics_toggled)

        # ============================================================
        # Таймер статистики
        # ============================================================
        self._stats_timer = QTimer(self)
        self._stats_timer.timeout.connect(self._refresh_stats)
        self._stats_timer.start(3000)

        self._refresh_stats()

        # Громкость и autoplay из настроек
        self.player.set_volume(self.settings.get('player_volume', 70))
        self.player.set_autoplay_next(self.settings.get('player_autoplay_next', True))

    # ================================================================
    # TitleBar
    # ================================================================

    def _toggle_maximize(self) -> None:
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()

    def _on_global_search(self, text: str) -> None:
        """Поиск из TitleBar фильтрует список и переключает на библиотеку."""
        if hasattr(self, 'track_list'):
            self.track_list.set_external_search(text)
            self.stack.setCurrentIndex(0)
            self.sidebar.set_section('library')

    # ================================================================
    # WebSocket
    # ================================================================

    def _on_track_played(self, data: dict) -> None:
        try:
            track_id = self.db.upsert_from_play(data)
            logger.info(f"Трек сохранён: id={track_id}, title={data.get('title')}")
            self.statusBar().showMessage(f"♪  {data.get('title', '—')}", 5000)

            if self.stack.currentIndex() == 0:
                self.track_list.refresh()
        except Exception as e:
            logger.exception(f"Ошибка сохранения трека: {e}")

    def _on_client_connected(self, remote: str) -> None:
        self.statusBar().showMessage(f"🟢 Браузер подключён: {remote}", 5000)

    def _on_client_disconnected(self, remote: str) -> None:
        self.statusBar().showMessage(f"🔴 Браузер отключён: {remote}", 5000)

    # ================================================================
    # Разделы
    # ================================================================

    def _on_section_changed(self, section: str) -> None:
        if section == 'settings':
            self._open_settings()
            self.sidebar.set_section('library')
            return

        index_map = {'library': 0, 'downloads': 1}
        self.stack.setCurrentIndex(index_map.get(section, 0))

    # ================================================================
    # Список / плеер
    # ================================================================

    def _on_track_activated(self, track: Track) -> None:
        logger.info(f"Выбран трек: {track.title}")
        self.statusBar().showMessage(
            f"Выбран: {track.title} — {track.channel or '—'}", 5000
        )

    def _on_play_requested(self, track: Track) -> None:
        queue = [
            self.track_list.model.get_track(i)
            for i in range(self.track_list.model.rowCount())
        ]
        queue = [t for t in queue if t]

        if self.player.play_track(track, queue=queue):
            self.statusBar().showMessage(f"♪  {track.title}", 5000)

    def _on_player_track_changed(self, track: Track) -> None:
        self.track_list.set_playing(track.video_id)
        if self.lyrics_panel.isVisible():
            self._load_lyrics_for_track(track)

    # ================================================================
    # Текст
    # ================================================================

    def _on_player_position(self, position_ms: int) -> None:
        if not self.lyrics_panel.isVisible():
            return
        if self.player.current_track() is None:
            return
        self.lyrics_panel.update_position(position_ms, self._lyrics_synced)

    def _on_lyrics_toggled(self, visible: bool) -> None:
        self.lyrics_panel.setVisible(visible)
        if visible and self.player.current_track():
            self._load_lyrics_for_track(self.player.current_track())

    def _on_lyrics_closed(self) -> None:
        self.lyrics_panel.setVisible(False)
        try:
            self.player_widget.btn_lyrics.setChecked(False)
        except AttributeError:
            pass

    def _load_lyrics_for_track(self, track: Track) -> None:
        if not self.lyrics_panel.isVisible():
            return

        from PyQt6.QtCore import QThread, pyqtSignal

        class LyricsLoader(QThread):
            loaded = pyqtSignal(object)

            def __init__(self, title, artist, duration, lyrics_dir, video_id):
                super().__init__()
                self.title = title
                self.artist = artist
                self.duration = duration
                self.lyrics_dir = lyrics_dir
                self.video_id = video_id

            def run(self):
                data = fetch_lyrics(
                    title=self.title,
                    artist=self.artist,
                    duration_sec=self.duration or 0,
                    lyrics_dir=self.lyrics_dir,
                    video_id=self.video_id,
                )
                self.loaded.emit(data)

        loader = LyricsLoader(
            title=track.title,
            artist=track.channel or '',
            duration=track.duration or 0,
            lyrics_dir=self.lyrics_dir,
            video_id=track.video_id,
        )
        loader.loaded.connect(self._on_lyrics_loaded)
        self._lyrics_loader = loader
        loader.start()

    def _on_lyrics_loaded(self, data) -> None:
        track = self.player.current_track()
        if track is None:
            return
        self._lyrics_synced = bool(data and data.is_synced)
        self.lyrics_panel.show_lyrics(data, track.title)

    # ================================================================
    # DownloadManager
    # ================================================================

    def _on_download_started(self, track_id: int, title: str) -> None:
        self.statusBar().showMessage(f"⬇ Скачиваю: {title}", 10000)
        self.track_list.model.update_track(track_id)
        self.downloads_page._reload()

    def _on_download_progress(self, track_id: int, percent: int) -> None:
        if percent % 5 == 0:
            self.statusBar().showMessage(f"⬇ Скачивание {percent}%", 5000)

        # Полоска в списке треков
        self.track_list.set_track_progress(track_id, percent)

        # Прогресс-бар на странице «Загрузки»
        self.downloads_page.update_progress(track_id, percent)

    def _on_download_finished(self, track_id: int, path: str) -> None:
        self.track_list.model.clear_progress(track_id)
        self.statusBar().showMessage(f"✓ Скачано: {path}", 8000)
        self.track_list.model.update_track(track_id)
        self.downloads_page._reload()
        self._refresh_stats()

    def _on_download_failed(self, track_id: int, error: str) -> None:
        self.track_list.model.clear_progress(track_id)
        self.statusBar().showMessage(f"✕ Ошибка: {error[:80]}", 10000)
        self.track_list.model.update_track(track_id)
        self.downloads_page._reload()
        self._refresh_stats()

    def _on_queue_changed(self) -> None:
        self._refresh_stats()

    # ================================================================
    # Статистика
    # ================================================================

    def _refresh_stats(self) -> None:
        try:
            s = self.db.stats()
            self._stats_label.setText(
                f"Всего: {s['total']}  •  "
                f"Скачано: {s['done']}  •  "
                f"Очередь: {s['pending']}  •  "
                f"Ошибки: {s['failed']}"
            )
        except Exception as e:
            logger.exception(f"Ошибка статистики: {e}")

    # ================================================================
    # Настройки
    # ================================================================

    def _open_settings(self) -> None:
        dialog = SettingsDialog(self.settings, self.downloads_dir, self)
        dialog.settings_changed.connect(self._apply_settings)
        dialog.exec()

    def _apply_settings(self) -> None:
        logger.info("Настройки обновлены")
        self.player.set_volume(self.settings.get('player_volume', 70))
        self.player.set_autoplay_next(self.settings.get('player_autoplay_next', True))
        self.download_manager.quality_v0 = self.settings.get('audio_quality_v0', True)
        self.download_manager.cover_mode = self.settings.get('cover_mode', 'auto')
        self.download_manager.video_frame_second = self.settings.get('video_frame_second', 15)
        self.download_manager.proxy = self.settings.get('proxy', 'http://127.0.0.1:7897')

    # ================================================================
    # Трей / выход
    # ================================================================

    def _restore_from_tray(self) -> None:
        self.showNormal()
        self.activateWindow()

    def _quit_from_tray(self) -> None:
        self._shutdown()
        QApplication.quit()

    def _shutdown(self) -> None:
        logger.info("Остановка фоновых потоков")
        if self.download_manager.isRunning():
            self.download_manager.stop()
            self.download_manager.wait(3000)
        if self.ws.isRunning():
            self.ws.stop()
            self.ws.wait(3000)

    def closeEvent(self, event) -> None:
        if self.settings.get('minimize_to_tray', True):
            event.ignore()
            self.hide()
            try:
                self.tray.show_message(
                    "YT Music Local",
                    "Свернуто в трей. Двойной клик — развернуть."
                )
            except Exception:
                pass
            return

        self._shutdown()
        event.accept()