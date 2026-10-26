"""
Модель настроек приложения на Pydantic.

Обеспечивает:
- Валидацию типов
- Дефолтные значения
- Автокомплит в IDE
- Миграции версий
"""

from typing import Literal

from pydantic import BaseModel, Field, field_validator


# Версия схемы настроек — увеличивается при breaking-изменениях
CONFIG_VERSION = 2


class AppConfig(BaseModel):
    """Полная модель настроек приложения."""

    # ---- Служебное ----
    config_version: int = Field(
        default=CONFIG_VERSION,
        description="Версия схемы настроек для миграций",
    )

    # ---- Пути ----
    downloads_dir: str = Field(
        default="downloads",
        description="Папка для скачанных MP3 (относительно data/)",
    )
    covers_dir: str = Field(
        default="covers",
        description="Папка для обложек",
    )

    # ---- Аудио ----
    audio_format: Literal["mp3", "opus"] = Field(
        default="mp3",
        description="Формат аудио",
    )
    audio_quality_v0: bool = Field(
        default=True,
        description="True = V0 (~245 kbps), False = V2 (~190 kbps)",
    )

    # ---- Обложки ----
    cover_mode: Literal["auto", "poster", "video_frame"] = Field(
        default="video_frame",
        description="Режим обложек: постер / кадр из видео / авто",
    )
    video_frame_second: int = Field(
        default=15,
        ge=1,
        le=600,
        description="Секунда, с которой берётся кадр из видео",
    )
    cover_size_list: Literal["mqdefault", "hqdefault", "maxresdefault"] = Field(
        default="hqdefault",
        description="Размер обложки в списке",
    )
    cover_size_player: Literal["mqdefault", "hqdefault", "maxresdefault"] = Field(
        default="maxresdefault",
        description="Размер обложки в плеере",
    )

    # ---- Автоскачивание ----
    auto_download: bool = Field(
        default=True,
        description="Автоматически скачивать новые треки",
    )
    max_concurrent_downloads: int = Field(
        default=1,
        ge=1,
        le=5,
        description="Максимум параллельных загрузок",
    )
    download_timeout_seconds: int = Field(
        default=300,
        ge=30,
        le=3600,
        description="Таймаут скачивания одного трека",
    )

    # ---- Фильтры контента ----
    max_duration_seconds: int = Field(
        default=600,
        ge=0,
        description="Максимальная длительность видео (0 = без ограничений)",
    )
    exclude_podcasts: bool = Field(
        default=True,
        description="Исключать подкасты",
    )
    exclude_livestreams: bool = Field(
        default=True,
        description="Исключать стримы",
    )
 # ---- Дополнительные фильтры ----
    extra_exclude_keywords: list[str] = Field(
        default_factory=list,
        description="Дополнительные ключевые слова для исключения",
    )
    extra_exclude_categories: list[str] = Field(
        default_factory=list,
        description="Дополнительные категории для исключения",
    )

    # ---- Плеер ----
    player_volume: int = Field(
        default=70,
        ge=0,
        le=100,
        description="Громкость по умолчанию (0-100)",
    )
    player_autoplay_next: bool = Field(
        default=True,
        description="Автоматически играть следующий трек",
    )
    queue_track_ids: list[int] = Field(default_factory=list, max_length=200)
    queue_current_index: int = Field(default=-1, ge=-1, le=199)
    player_crossfade_ms: int = Field(
        default=0,
        ge=0,
        le=10000,
        description="Crossfade между треками (мс, 0 = выкл)",
    )

    # ---- Оптимизатор ----
    optimize_threshold_kbps: int = Field(
        default=250,
        ge=64,
        le=320,
        description="Порог битрейта для перекодирования",
    )

    # ---- UI ----
    global_hotkeys_enabled: bool = Field(
        default=True,
        description="Включить глобальные горячие клавиши",
    )
    minimize_to_tray: bool = Field(
        default=True,
        description="Сворачивать в трей при закрытии",
    )
    start_minimized: bool = Field(
        default=False,
        description="Запускать свёрнутым в трей",
    )
    theme: Literal["dark", "light", "auto"] = Field(
        default="dark",
        description="Тема оформления",
    )
    language: str = Field(
        default="ru",
        description="Язык интерфейса (ru, en)",
    )

    # ---- WebSocket ----
    ws_host: str = Field(
        default="127.0.0.1",
        description="Хост WebSocket-сервера",
    )
    ws_port: int = Field(
        default=8765,
        ge=1024,
        le=65535,
        description="Порт WebSocket-сервера",
    )

    # ---- Сеть ----
    proxy: str | None = Field(
        default=None,
        description="Прокси (например, http://127.0.0.1:7897)",
    )
    cookies_file: str | None = Field(
        default="cookies.txt",
        description="Путь к cookies.txt (относительно data/)",
    )

    # ---- Валидаторы ----

    @field_validator("proxy")
    @classmethod
    def validate_proxy(cls, v: str | None) -> str | None:
        """Проверяет, что прокси — валидный URL или None."""
        if v is None or v == "":
            return None
        if not (v.startswith("http://") or v.startswith("https://") or v.startswith("socks")):
            raise ValueError(
                "Прокси должен начинаться с http://, https:// или socks"
            )
        return v

    @field_validator("language")
    @classmethod
    def validate_language(cls, v: str) -> str:
        """Проверяет, что язык в списке поддерживаемых."""
        supported = {"ru", "en"}
        if v not in supported:
            raise ValueError(f"Неподдерживаемый язык: {v}. Доступны: {supported}")
        return v

    class Config:
        """Настройки Pydantic-модели."""
        extra = "ignore"              # игнорировать неизвестные ключи
        validate_assignment = True    # валидировать при изменении 