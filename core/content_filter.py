"""
Фильтр контента — решает, стоит ли скачивать видео.

Правила:
1. Длительность > max_duration_seconds → skip.
2. Категория в списке исключений (Podcasts, Livestreams) → skip.
3. Название содержит исключённые слова (podcast, full album, live, mix) → skip.
4. Всё остальное → allow.
"""

import logging
from dataclasses import dataclass, field

logger = logging.getLogger('yt-local.filter')


# Категории YouTube, которые считаем "мусором" по умолчанию
DEFAULT_EXCLUDED_CATEGORIES = {
    'Podcasts',
    'Livestreams',
    'News & Politics',
    'Sports',
}

# Ключевые слова в названии, которые считаем "мусором" по умолчанию
DEFAULT_EXCLUDED_KEYWORDS = {
    'podcast',
    'full album',
    'live stream',
    'livestream',
    'radio show',
    'compilation',
    'full movie',
    'audiobook',
    'asmr',
    'sleep music',
    'white noise',
    '10 hours',
    '1 hour',
}


@dataclass
class FilterResult:
    """Результат проверки видео."""
    allowed: bool
    reason: str = ''
    # Дополнительная информация (для логов)
    duration: int = 0
    categories: list[str] = field(default_factory=list)
    matched_keyword: str = ''


class ContentFilter:
    """
    Фильтр контента на основе метаданных yt-dlp.

    Использование:
        cf = ContentFilter(max_duration=600, exclude_podcasts=True)
        info = ydl.extract_info(url, download=False)
        result = cf.check(info)
        if not result.allowed:
            print(f"Пропускаю: {result.reason}")
    """

    def __init__(
        self,
        max_duration: int = 600,
        exclude_podcasts: bool = True,
        exclude_livestreams: bool = True,
        extra_keywords: set[str] | None = None,
        extra_categories: set[str] | None = None,
    ):
        """
        Args:
            max_duration: максимальная длительность в секундах (0 = без ограничений)
            exclude_podcasts: исключать категорию Podcasts
            exclude_livestreams: исключать категорию Livestreams
            extra_keywords: дополнительные ключевые слова для исключения
            extra_categories: дополнительные категории для исключения
        """
        self.max_duration = max_duration
        self.exclude_podcasts = exclude_podcasts
        self.exclude_livestreams = exclude_livestreams

        # Собираем категории для исключения
        self.excluded_categories: set[str] = set()
        if exclude_podcasts:
            self.excluded_categories.add('Podcasts')
        if exclude_livestreams:
            self.excluded_categories.add('Livestreams')
        if extra_categories:
            self.excluded_categories.update(extra_categories)

        # Ключевые слова — всегда базовый набор + пользовательские
        self.excluded_keywords: set[str] = set(DEFAULT_EXCLUDED_KEYWORDS)
        if extra_keywords:
            self.excluded_keywords.update(kw.lower() for kw in extra_keywords)

    def check(self, info: dict) -> FilterResult:
        duration = int(info.get('duration') or 0)
        title = (info.get('title') or '').lower()
        categories = info.get('categories') or []
        if isinstance(categories, str):
            categories = [categories]

        # ---- Проверка 1: категории ----
        for cat in categories:
            if cat in self.excluded_categories:
                reason = f"Исключённая категория: {cat}"
                logger.info(f"Фильтр: {reason} — {info.get('title', '?')}")
                return FilterResult(
                    allowed=False,
                    reason=reason,
                    duration=duration,
                    categories=categories,
                )

        # ---- Проверка 2: ключевые слова ----
        for keyword in self.excluded_keywords:
            if keyword in title:
                reason = f"Ключевое слово в названии: '{keyword}'"
                logger.info(f"Фильтр: {reason} — {info.get('title', '?')}")
                return FilterResult(
                    allowed=False,
                    reason=reason,
                    duration=duration,
                    categories=categories,
                    matched_keyword=keyword,
                )

        # ---- Проверка 3: длительность ----
        if self.max_duration > 0 and duration > self.max_duration:
            minutes = duration // 60
            reason = f"Слишком длинное: {minutes} мин > {self.max_duration // 60} мин"
            logger.info(f"Фильтр: {reason} — {info.get('title', '?')}")
            return FilterResult(
                allowed=False,
                reason=reason,
                duration=duration,
                categories=categories,
            )

        # ---- Всё ок ----
        return FilterResult(
            allowed=True,
            duration=duration,
            categories=categories,
        )

    @classmethod
    def from_settings(cls, settings) -> 'ContentFilter':
        """
        Создаёт фильтр из объекта Settings.

        Args:
            settings: экземпляр core.settings.Settings.

        Returns:
            ContentFilter с настройками из settings.
        """
        return cls(
            max_duration=settings.get('max_duration_seconds', 600),
            exclude_podcasts=settings.get('exclude_podcasts', True),
            exclude_livestreams=settings.get('exclude_livestreams', True),
        )