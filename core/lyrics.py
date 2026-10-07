"""
Работа с текстами песен через LRCLIB (lyriq).
"""

import logging
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger('yt-local.lyrics')


@dataclass
class LyricsLine:
    """Одна строка текста с временной меткой."""
    timestamp_ms: int
    text: str


@dataclass
class LyricsData:
    """Текст песни (синхронизированный или обычный)."""
    lines: list[LyricsLine]
    is_synced: bool
    raw_lrc: str = ''

    def is_empty(self) -> bool:
        return not self.lines


def fetch_lyrics(
    title: str,
    artist: str = '',
    duration_sec: int = 0,
    lyrics_dir: Path | None = None,
    video_id: str | None = None,
) -> LyricsData | None:
    """
    Загружает текст песни.
    1. Если есть локальный LRC-файл — читает его.
    2. Иначе — ищет через lyriq и сохраняет локально.
    """
    # 1. Локальный кэш
    if lyrics_dir and video_id:
        cached = lyrics_dir / f"{video_id}.lrc"
        if cached.exists():
            try:
                text = cached.read_text(encoding='utf-8')
                return _parse_lrc(text, is_synced=True)
            except OSError as e:
                logger.warning(f"Не удалось прочитать {cached}: {e}")

    # 2. Поиск через API
    try:
        import lyriq
    except ImportError:
        logger.error("lyriq не установлен. Выполните: pip install lyriq")
        return None

    query = f"{title} {artist}".strip()
    if not query:
        return None

    try:
        # lyriq.search_lyrics возвращает объект Lyrics или None
        results = lyriq.search_lyrics(q=query)
        if not results:
            logger.info(f"Текст не найден: {query}")
            return None
        result = results[0]
    except Exception as e:
        logger.warning(f"Ошибка поиска текста для '{query}': {e}")
        return None

    if result is None:
        logger.info(f"Текст не найден: {query}")
        return None

    # Проверяем, синхронизированный ли текст
    is_synced = bool(getattr(result, 'synced_lyrics', None))

    if is_synced:
        raw_lrc = result.synced_lyrics
        data = _parse_lrc(raw_lrc, is_synced=True)
    else:
        plain = getattr(result, 'plain_lyrics', '') or ''
        raw_lrc = ''
        data = _parse_plain(plain)

    # 3. Сохраняем локально
    if lyrics_dir and video_id and raw_lrc:
        lyrics_dir.mkdir(parents=True, exist_ok=True)
        try:
            (lyrics_dir / f"{video_id}.lrc").write_text(raw_lrc, encoding='utf-8')
            logger.info(f"Текст сохранён: {video_id}.lrc")
        except OSError as e:
            logger.warning(f"Не удалось сохранить текст: {e}")

    return data


def _parse_lrc(lrc_text: str, is_synced: bool = True) -> LyricsData:
    """
    Парсит LRC-текст в список LyricsLine.
    Формат: [MM:SS.ms] текст
    """
    lines: list[LyricsLine] = []
    for raw in lrc_text.splitlines():
        raw = raw.strip()
        if not raw or raw.startswith('[') and ']' not in raw:
            continue

        # Ищем метки времени
        if raw.startswith('['):
            try:
                end = raw.index(']')
                stamp = raw[1:end]
                text = raw[end + 1:].strip()
                if ':' in stamp:
                    mm, rest = stamp.split(':', 1)
                    ss, _, ms = rest.partition('.')
                    timestamp_ms = (
                        int(mm) * 60_000
                        + int(ss) * 1000
                        + int(ms[:3].ljust(3, '0'))
                    )
                    if text:
                        lines.append(LyricsLine(timestamp_ms, text))
            except (ValueError, IndexError):
                continue

    return LyricsData(lines=lines, is_synced=is_synced, raw_lrc=lrc_text)


def _parse_plain(text: str) -> LyricsData:
    """Парсит обычный текст без временных меток."""
    lines = [
        LyricsLine(0, line.strip())
        for line in text.splitlines()
        if line.strip()
    ]
    return LyricsData(lines=lines, is_synced=False)


def find_current_line(lines: list[LyricsLine], position_ms: int) -> int:
    """
    Бинарный поиск индекса текущей строки.
    Возвращает -1, если position_ms меньше первой метки.
    """
    if not lines:
        return -1
    lo, hi = 0, len(lines) - 1
    result = -1
    while lo <= hi:
        mid = (lo + hi) // 2
        if lines[mid].timestamp_ms <= position_ms:
            result = mid
            lo = mid + 1
        else:
            hi = mid - 1
    return result