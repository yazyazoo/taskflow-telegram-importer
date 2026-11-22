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
        self.calls: list[str] = []
        self.futures: dict[str, asyncio.Future[Path]] = {}

    async def get_local_file(self, file_id: str) -> Path:
        self.calls.append(file_id)
        future = self.futures.setdefault(file_id, asyncio.get_running_loop().create_future())
        return await future

    def succeed(self, file_id: str, path: Path) -> None:
        self.futures[file_id].set_result(path)

    def fail(self, file_id: str) -> None:
        self.futures[file_id].set_exception(RuntimeError("Telegram failed"))


class ImmediatePublisher(FilesystemPublisher):
    def prepare_file(
        self, session_id: str, filename: str, source: Path, expected_size: int
    ) -> Path:
        target = self.staging / session_id / filename
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())
        return target


def _file(index: int, state: FileState = FileState.RECEIVED) -> ImportFile:
    return ImportFile(
        message_id=100 + index,
        file_id=f"file-{index}",
        file_unique_id=f"unique-{index}",
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


def _setup(tmp_path: Path):
    repository = SessionRepository(tmp_path / "manifests")
    publisher = ImmediatePublisher(tmp_path / "staging", tmp_path / "gate", 0)
    source = ControlledSource()
    async def run_direct(function, *args):
        return function(*args)

    coordinator = DownloadCoordinator(
        repository, publisher, source, blocking_runner=run_direct
    )
    return repository, publisher, source, coordinator


async def _until(predicate, timeout: float = 1.0) -> None:
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_starts_ten_files_before_any_download_completes(tmp_path: Path) -> None:
    repository, _, source, coordinator = _setup(tmp_path)
    files = tuple(_file(index) for index in range(10))
    repository.create(_session("one", files))

    for item in files:
        coordinator.start("one", item)
    await _until(lambda: len(source.calls) == 10)

    assert len(coordinator.active_keys) == 10
    assert all(not future.done() for future in source.futures.values())

    sources = tmp_path / "sources"
    sources.mkdir()
    for item in files:
        path = sources / item.filename
        path.write_bytes(b"content")
        source.succeed(item.file_id, path)
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

    assert source.calls == ["file-1"]
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
    success_path = tmp_path / "success.mkv"
    success_path.write_bytes(b"content")
    source.fail(failed.file_id)
    source.succeed(successful.file_id, success_path)
    await coordinator.wait_idle()

    assert repository.load("one").files[0].state is FileState.FAILED
    assert repository.load("two").files[0].state is FileState.COMPLETE

    source.futures.pop(failed.file_id)
    retry_path = tmp_path / "retry.mkv"
    retry_path.write_bytes(b"content")
    coordinator.retry("one", failed.message_id)
    await _until(lambda: source.calls.count(failed.file_id) == 2)
    source.succeed(failed.file_id, retry_path)
    await coordinator.wait_idle()

    assert repository.load("one").files[0].state is FileState.COMPLETE
    assert source.calls.count(successful.file_id) == 1


@pytest.mark.asyncio
async def test_excludes_failed_file_without_touching_other_files(tmp_path: Path) -> None:
    repository, _, source, coordinator = _setup(tmp_path)
    first, second = _file(1), _file(2)
    repository.create(_session("one", (first, second)))
    coordinator.start("one", first)
    await _until(lambda: len(source.calls) == 1)
    source.fail(first.file_id)
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
async def test_recovery_restarts_only_incomplete_unpublished_files(tmp_path: Path) -> None:
    repository, _, source, coordinator = _setup(tmp_path)
    complete_path = tmp_path / "already.mkv"
    complete_path.write_bytes(b"content")
    complete = replace(_file(1, FileState.COMPLETE), staging_path=complete_path)
    incomplete = _file(2, FileState.DOWNLOADING)
    failed = _file(3, FileState.FAILED)
    repository.create(_session("one", (complete, incomplete, failed), SessionState.SEALED))
    repository.create(_session("two", (_file(4),), SessionState.PUBLISHED))

    coordinator.recover()
    await _until(lambda: len(source.calls) == 1)

    assert source.calls == [incomplete.file_id]
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
