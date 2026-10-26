"""
Тесты для core.content_filter.
"""

import pytest

from core.content_filter import ContentFilter, FilterResult


class TestContentFilter:
    """Тесты фильтра."""

    def test_allow_normal(self):
        """Обычное видео пропускается."""
        cf = ContentFilter(max_duration=600)
        info = {
            'title': 'Nightcore - Babydoll',
            'duration': 180,
            'categories': ['Music'],
        }
        result = cf.check(info)
        assert result.allowed is True
        assert result.reason == ''

    def test_block_long_duration(self):
        """Длинное видео отсекается."""
        cf = ContentFilter(max_duration=600)
        info = {
            'title': 'DJ Set 2 hours',
            'duration': 7200,
            'categories': ['Music'],
        }
        result = cf.check(info)
        assert result.allowed is False
        assert 'Слишком длинное' in result.reason

    def test_block_podcast(self):
        """Подкаст отсекается."""
        cf = ContentFilter(exclude_podcasts=True)
        info = {
            'title': 'Some Podcast Episode',
            'duration': 1800,
            'categories': ['Podcasts'],
        }
        result = cf.check(info)
        assert result.allowed is False
        assert 'Podcasts' in result.reason

    def test_block_livestream(self):
        """Стрим отсекается."""
        cf = ContentFilter(exclude_livestreams=True)
        info = {
            'title': 'Live Stream Today',
            'duration': 3600,
            'categories': ['Livestreams'],
        }
        result = cf.check(info)
        assert result.allowed is False
        assert 'Livestreams' in result.reason

    def test_block_keyword_full_album(self):
        """Ключевое слово 'full album' отсекает."""
        cf = ContentFilter(max_duration=0)
        info = {
            'title': 'Pink Floyd - Full Album (1973)',
            'duration': 2400,
            'categories': ['Music'],
        }
        result = cf.check(info)
        assert result.allowed is False
        assert 'full album' in result.reason.lower()

    def test_block_keyword_case_insensitive(self):
        """Ключевое слово работает в любом регистре."""
        cf = ContentFilter(max_duration=0)
        info = {
            'title': 'LIVE STREAM on YouTube',
            'duration': 300,
            'categories': ['Music'],
        }
        result = cf.check(info)
        assert result.allowed is False

    def test_max_duration_zero_means_no_limit(self):
        """max_duration=0 — без ограничений."""
        cf = ContentFilter(max_duration=0)
        info = {
            'title': 'Very long video',
            'duration': 36000,
            'categories': ['Music'],
        }
        result = cf.check(info)
        assert result.allowed is True

    def test_extra_keywords(self):
        """Дополнительные ключевые слова работают."""
        cf = ContentFilter(max_duration=0, extra_keywords={'megamix', 'dj set'})
        info = {
            'title': 'Summer Megamix 2026',
            'duration': 1800,
            'categories': ['Music'],
        }
        result = cf.check(info)
        assert result.allowed is False
        assert 'megamix' in result.reason.lower()

    def test_from_settings(self):
        """Фабрика from_settings работает."""
        class FakeSettings:
            def __init__(self):
                self._data = {
                    'max_duration_seconds': 300,
                    'exclude_podcasts': True,
                    'exclude_livestreams': False,
                }
            def get(self, key, default=None):
                return self._data.get(key, default)

        cf = ContentFilter.from_settings(FakeSettings())
        assert cf.max_duration == 300
        assert cf.exclude_podcasts is True
        assert cf.exclude_livestreams is False
        assert 'Podcasts' in cf.excluded_categories
        assert 'Livestreams' not in cf.excluded_categories

    def test_missing_duration(self):
        """Отсутствие duration не ломает."""
        cf = ContentFilter(max_duration=600)
        info = {'title': 'Unknown', 'categories': ['Music']}
        result = cf.check(info)
        assert result.allowed is True
        assert result.duration == 0

    def test_missing_categories(self):
        """Отсутствие categories не ломает."""
        cf = ContentFilter(max_duration=600)
        info = {'title': 'Unknown', 'duration': 180}
        result = cf.check(info)
        assert result.allowed is True