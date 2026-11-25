from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path

import pytest

from taskflow_telegram_importer.downloads import DownloadCoordinator
from taskflow_telegram_importer.publisher import FilesystemPublisher
from taskflow_telegram_importer.sessions import (
    FileState,
    ImportFile,
    ImportSession,
    SessionRepository,
    SessionState,
)


class ControlledSource:
    def __init__(self) -> None:
        self.calls: list[int] = []
        self.futures: dict[int, asyncio.Future[bytes]] = {}

    async def download(self, chat_id, message_id, target, progress_callback) -> Path:
        self.calls.append(message_id)
        future = self.futures.setdefault(
            message_id, asyncio.get_running_loop().create_future()
        )
        content = await future
        midpoint = len(content) // 2
        await progress_callback(midpoint, len(content))
        target.write_bytes(content)
        await progress_callback(len(content), len(content))
        return target

    def succeed(self, message_id: int, content: bytes = b"content") -> None:
        self.futures[message_id].set_result(content)

    def fail(self, message_id: int) -> None:
        self.futures[message_id].set_exception(RuntimeError("Telegram failed"))


class PartialFailureSource(ControlledSource):
    async def download(self, chat_id, message_id, target, progress_callback) -> Path:
        self.calls.append(message_id)
        target.write_bytes(b"part")
        await progress_callback(4, 7)
        future = self.futures.setdefault(
            message_id, asyncio.get_running_loop().create_future()
        )
        content = await future
        target.write_bytes(content)
        await progress_callback(len(content), len(content))
        return target


def _file(index: int, state: FileState = FileState.RECEIVED) -> ImportFile:
    return ImportFile(
        message_id=100 + index,
        filename=f"episode-{index}.mkv",
        expected_size=7,
        state=state,
    )


def _session(
    session_id: str, files: tuple[ImportFile, ...], state: SessionState = SessionState.COLLECTING
) -> ImportSession:
    return ImportSession(
        session_id=session_id,
        chat_id=20,
        user_id=10 if session_id == "one" else 11,
        state=state,
        files=files,
    )


def _setup(tmp_path: Path, *, max_concurrent_downloads: int = 2):
    repository = SessionRepository(tmp_path / "manifests")
    publisher = FilesystemPublisher(tmp_path / "staging", tmp_path / "gate", 0)
    source = ControlledSource()
    coordinator = DownloadCoordinator(
        repository,
        publisher,
        source,
        max_concurrent_downloads=max_concurrent_downloads,
        progress_refresh_seconds=30,
    )
    return repository, publisher, source, coordinator


async def _until(predicate, timeout: float = 1.0) -> None:
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_limits_active_downloads_and_starts_queued_files_as_slots_open(
    tmp_path: Path,
) -> None:
    repository, _, source, coordinator = _setup(tmp_path)
    files = tuple(_file(index) for index in range(10))
    repository.create(_session("one", files))

    for item in files:
        coordinator.start("one", item)
    await _until(lambda: len(source.calls) == 2)

    assert len(coordinator.active_keys) == 10
    assert source.calls == [100, 101]
    assert all(not future.done() for future in source.futures.values())

    for index, item in enumerate(files):
        if item.message_id not in source.futures:
            await _until(lambda index=index: len(source.calls) > index)
        source.succeed(item.message_id)
        if index + 2 < len(files):
            await _until(lambda index=index: len(source.calls) >= index + 3)
    await asyncio.wait_for(coordinator.wait_idle(), timeout=3)

    assert all(item.state is FileState.COMPLETE for item in repository.load("one").files)


@pytest.mark.asyncio
async def test_duplicate_start_does_not_download_message_twice(tmp_path: Path) -> None:
    repository, _, source, coordinator = _setup(tmp_path)
    item = _file(1)
    repository.create(_session("one", (item,)))

    coordinator.start("one", item)
    coordinator.start("one", item)
    await _until(lambda: len(source.calls) == 1)

    assert source.calls == [101]
    await coordinator.shutdown()


@pytest.mark.asyncio
async def test_failure_is_isolated_and_retry_only_restarts_failed_file(tmp_path: Path) -> None:
    repository, _, source, coordinator = _setup(tmp_path)
    failed = _file(1)
    successful = _file(2)
    repository.create(_session("one", (failed,)))
    repository.create(_session("two", (successful,)))
    coordinator.start("one", failed)
    coordinator.start("two", successful)
    await _until(lambda: len(source.calls) == 2)
    source.fail(failed.message_id)
    source.succeed(successful.message_id)
    await coordinator.wait_idle()

    assert repository.load("one").files[0].state is FileState.FAILED
    assert repository.load("two").files[0].state is FileState.COMPLETE

    source.futures.pop(failed.message_id)
    coordinator.retry("one", failed.message_id)
    await _until(lambda: source.calls.count(failed.message_id) == 2)
    source.succeed(failed.message_id)
    await coordinator.wait_idle()

    assert repository.load("one").files[0].state is FileState.COMPLETE
    assert source.calls.count(successful.message_id) == 1


