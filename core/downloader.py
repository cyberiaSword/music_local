"""
Скачивание MP3 через yt-dlp Python API.
"""

import logging
import shutil
from pathlib import Path
from typing import Callable
from core.paths import get_binaries_dir

logger = logging.getLogger('yt-local.downloader')


class DownloadResult:
    """Результат скачивания одного трека."""

    def __init__(
        self,
        success: bool,
        video_id: str,
        mp3_path: Path | None = None,
        error: str = '',
        title: str = '',
    ):
        self.success = success
        self.video_id = video_id
        self.mp3_path = mp3_path
        self.error = error
        self.title = title
        binaries_dir = get_binaries_dir()
        ffmpeg_path = binaries_dir / 'ffmpeg.exe'
        deno_path = binaries_dir / 'deno.exe'


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


def download_audio(
    url: str,
    video_id: str,
    output_dir: Path,
    quality_v0: bool = True,
    progress_callback: Callable[[dict], None] | None = None,
    proxy: str | None = None,
) -> DownloadResult:
    """
    Скачивает аудио с YouTube в MP3.

    proxy — например, 'http://127.0.0.1:7897' (Clash Verge Mixed Port).
    progress_callback получает словарь yt-dlp.
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
        'format': 'bestaudio/best',
        'outtmpl': mp3_template,
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '0' if quality_v0 else '2',
        }],
        'quiet': True,
        'no_warnings': True,
        'noprogress': True,
        'progress_hooks': [progress_callback] if progress_callback else [],
        'nocheckcertificate': True,
        'geo_bypass': True,
        'noplaylist': True,
        'no_color': True,
        'nocheckcertificate': True,
        'cookiefile': str(Path(__file__).resolve().parent.parent / 'data' / 'cookies.txt'),

        # ---- EJS-челленджер (обязательно для YouTube 2025+) ----
        'remote_components': ['ejs:github'],

        # ---- JS-рантайм ----
        # Deno включён по умолчанию, если он в PATH.
        # Если Deno в нестандартном месте — раскомментируйте:
        # 'js_runtimes': {'deno': 'C:/path/to/deno.exe'},
        

        # ---- Клиенты YouTube ----
        # default решает JS-челлендж, web_embedded — fallback
        'extractor_args': {
            'youtube': {
                'player_client': ['tv_embedded', 'web_creator'],
            }
        },

        # ---- Сеть ----
        'socket_timeout': 120,
        'retries': 20,
        'fragment_retries': 20,
        'force_ipv4': True,

        
    
        
    }

    from core.paths import get_binaries_dir, get_data_dir

    binaries_dir = get_binaries_dir()
    ffmpeg_path = binaries_dir / 'ffmpeg.exe'
    deno_path = binaries_dir / 'deno.exe'

    # Путь к ffmpeg для yt-dlp
    if ffmpeg_path.exists():
        ydl_opts['ffmpeg_location'] = str(binaries_dir)
        logger.info(f"Использую ffmpeg из: {binaries_dir}")

    # Путь к Deno для JS-челленджей
    if deno_path.exists():
        ydl_opts['js_runtimes'] = {'deno': {'path': str(deno_path)}}
        logger.info(f"Использую Deno из: {deno_path}")

    # Cookies (если пользователь положил файл)
    cookies_file = get_data_dir() / 'cookies.txt'
    if cookies_file.exists():
        ydl_opts['cookiefile'] = str(cookies_file)
        logger.info(f"Использую cookies: {cookies_file}")

    # ---- Прокси ----
    if proxy:
        ydl_opts['proxy'] = proxy
        logger.info(f"Использую прокси: {proxy}")

    # ---- Запуск ----
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            title = info.get('title', video_id)
    except Exception as e:
        logger.exception(f"Ошибка скачивания {video_id}: {e}")
        return DownloadResult(
            success=False,
            video_id=video_id,
            error=f"yt-dlp: {e}",
        )

    # ---- Поиск результата ----
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