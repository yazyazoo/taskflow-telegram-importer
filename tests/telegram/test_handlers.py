from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import pytest

from taskflow_telegram_importer.errors import ImporterError
from taskflow_telegram_importer.sessions import (
    EditorialHint,
    FileState,
    ImportFile,
    ImportMode,
    ImportSession,
    QuickStage,
    QuickWorkflowDraft,
    SessionState,
    VideoMetadata,
)
from taskflow_telegram_importer.telegram.handlers import TelegramHandlers


class ServiceStub:
    def __init__(self) -> None:
        self.calls = []
        self.listeners = []
        self.session = ImportSession("abc123", 20, 10, SessionState.COLLECTING)

    def add_listener(self, listener):
        self.listeners.append(listener)

    def receive_descriptor(self, *args):
        self.calls.append(("descriptor", args))
        return self.session

    def receive_video(self, **kwargs):
        self.calls.append(("video", kwargs))
        if not self.session.files:
            item = ImportFile(
                kwargs["message_id"],
                kwargs["filename"],
                kwargs["expected_size"],
                FileState.RECEIVED,
            )
            self.session = replace(self.session, files=(item,))
        return self.session

    def finish_collection(self, user_id):
        self.calls.append(("finish", user_id))
        self.session = replace(self.session, state=SessionState.SEALED)
        return self.session

    def confirm_metadata(self, session_id, user_id):
        self.calls.append(("confirm", session_id, user_id))
        return self.session

    def start_manual(self, session_id, user_id):
        self.calls.append(("manual", session_id, user_id))
        self.session = replace(
            self.session, mode=ImportMode.MANUAL, metadata_confirmed=True
        )
        return self.session

    def begin_quick(self, session_id, user_id):
        self.calls.append(("quick", session_id, user_id))
        self.session = replace(
            self.session,
            mode=ImportMode.QUICK,
            quick=QuickWorkflowDraft(QuickStage.MEDIA_KIND),
        )
        return self.session

    def set_quick_media_kind(self, session_id, user_id, media_kind):
        self.calls.append(("kind", session_id, user_id, media_kind))
        self.session = replace(
            self.session,
            quick=replace(
                self.session.quick, stage=QuickStage.QUERY, media_kind=media_kind
            ),
        )
        return self.session

    async def search_quick(self, session_id, user_id, title, year):
        self.calls.append(("search", session_id, user_id, title, year))
        return self.session

    def edit_metadata(self, session_id, user_id, title, year):
        self.calls.append(("edit", session_id, user_id, title, year))
        self.session = replace(
            self.session, editorial_hint=EditorialHint(title, year)
        )
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


class FakeClient:
    def __init__(self) -> None:
        self.edits = []
        self.deletes = []
        self.sent = []

    async def edit_message(self, chat_id, message_id, text, *, buttons=None):
        self.edits.append((chat_id, message_id, text, buttons))

    async def delete_messages(self, chat_id, message_ids):
        self.deletes.append((chat_id, tuple(message_ids)))

    async def send_message(self, chat_id, text, *, buttons=None):
        self.sent.append((chat_id, text, buttons))
        return SimpleNamespace(id=900 + len(self.sent))


class FakeEvent:
    def __init__(
        self,
        *,
        sender_id=10,
        chat_id=20,
        is_private=True,
        message_id=1,
        filename=None,
        size=0,
        width=None,
        height=None,
        duration=None,
        text=None,
        caption=None,
        photo=False,
        data=None,
    ) -> None:
        self.sender_id = sender_id
        self.chat_id = chat_id
        self.is_private = is_private
        self.data = data.encode() if isinstance(data, str) else data
        file = (
            SimpleNamespace(
                name=filename,
                size=size,
                width=width,
                height=height,
                duration=duration,
            )
            if filename
            else None
        )
        self.message = SimpleNamespace(
            id=message_id,
            file=file,
            photo=object() if photo else None,
            raw_text=caption or text or "",
            text=text or caption or "",
        )
        self.responses = []
        self.answers = 0
        self.edits = []

    async def respond(self, text, *, buttons=None):
        self.responses.append((text, buttons))
        return SimpleNamespace(id=800 + len(self.responses))

    async def answer(self):
        self.answers += 1

    async def edit(self, text, *, buttons=None):
        self.edits.append((text, buttons))


def _handlers(service=None):
    service = service or ServiceStub()
    client = FakeClient()
    return (
        TelegramHandlers(
            service,
            client,
            (10,),
            (".mkv",),
            taskflow_webui_url="https://taskflow.redprimrose.mov/ui/telegram-ui/",
            refresh_seconds=30,
        ),
        service,
        client,
    )


@pytest.mark.asyncio
async def test_receives_large_video_without_bot_api_file_identifiers() -> None:
    handlers, service, _ = _handlers()
    event = FakeEvent(
        filename="episode.mkv",
        size=5_000_000_000,
        width=1920,
        height=816,
        duration=3319.92,
    )

    await handlers.handle_message(event)

    payload = service.calls[0][1]
    assert payload == {
        "chat_id": 20,
        "user_id": 10,
        "message_id": 1,
        "filename": "episode.mkv",
        "expected_size": 5_000_000_000,
        "metadata": VideoMetadata(1920, 816, 3319.92),
        "caption": "",
    }


@pytest.mark.asyncio
async def test_ignores_unauthorized_users_and_non_private_chats() -> None:
    handlers, service, _ = _handlers()

    await handlers.handle_message(FakeEvent(sender_id=11, filename="x.mkv"))
    await handlers.handle_message(FakeEvent(is_private=False, filename="x.mkv"))

    assert service.calls == []


