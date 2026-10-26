"""
Главное окно: TitleBar + sidebar + стек разделов + плеер + панель текста + трей.
"""

import logging
import sqlite3
from collections.abc import Callable
from functools import partial
from core.paths import get_data_dir
from core.content_filter import ContentFilter

from PyQt6.QtCore import Qt, QTimer, pyqtSignal, pyqtSlot
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QStackedWidget,
    QLabel, QStatusBar, QSystemTrayIcon, QApplication, QInputDialog, QMessageBox
)

from ui.queue_panel import QueuePanel

from core.database import Database, Track
from core.hotkeys import GlobalHotkeyManager
from core.settings import Settings
from core.ws_server import WebSocketServer
from core.download_manager import DownloadManager
from core.environment import EnvironmentCheckWorker
from core.player import Player
from ui.controllers import (
    DownloadController,
    LyricsController,
    PlayerController,
    TrackController,
)
from ui.feedback_widgets import Toast
from ui.title_bar import TitleBar
from ui.sidebar import Sidebar
from ui.track_list import TrackListWidget
from ui.player import PlayerWidget
from ui.downloads_page import DownloadsPage
from ui.overview_page import OverviewPage
from ui.lyrics_panel import LyricsPanel
from ui.settings_dialog import SettingsDialog
from ui.shortcuts import LocalShortcuts
from ui.tray import Tray
from ui.styles import COLORS

logger = logging.getLogger('yt-local.ui')


