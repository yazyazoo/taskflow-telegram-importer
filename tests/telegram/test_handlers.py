from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from taskflow_telegram_importer.config import (
    FileSettings,
    LoggingSettings,
    PathSettings,
    SecretCommand,
    Settings,
    TelegramSettings,
)
from taskflow_telegram_importer.errors import ImporterError
from taskflow_telegram_importer.sessions import FileState, ImportFile, ImportSession, SessionState
from taskflow_telegram_importer.telegram import TelegramHandlers, build_application


class ServiceStub:
    def __init__(self) -> None:
        self.calls = []
        self.listeners = []
        self.session = ImportSession("abc123", 20, 10, SessionState.COLLECTING)

    def receive_descriptor(self, *args):
        self.calls.append(("descriptor", args))
        return self.session

    def receive_video(self, **kwargs):
        self.calls.append(("video", kwargs))
        if not self.session.files:
            file = ImportFile(
                kwargs["message_id"],
                kwargs["file_id"],
                kwargs["file_unique_id"],
                kwargs["filename"],
                kwargs["expected_size"],
                FileState.RECEIVED,
            )
            self.session = replace(self.session, files=(file,))
        return self.session

    def finish_collection(self, user_id):
        self.calls.append(("finish", user_id))
        self.session = replace(self.session, state=SessionState.SEALED)
        return self.session

    def confirm_metadata(self, session_id, user_id):
        self.calls.append(("confirm", session_id, user_id))
        return self.session

    def edit_metadata(self, session_id, user_id, title, year):
        self.calls.append(("edit", session_id, user_id, title, year))
        return self.session

    def retry_file(self, session_id, user_id, message_id):
        self.calls.append(("retry", session_id, user_id, message_id))

    async def exclude_file(self, session_id, user_id, message_id):
        self.calls.append(("exclude", session_id, user_id, message_id))
        return self.session

    async def delete_session(self, session_id, user_id):
        self.calls.append(("delete", session_id, user_id))

    def get(self, session_id, user_id):
        if user_id != self.session.user_id:
            raise ImporterError("session belongs to another operator")
        return self.session

    def add_listener(self, listener):
        self.listeners.append(listener)


class FakeMessage:
    def __init__(self, *, message_id=1, caption=None, text=None, photo=None, document=None, video=None):
        self.message_id = message_id
        self.caption = caption
        self.text = text
        self.photo = photo
        self.document = document
        self.video = video
        self.replies = []

    async def reply_text(self, text, **kwargs):
        self.replies.append((text, kwargs))
        return SimpleNamespace(message_id=900)


class FakeBot:
    def __init__(self):
        self.edits = []

    async def edit_message_text(self, **kwargs):
        self.edits.append(kwargs)


class FakeQuery:
    def __init__(self, data, message):
        self.data = data
        self.message = message
        self.answers = 0
        self.edits = []

    async def answer(self):
        self.answers += 1

    async def edit_message_text(self, text):
        self.edits.append(text)


def _update(message, *, user_id=10, chat_type="private"):
    return SimpleNamespace(
        effective_user=SimpleNamespace(id=user_id),
        effective_chat=SimpleNamespace(id=20, type=chat_type),
        effective_message=message,
        callback_query=None,
    )


def _callback(data, *, user_id=10):
    message = FakeMessage()
    query = FakeQuery(data, message)
    update = _update(message, user_id=user_id)
    update.callback_query = query
    return update, query


