from __future__ import annotations

from pathlib import Path
from typing import Protocol


class TelegramFileSource(Protocol):
    async def download(
        self,
        chat_id: int,
        message_id: int,
        target: Path,
        progress_callback,
    ) -> Path:
        """Download one Telegram message directly to the requested staging path."""
