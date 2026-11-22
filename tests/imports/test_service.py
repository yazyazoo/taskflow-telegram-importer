from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import logging

import pytest

from taskflow_telegram_importer.imports import ImportService
from taskflow_telegram_importer.publisher import FilesystemPublisher
from taskflow_telegram_importer.sessions import (
    FileState,
    ImportSession,
    SessionRepository,
    SessionState,
)


class CoordinatorStub:
    def __init__(self) -> None:
        self.started: list[tuple[str, int]] = []
        self.retried: list[tuple[str, int]] = []
        self.excluded: list[tuple[str, int]] = []
        self.deleted: list[str] = []

    def start(self, session_id, file) -> None:
        self.started.append((session_id, file.message_id))

    def retry(self, session_id, message_id) -> None:
        self.retried.append((session_id, message_id))

    async def exclude(self, session_id, message_id) -> None:
        self.excluded.append((session_id, message_id))

    async def cancel_session(self, session_id) -> None:
        self.deleted.append(session_id)


def _service(tmp_path: Path):
    repository = SessionRepository(tmp_path / "manifests")
    publisher = FilesystemPublisher(tmp_path / "staging", tmp_path / "gate", 0)
    coordinator = CoordinatorStub()
    ids = iter(("session-one", "session-two", "session-three"))
    service = ImportService(repository, coordinator, publisher, id_factory=lambda: next(ids))
    return service, repository, publisher, coordinator


def _receive(service: ImportService, message_id: int = 1):
    return service.receive_video(
        chat_id=20,
        user_id=10,
        message_id=message_id,
        file_id=f"file-{message_id}",
        file_unique_id=f"unique-{message_id}",
        filename=f"episode-{message_id}.mkv",
        expected_size=5,
        caption="Cape Fear (2025)" if message_id == 1 else None,
    )


def test_descriptor_is_optional_and_caption_is_retained_without_photo(tmp_path: Path) -> None:
    service, repository, _, _ = _service(tmp_path)

    snapshot = service.receive_descriptor(20, 10, 90, "Cape Fear (2025)")

    session = repository.load(snapshot.session_id)
    assert session.files == ()
    assert session.captions == ("Cape Fear (2025)",)
    assert session.descriptor_message_ids == (90,)


def test_received_files_share_one_collecting_session_and_start_immediately(
    tmp_path: Path,
) -> None:
    service, repository, _, coordinator = _service(tmp_path)

    first = _receive(service, 1)
    second = _receive(service, 2)
    duplicate = _receive(service, 2)

    assert first.session_id == second.session_id == duplicate.session_id
    assert len(repository.load(first.session_id).files) == 2
    assert coordinator.started == [(first.session_id, 1), (first.session_id, 2)]


def test_session_milestones_are_logged(tmp_path: Path, caplog) -> None:
    service, _, _, _ = _service(tmp_path)
    caplog.set_level(logging.INFO, logger="taskflow_telegram_importer.imports")

    _receive(service, 1)

    assert "received video session=session-one message=1" in caplog.text


def test_finish_is_explicit_and_opens_next_collection_while_downloads_continue(
    tmp_path: Path,
) -> None:
    service, repository, _, _ = _service(tmp_path)
    first = _receive(service)

    sealed = service.finish_collection(user_id=10)
    next_session = service.receive_descriptor(20, 10, 99, "Next (2026)")

    assert sealed.state is SessionState.SEALED
    assert sealed.editorial_hint.title == "Cape Fear"
    assert next_session.session_id != first.session_id
    assert repository.load(first.session_id).state is SessionState.SEALED


def test_duplicate_update_from_sealed_session_is_not_added_or_downloaded_again(
    tmp_path: Path,
) -> None:
    service, repository, _, coordinator = _service(tmp_path)
    first = _receive(service, 1)
    service.finish_collection(10)

    duplicate = _receive(service, 1)

    assert duplicate.session_id == first.session_id
    assert len(repository.list_all()) == 1
    assert coordinator.started == [(first.session_id, 1)]


def test_edit_then_confirm_metadata_does_not_publish_incomplete_files(
    tmp_path: Path,
) -> None:
    service, repository, publisher, _ = _service(tmp_path)
    snapshot = _receive(service)
    service.finish_collection(10)

    edited = service.edit_metadata(snapshot.session_id, 10, "Cape Fear Edited", 2025)
    confirmed = service.confirm_metadata(snapshot.session_id, 10)

    assert edited.editorial_hint.title == "Cape Fear Edited"
    assert confirmed.metadata_confirmed is True
    assert confirmed.state is SessionState.SEALED
    assert not list(publisher.gate.glob("*"))


def test_reconcile_publishes_after_every_file_is_complete(tmp_path: Path) -> None:
    service, repository, publisher, _ = _service(tmp_path)
    snapshot = _receive(service)
    service.finish_collection(10)
    service.confirm_metadata(snapshot.session_id, 10)
    staged = publisher.staging / snapshot.session_id / "episode-1.mkv"
    staged.parent.mkdir(parents=True, exist_ok=True)
    staged.write_bytes(b"video")
    session = repository.load(snapshot.session_id)
    complete = replace(session.files[0], state=FileState.COMPLETE, staging_path=staged)
    repository.save(replace(session, files=(complete,)))

    published = service.reconcile(snapshot.session_id)

    assert published.state is SessionState.PUBLISHED
    assert published.published_paths == (publisher.gate / "episode-1.mkv",)
    assert published.published_paths[0].read_bytes() == b"video"


def test_reconcile_recovers_commit_lost_after_atomic_rename(tmp_path: Path) -> None:
    service, repository, publisher, _ = _service(tmp_path)
    snapshot = _receive(service)
    service.finish_collection(10)
    service.confirm_metadata(snapshot.session_id, 10)
    staged = publisher.staging / snapshot.session_id / "episode-1.mkv"
    staged.parent.mkdir(parents=True, exist_ok=True)
    staged.write_bytes(b"video")
    session = repository.load(snapshot.session_id)
    complete = replace(session.files[0], state=FileState.COMPLETE, staging_path=staged)
    publishing = replace(
        session,
        state=SessionState.PUBLISHING,
        files=(complete,),
        published_paths=(publisher.gate / "episode-1.mkv",),
    )
    repository.save(publishing)
    publisher.publish(publishing)

    recovered = service.reconcile(snapshot.session_id)

    assert recovered.state is SessionState.PUBLISHED
    assert recovered.published_paths[0].read_bytes() == b"video"


@pytest.mark.asyncio
async def test_terminal_change_notifies_registered_listener(tmp_path: Path) -> None:
    service, _, _, _ = _service(tmp_path)
    snapshot = _receive(service)
    seen = []

    async def listener(session):
        seen.append(session.session_id)

    service.add_listener(listener)
    await service.file_terminal(snapshot.session_id)

    assert seen == [snapshot.session_id]


@pytest.mark.asyncio
async def test_retry_exclude_and_delete_delegate_to_coordinator(tmp_path: Path) -> None:
    service, _, _, coordinator = _service(tmp_path)
    snapshot = _receive(service)

    service.retry_file(snapshot.session_id, 10, 1)
    await service.exclude_file(snapshot.session_id, 10, 1)
    await service.delete_session(snapshot.session_id, 10)

    assert coordinator.retried == [(snapshot.session_id, 1)]
    assert coordinator.excluded == [(snapshot.session_id, 1)]
    assert coordinator.deleted == [snapshot.session_id]
