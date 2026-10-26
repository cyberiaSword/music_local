"""
Хранилище пользовательских настроек.

Внутри использует Pydantic-модель AppConfig для валидации.
API сохранён обратно совместимым: get(), set(), [].
"""

import json
import logging
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from core.config import AppConfig, CONFIG_VERSION

logger = logging.getLogger('yt-local.settings')


class Settings:
    """
    Обёртка над AppConfig с сохранением в JSON.

    Использование:
        settings = Settings(Path('data/settings.json'))
        volume = settings.get('player_volume', 70)
        settings.set('player_volume', 80)
        settings.save()
    """

    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._config: AppConfig = AppConfig()
        self.load()

    # ============================================================
    # Загрузка и сохранение
    # ============================================================

    def load(self) -> None:
        """Загружает настройки из JSON. При ошибке — дефолты."""
        if not self.path.exists():
            logger.info(f"Файл настроек не найден, использую дефолты: {self.path}")
            self._config = AppConfig()
            self.save()
            return

        try:
            with open(self.path, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logger.error(f"Не удалось прочитать {self.path}: {e}")
            self._config = AppConfig()
            return

        # Миграции версий
        file_version = data.get('config_version', 0)
        if file_version < CONFIG_VERSION:
            logger.info(f"Миграция настроек: v{file_version} → v{CONFIG_VERSION}")
            data = self._migrate(data, file_version)
            data['config_version'] = CONFIG_VERSION

        # Загрузка через Pydantic с валидацией
        try:
            self._config = AppConfig(**data)
            logger.info(f"Настройки загружены: {self.path}")
        except ValidationError as e:
            logger.error(f"Ошибки валидации настроек:\n{e}")
            logger.warning("Использую дефолтные значения для невалидных полей")
            self._config = self._load_with_fallbacks(data)
            self.save()

    def _migrate(self, data: dict, from_version: int) -> dict:
        """
        Миграции настроек между версиями.
        Сейчас одна версия, но шаблон готов для будущего.
        """
        # Пример будущей миграции:
        # if from_version < 1:
        #     data['new_key'] = data.pop('old_key', default)
        return data

    def _load_with_fallbacks(self, data: dict) -> AppConfig:
        """Загружает по одному полю, игнорируя невалидные."""
        defaults = AppConfig()
        result = {}

        for field_name in AppConfig.model_fields:
            value = data.get(field_name, getattr(defaults, field_name))
            result[field_name] = value

        try:
            return AppConfig(**result)
        except ValidationError:
            logger.warning("Полная загрузка не удалась, использую дефолты")
            return defaults

    def save(self) -> None:
        """Сохраняет настройки в JSON."""
        try:
            data = self._config.model_dump()
            with open(self.path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except OSError as e:
            logger.error(f"Не удалось сохранить {self.path}: {e}")

    # ============================================================
    # Обратно совместимый API
    # ============================================================

    def get(self, key: str, default: Any = None) -> Any:
        """Возвращает значение настройки или default."""
        if hasattr(self._config, key):
            return getattr(self._config, key)
        if default is not None:
            logger.debug(f"Ключ '{key}' не найден, использую default={default}")
        return default

    def set(self, key: str, value: Any) -> None:
        """Устанавливает значение с валидацией."""
        if not hasattr(self._config, key):
            logger.warning(f"Попытка установить неизвестный ключ: {key}")
            return

        try:
            setattr(self._config, key, value)
        except ValidationError as e:
            logger.error(f"Невалидное значение для '{key}': {value}\n{e}")

    def __getitem__(self, key: str) -> Any:
        if not hasattr(self._config, key):
            raise KeyError(key)
        return getattr(self._config, key)

    def __setitem__(self, key: str, value: Any) -> None:
        self.set(key, value)

    def __contains__(self, key: str) -> bool:
        return hasattr(self._config, key)

    # ============================================================
    # Дополнительные удобства
    # ============================================================

    @property
    def config(self) -> AppConfig:
        """Прямой доступ к Pydantic-модели."""
        return self._config

    @property
    def global_hotkeys_enabled(self) -> bool:
        """Желаемое состояние глобальных клавиш, независимо от listener."""
        return self._config.global_hotkeys_enabled

    @global_hotkeys_enabled.setter
    def global_hotkeys_enabled(self, enabled: bool) -> None:
        self.set('global_hotkeys_enabled', enabled)

    def reset_to_defaults(self) -> None:
        """Сбрасывает все настройки к дефолтным."""
        self._config = AppConfig()
        self.save()
        logger.info("Настройки сброшены к дефолтным")

    def to_dict(self) -> dict:
        """Возвращает настройки как dict (для экспорта)."""
        return self._config.model_dump()