@pytest.mark.asyncio
async def test_failure_removes_partial_file_so_retry_can_restart(tmp_path: Path) -> None:
    repository = SessionRepository(tmp_path / "manifests")
    publisher = FilesystemPublisher(tmp_path / "staging", tmp_path / "gate", 0)
    source = PartialFailureSource()
    coordinator = DownloadCoordinator(
        repository,
        publisher,
        source,
        max_concurrent_downloads=2,
        progress_refresh_seconds=30,
    )
    item = _file(1)
    repository.create(_session("one", (item,)))
    coordinator.start("one", item)
    await _until(lambda: item.message_id in source.futures)
    source.fail(item.message_id)
    await coordinator.wait_idle()

    partial = publisher.staging / "one" / f".{item.filename}.part"
    assert repository.load("one").files[0].state is FileState.FAILED
    assert not partial.exists()

    source.futures.pop(item.message_id)
    coordinator.retry("one", item.message_id)
    await _until(lambda: source.calls.count(item.message_id) == 2)
    source.succeed(item.message_id)
    await coordinator.wait_idle()

    assert repository.load("one").files[0].state is FileState.COMPLETE


@pytest.mark.asyncio
async def test_excludes_failed_file_without_touching_other_files(tmp_path: Path) -> None:
    repository, _, source, coordinator = _setup(tmp_path)
    first, second = _file(1), _file(2)
    repository.create(_session("one", (first, second)))
    coordinator.start("one", first)
    await _until(lambda: len(source.calls) == 1)
    source.fail(first.message_id)
    await coordinator.wait_idle()

    await coordinator.exclude("one", first.message_id)

    session = repository.load("one")
    assert session.files[0].state is FileState.EXCLUDED
    assert session.files[1].state is FileState.RECEIVED


@pytest.mark.asyncio
async def test_cancel_waits_for_jobs_then_removes_session(tmp_path: Path) -> None:
    repository, publisher, source, coordinator = _setup(tmp_path)
    files = (_file(1), _file(2))
    repository.create(_session("one", files))
    for item in files:
        coordinator.start("one", item)
    await _until(lambda: len(source.calls) == 2)

    await coordinator.cancel_session("one")

    assert not coordinator.active_keys
    assert repository.list_all() == ()
    assert not (publisher.staging / "one").exists()


@pytest.mark.asyncio
async def test_cancel_interrupts_mtproto_download_and_removes_partial_file(tmp_path: Path) -> None:
    repository = SessionRepository(tmp_path / "manifests")
    publisher = FilesystemPublisher(tmp_path / "staging", tmp_path / "gate", 0)
    entered = asyncio.Event()

    class Source:
        async def download(self, chat_id, message_id, target, progress_callback):
            entered.set()
            await asyncio.Event().wait()
            target.write_bytes(b"content")
            return target

    item = _file(1)
    repository.create(_session("one", (item,)))
    coordinator = DownloadCoordinator(
        repository,
        publisher,
        Source(),
        max_concurrent_downloads=2,
        progress_refresh_seconds=30,
    )
    coordinator.start("one", item)
    await asyncio.wait_for(entered.wait(), 1)

    await asyncio.wait_for(coordinator.cancel_session("one"), 3)

    assert repository.list_all() == ()
    assert not (publisher.staging / "one" / item.filename).exists()
    assert not (publisher.staging / "one" / f".{item.filename}.part").exists()


@pytest.mark.asyncio
async def test_recovery_restarts_only_incomplete_unpublished_files(tmp_path: Path) -> None:
    repository, publisher, source, coordinator = _setup(tmp_path)
    complete_path = tmp_path / "already.mkv"
    complete_path.write_bytes(b"content")
    complete = replace(_file(1, FileState.COMPLETE), staging_path=complete_path)
    incomplete = _file(2, FileState.DOWNLOADING)
    failed = _file(3, FileState.FAILED)
    repository.create(replace(
        _session("one", (complete, incomplete, failed), SessionState.SEALED),
        metadata_confirmed=True,
    ))
    repository.create(_session("two", (_file(4),), SessionState.PUBLISHED))
    stale_directory = publisher.staging / "one"
    stale_directory.mkdir(parents=True)
    stale_partial = stale_directory / f".{incomplete.filename}.part"
    stale_partial.write_bytes(b"interrupted")

    coordinator.recover()
    await _until(lambda: len(source.calls) == 1)

    assert source.calls == [incomplete.message_id]
    assert not stale_partial.exists()
    await coordinator.shutdown()
    assert repository.load("one").files[1].state is FileState.RECEIVED


@pytest.mark.asyncio
async def test_shutdown_cancels_jobs_but_keeps_recoverable_manifests(tmp_path: Path) -> None:
    repository, _, source, coordinator = _setup(tmp_path)
    item = _file(1)
    repository.create(_session("one", (item,)))
    coordinator.start("one", item)
    await _until(lambda: len(source.calls) == 1)

    await coordinator.shutdown()

    assert not coordinator.active_keys
    assert repository.load("one").files[0].state is FileState.RECEIVED