class MainWindow(QMainWindow):
    global_hotkeys_changed = pyqtSignal(bool)

    def __init__(self, db: Database, settings: Settings, ws: WebSocketServer):
        super().__init__()
        self.db = db
        self.settings = settings
        self.ws = ws
        self._shutdown_done = False
        self._active_playlist_id: str | None = None
        self._environment_worker: EnvironmentCheckWorker | None = None

        self.setWindowTitle("YT Music Local")
        self.resize(1200, 800)
        self.setMinimumSize(900, 600)

        # Пути к данным (рядом с main.py)
        self.data_dir = get_data_dir()
        self.downloads_dir = self.data_dir / 'downloads'
        self.covers_dir = self.data_dir / 'covers'
        self.lyrics_dir = self.data_dir / 'lyrics'

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

        # Обзор
        self.overview_page = OverviewPage(db)
        self.stack.addWidget(self.overview_page)

        # Библиотека
        self.track_list = TrackListWidget(db)
        self.stack.addWidget(self.track_list)

        # Загрузки
        self.downloads_page = DownloadsPage(db)
        self.stack.addWidget(self.downloads_page)

        # ---- Панель текста ----
        self.lyrics_panel = LyricsPanel()
        self.lyrics_panel.setVisible(False)

        # ---- Контейнер: стек + панель текста ----
        content_row = QWidget()
        content_row_layout = QHBoxLayout(content_row)
        content_row_layout.setContentsMargins(0, 0, 0, 0)
        content_row_layout.setSpacing(0)

        content_row_layout.addWidget(self.stack, stretch=1)
        content_row_layout.addWidget(self.lyrics_panel)
        self.queue_panel = QueuePanel(self)
        self.queue_panel.setVisible(False)
        content_row_layout.addWidget(self.queue_panel)

        right_layout.addWidget(content_row, stretch=1)

        # ---- Плеер ----
        self.player = Player(db)
        self.player_widget = PlayerWidget(self.player)
        right_layout.addWidget(self.player_widget)

        root.addWidget(right_column, stretch=1)

        outer.addWidget(content, stretch=1)

        self.setCentralWidget(central)
        self.toast = Toast(central)

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


        content_filter = ContentFilter.from_settings(settings)
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
            proxy=settings.get('proxy'),
            content_filter=content_filter,
        )

        self.track_controller = TrackController(self.track_list, self)
        self.player_controller = PlayerController(
            self.player, self.track_controller, self.statusBar(), self,
            settings=settings,
        )
        self.player_widget.btn_play.clicked.disconnect(self.player.play_pause)
        self.player_widget.btn_play.clicked.connect(self.player_controller.play_pause)
        self.player_widget.queue_toggled.connect(self.queue_panel.setVisible)
        self.player_widget.queue_toggled.connect(
            lambda visible: self.player_widget.btn_lyrics.setChecked(False) if visible else None)
        self.player_widget.lyrics_toggled.connect(
            lambda visible: self.player_widget.btn_queue.setChecked(False) if visible else None)
        self.player_controller.queue_changed.connect(self._on_queue_changed)
        self.queue_panel.play_requested.connect(self.player_controller.play_queue_index)
        self.queue_panel.remove_requested.connect(self.player_controller.remove_from_queue)
        self.queue_panel.move_requested.connect(self.player_controller.move_in_queue)
        self.queue_panel.next_requested.connect(self.player_controller.play_next)
        self.queue_panel.clear_requested.connect(self.player_controller.clear_queue)
        for widget in (self.track_list, self.queue_panel,
                       self.overview_page, self.downloads_page):
            widget.enqueue_requested.connect(self._enqueue_track)
            widget.playlist_add_requested.connect(self._add_to_playlist)
        self.sidebar.playlist_selected.connect(self._select_playlist)
        self.sidebar.playlist_create_requested.connect(self._create_playlist)
        self.sidebar.playlist_rename_requested.connect(self._rename_playlist)
        self.sidebar.playlist_delete_requested.connect(self._delete_playlist)
        self.sidebar.playlist_tracks_dropped.connect(self._add_tracks_to_playlist)
        self.track_list.playlist_remove_requested.connect(self._remove_from_playlist)
        self.track_list.playlist_reorder_requested.connect(self._reorder_playlist)
        playing_index = (self.player_controller.current_index
                         if self.player.current_track() is not None else -1)
        self._on_queue_changed(self.player_controller.queue_tracks, playing_index)
        self._refresh_playlists()
        self.lyrics_controller = LyricsController(
            self.player,
            self.player_widget,
            self.lyrics_panel,
            self.lyrics_dir,
            self,
        )
        self.download_controller = DownloadController(
            self.download_manager,
            self.track_controller,
            self.downloads_page,
            self.statusBar(),
            self._refresh_stats,
            self,
        )
        self.track_controller.track_activated.connect(self._on_track_activated)
        self.track_controller.play_requested.connect(self._play_list_track)
        self.overview_page.track_play_requested.connect(self.player_controller.play_track)
        self.overview_page.resume_play_requested.connect(self.player_controller.resume_track)
        self.player.track_changed.connect(self.overview_page.refresh)
        self.download_manager.download_finished.connect(self.overview_page.refresh)
        self.track_controller.clear_search_requested.connect(self.title_bar.search.clear)
        self.player_controller.toast_requested.connect(self.toast.show_message)
        self.download_controller.toast_requested.connect(self.toast.show_message)

        if settings.get('auto_download', True):
            self.download_manager.start()

        # ============================================================
        # Трей
        # ============================================================
        self.tray = Tray(self)
        self.tray.show_window_requested.connect(self._restore_from_tray)
        self.tray.play_pause_requested.connect(self.player_controller.play_pause)
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
        self._setup_shortcuts()
        application = QApplication.instance()
        if application is not None:
            application.aboutToQuit.connect(self._shutdown)

    def _setup_shortcuts(self) -> None:
        controller = self.player_controller
        actions: dict[str, Callable[[], None]] = {
            'play_pause': controller.play_pause,
            'next_track': controller.next_track,
            'prev_track': controller.prev_track,
            'volume_up': partial(self._adjust_volume, 5),
            'volume_down': partial(self._adjust_volume, -5),
            'mute': self.player_widget.btn_volume.click,
            'shuffle': self.player_widget.btn_shuffle.click,
            'repeat': self.player_widget.btn_repeat.click,
            'search': self._focus_search,
            'lyrics': self.player_widget.btn_lyrics.toggle,
            'escape': self._escape_search,
        }
        for index, section in enumerate(self.sidebar.section_ids[:5], start=1):
            actions[f'page_{index}'] = partial(self._shortcut_section, section)
        self.local_shortcuts = LocalShortcuts(self, actions)
        self.local_shortcuts.install()
        self.global_hotkeys = GlobalHotkeyManager(self)
        self.global_hotkeys.play_pause.connect(controller.play_pause)
        self.global_hotkeys.next_track.connect(controller.next_track)
        self.global_hotkeys.prev_track.connect(controller.prev_track)
        self.global_hotkeys.stop_requested.connect(controller.stop)
        self.tray.global_hotkeys_toggled.connect(self._set_global_hotkeys_enabled)
        self.global_hotkeys_changed.connect(self.tray.set_global_hotkeys_enabled)
        self._set_global_hotkeys_enabled(self.settings.get('global_hotkeys_enabled', True))

    def _adjust_volume(self, delta: int) -> None:
        self.player.set_volume(self.player.get_volume() + delta)

    def _focus_search(self) -> None:
        search = self.title_bar.search
        if QApplication.focusWidget() is not search:
            search.setFocus(Qt.FocusReason.ShortcutFocusReason)
        search.selectAll()

    def _escape_search(self) -> None:
        if QApplication.focusWidget() is self.title_bar.search:
            self.title_bar.search.clearFocus()
            self.stack.currentWidget().setFocus(Qt.FocusReason.ShortcutFocusReason)

    def _shortcut_section(self, section: str) -> None:
        self.sidebar.set_section(section)
        self._on_section_changed(section)

    @pyqtSlot(bool)
    def _set_global_hotkeys_enabled(self, enabled: bool) -> None:
        if self._shutdown_done:
            return
        if self.settings.get('global_hotkeys_enabled', True) != enabled:
            self.settings.set('global_hotkeys_enabled', enabled)
            self.settings.save()
        if enabled:
            self.global_hotkeys.start()
        else:
            self.global_hotkeys.stop()
        self.global_hotkeys_changed.emit(enabled)

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
            self._active_playlist_id = None
            self.track_list.set_playlist(None)
            self.track_list.set_external_search(text)
            self.stack.setCurrentIndex(1)
            self.sidebar.set_section('library')

    # ================================================================
    # WebSocket
    # ================================================================

    def _on_track_played(self, data: dict) -> None:
        url = data.get('url', '')
        if '/shorts/' in url.lower():
            logger.info(f"Пропускаю Shorts: {data.get('title')}")
            return
        try:
            track_id = self.db.upsert_from_play(data)
            logger.info(f"Трек сохранён: id={track_id}, title={data.get('title')}")
            self.statusBar().showMessage(
                f"Трек добавлен в библиотеку: {data.get('title', '—')}", 5000
            )
            self.overview_page.refresh()
            if self.stack.currentIndex() == 1:
                self.track_list.refresh()
        except Exception as e:
            logger.exception(f"Ошибка сохранения трека: {e}")

    def _on_client_connected(self, remote: str) -> None:
        self.statusBar().showMessage(f"Браузер подключён: {remote}", 5000)

    def _on_client_disconnected(self, remote: str) -> None:
        self.statusBar().showMessage(f"Браузер отключён: {remote}", 5000)

    # ================================================================
    # Разделы
    # ================================================================

    def _on_section_changed(self, section: str) -> None:
        if section == 'settings':
            self._open_settings()
            if self._active_playlist_id is not None:
                self.sidebar.set_playlist(self._active_playlist_id)
            else:
                current_section = ('overview', 'library', 'downloads')[self.stack.currentIndex()]
                self.sidebar.set_section(current_section)
            return

        self._active_playlist_id = None
        self.track_list.set_playlist(None)
        index_map = {'overview': 0, 'library': 1, 'downloads': 2}
        self.stack.setCurrentIndex(index_map.get(section, 0))
        if section == 'overview':
            self.player.save_playback_state()
            self.overview_page.refresh()

    # ================================================================
    # Список / плеер
    # ================================================================

    def _on_track_activated(self, track: Track) -> None:
        logger.info(f"Выбран трек: {track.title}")
        self.statusBar().showMessage(
            f"Выбран: {track.title} — {track.channel or '—'}", 5000
        )

    def _playlist_error(self, error: Exception) -> None:
        message = f"Не удалось выполнить действие: {error}"
        logger.warning(message)
        self.toast.show_message(message)

    def _refresh_playlists(self) -> None:
        try:
            playlists = self.db.list_playlists()
            for widget in (self.sidebar, self.track_list, self.queue_panel,
                           self.overview_page, self.downloads_page):
                widget.set_playlists(playlists)
            if self._active_playlist_id is not None:
                if any(item.id == self._active_playlist_id for item in playlists):
                    self.sidebar.set_playlist(self._active_playlist_id)
                    self.track_list.refresh()
                else:
                    self._on_section_changed('library')
                    self.sidebar.set_section('library')
        except (ValueError, sqlite3.Error) as error:
            self._playlist_error(error)

    def _select_playlist(self, playlist_id: str) -> None:
        self._active_playlist_id = playlist_id
        self.track_list.set_playlist(playlist_id)
        self.sidebar.set_playlist(playlist_id)
        self.stack.setCurrentIndex(1)

    def _create_playlist(self) -> None:
        name, accepted = QInputDialog.getText(self, 'Создать плейлист', 'Название:')
        if not accepted:
            return
        try:
            name = name.strip()
            if not name:
                raise ValueError('Имя плейлиста не должно быть пустым')
            playlist_id = self.db.create_playlist(name)
            self._refresh_playlists()
            self._select_playlist(playlist_id)
        except (ValueError, sqlite3.Error) as error:
            self._playlist_error(error)

    def _rename_playlist(self, playlist_id: str) -> None:
        try:
            playlist = next((item for item in self.db.list_playlists()
                             if item.id == playlist_id), None)
            if playlist is None:
                raise ValueError('Неизвестный плейлист')
            name, accepted = QInputDialog.getText(
                self, 'Переименовать плейлист', 'Название:', text=playlist.name)
            if not accepted:
                return
            name = name.strip()
            if not name:
                raise ValueError('Имя плейлиста не должно быть пустым')
            self.db.rename_playlist(playlist_id, name)
            self._refresh_playlists()
        except (ValueError, sqlite3.Error) as error:
            self._playlist_error(error)

    def _delete_playlist(self, playlist_id: str) -> None:
        answer = QMessageBox.question(
            self, 'Удалить плейлист',
            'Удалить плейлист? Треки останутся в библиотеке.',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self.db.delete_playlist(playlist_id)
            self._refresh_playlists()
        except (ValueError, sqlite3.Error) as error:
            self._playlist_error(error)

    def _add_to_playlist(self, playlist_id: str, track_id: int) -> None:
        self._add_tracks_to_playlist(playlist_id, [track_id])

    def _add_tracks_to_playlist(self, playlist_id: str, track_ids: list[int]) -> None:
        try:
            for track_id in track_ids:
                self.db.add_to_playlist(playlist_id, track_id)
        except (ValueError, sqlite3.Error) as error:
            self._playlist_error(error)
        finally:
            self._refresh_playlists()

    def _remove_from_playlist(self, playlist_id: str, track_id: int) -> None:
        try:
            self.db.remove_from_playlist(playlist_id, track_id)
        except (ValueError, sqlite3.Error) as error:
            self._playlist_error(error)
        finally:
            self._refresh_playlists()

    def _reorder_playlist(self, playlist_id: str, track_ids: list[int]) -> None:
        try:
            self.db.reorder_playlist(playlist_id, track_ids)
        except (ValueError, sqlite3.Error) as error:
            self._playlist_error(error)
        finally:
            self._refresh_playlists()

    def _play_list_track(self, track: Track) -> None:
        try:
            if self._active_playlist_id is not None:
                tracks = self.db.get_playlist_tracks(self._active_playlist_id)
                self.player_controller.play_tracks(tracks, track)
            else:
                self.player_controller.play_track(track)
        except (ValueError, sqlite3.Error) as error:
            self._playlist_error(error)

    def _enqueue_track(self, track_id: int, position: str) -> None:
        try:
            self.player_controller.enqueue(track_id, position)
        except (ValueError, sqlite3.Error) as error:
            self._playlist_error(error)

    def _on_queue_changed(self, tracks: list[Track], playing_index: int) -> None:
        self.queue_panel.set_queue(tracks, playing_index)
        self.track_list.set_queued([track.id for track in tracks])

    # ================================================================
    # Текст
    # ================================================================

    # ================================================================
    # DownloadManager
    # ================================================================

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

    def start_environment_check(self) -> None:
        if self._environment_worker is not None and self._environment_worker.isRunning():
            return
        worker = EnvironmentCheckWorker(self.settings.get('proxy'), self)
        worker.warnings_ready.connect(self.show_environment_warnings)
        worker.finished.connect(self._on_environment_check_finished)
        self._environment_worker = worker
        worker.start()

    def _on_environment_check_finished(self) -> None:
        worker = self._environment_worker
        if worker is not None and not worker.isRunning():
            worker.deleteLater()
            self._environment_worker = None

    def show_environment_warnings(self, warnings: list[str]) -> None:
        if not warnings:
            logger.info("Проверка окружения завершена: проблем не обнаружено")
            return
        for warning in warnings:
            logger.warning("Проверка окружения: %s", warning)
        message = " ".join(warnings)
        self.statusBar().showMessage(message, 15000)
        self.toast.show_message(message)

    def show_runtime_error(self, message: str) -> None:
        self.statusBar().showMessage(message, 15000)
        self.toast.show_message(message)

    # ================================================================
    # Настройки
    # ================================================================

    def _open_settings(self) -> None:
        dialog = SettingsDialog(self.settings, self.downloads_dir, self)
        dialog.settings_changed.connect(self._apply_settings)
        dialog.global_hotkeys_toggled.connect(self._set_global_hotkeys_enabled)
        self.global_hotkeys_changed.connect(dialog.set_global_hotkeys_enabled)
        try:
            dialog.exec()
        finally:
            self.global_hotkeys_changed.disconnect(dialog.set_global_hotkeys_enabled)
            dialog.deleteLater()

    def _apply_settings(self) -> None:
        logger.info("Настройки обновлены")
        self.player.set_volume(self.settings.get('player_volume', 70))
        self.player.set_autoplay_next(self.settings.get('player_autoplay_next', True))
        self.download_manager.quality_v0 = self.settings.get('audio_quality_v0', True)
        self.download_manager.cover_mode = self.settings.get('cover_mode', 'auto')
        self.download_manager.video_frame_second = self.settings.get('video_frame_second', 15)
        self.download_manager.proxy = self.settings.get('proxy')
        self.download_manager.content_filter = ContentFilter.from_settings(self.settings)
        self._set_global_hotkeys_enabled(self.settings.get('global_hotkeys_enabled', True))

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
        if self._shutdown_done:
            return
        self._shutdown_done = True
        logger.info("Остановка фоновых потоков")
        self.global_hotkeys.stop()
        self.local_shortcuts.uninstall()
        self._stats_timer.stop()
        self.player.shutdown()

        if self.download_manager.isRunning():
            self.download_manager.stop()
            self.download_manager.wait()

        if self._environment_worker is not None:
            self._environment_worker.requestInterruption()
            self._environment_worker.wait()
            self._environment_worker = None

        self.overview_page.shutdown()
        self.lyrics_controller.shutdown()
        self.track_list.shutdown()
        self.downloads_page.shutdown()

        if self.ws.isRunning():
            self.ws.stop()
            self.ws.wait()

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