def _file(**overrides):
    values = {
        "file_id": "telegram-file",
        "file_unique_id": "unique",
        "file_name": "episode.mkv",
        "file_size": 5_000_000_000,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


@pytest.mark.asyncio
async def test_rejects_unauthorized_users_and_non_private_chats() -> None:
    service = ServiceStub()
    handlers = TelegramHandlers(service, (10,), (".mkv",))
    context = SimpleNamespace(bot=FakeBot())

    await handlers.handle_message(_update(FakeMessage(document=_file()), user_id=11), context)
    await handlers.handle_message(_update(FakeMessage(document=_file()), chat_type="group"), context)

    assert service.calls == []


@pytest.mark.asyncio
async def test_descriptor_caption_is_kept_without_downloading_photo() -> None:
    service = ServiceStub()
    handlers = TelegramHandlers(service, (10,), (".mkv",))

    await handlers.handle_message(
        _update(FakeMessage(message_id=9, caption="Cape Fear (2025)", photo=[object()])),
        SimpleNamespace(bot=FakeBot()),
    )

    assert service.calls[0] == ("descriptor", (20, 10, 9, "Cape Fear (2025)"))


@pytest.mark.asyncio
async def test_extracts_document_and_preserves_64_bit_size() -> None:
    service = ServiceStub()
    handlers = TelegramHandlers(service, (10,), (".mkv",))

    await handlers.handle_message(
        _update(FakeMessage(document=_file())), SimpleNamespace(bot=FakeBot())
    )

    payload = service.calls[0][1]
    assert payload["expected_size"] == 5_000_000_000
    assert payload["filename"] == "episode.mkv"


@pytest.mark.asyncio
@pytest.mark.parametrize("file", [_file(file_name=None), _file(file_name="archive.zip")])
async def test_rejects_absent_filename_or_disallowed_extension(file) -> None:
    service = ServiceStub()
    handlers = TelegramHandlers(service, (10,), (".mkv",))
    message = FakeMessage(document=file)

    await handlers.handle_message(_update(message), SimpleNamespace(bot=FakeBot()))

    assert service.calls == []
    assert message.replies


@pytest.mark.asyncio
async def test_reuses_one_status_message_for_following_updates() -> None:
    service = ServiceStub()
    handlers = TelegramHandlers(service, (10,), (".mkv",))
    bot = FakeBot()
    first = FakeMessage(message_id=1, document=_file())
    second = FakeMessage(message_id=2, document=_file(file_id="second", file_unique_id="u2"))

    await handlers.handle_message(_update(first), SimpleNamespace(bot=bot))
    await handlers.handle_message(_update(second), SimpleNamespace(bot=bot))

    assert len(first.replies) == 1
    assert len(bot.edits) == 1
    assert bot.edits[0]["message_id"] == 900


@pytest.mark.asyncio
async def test_background_session_event_edits_existing_status() -> None:
    service = ServiceStub()
    handlers = TelegramHandlers(service, (10,), (".mkv",))
    bot = FakeBot()
    await handlers.handle_message(
        _update(FakeMessage(document=_file())), SimpleNamespace(bot=bot)
    )

    await service.listeners[0](service.session)

    assert bot.edits[-1]["message_id"] == 900
    assert "Completati" in bot.edits[-1]["text"]


@pytest.mark.asyncio
async def test_delete_requires_two_callbacks_and_enforces_owner() -> None:
    service = ServiceStub()
    handlers = TelegramHandlers(service, (10, 11), (".mkv",))
    context = SimpleNamespace(bot=FakeBot())
    request_update, _ = _callback("delete-request:abc123")

    await handlers.handle_callback(request_update, context)
    assert not any(call[0] == "delete" for call in service.calls)

    confirm_update, confirm_query = _callback("delete-confirm:abc123")
    await handlers.handle_callback(confirm_update, context)
    assert ("delete", "abc123", 10) in service.calls
    assert confirm_query.edits == ["Sessione eliminata."]

    other_update, other_query = _callback("confirm:abc123", user_id=11)
    await handlers.handle_callback(other_update, context)
    assert other_query.message.replies
    assert not any(call[0] == "confirm" and call[-1] == 11 for call in service.calls)


@pytest.mark.asyncio
async def test_stale_finish_button_does_not_finish_another_session() -> None:
    service = ServiceStub()
    service.session = replace(service.session, state=SessionState.SEALED)
    handlers = TelegramHandlers(service, (10,), (".mkv",))
    update, query = _callback("finish:abc123")

    await handlers.handle_callback(update, SimpleNamespace(bot=FakeBot()))

    assert not any(call[0] == "finish" for call in service.calls)
    assert query.message.replies


def test_build_application_uses_local_bot_api_and_sequential_updates(tmp_path: Path) -> None:
    settings = Settings(
        telegram=TelegramSettings(
            api_base_url="http://127.0.0.1:8081/bot",
            local_mode=True,
            long_poll_request_timeout_seconds=30,
            allowed_user_ids=(10,),
            token_command=SecretCommand(Path("/bin/false"), "alias", "token"),
        ),
        paths=PathSettings(tmp_path / "staging", tmp_path / "gate", tmp_path / "log"),
        files=FileSettings((".mkv",), 0),
        logging=LoggingSettings("INFO"),
    )

    application = build_application(settings, ServiceStub(), token="123456:TEST_TOKEN")

    assert application.bot.local_mode is True
    assert application.bot.base_url == "http://127.0.0.1:8081/bot123456:TEST_TOKEN"
    assert application.update_processor.max_concurrent_updates == 1
