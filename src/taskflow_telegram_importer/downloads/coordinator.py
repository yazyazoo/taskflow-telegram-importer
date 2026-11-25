from __future__ import annotations

import asyncio
import inspect
import logging
import time
from dataclasses import replace
from typing import Callable

from taskflow_telegram_importer.errors import ImporterError
from taskflow_telegram_importer.publisher import FilesystemPublisher
from taskflow_telegram_importer.sessions import (
    FileState,
    ImportFile,
    ImportSession,
    SessionRepository,
    SessionState,
)

from .source import TelegramFileSource
from .progress import ProgressMeter

_LOGGER = logging.getLogger("taskflow_telegram_importer.downloads")


class DownloadCoordinator:
    def __init__(
        self,
        repository: SessionRepository,
        publisher: FilesystemPublisher,
        source: TelegramFileSource,
        max_concurrent_downloads: int,
        progress_refresh_seconds: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._repository = repository
        self._publisher = publisher
        self._source = source
        self._download_slots = asyncio.Semaphore(max_concurrent_downloads)
        self._progress_refresh_seconds = progress_refresh_seconds
        self._clock = clock
        self._tasks: dict[tuple[str, int], asyncio.Task[None]] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._change_callback = None

    @property
    def active_keys(self) -> frozenset[tuple[str, int]]:
        return frozenset(self._tasks)

    def start(self, session_id: str, file: ImportFile) -> None:
        key = (session_id, file.message_id)
        task = self._tasks.get(key)
        if task is not None and not task.done():
            return
        task = asyncio.create_task(
            self._download(session_id, file.message_id),
            name=f"telegram-download:{session_id}:{file.message_id}",
        )
        self._tasks[key] = task
        task.add_done_callback(lambda completed, key=key: self._discard(key, completed))

    def set_change_callback(self, callback) -> None:
        self._change_callback = callback

    def retry(self, session_id: str, message_id: int) -> None:
        session = self._repository.load(session_id)
        file = _find_file(session, message_id)
        if file.state is not FileState.FAILED:
            raise ImporterError("only failed files can be retried")
        reset = replace(
            file,
            state=FileState.RECEIVED,
            error=None,
            staging_path=None,
            downloaded_bytes=0,
            download_speed_bps=0.0,
            download_eta_seconds=None,
        )
        self._repository.save(_replace_file(session, reset))
        _LOGGER.info("retry requested session=%s message=%d", session_id, message_id)
        self.start(session_id, reset)

    async def exclude(self, session_id: str, message_id: int) -> None:
        key = (session_id, message_id)
        task = self._tasks.get(key)
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        async with self._lock(session_id):
            session = self._repository.load(session_id)
            file = _find_file(session, message_id)
            if file.state not in {FileState.FAILED, FileState.RECEIVED}:
                raise ImporterError("only failed or pending files can be excluded")
            if file.staging_path is not None:
                self._publisher.delete_owned_paths(replace(session, files=(file,), published_paths=()))
            excluded = replace(file, state=FileState.EXCLUDED, staging_path=None, error=None)
            self._repository.save(_replace_file(session, excluded))
            _LOGGER.info("file excluded session=%s message=%d", session_id, message_id)

    async def cancel_session(self, session_id: str) -> None:
        tasks = [
            task for (current_id, _), task in self._tasks.items() if current_id == session_id
        ]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        try:
            session = self._repository.load(session_id)
        except ImporterError:
            return
        self._publisher.delete_owned_paths(session)
        session_directory = self._publisher.staging / session_id
        try:
            session_directory.rmdir()
        except OSError:
            pass
        self._repository.delete_manifest(session_id)
        _LOGGER.info("session deleted session=%s", session_id)

    def recover(self) -> None:
        recovered = 0
        for session in self._repository.list_all():
            if session.state is SessionState.PUBLISHED or not session.metadata_confirmed:
                continue
            for file in session.files:
                if file.state in {FileState.RECEIVED, FileState.DOWNLOADING}:
                    self._publisher.discard_incomplete_download(
                        session.session_id, file.filename
                    )
                    self.start(session.session_id, file)
                    recovered += 1
        if recovered:
            _LOGGER.warning("recovered incomplete downloads count=%d", recovered)

    async def wait_idle(self, session_id: str | None = None) -> None:
        while True:
            tasks = [
                task
                for (current_id, _), task in self._tasks.items()
                if session_id is None or current_id == session_id
            ]
            if not tasks:
                return
            await asyncio.gather(*tasks, return_exceptions=True)
            for key, task in tuple(self._tasks.items()):
                if task.done():
                    self._tasks.pop(key, None)

    async def shutdown(self) -> None:
        tasks = list(self._tasks.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _download(self, session_id: str, message_id: int) -> None:
        target = None
        staged_path = None
        try:
            async with self._download_slots:
                file = await self._transition(
                    session_id, message_id, FileState.DOWNLOADING
                )
                await self._notify_change(session_id)
                session = self._repository.load(session_id)
                target = self._publisher.prepare_download(
                    session_id, file.filename, file.expected_size
                )
                started_at = self._clock()
                meter = ProgressMeter(started_at=started_at)
                last_reported_at = started_at - self._progress_refresh_seconds

                async def report_progress(current: int, total: int) -> None:
                    nonlocal last_reported_at
                    now = self._clock()
                    if (
                        current < total
                        and now - last_reported_at < self._progress_refresh_seconds
                    ):
                        return
                    last_reported_at = now
                    snapshot = meter.snapshot(current=current, total=total, now=now)
                    await self._progress(session_id, message_id, snapshot)
                    await self._notify_change(session_id)

                await self._source.download(
                    session.chat_id,
                    message_id,
                    target.temporary,
                    report_progress,
                )
                staged_path = self._publisher.finalize_download(
                    target, file.expected_size
                )
                await self._transition(
                    session_id,
                    message_id,
                    FileState.COMPLETE,
                    staging_path=staged_path,
                    error=None,
                    downloaded_bytes=file.expected_size,
                    download_eta_seconds=0,
                )
                await self._notify_change(session_id)
                _LOGGER.info(
                    "download complete session=%s message=%d", session_id, message_id
                )
        except asyncio.CancelledError:
            if target is not None:
                self._publisher.discard_staged(session_id, target.temporary)
                self._publisher.discard_staged(session_id, target.final)
            try:
                await self._transition(
                    session_id,
                    message_id,
                    FileState.RECEIVED,
                    staging_path=None,
                    error=None,
                    downloaded_bytes=0,
                    download_speed_bps=0.0,
                    download_eta_seconds=None,
                )
            except ImporterError:
                pass
            raise
        except Exception as exc:
            if target is not None:
                self._publisher.discard_staged(session_id, target.temporary)
                self._publisher.discard_staged(session_id, target.final)
            _LOGGER.error(
                "download failed session=%s message=%d component=%s",
                session_id,
                message_id,
                type(exc).__name__,
            )
            await self._transition(
                session_id,
                message_id,
                FileState.FAILED,
                staging_path=None,
                error=f"{type(exc).__name__}: {exc}",
                download_speed_bps=0.0,
                download_eta_seconds=None,
            )
            await self._notify_change(session_id)

    async def _transition(
        self,
        session_id: str,
        message_id: int,
        state: FileState,
        *,
        staging_path=None,
        error: str | None = None,
        downloaded_bytes: int | None = None,
        download_speed_bps: float | None = None,
        download_eta_seconds: int | None = None,
    ) -> ImportFile:
        async with self._lock(session_id):
            session = self._repository.load(session_id)
            current = _find_file(session, message_id)
            changes = {"state": state, "staging_path": staging_path, "error": error}
            if downloaded_bytes is not None:
                changes["downloaded_bytes"] = downloaded_bytes
            if download_speed_bps is not None:
                changes["download_speed_bps"] = download_speed_bps
            changes["download_eta_seconds"] = download_eta_seconds
            updated = replace(current, **changes)
            self._repository.save(_replace_file(session, updated))
            return updated

    async def _progress(self, session_id, message_id, snapshot) -> None:
        async with self._lock(session_id):
            session = self._repository.load(session_id)
            current = _find_file(session, message_id)
            updated = replace(
                current,
                downloaded_bytes=snapshot.downloaded_bytes,
                download_speed_bps=snapshot.bytes_per_second,
                download_eta_seconds=snapshot.eta_seconds,
            )
            self._repository.save(_replace_file(session, updated))

    def _lock(self, session_id: str) -> asyncio.Lock:
        return self._locks.setdefault(session_id, asyncio.Lock())

    async def _notify_change(self, session_id: str) -> None:
        if self._change_callback is None:
            return
        try:
            result = self._change_callback(session_id)
            if inspect.isawaitable(result):
                await result
        except Exception as exc:
            _LOGGER.error(
                "terminal reconciliation failed session=%s component=%s",
                session_id,
                type(exc).__name__,
            )

    def _discard(
        self, key: tuple[str, int], completed: asyncio.Task[None]
    ) -> None:
        if self._tasks.get(key) is completed:
            self._tasks.pop(key, None)


def _find_file(session: ImportSession, message_id: int) -> ImportFile:
    for file in session.files:
        if file.message_id == message_id:
            return file
    raise ImporterError(f"session has no file for message {message_id}")


def _replace_file(session: ImportSession, updated: ImportFile) -> ImportSession:
    return replace(
        session,
        files=tuple(
            updated if file.message_id == updated.message_id else file
            for file in session.files
        ),
    )
