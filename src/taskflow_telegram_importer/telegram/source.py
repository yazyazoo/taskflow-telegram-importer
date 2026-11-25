from __future__ import annotations

from pathlib import Path

from taskflow_telegram_importer.errors import ImporterError


class TelethonFileSource:
    def __init__(self, client) -> None:
        self._client = client

    async def download(
        self,
        chat_id: int,
        message_id: int,
        target: Path,
        progress_callback,
    ) -> Path:
        message = await self._client.get_messages(chat_id, ids=message_id)
        if message is None:
            raise ImporterError("Telegram message is no longer available")
        result = await self._client.download_media(
            message,
            file=str(target),
            progress_callback=progress_callback,
        )
        if result is None or Path(result) != target:
            raise ImporterError("Telegram download did not produce the requested file")
        return target
