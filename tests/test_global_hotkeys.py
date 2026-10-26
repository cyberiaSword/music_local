"""Offscreen-тесты глобальных клавиш без pynput и native hooks."""

import builtins
import logging
import os
import sys
import threading
import time
from types import ModuleType, SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PyQt6")
from PyQt6.QtCore import QObject, QThread, Qt, pyqtSlot
from PyQt6.QtTest import QSignalSpy, QTest
from PyQt6.QtWidgets import QApplication

from core import hotkeys


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def wait_until(app, predicate, timeout=3):
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        app.processEvents()
        QTest.qWait(10)
    assert predicate(), "Истекло ожидание Qt/worker"
    app.processEvents()


@pytest.fixture
def backend(monkeypatch):
    state = SimpleNamespace(listeners=[], failure=None, hooks=[], unavailable=False,
                            entered=threading.Event(), gate=threading.Event())
    state.gate.set()
    keys = SimpleNamespace(media_play_pause="play", media_next="next",
                           media_previous="previous", media_stop="stop")

    class FakeListener(threading.Thread):
        def __init__(self, *, on_press, on_release, suppress):
            if state.failure == "constructor":
                raise RuntimeError("fake constructor failure")
            super().__init__(name="fake-hotkey-listener")
            self.on_press = on_press
            self.on_release = on_release
            self.suppress = suppress
            self.finished = threading.Event()
            self.active = threading.Event()
            self.callback_threads = []
            state.listeners.append(self)

        @property
        def running(self):
            return self.active.is_set()

        def run(self):
            self.active.set()
            try:
                self.finished.wait()
            finally:
                self.active.clear()

        def start(self):
            if state.failure == "start":
                raise RuntimeError("fake start failure")
            super().start()

        def stop(self):
            self.finished.set()
            if state.failure == "stop":
                raise RuntimeError("fake stop failure")

        def join(self, timeout=None):
            if state.failure == "join":
                raise RuntimeError("fake join failure")
            super().join(timeout)

        @staticmethod
        def canonical(key):
            return {"ctrl_l": "ctrl", "ctrl_r": "ctrl", "alt_l": "alt",
                    "alt_r": "alt", "spacebar": "space", "play": "vk_play",
                    "next": "vk_next", "previous": "vk_previous",
                    "stop": "vk_stop"}.get(key, key)

        def send(self, *events):
            errors = []

            def invoke():
                self.callback_threads.append(threading.get_ident())
                try:
                    for action, key in events:
                        getattr(self, "on_" + action)(key)
                except BaseException as error:
                    errors.append(error)

            thread = threading.Thread(target=invoke, daemon=True)
            thread.start()
            thread.join(1)
            assert not thread.is_alive(), "Native callback заблокирован"
            assert not errors, errors

    class FakeHotKey:
        def __init__(self, keys, callback):
            self.keys = set(keys)
            self.pressed = set()
            self.callback = callback

        @staticmethod
        def parse(value):
            assert value == "<ctrl>+<alt>+<space>"
            return ["ctrl", "alt", "space"]

        def press(self, key):
            self.pressed.add(key)
            if self.keys <= self.pressed:
                self.callback()

        def release(self, key):
            self.pressed.discard(key)

    module = ModuleType("pynput")
    module.keyboard = SimpleNamespace(Key=keys, Listener=FakeListener, HotKey=FakeHotKey)
    monkeypatch.setitem(sys.modules, "pynput", module)
    original_import = builtins.__import__

    def import_backend(name, *args, **kwargs):
        if name == "pynput":
            state.entered.set()
            if not state.gate.wait(5):
                raise RuntimeError("Backend import gate timed out")
            if state.unavailable:
                raise ImportError("fake pynput unavailable")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", import_backend)
    monkeypatch.setattr(hotkeys.atexit, "register", state.hooks.append)
    return state


