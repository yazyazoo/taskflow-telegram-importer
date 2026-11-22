from __future__ import annotations

from pathlib import Path
from typing import Protocol, Sequence


class ContentProcessor(Protocol):
    def process(self, paths: Sequence[Path]) -> tuple[Path, ...]:
        """Validate and return complete video paths ready for publication."""