@pytest.mark.asyncio
async def test_descriptor_is_retained_without_downloading_photo() -> None:
    handlers, service, _ = _handlers()

    await handlers.handle_message(
        FakeEvent(message_id=9, caption="Cape Fear (2025)", photo=True)
    )

    assert service.calls == [("descriptor", (20, 10, 9, "Cape Fear (2025)"))]


@pytest.mark.asyncio
async def test_status_updates_edit_one_existing_message() -> None:
    handlers, service, client = _handlers()
    first = FakeEvent(filename="one.mkv", size=5)
    second = FakeEvent(message_id=2, filename="two.mkv", size=5)

    await handlers.handle_message(first)
    await handlers.handle_message(second)
    await service.listeners[0](service.session)

    assert len(client.sent) == 1
    assert len(client.edits) == 2
    assert client.edits[-1][1] == 901


@pytest.mark.asyncio
async def test_new_session_sends_a_new_status_message_for_the_same_user() -> None:
    handlers, service, client = _handlers()

    await handlers.handle_message(FakeEvent(filename="one.mkv", size=5))
    first_session = service.session
    service.session = ImportSession("def456", 20, 10, SessionState.COLLECTING)
    await handlers.handle_message(
        FakeEvent(message_id=2, filename="two.mkv", size=5)
    )
    second_session = service.session

    await service.listeners[0](first_session)
    await service.listeners[0](second_session)

    assert len(client.sent) == 2
    assert "Sessione abc123" in client.sent[0][1]
    assert "Sessione def456" in client.sent[1][1]
    assert [edit[1] for edit in client.edits] == [901, 902]


@pytest.mark.asyncio
async def test_metadata_edit_creates_new_sequential_status_panel() -> None:
    handlers, service, client = _handlers()
    service.session = replace(service.session, state=SessionState.SEALED)
    handlers._editing[10] = "abc123"
    handlers._status_messages["abc123"] = (20, 700)

    await handlers.handle_message(FakeEvent(text="Cape Fear | 2025"))

    assert service.calls[-1] == ("edit", "abc123", 10, "Cape Fear", 2025)
    assert client.deletes == [(20, (700,))]
    assert client.sent[0][1] == "Titolo e anno aggiornati."
    assert "Titolo: Cape Fear (2025)" in client.sent[1][1]


@pytest.mark.asyncio
async def test_taskflow_command_opens_configured_mobile_webui() -> None:
    handlers, _, client = _handlers()

    await handlers.handle_message(FakeEvent(text="/taskflow"))

    assert client.sent[0][1] == "Apri TaskFlow dal telefono."
    assert client.sent[0][2]


@pytest.mark.asyncio
async def test_quick_branch_asks_kind_then_searches_tmdb_without_downloading() -> None:
    handlers, service, client = _handlers()
    service.session = replace(service.session, state=SessionState.SEALED)

    await handlers.handle_callback(FakeEvent(data="quick:abc123"))
    await handlers.handle_callback(FakeEvent(data="kind:abc123:tv"))
    await handlers.handle_callback(FakeEvent(data="query:abc123"))
    await handlers.handle_message(FakeEvent(text="Cape Fear | 2025"))

    assert ("quick", "abc123", 10) in service.calls
    assert ("kind", "abc123", 10, "tv") in service.calls
    assert ("search", "abc123", 10, "Cape Fear", 2025) in service.calls
    assert any(item[1] == "Invia: Titolo | Anno" for item in client.sent)


@pytest.mark.asyncio
async def test_tmdb_no_candidates_is_not_reported_as_invalid_input_format() -> None:
    service = ServiceStub()

    async def search_without_candidates(session_id, user_id, title, year):
        raise ImporterError("TMDB search returned no candidates")

    service.search_quick = search_without_candidates
    handlers, _, client = _handlers(service)
    handlers._editing[10] = ("quick-query", "abc123")

    await handlers.handle_message(
        FakeEvent(text="Nanuq: An Arctic Journey from Past to Future | 2020")
    )

    assert client.sent[-1][1] == "Nessun match TMDB trovato."


@pytest.mark.asyncio
async def test_delete_requires_explicit_confirmation() -> None:
    handlers, service, _ = _handlers()

    await handlers.handle_callback(FakeEvent(data="delete-request:abc123"))
    assert not any(call[0] == "delete" for call in service.calls)

    event = FakeEvent(data="delete-confirm:abc123")
    await handlers.handle_callback(event)

    assert ("delete", "abc123", 10) in service.calls
    assert event.edits[0][0] == "Sessione eliminata."


@pytest.mark.asyncio
async def test_confirmed_delete_clears_pending_text_input_for_next_session() -> None:
    handlers, service, client = _handlers()
    handlers._editing[10] = ("quick-query", "abc123")

    await handlers.handle_callback(FakeEvent(data="delete-confirm:abc123"))
    service.session = ImportSession("def456", 20, 10, SessionState.COLLECTING)
    await handlers.handle_message(
        FakeEvent(
            message_id=2,
            filename="next.mkv",
            size=100,
            caption="Nanuq: An Arctic Journey from Past to Future (2020)",
        )
    )

    assert 10 not in handlers._editing
    assert service.calls[-1][0] == "video"
    assert all(message != "Formato non valido. Usa: Titolo | Anno" for _, message, _ in client.sent)


@pytest.mark.asyncio
async def test_confirmed_delete_removes_only_the_selected_session_monitor() -> None:
    handlers, _, _ = _handlers()
    handlers._status_messages["abc123"] = (20, 700)
    handlers._status_messages["def456"] = (20, 701)

    await handlers.handle_callback(FakeEvent(data="delete-confirm:abc123"))

    assert "abc123" not in handlers._status_messages
    assert handlers._status_messages["def456"] == (20, 701)
