from __future__ import annotations

import re
from pathlib import Path
from typing import Sequence

from .models import EditorialHint


_YEAR_GROUP = re.compile(r"\((\d{4})(?:[^)]*)\)")
_VALID_YEAR_MIN = 1888
_VALID_YEAR_MAX = 2200


def parse_editorial_hint(
    captions: Sequence[str], filenames: Sequence[str]
) -> EditorialHint | None:
    first_caption_line = _first_nonempty_line(captions)
    if first_caption_line is not None:
        parsed = _parse_candidate(first_caption_line)
        if parsed is not None:
            return parsed

    candidates = {
        parsed
        for filename in filenames
        if (parsed := _parse_candidate(Path(filename).stem)) is not None
    }
    if len(candidates) == 1:
        return candidates.pop()
    return None


def _first_nonempty_line(values: Sequence[str]) -> str | None:
    for value in values:
        for line in value.splitlines():
            if line.strip():
                return line.strip()
    return None


def _parse_candidate(value: str) -> EditorialHint | None:
    matches = list(_YEAR_GROUP.finditer(value))
    for match in reversed(matches):
        year = int(match.group(1))
        if not _VALID_YEAR_MIN <= year <= _VALID_YEAR_MAX:
            continue
        title = value[: match.start()].strip(" ._-–—")
        if not title:
            return None
        return EditorialHint(title=title, year=year)
    return None
