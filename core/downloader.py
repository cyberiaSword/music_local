"""
Скачивание MP3 через yt-dlp Python API.
"""

import logging
import shutil
from pathlib import Path
from typing import Callable

from core.paths import get_binaries_dir, get_data_dir
from core.content_filter import ContentFilter

logger = logging.getLogger('yt-local.downloader')


_COOKIE_AUTH_ERROR_MARKERS = (
    'please sign in',
    'sign in to confirm',
    'login_required',
    'login required',
    'authentication required',
    'confirm you are not a bot',
)


class _CookieAuthError(RuntimeError):
    """Ошибка, связанная с требованием авторизации YouTube."""


def _is_cookie_auth_error(error: BaseException | str) -> bool:
    error_text = str(error).lower()
    return any(marker in error_text for marker in _COOKIE_AUTH_ERROR_MARKERS)


def _friendly_download_error(error: BaseException | str) -> str:
    """Преобразует сообщение yt-dlp в понятное сообщение для интерфейса."""
    error_text = str(error).lower()
    if _is_cookie_auth_error(error_text):
        return "YouTube требует авторизацию. Обновите cookies и попробуйте снова."
    if "http error 400" in error_text or "400 bad request" in error_text:
        return "YouTube отклонил запрос. Проверьте cookies и повторите загрузку."
    if "http error 429" in error_text or "too many requests" in error_text:
        return "YouTube временно ограничил загрузки. Повторите попытку позже."
    if "timed out" in error_text or "timeout" in error_text:
        return "Истекло время ожидания ответа YouTube. Проверьте соединение."
    if "ffmpeg" in error_text and ("not found" in error_text or "not installed" in error_text):
        return "Для преобразования аудио не найден FFmpeg. Установите его и повторите."
    if "requested format is not available" in error_text:
        return "Для этого видео не удалось подобрать доступный аудиоформат."
    return "Не удалось скачать трек. Проверьте соединение и повторите попытку."


class DownloadResult:
    """Результат скачивания одного трека."""

    def __init__(
        self,
        success: bool,
        video_id: str,
        mp3_path: Path | None = None,
        error: str = '',
        title: str = '',
        skipped: bool = False,
        skip_reason: str = '',
    ):
        self.success = success
        self.video_id = video_id
        self.mp3_path = mp3_path
        self.error = error
        self.title = title
        self.skipped = skipped
        self.skip_reason = skip_reason


def is_ytdlp_available() -> bool:
    """Проверяет, установлен ли yt-dlp как Python-модуль."""
    try:
        import yt_dlp  # noqa: F401
        return True
    except ImportError:
        return False


def is_ffmpeg_available() -> bool:
    """Проверяет наличие ffmpeg в PATH."""
    return shutil.which('ffmpeg') is not None


def is_deno_available() -> bool:
    """Проверяет наличие Deno (JS-рантайм для челленджей YouTube)."""
    return shutil.which('deno') is not None


def _try_clients(
    url: str,
    base_opts: dict,
    clients: list[str | None],
    download: bool = True,
) -> dict:
    """Пробует клиентов по очереди: сначала с cookies, затем без них."""
    import yt_dlp

    last_error = None
    cookie_auth_error = None
    cookie_file = base_opts.get('cookiefile')

    for client in clients:
        cookie_modes = [True, False] if cookie_file else [False]
        for use_cookies in cookie_modes:
            opts = base_opts.copy()
            if cookie_file and not use_cookies:
                opts.pop('cookiefile', None)

            extractor_args = {
                key: value.copy() if isinstance(value, dict) else value
                for key, value in opts.get('extractor_args', {}).items()
            }
            youtube_args = extractor_args.get('youtube', {}).copy()
            if client is not None:
                youtube_args['player_client'] = [client]
            extractor_args['youtube'] = youtube_args
            opts['extractor_args'] = extractor_args

            режим = 'с cookies' if use_cookies else 'без cookies'
            logger.info(f"Пробую клиент {client or 'по умолчанию'} ({режим})")
            try:
                with yt_dlp.YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(url, download=download)
                if info:
                    return info
                raise RuntimeError("yt-dlp не вернул сведения о треке")
            except Exception as error:
                logger.warning(
                    f"Клиент {client or 'по умолчанию'} ({режим}) не сработал: {error}"
                )
                last_error = error
                if _is_cookie_auth_error(error):
                    cookie_auth_error = error

    if cookie_auth_error is not None:
        raise _CookieAuthError(str(cookie_auth_error)) from cookie_auth_error
    if last_error is not None:
        raise last_error
    raise RuntimeError("Не задан ни один клиент yt-dlp")


