"""
WebSocket-сервер, встроенный в Qt-приложение.
Принимает полные данные о треке от Tampermonkey.
"""

import asyncio
import json
import logging

from PyQt6.QtCore import QThread, pyqtSignal
import websockets
from websockets.asyncio.server import serve

logger = logging.getLogger('yt-local.ws')


class WebSocketServer(QThread):
    """
    Поток с asyncio-сервером WebSocket.
    Сигналы:
        track_played(dict)  — action=play с полным набором полей
        track_paused(dict)  — action=pause
        track_ended(dict)   — action=ended
        client_connected(str)
        client_disconnected(str)
    """

    track_played = pyqtSignal(dict)
    track_paused = pyqtSignal(dict)
    track_ended = pyqtSignal(dict)
    client_connected = pyqtSignal(str)
    client_disconnected = pyqtSignal(str)

    def __init__(self, host: str = '127.0.0.1', port: int = 8765):
        super().__init__()
        self.host = host
        self.port = port
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stop_event: asyncio.Event | None = None

    def run(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._serve())
        except Exception as e:
            logger.exception(f"WebSocket-сервер упал: {e}")
        finally:
            self._loop.close()

    async def _serve(self) -> None:
        self._stop_event = asyncio.Event()
        async with serve(self._handle, self.host, self.port) as server:
            logger.info(f"WebSocket-сервер запущен: ws://{self.host}:{self.port}")
            await self._stop_event.wait()
            server.close()
            await server.wait_closed()

    async def _handle(self, websocket) -> None:
        remote = f"{websocket.remote_address[0]}:{websocket.remote_address[1]}"
        logger.info(f"Клиент подключён: {remote}")
        self.client_connected.emit(remote)

        try:
            async for message in websocket:
                try:
                    data = json.loads(message)
                except json.JSONDecodeError:
                    logger.warning(f"Некорректный JSON: {message[:100]}")
                    continue

                action = data.get('action')
                logger.info(f"Получено: action={action}, title={data.get('title', '?')}")

                if action == 'play':
                    self.track_played.emit(data)
                elif action == 'pause':
                    self.track_paused.emit(data)
                elif action == 'ended':
                    self.track_ended.emit(data)

        except websockets.ConnectionClosed:
            pass
        finally:
            logger.info(f"Клиент отключён: {remote}")
            self.client_disconnected.emit(remote)

    def stop(self) -> None:
        if self._loop and self._stop_event:
            asyncio.run_coroutine_threadsafe(self._set_stop(), self._loop)

    async def _set_stop(self) -> None:
        if self._stop_event:
            self._stop_event.set()