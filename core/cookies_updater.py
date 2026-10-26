"""
Автообновление cookies из браузера.

Использует rookiepy для чтения cookies из профилей браузеров.
Формат — Netscape (совместим с yt-dlp).

Поддерживаемые браузеры:
- Chrome
- Firefox
- Edge
- Brave
- Opera
- Chromium

Vivaldi НЕ поддерживается — fallback на ручной экспорт.
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger('yt-local.cookies')


# Домены, cookies которых нам нужны
TARGET_DOMAINS = [
    '.youtube.com',
    '.google.com',
]


# Браузеры в порядке приоритета
BROWSER_PRIORITY = [
    'chrome',
    'firefox',
    'edge',
    'brave',
    'opera',
    'chromium',
]


@dataclass
class CookieUpdateResult:
    """Результат обновления cookies."""
    success: bool
    browser: str = ''
    cookies_count: int = 0
    path: Path | None = None
    error: str = ''

    def __bool__(self) -> bool:
        return self.success


def _is_youtube_cookie(cookie: dict) -> bool:
    """Проверяет, относится ли cookie к YouTube/Google."""
    domain = cookie.get('domain', '')
    return any(target in domain for target in TARGET_DOMAINS)


def _cookie_to_netscape(cookie: dict) -> str:
    """
    Преобразует cookie в строку формата Netscape.
    Формат: domain\tflag\tpath\tsecure\texpires\tname\tvalue
    """
    domain = cookie.get('domain', '')
    # Флаг TRUE, если домен начинается с точки (wildcard)
    flag = 'TRUE' if domain.startswith('.') else 'FALSE'
    path = cookie.get('path', '/')
    secure = 'TRUE' if cookie.get('secure', False) else 'FALSE'

    # expires — Unix timestamp. Если сессионная — 0
    expires = cookie.get('expires', 0) or 0
    name = cookie.get('name', '')
    value = cookie.get('value', '')

    return f"{domain}\t{flag}\t{path}\t{secure}\t{expires}\t{name}\t{value}"


def update_cookies_from_browser(
    output_path: Path,
    browser: str | None = None,
) -> CookieUpdateResult:
    """
    Пытается экспортировать cookies из браузера.

    Args:
        output_path: куда сохранить cookies.txt.
        browser: конкретный браузер ('chrome', 'firefox', ...).
                 Если None — перебирает все в порядке BROWSER_PRIORITY.

    Returns:
        CookieUpdateResult с полем success.
    """
    try:
        import rookiepy
    except ImportError:
        return CookieUpdateResult(
            success=False,
            error="rookiepy не установлен. Выполните: pip install rookiepy",
        )

    browsers_to_try = [browser] if browser else BROWSER_PRIORITY

    last_error = ''

    for browser_name in browsers_to_try:
        try:
            logger.info(f"Пробую извлечь cookies из {browser_name}...")

            # Получаем функцию для браузера
            extractor = getattr(rookiepy, browser_name, None)
            if extractor is None:
                logger.debug(f"rookiepy не поддерживает {browser_name}")
                continue

            # Читаем cookies
            all_cookies = extractor()

            if not all_cookies:
                logger.info(f"{browser_name}: cookies не найдены (браузер не запущен?)")
                continue

            # Фильтруем только YouTube/Google
            youtube_cookies = [c for c in all_cookies if _is_youtube_cookie(c)]

            if not youtube_cookies:
                logger.info(f"{browser_name}: нет cookies YouTube (не авторизованы?)")
                continue

            # Проверяем, что есть SID (признак авторизации)
            has_sid = any(c.get('name') == 'SID' for c in youtube_cookies)
            if not has_sid:
                logger.warning(
                    f"{browser_name}: cookies YouTube найдены, но нет SID. "
                    "Возможно, вы не авторизованы в YouTube."
                )
                # Продолжаем — cookies всё равно могут быть полезны

            # Записываем в файл
            output_path.parent.mkdir(parents=True, exist_ok=True)

            now = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
            with open(output_path, 'w', encoding='utf-8', newline='\n') as f:
                # Заголовок Netscape
                f.write("# Netscape HTTP Cookie File\n")
                f.write(f"# Exported by YT Music Local from {browser_name}\n")
                f.write(f"# Date: {now}\n")
                f.write("# https://curl.se/docs/http-cookies.html\n")
                f.write("# This file is required by yt-dlp for YouTube authentication\n\n")

                # Cookies
                for cookie in youtube_cookies:
                    try:
                        f.write(_cookie_to_netscape(cookie) + '\n')
                    except Exception as e:
                        logger.debug(f"Ошибка записи cookie {cookie.get('name')}: {e}")

            logger.info(
                f"✅ Экспортировано {len(youtube_cookies)} cookies из {browser_name} → {output_path}"
            )

            return CookieUpdateResult(
                success=True,
                browser=browser_name,
                cookies_count=len(youtube_cookies),
                path=output_path,
            )

        except Exception as e:
            logger.warning(f"{browser_name}: ошибка чтения cookies — {e}")
            last_error = str(e)
            continue

    # Все браузеры перепробованы
    return CookieUpdateResult(
        success=False,
        error=(
            f"Не удалось прочитать cookies из браузеров: {', '.join(browsers_to_try)}. "
            f"Последняя ошибка: {last_error}. "
            "Возможные причины: браузер не запущен, не авторизованы в YouTube, "
            "или используется Vivaldi (не поддерживается)."
        ),
    )


def check_cookies_valid(cookies_path: Path) -> tuple[bool, str]:
    """
    Проверяет, что cookies.txt существует и содержит нужные ключи.

    Returns:
        (валидны ли, причина)
    """
    if not cookies_path.exists():
        return False, "Файл не существует"

    try:
        content = cookies_path.read_text(encoding='utf-8')
    except OSError as e:
        return False, f"Не удалось прочитать: {e}"

    if not content.strip():
        return False, "Файл пустой"

    if '# Netscape HTTP Cookie File' not in content and '# HTTP Cookie File' not in content:
        return False, "Нет заголовка Netscape (неверный формат)"

    # Проверяем наличие ключевых cookies
    required = ['SID', 'HSID', 'SSID', 'LOGIN_INFO']
    found = []
    for name in required:
        if f"\t{name}\t" in content or f"\t{name}\n" in content:
            found.append(name)

    if 'SID' not in found:
        return False, "Нет cookie SID (не авторизованы в YouTube)"

    return True, f"OK (найдено: {', '.join(found)})"