@pytest.fixture
def manager(app, backend):
    instance = hotkeys.GlobalHotkeyManager()
    yield instance
    instance.stop()
    backend.gate.set()
    # После restart старый supervisor уже не хранится в instance._worker.
    workers = [thread for thread in threading.enumerate()
               if thread.name == "global-hotkeys"]
    for thread in workers:
        thread.join(2)
    for listener in backend.listeners:
        listener.finished.set()
        if listener.ident is not None:
            threading.Thread.join(listener, 2)
        assert not listener.is_alive()
    assert all(not thread.is_alive() for thread in workers)
    app.processEvents()


def start_listener(app, manager, backend):
    manager.start()
    wait_until(app, lambda: manager.is_running)
    return backend.listeners[-1]


def signal_spies(manager):
    return [QSignalSpy(getattr(manager, name)) for name in
            ("play_pause", "next_track", "prev_track", "stop_requested")]


def assert_warning_only(caplog):
    records = [record for record in caplog.records
               if record.name == "yt-local.hotkeys"]
    assert any(record.levelno == logging.WARNING for record in records)
    assert all(record.levelno < logging.ERROR for record in records)


def test_start_stop_idempotent_and_fresh_restart(app, manager, backend):
    assert not manager.is_running
    manager.stop()
    manager.stop()
    first = start_listener(app, manager, backend)
    worker = manager._worker
    assert worker.daemon and first.daemon and not first.suppress
    assert worker.ident != threading.get_ident()
    assert first.ident != worker.ident
    for _ in range(5):
        manager.start()
    assert manager._worker is worker
    assert backend.listeners == [first]
    manager.stop()
    manager.stop()
    assert not manager.is_running
    wait_until(app, lambda: not worker.is_alive() and not first.is_alive())
    second = start_listener(app, manager, backend)
    assert second is not first
    assert manager._worker is not worker
    assert len(backend.listeners) == 2


def test_slow_import_nonblocking_and_async_running(app, manager, backend):
    backend.gate.clear()
    started = time.monotonic()
    manager.start()
    elapsed = time.monotonic() - started
    assert elapsed < 0.5, f"start блокировал GUI на {elapsed:.3f} с"
    wait_until(app, backend.entered.is_set)
    assert not manager.is_running
    assert not backend.listeners
    worker, cancel = manager._worker, manager._cancel
    for _ in range(5):
        manager.start()
    assert manager._worker is worker and manager._cancel is cancel
    assert worker.daemon
    # Event loop работает, пока backend остаётся заблокированным.
    QTest.qWait(20)
    assert not backend.gate.is_set() and worker.is_alive()
    backend.gate.set()
    wait_until(app, lambda: manager.is_running)


def test_stop_before_init_and_rapid_restart_cancels_old_callbacks(app, manager, backend):
    backend.gate.clear()
    manager.stop()
    manager.start()
    wait_until(app, backend.entered.is_set)
    first_worker = manager._worker
    first_cancel = manager._cancel
    manager.stop()
    manager.start()
    second_worker = manager._worker
    second_cancel = manager._cancel
    manager.stop()
    assert first_cancel.is_set() and second_cancel.is_set()
    assert not manager.is_running
    backend.gate.set()
    wait_until(app, lambda: not first_worker.is_alive() and not second_worker.is_alive())
    assert all(listener.ident is None for listener in backend.listeners)
    spies = signal_spies(manager)
    listener = start_listener(app, manager, backend)
    for stale in backend.listeners[:-1]:
        stale.send(("press", "play"), ("release", "play"))
    manager._command.emit("play_pause", first_cancel)
    manager._command.emit("play_pause", second_cancel)
    app.processEvents()
    assert [len(spy) for spy in spies] == [0, 0, 0, 0]
    listener.send(("press", "play"))
    wait_until(app, lambda: len(spies[0]) == 1)


@pytest.mark.parametrize("key,index", [("play", 0), ("next", 1),
                                      ("previous", 2), ("stop", 3)])
