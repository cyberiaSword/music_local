"""Offscreen-проверки локальных сочетаний без pytest-qt."""

import os
from collections.abc import Callable, Iterator
from functools import partial

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PyQt6")
from PyQt6.QtCore import QCoreApplication, QEvent, Qt
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import (
    QApplication, QComboBox, QDialog, QLineEdit, QMainWindow, QPlainTextEdit,
    QSpinBox, QTextEdit, QVBoxLayout, QWidget,
)

from ui.shortcuts import BINDINGS, LocalShortcuts


@pytest.fixture(scope="module")
def app() -> Iterator[QApplication]:
    application = QApplication.instance() or QApplication([])
    yield application


@pytest.fixture
def setup_window(app: QApplication) -> Iterator[tuple]:
    window = QMainWindow()
    body = QWidget()
    body.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
    window.setCentralWidget(body)
    layout = QVBoxLayout(body)
    calls: list[str] = []
    actions: dict[str, Callable[[], None]] = {
        action_id: partial(calls.append, action_id)
        for action_id, _sequence, _label in BINDINGS
    }
    shortcuts = LocalShortcuts(window, actions)
    window.resize(400, 300)
    window.show()
    window.activateWindow()
    body.setFocus()
    app.processEvents()
    shortcuts.install()
    yield window, body, layout, calls, shortcuts
    shortcuts.uninstall()
    window.close()
    window.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()


def press(widget: QWidget, sequence: str) -> None:
    combination = QKeySequence(sequence)[0]
    QTest.keyClick(widget, combination.key(), combination.keyboardModifiers())
    QApplication.processEvents()


def test_bindings_and_creation(setup_window: tuple) -> None:
    window, _body, _layout, _calls, manager = setup_window
    assert isinstance(BINDINGS, tuple)
    assert all(isinstance(binding, tuple) and len(binding) == 3 for binding in BINDINGS)
    assert len({binding[0] for binding in BINDINGS}) == len(BINDINGS)
    assert [entry for entry in BINDINGS if entry[0].startswith("page_")] == [
        ("page_1", "Ctrl+1", "Обзор"),
        ("page_2", "Ctrl+2", "Библиотека"),
        ("page_3", "Ctrl+3", "Загрузки"),
        ("page_4", "Ctrl+4", "Настройки"),
    ]
    children = window.findChildren(QShortcut)
    assert len(children) == len(BINDINGS)
    assert all(child.parent() is window for child in children)
    assert all(child.context() == Qt.ShortcutContext.WindowShortcut for child in children)
    assert all(not child.autoRepeat() for child in children)
    assert manager.parent() is window


@pytest.mark.parametrize("action_id,sequence,label", BINDINGS)
def test_callbacks(setup_window: tuple, action_id: str, sequence: str, label: str) -> None:
    _window, body, _layout, calls, _manager = setup_window
    press(body, sequence)
    assert calls == [action_id]


def test_install_uninstall_reinstall(app: QApplication, setup_window: tuple) -> None:
    window, body, _layout, calls, manager = setup_window
    count = app.receivers(app.focusChanged)
    original = window.findChildren(QShortcut)
    manager.install()
    assert window.findChildren(QShortcut) == original
    assert app.receivers(app.focusChanged) == count
    manager.uninstall()
    manager.uninstall()
    assert app.receivers(app.focusChanged) == count - 1
    assert all(not shortcut.isEnabled() for shortcut in original)
    for shortcut in original:
        shortcut.activated.emit()
    press(body, "Space")
    assert not calls
    manager.install()
    press(body, "Space")
    assert calls == ["play_pause"]
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert len(window.findChildren(QShortcut)) == len(BINDINGS)
    assert app.receivers(app.focusChanged) == count


@pytest.mark.parametrize("editor_type", [QLineEdit, QPlainTextEdit, QTextEdit])
def test_editors_keep_space_and_word_navigation(
    app: QApplication, setup_window: tuple, editor_type: type[QWidget],
) -> None:
    _window, body, layout, calls, manager = setup_window
    editor = editor_type()
    layout.addWidget(editor)
    editor.setFocus()
    app.processEvents()
    QTest.keyClicks(editor, "alpha beta")
    press(editor, "Ctrl+Left")
    press(editor, "Space")
    text = editor.text() if isinstance(editor, QLineEdit) else editor.toPlainText()
    assert text == "alpha  beta"
    assert not calls
    for action_id, shortcut in manager._shortcuts.items():
        assert shortcut.isEnabled() == (action_id in {"search", "escape"})
        if action_id not in {"search", "escape"}:
            shortcut.activated.emit()
    assert not calls
    body.setFocus()
    app.processEvents()
    assert all(shortcut.isEnabled() for shortcut in manager._shortcuts.values())
    press(body, "Space")
    assert calls == ["play_pause"]