def download_audio(
    url: str,
    video_id: str,
    output_dir: Path,
    quality_v0: bool = True,
    progress_callback: Callable[[dict], None] | None = None,
    proxy: str | None = None,
    content_filter: ContentFilter | None = None,
) -> DownloadResult:
    """
    Скачивает аудио с YouTube в MP3.
    """
    try:
        import yt_dlp
    except ImportError:
        return DownloadResult(
            success=False,
            video_id=video_id,
            error="yt-dlp не установлен. Выполните: pip install yt-dlp",
        )

    if not is_ffmpeg_available():
        logger.warning("ffmpeg не найден в PATH — конвертация в MP3 может не работать")

    if not is_deno_available():
        logger.warning(
            "Deno не найден в PATH. YouTube может отдавать только формат 18. "
            "Установите: winget install DenoLand.Deno"
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    mp3_template = str(output_dir / f"{video_id}.%(ext)s")

    # ---- Базовые параметры ----
    ydl_opts: dict = {
        # Выбираем лучший аудиопоток. Если SABR блокирует, откатываемся на формат 18 (360p с аудио)
        'format': 'bestaudio/best/18',
        'outtmpl': mp3_template,
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '0' if quality_v0 else '2',
        }],
        'postprocessor_args': {
            'ffmpeg': ['-loglevel', 'error'],
        },
        'quiet': True,
        'no_warnings': True,
        'noprogress': True,
        'progress_hooks': [progress_callback] if progress_callback else [],
        'nocheckcertificate': True,
        'geo_bypass': True,
        'noplaylist': True,
        'no_color': True,
        'remote_components': ['ejs:github'],

        # ---- Сеть ----
        'socket_timeout': 20,
        'retries': 2,
        'fragment_retries': 2,
        'file_access_retries': 1,
        'force_ipv4': True,

    }

    # ---- Пути ----
    binaries_dir = get_binaries_dir()
    ffmpeg_path = binaries_dir / 'ffmpeg.exe'
    deno_path = binaries_dir / 'deno.exe'

    if ffmpeg_path.exists():
        ydl_opts['ffmpeg_location'] = str(binaries_dir)
        logger.info(f"Использую ffmpeg из: {binaries_dir}")

    if deno_path.exists():
        ydl_opts['js_runtimes'] = {'deno': {'path': str(deno_path)}}
        logger.info(f"Использую Deno из: {deno_path}")

    cookies_file = get_data_dir() / 'cookies.txt'
    if cookies_file.exists():
        ydl_opts['cookiefile'] = str(cookies_file)
        logger.info(f"Использую cookies: {cookies_file}")

    if proxy:
        ydl_opts['proxy'] = proxy
        logger.info(f"Использую прокси: {proxy}")

    # ═══════════════════════════════════════════════════════════
    # 1. ПРОВЕРКА ФИЛЬТРА (без скачивания)
    # ═══════════════════════════════════════════════════════════
    if content_filter is not None:
        try:
            meta_opts = {
                'quiet': True,
                'no_warnings': True,
                'extract_flat': False,
            }
            if cookies_file.exists():
                meta_opts['cookiefile'] = str(cookies_file)
            if proxy:
                meta_opts['proxy'] = proxy

            with yt_dlp.YoutubeDL(meta_opts) as ydl_meta:
                info_meta = ydl_meta.extract_info(url, download=False)
        except Exception as e:
            logger.warning(f"Не удалось получить метаданные {video_id}: {e}")
            info_meta = None

        if info_meta:
            filter_result = content_filter.check(info_meta)
            if not filter_result.allowed:
                logger.info(f"Трек отсеян фильтром: {filter_result.reason}")
                return DownloadResult(
                    success=False,
                    video_id=video_id,
                    title=info_meta.get('title', video_id),
                    skipped=True,
                    skip_reason=filter_result.reason,
                )

    # ═══════════════════════════════════════════════════════════
    # 2. СКАЧИВАНИЕ с каскадной сменой cookies и клиентов
    # ═══════════════════════════════════════════════════════════
    clients_to_try = ['tv_downgraded', 'ios', 'android', 'mweb', 'android_vr']

    try:
        info = _try_clients(url, ydl_opts, clients_to_try, download=True)
    except Exception as error:
        logger.exception(f"Не удалось скачать {video_id}: {error}")
        return DownloadResult(
            success=False,
            video_id=video_id,
            error=_friendly_download_error(error),
        )

    title = info.get('title', video_id)

    # ═══════════════════════════════════════════════════════════
    # 3. ПОИСК РЕЗУЛЬТАТА
    # ═══════════════════════════════════════════════════════════
    mp3_path = output_dir / f"{video_id}.mp3"
    if not mp3_path.exists():
        candidates = list(output_dir.glob(f"{video_id}*.mp3"))
        if candidates:
            mp3_path = candidates[0]
        else:
            return DownloadResult(
                success=False,
                video_id=video_id,
                error="MP3-файл не найден после скачивания",
                title=title,
            )

    logger.info(f"Скачано: {title} → {mp3_path.name}")
    return DownloadResult(
        success=True,
        video_id=video_id,
        mp3_path=mp3_path,
        title=title,
    )