def test_media_exact_counts_and_repeated_press_suppression(app, manager, backend, key, index):
    spies = signal_spies(manager)
    listener = start_listener(app, manager, backend)
    listener.send(*[("press", key)] * 5)
    wait_until(app, lambda: len(spies[index]) == 1)
    assert [len(spy) for spy in spies] == [int(i == index) for i in range(4)]
    listener.send(("release", key), ("press", key), ("press", key), ("release", key))
    wait_until(app, lambda: len(spies[index]) == 2)
    assert [len(spy) for spy in spies] == [2 * int(i == index) for i in range(4)]
    assert all(list(args) == [] for args in spies[index])


@pytest.mark.parametrize("ctrl,alt", [("ctrl_l", "alt_r"), ("ctrl_r", "alt_l")])
def test_ctrl_alt_space_one_dispatch_per_press(app, manager, backend, ctrl, alt):
    spies = signal_spies(manager)
    listener = start_listener(app, manager, backend)
    listener.send(("press", ctrl), ("press", alt))
    app.processEvents()
    assert [len(spy) for spy in spies] == [0, 0, 0, 0]
    listener.send(("press", "spacebar"), ("press", "spacebar"), ("press", ctrl))
    wait_until(app, lambda: len(spies[0]) == 1)
    assert [len(spy) for spy in spies] == [1, 0, 0, 0]
    listener.send(("release", "spacebar"), ("press", "spacebar"),
                  ("release", "spacebar"), ("release", alt), ("release", ctrl))
    wait_until(app, lambda: len(spies[0]) == 2)
    listener.send(("press", "spacebar"), ("release", "spacebar"))
    app.processEvents()
    assert [len(spy) for spy in spies] == [2, 0, 0, 0]


def test_stop_discards_queued_and_late_callbacks_even_after_restart(app, manager, backend):
    spies = signal_spies(manager)
    listener = start_listener(app, manager, backend)
    worker = manager._worker
    listener.send(("press", "play"), ("press", "next"),
                  ("press", "previous"), ("press", "stop"))
    assert [len(spy) for spy in spies] == [0, 0, 0, 0]
    manager.stop()
    listener.send(("release", "play"), ("press", "play"))
    wait_until(app, lambda: not worker.is_alive())
    assert [len(spy) for spy in spies] == [0, 0, 0, 0]
    current = start_listener(app, manager, backend)
    listener.send(("release", "next"), ("press", "next"))
    app.processEvents()
    assert [len(spy) for spy in spies] == [0, 0, 0, 0]
    current.send(("press", "next"))
    wait_until(app, lambda: len(spies[1]) == 1)
    assert [len(spy) for spy in spies] == [0, 1, 0, 0]


def test_foreign_callbacks_use_command_bridge_and_gui_slots(app, manager, backend, monkeypatch):
    gui_ident = threading.get_ident()
    qt_names = {name for name in dir(QObject) if not name.startswith("__")}
    qt_names.update(("play_pause", "next_track", "prev_track", "stop_requested", "_dispatch"))
    forbidden_accesses = []
    original_getattribute = hotkeys.GlobalHotkeyManager.__getattribute__

    def audited_getattribute(instance, name):
        if threading.get_ident() != gui_ident and name in qt_names:
            forbidden_accesses.append((name, threading.get_ident()))
        return original_getattribute(instance, name)

    monkeypatch.setattr(hotkeys.GlobalHotkeyManager, "__getattribute__", audited_getattribute)

    class Receiver(QObject):
        def __init__(self):
            super().__init__()
            self.calls = []

        @pyqtSlot()
        def receive(self):
            self.calls.append((threading.get_ident(), QThread.currentThread()))

    receiver = Receiver()
    bridges = []
    for name in ("play_pause", "next_track", "prev_track", "stop_requested"):
        getattr(manager, name).connect(receiver.receive)
    manager._command.connect(
        lambda action, cancel: bridges.append((action, cancel, threading.get_ident())),
        Qt.ConnectionType.DirectConnection,
    )
    listener = start_listener(app, manager, backend)
    listener.send(("press", "play"), ("press", "next"),
                  ("press", "previous"), ("press", "stop"))
    assert receiver.calls == []
    assert [row[0] for row in bridges] == [
        "play_pause", "next_track", "prev_track", "stop_requested"]
    assert all(row[1] is manager._cancel for row in bridges)
    assert all(row[2] == listener.callback_threads[-1] != gui_ident for row in bridges)
    wait_until(app, lambda: len(receiver.calls) == 4)
    assert all(ident == gui_ident and qt_thread == app.thread()
               for ident, qt_thread in receiver.calls)
    manager.stop()
    wait_until(app, lambda: manager._worker is None)
    assert forbidden_accesses == []


