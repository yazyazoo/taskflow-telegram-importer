from __future__ import annotations

import asyncio
from dataclasses import replace
from typing import Awaitable, Callable

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


class DownloadCoordinator:
    def __init__(
        self,
        repository: SessionRepository,
        publisher: FilesystemPublisher,
        source: TelegramFileSource,
        blocking_runner: Callable[..., Awaitable] = asyncio.to_thread,
    ) -> None:
        self._repository = repository
        self._publisher = publisher
        self._source = source
        self._blocking_runner = blocking_runner
        self._tasks: dict[tuple[str, int], asyncio.Task[None]] = {}
        self._locks: dict[str, asyncio.Lock] = {}

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

    def retry(self, session_id: str, message_id: int) -> None:
        session = self._repository.load(session_id)
        file = _find_file(session, message_id)
        if file.state is not FileState.FAILED:
            raise ImporterError("only failed files can be retried")
        reset = replace(file, state=FileState.RECEIVED, error=None, staging_path=None)
        self._repository.save(_replace_file(session, reset))
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

    def recover(self) -> None:
        for session in self._repository.list_all():
            if session.state is SessionState.PUBLISHED:
                continue
            for file in session.files:
                if file.state in {FileState.RECEIVED, FileState.DOWNLOADING}:
                    self.start(session.session_id, file)

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
        try:
            file = await self._transition(session_id, message_id, FileState.DOWNLOADING)
            source_path = await self._source.get_local_file(file.file_id)
            staged_path = await self._blocking_runner(
                self._publisher.prepare_file,
                session_id,
                file.filename,
                source_path,
                file.expected_size,
            )
            await self._transition(
                session_id,
                message_id,
                FileState.COMPLETE,
                staging_path=staged_path,
                error=None,
            )
        except asyncio.CancelledError:
            try:
                await self._transition(
                    session_id,
                    message_id,
                    FileState.RECEIVED,
                    staging_path=None,
                    error=None,
                )
            except ImporterError:
                pass
            raise
        except Exception as exc:
            await self._transition(
                session_id,
                message_id,
                FileState.FAILED,
                staging_path=None,
                error=f"{type(exc).__name__}: {exc}",
            )

    async def _transition(
        self,
        session_id: str,
        message_id: int,
        state: FileState,
        *,
        staging_path=None,
        error: str | None = None,
    ) -> ImportFile:
        async with self._lock(session_id):
            session = self._repository.load(session_id)
            current = _find_file(session, message_id)
            updated = replace(
                current, state=state, staging_path=staging_path, error=error
            )
            self._repository.save(_replace_file(session, updated))
            return updated

    def _lock(self, session_id: str) -> asyncio.Lock:
        return self._locks.setdefault(session_id, asyncio.Lock())

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