def test_missing_actions_and_optional_page(app: QApplication) -> None:
    window = QMainWindow()
    calls: list[str] = []
    manager = LocalShortcuts(window, {"page_5": partial(calls.append, "page_5")})
    manager.install()
    children = window.findChildren(QShortcut)
    assert len(children) == 1
    assert children[0].key() == QKeySequence("Ctrl+5")
    window.show()
    window.activateWindow()
    app.processEvents()
    press(window, "Ctrl+5")
    assert calls == ["page_5"]
    manager.uninstall()
    empty = LocalShortcuts(window, {"unknown": lambda: None})
    empty.install()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert not window.findChildren(QShortcut)
    empty.uninstall()
    window.close()
    window.deleteLater()


@pytest.mark.parametrize("container_type", [QComboBox, QSpinBox, QPlainTextEdit, QTextEdit])
def test_nested_editor_focus(
    app: QApplication, setup_window: tuple, container_type: type[QWidget],
) -> None:
    _window, _body, layout, calls, manager = setup_window
    container = container_type()
    if isinstance(container, QComboBox):
        container.setEditable(True)
    layout.addWidget(container)
    if isinstance(container, (QComboBox, QSpinBox)):
        target = container.findChild(QLineEdit)
    else:
        target = QWidget(container.viewport())
        target.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        target.show()
    assert target is not None
    target.setFocus()
    app.processEvents()
    # Qt может хранить фокус на составном поле, а не на его lineEdit.
    assert app.focusWidget() in (target, container)
    assert not manager._shortcuts["play_pause"].isEnabled()
    assert not manager._shortcuts["prev_track"].isEnabled()
    press(app.focusWidget(), "Space")
    press(app.focusWidget(), "Ctrl+Left")
    assert not calls


def test_search_repeated_focus_and_escape(app: QApplication, setup_window: tuple) -> None:
    window, body, layout, calls, original = setup_window
    original.uninstall()
    editor = QLineEdit("query")
    layout.addWidget(editor)

    def search() -> None:
        calls.append("search")
        editor.setFocus()
        editor.selectAll()

    manager = LocalShortcuts(window, {
        "search": search,
        "escape": partial(calls.append, "escape"),
        "play_pause": partial(calls.append, "play_pause"),
    })
    manager.install()
    try:
        press(body, "Ctrl+F")
        assert app.focusWidget() is editor
        assert editor.selectedText() == "query"
        editor.deselect()
        press(editor, "Ctrl+F")
        assert editor.selectedText() == "query"
        press(editor, "Esc")
        assert calls == ["search", "search", "escape"]
    finally:
        manager.uninstall()


@pytest.mark.parametrize("modal", [False, True])
def test_dialog_escape_is_native(
    app: QApplication, setup_window: tuple, modal: bool,
) -> None:
    window, _body, _layout, calls, manager = setup_window
    dialog = QDialog(window)
    dialog.setModal(modal)
    dialog.show()
    dialog.activateWindow()
    app.processEvents()
    try:
        press(dialog, "Space")
        press(dialog, "Ctrl+1")
        for shortcut in manager._shortcuts.values():
            shortcut.activated.emit()
        assert not calls
        press(dialog, "Esc")
        assert not dialog.isVisible()
        assert dialog.result() == QDialog.DialogCode.Rejected
        assert not calls
    finally:
        dialog.close()
        dialog.deleteLater()


def test_other_window_is_local(app: QApplication, setup_window: tuple) -> None:
    _window, _body, _layout, calls, manager = setup_window
    other = QMainWindow()
    other.show()
    other.activateWindow()
    app.processEvents()
    try:
        assert app.activeWindow() is other
        for _action_id, sequence, _label in BINDINGS:
            press(other, sequence)
        for shortcut in manager._shortcuts.values():
            shortcut.activated.emit()
        assert not calls
    finally:
        other.close()
        other.deleteLater()


def test_minimized_window_does_not_run(app: QApplication, setup_window: tuple) -> None:
    window, body, _layout, calls, manager = setup_window
    window.showMinimized()
    app.processEvents()
    assert window.isMinimized()
    press(body, "Space")
    for shortcut in manager._shortcuts.values():
        shortcut.activated.emit()
    assert not calls