def test_qt_stop_signal_does_not_shadow_lifecycle_method(app, manager, backend):
    assert isinstance(manager, QObject)
    assert callable(manager.stop)
    assert manager.metaObject().indexOfSignal("stop()") >= 0
    assert manager.stop_requested.signal.endswith("stop()")
    spy = QSignalSpy(manager.stop_requested)
    listener = start_listener(app, manager, backend)
    listener.send(("press", "stop"))
    wait_until(app, lambda: len(spy) == 1)
    assert manager.is_running
    manager.stop()
    app.processEvents()
    assert len(spy) == 1
    assert not manager.is_running


def test_unavailable_pynput_logs_warning_not_critical(app, manager, backend, caplog):
    backend.unavailable = True
    caplog.set_level(logging.DEBUG, logger="yt-local.hotkeys")
    manager.start()
    wait_until(app, backend.entered.is_set)
    wait_until(app, lambda: manager._worker is None)
    assert not manager.is_running and backend.listeners == []
    assert_warning_only(caplog)
    assert any(record.exc_info and isinstance(record.exc_info[1], ImportError)
               for record in caplog.records)
    backend.unavailable = False
    start_listener(app, manager, backend)


@pytest.mark.parametrize("failure", ["constructor", "start", "join", "stop"])
def test_listener_errors_warn_without_crash_and_allow_restart(
        app, manager, backend, caplog, failure):
    backend.failure = failure
    caplog.set_level(logging.DEBUG, logger="yt-local.hotkeys")
    if failure == "stop":
        start_listener(app, manager, backend)
        manager.stop()
    else:
        manager.start()
    wait_until(app, backend.entered.is_set)
    wait_until(app, lambda: manager._worker is None)
    assert not manager.is_running
    wait_until(app, lambda: all(not listener.is_alive() for listener in backend.listeners))
    assert_warning_only(caplog)
    assert any(record.exc_info and f"fake {failure} failure" in str(record.exc_info[1])
               for record in caplog.records)
    backend.failure = None
    start_listener(app, manager, backend)


def test_supervisor_start_error_warns_and_can_retry(app, manager, backend, monkeypatch, caplog):
    original_start = threading.Thread.start

    def fail_supervisor(thread):
        if thread.name == "global-hotkeys":
            raise RuntimeError("fake supervisor failure")
        return original_start(thread)

    caplog.set_level(logging.DEBUG, logger="yt-local.hotkeys")
    with monkeypatch.context() as patch:
        patch.setattr(threading.Thread, "start", fail_supervisor)
        manager.start()
    assert not manager.is_running and manager._worker is None
    assert backend.listeners == []
    assert_warning_only(caplog)
    start_listener(app, manager, backend)


def test_registered_atexit_hook_stops_listener(app, manager, backend):
    assert backend.hooks == [manager.stop]
    listener = start_listener(app, manager, backend)
    worker = manager._worker
    backend.hooks[0]()
    backend.hooks[0]()
    assert not manager.is_running
    wait_until(app, lambda: not worker.is_alive() and not listener.is_alive())
