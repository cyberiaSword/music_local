"""Локальные сочетания главного окна и их публичные описания."""

from collections.abc import Callable
from functools import partial

from PyQt6.QtCore import QObject, Qt
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QAbstractSpinBox, QApplication, QComboBox, QLineEdit, QMainWindow,
    QPlainTextEdit, QTextEdit, QWidget,
)


BINDINGS: tuple[tuple[str, str, str], ...] = (
    ("play_pause", "Space", "Воспроизведение / пауза"),
    ("next_track", "Ctrl+Right", "Следующий трек"),
    ("prev_track", "Ctrl+Left", "Предыдущий трек"),
    ("volume_up", "Ctrl+Up", "Увеличить громкость"),
    ("volume_down", "Ctrl+Down", "Уменьшить громкость"),
    ("mute", "Ctrl+M", "Выключить / включить звук"),
    ("shuffle", "Ctrl+S", "Перемешивание"),
    ("repeat", "Ctrl+R", "Повтор"),
    ("search", "Ctrl+F", "Поиск"),
    ("lyrics", "Ctrl+L", "Текст песни"),
    ("page_1", "Ctrl+1", "Обзор"),
    ("page_2", "Ctrl+2", "Библиотека"),
    ("page_3", "Ctrl+3", "Загрузки"),
    ("page_4", "Ctrl+4", "Настройки"),
    ("escape", "Esc", "Закрыть / отменить"),
)

_OPTIONAL_BINDINGS: tuple[tuple[str, str, str], ...] = (
    ("page_5", "Ctrl+5", "Страница 5"),
)
_EDITING_ALLOWED = frozenset({"search", "escape"})


def _is_text_focus(widget: QWidget | None) -> bool:
    while widget is not None:
        if isinstance(widget, (QLineEdit, QTextEdit, QPlainTextEdit, QAbstractSpinBox)):
            return True
        if isinstance(widget, QComboBox) and widget.isEditable():
            return True
        widget = widget.parentWidget()
    return False


class LocalShortcuts(QObject):
    """Явная установка и снятие сочетаний без глобального перехвата клавиш."""

    def __init__(
        self, window: QMainWindow, actions: dict[str, Callable[[], None]],
    ) -> None:
        super().__init__(window)
        self._window = window
        self._actions = dict(actions)
        self._shortcuts: dict[str, QShortcut] = {}
        self._slots: dict[str, Callable[[], None]] = {}
        self._application: QApplication | None = None
        self._installed = False

    def install(self) -> None:
        if self._installed:
            return
        application = QApplication.instance()
        if not isinstance(application, QApplication):
            raise RuntimeError("LocalShortcuts требует QApplication")
        self._application = application
        self._installed = True
        for action_id, sequence, _label in BINDINGS + _OPTIONAL_BINDINGS:
            if action_id not in self._actions:
                continue
            shortcut = QShortcut(QKeySequence(sequence), self._window)
            shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
            shortcut.setAutoRepeat(False)
            slot = partial(self._activate, action_id)
            shortcut.activated.connect(slot)
            self._shortcuts[action_id] = shortcut
            self._slots[action_id] = slot
        application.focusChanged.connect(self._on_focus_changed)
        self._on_focus_changed(None, application.focusWidget())

    def uninstall(self) -> None:
        if not self._installed:
            return
        self._installed = False
        if self._application is not None:
            self._application.focusChanged.disconnect(self._on_focus_changed)
        for action_id, shortcut in self._shortcuts.items():
            shortcut.setEnabled(False)
            shortcut.activated.disconnect(self._slots[action_id])
            shortcut.deleteLater()
        self._shortcuts.clear()
        self._slots.clear()
        self._application = None

    def _on_focus_changed(
        self, _previous: QWidget | None, current: QWidget | None,
    ) -> None:
        editing = _is_text_focus(current)
        for action_id, shortcut in self._shortcuts.items():
            shortcut.setEnabled(not editing or action_id in _EDITING_ALLOWED)

    def _activate(self, action_id: str) -> None:
        application = self._application
        if not self._installed or application is None:
            return
        if (
            not self._window.isVisible()
            or self._window.isMinimized()
            or application.activeWindow() is not self._window
            or application.activeModalWidget() is not None
        ):
            return
        if (
            action_id not in _EDITING_ALLOWED
            and _is_text_focus(application.focusWidget())
        ):
            return
        self._actions[action_id]()
