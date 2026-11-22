from __future__ import annotations

from pathlib import Path
from typing import Protocol


class TelegramFileSource(Protocol):
    async def get_local_file(self, file_id: str) -> Path:
        """Return the regular local Bot API path for one Telegram file."""
