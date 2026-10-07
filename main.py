"""
YT Music Local — точка входа.
"""

import sys
import os

# ═══════════════════════════════════════════════════════════════
# АВАРИЙНЫЙ ЛОГ — пишем до всех импортов проекта
# ═══════════════════════════════════════════════════════════════
_emergency_log = None
try:
    _log_path = os.path.join(
        os.path.dirname(os.path.abspath(sys.argv[0])),
        'startup.log',
    )
    _emergency_log = open(_log_path, 'w', encoding='utf-8')
    _emergency_log.write("start\n")
    _emergency_log.flush()
except Exception:
    pass


def _log(msg: str) -> None:
    if _emergency_log:
        try:
            _emergency_log.write(msg + "\n")
            _emergency_log.flush()
        except Exception:
            pass


_log("Импорт стандартных модулей")
import logging
from pathlib import Path

_log("Импорт версии")
from core.version import __version__, __app_name__

_log("Импорт PyQt6")
from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QIcon

_log("Импорт core")
from core.database import Database
from core.settings import Settings
from core.ws_server import WebSocketServer

_log("Импорт ui")
from ui.main_window import MainWindow
from ui.styles import build_stylesheet

_log("Все импорты успешны")


# ═══════════════════════════════════════════════════════════════
# Логирование
# ═══════════════════════════════════════════════════════════════

def setup_logging() -> None:
    """Логи в файл с ротацией + в консоль (если есть)."""
    import logging.handlers
    from core.paths import get_data_dir
    from core.log_filters import SecretMaskFilter

    log_dir = get_data_dir() / 'logs'
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / 'app.log'

    # Создаём фильтр маскировки секретов
    mask_filter = SecretMaskFilter()

    # ==== Файловый хэндлер с ротацией ====
    file_handler = logging.handlers.RotatingFileHandler(
        log_file,
        maxBytes=10 * 1024 * 1024,   # 10 МБ
        backupCount=5,
        encoding='utf-8',
    )
    file_handler.addFilter(mask_filter)   # ← подключаем фильтр к файлу

    handlers = [file_handler]

    # ==== Консольный хэндлер (если stderr доступен) ====
    if sys.stderr is not None:
        try:
            console_handler = logging.StreamHandler()
            console_handler.addFilter(mask_filter)   # ← и к консоли
            handlers.append(console_handler)
        except Exception:
            pass

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        datefmt='%H:%M:%S',
        handlers=handlers,
        force=True,
    )

# ═══════════════════════════════════════════════════════════════
# Точка входа
# ═══════════════════════════════════════════════════════════════

def main() -> int:
    _log("main() стартовал")

    # Сначала создаём папку data, чтобы setup_logging мог в неё писать
    from core.paths import get_data_dir

    try:
        data_dir = get_data_dir()
        _log(f"data_dir = {data_dir}")
    except Exception as e:
        _log(f"ОШИБКА get_data_dir: {e}")
        import traceback
        _log(traceback.format_exc())
        return 1

    # Теперь включаем логирование
    try:
        setup_logging()
    except Exception as e:
        _log(f"ОШИБКА setup_logging: {e}")
        import traceback
        _log(traceback.format_exc())
        return 1

    logger = logging.getLogger('yt-local.main')
    logger.info(f"Запуск {__app_name__} v{__version__}")
    logger.info(f"Python: {sys.version.split()[0]}, ОС: {sys.platform}")
    logger.info(f"Папка данных: {data_dir}")

    # ---- QApplication ----
    _log("Создаю QApplication")
    app = QApplication(sys.argv)
    app.setApplicationName(__app_name__)
    app.setApplicationVersion(__version__)
    app.setOrganizationName("yt-music-local")

    # ---- Иконка ----
    _log("Загружаю иконку")
    try:
        from core.paths import get_assets_dir
        icon_path = get_assets_dir() / 'app.ico'
        _log(f"icon_path = {icon_path}")
        icon = QIcon(str(icon_path))
        if icon.isNull():
            logger.warning(f"Не удалось загрузить иконку: {icon_path}")
        else:
            app.setWindowIcon(icon)
            logger.info(f"Иконка загружена: {icon_path}")
    except Exception as e:
        logger.warning(f"Ошибка загрузки иконки: {e}")

    # ---- Стили ----
    _log("Применяю стили")
    try:
        app.setStyleSheet(build_stylesheet())
    except Exception as e:
        logger.warning(f"Ошибка применения стилей: {e}")

    # ---- База данных ----
    _log("Инициализирую БД")
    try:
        settings = Settings(data_dir / 'settings.json')
        db = Database(data_dir / 'tracks.db')
        db.verify_files()
        db.reset_stuck_statuses()
        _log("БД готова")
    except Exception as e:
        logger.exception(f"Ошибка инициализации БД: {e}")
        return 1

    # ---- WebSocket-сервер ----
    _log("Запускаю WebSocket-сервер")
    try:
        ws = WebSocketServer(
            host=settings.get('ws_host', '127.0.0.1'),
            port=settings.get('ws_port', 8765),
        )
        ws.start()
        _log("WebSocket-сервер запущен")
    except Exception as e:
        logger.exception(f"Ошибка запуска WebSocket: {e}")
        return 1

    # ---- Главное окно ----
    _log("Создаю MainWindow")
    try:
        window = MainWindow(db, settings, ws)
        window.show()
        _log("MainWindow показан")
    except Exception as e:
        logger.exception(f"Ошибка создания MainWindow: {e}")
        ws.stop()
        ws.wait(3000)
        return 1

    # ---- Главный цикл ----
    _log("Вход в app.exec()")
    exit_code = app.exec()

    # ---- Остановка ----
    logger.info("Остановка приложения")
    ws.stop()
    ws.wait(3000)

    _log("Приложение завершено")
    if _emergency_log:
        try:
            _emergency_log.close()
        except Exception:
            pass

    return exit_code


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as e:
        _log(f"НЕОБРАБОТАННОЕ ИСКЛЮЧЕНИЕ: {e}")
        import traceback
        _log(traceback.format_exc())
        if _emergency_log:
            try:
                _emergency_log.close()
            except Exception:
                pass
        sys.exit(1)