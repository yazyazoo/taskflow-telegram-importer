from __future__ import annotations

import re

from taskflow_telegram_importer.errors import ImporterError


_SEPARATORS = re.compile(r"[^\w]+", re.UNICODE)
_REPEATED_UNDERSCORES = re.compile(r"_+")


def normalize_session_directory(title: str, year: int) -> str:
    if "\x00" in title:
        raise ImporterError("title contains a NUL byte")
    if not 1000 <= year <= 9999:
        raise ImporterError("year must contain four digits")
    normalized = _SEPARATORS.sub("_", title.strip())
    normalized = _REPEATED_UNDERSCORES.sub("_", normalized).strip("_")
    if not normalized:
        raise ImporterError("title has no usable characters")
    return f"{normalized}_{year}"
