"""
Фильтры для логирования — маскируют секреты.
"""

import logging
import re


# Паттерны секретов в логах
_PATTERNS = [
    # cookies=..., SID=..., HSID=..., SSID=..., APISID=..., SAPISID=...
    (re.compile(r'((?:^|[?&\s])(?:cookies?|SID|HSID|SSID|APISID|SAPISID|LOGIN_INFO|__Secure-[\w-]+|Authorization)=)([^&\s]+)', re.IGNORECASE), r'\1***'),
    # "Cookie: ..." в заголовках
    (re.compile(r'(Cookie:\s*)(.+)', re.IGNORECASE), r'\1***'),
    # "Set-Cookie: ..."
    (re.compile(r'(Set-Cookie:\s*)(.+)', re.IGNORECASE), r'\1***'),
    # Bearer-токены
    (re.compile(r'(Bearer\s+)([A-Za-z0-9\-._~+/]+=*)'), r'\1***'),
    # API-ключи в URL (api_key=, key=, token=)
    (re.compile(r'((?:api[_-]?key|token|access[_-]?token)=)([^&\s]+)', re.IGNORECASE), r'\1***'),
]


class SecretMaskFilter(logging.Filter):
    """Маскирует секреты в сообщениях логов."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
            for pattern, replacement in _PATTERNS:
                msg = pattern.sub(replacement, msg)
            # Перезаписываем
            record.msg = msg
            record.args = ()
        except Exception:
            pass
        return True