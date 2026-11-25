from __future__ import annotations

from pathlib import Path

from telethon import TelegramClient, events


class TelethonGateway:
    def __init__(self, client, handlers, *, bot_token: str, session_path: Path) -> None:
        self.client = client
        self._handlers = handlers
        self._bot_token = bot_token
        self._session_path = session_path
        self._registered = False

    async def start(self) -> None:
        self._session_path.parent.mkdir(parents=True, exist_ok=True)
        if not self._registered:
            self.client.add_event_handler(
                self._handlers.handle_callback, events.CallbackQuery()
            )
            self.client.add_event_handler(
                self._handlers.handle_message, events.NewMessage(incoming=True)
            )
            self._registered = True
        await self.client.start(bot_token=self._bot_token)

    async def stop(self) -> None:
        await self.client.disconnect()


def build_client(*, session_path: Path, api_id: int, api_hash: str):
    return TelegramClient(str(session_path), api_id, api_hash)
