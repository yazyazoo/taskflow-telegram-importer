from __future__ import annotations

import os
from pathlib import Path
from typing import Sequence

from taskflow_telegram_importer.errors import ImporterError


class VideoProcessor:
    def __init__(self, allowed_extensions: Sequence[str], staging_root: Path) -> None:
        self._extensions = frozenset(value.lower() for value in allowed_extensions)
        self._staging_root = Path(os.path.abspath(staging_root))

    def process(self, paths: Sequence[Path]) -> tuple[Path, ...]:
        result: list[Path] = []
        for path in paths:
            path = Path(path)
            absolute = Path(os.path.abspath(path))
            if (
                self._staging_root not in absolute.parents
                or path.is_symlink()
                or not path.is_file()
            ):
                raise ImporterError(f"video path is missing or outside staging: {path}")
            if path.suffix.lower() not in self._extensions:
                raise ImporterError(f"unsupported video extension: {path.name}")
            result.append(path)
        if not result:
            raise ImporterError("no videos to process")
        return tuple(result)
