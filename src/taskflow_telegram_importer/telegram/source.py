from __future__ import annotations

from pathlib import Path

from telegram import Bot

from taskflow_telegram_importer.errors import ImporterError


class TelegramFileSource:
    def __init__(self, bot: Bot) -> None:
        self._bot = bot

    async def get_local_file(self, file_id: str) -> Path:
        telegram_file = await self._bot.get_file(file_id)
        if not telegram_file.file_path:
            raise ImporterError("local Bot API returned no file path")
        path = Path(telegram_file.file_path)
        if not path.is_absolute() or path.is_symlink() or not path.is_file():
            raise ImporterError("local Bot API returned an unsafe file path")
        return path
