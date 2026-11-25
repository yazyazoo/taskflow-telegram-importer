from __future__ import annotations

import uuid
import inspect
import logging
from dataclasses import replace
from typing import Callable

from taskflow_telegram_importer.downloads import DownloadCoordinator
from taskflow_telegram_importer.errors import ImporterError
from taskflow_telegram_importer.publisher import FilesystemPublisher
from taskflow_telegram_importer.processors import ContentProcessor
from taskflow_telegram_importer.sessions import (
    EditorialHint,
    FileState,
    ImportFile,
    ImportSession,
    SessionRepository,
    SessionState,
    parse_editorial_hint,
)

_LOGGER = logging.getLogger("taskflow_telegram_importer.imports")


class ImportService:
    def __init__(
        self,
        repository: SessionRepository,
        coordinator: DownloadCoordinator,
        publisher: FilesystemPublisher,
        *,
        id_factory: Callable[[], str] | None = None,
        processor: ContentProcessor | None = None,
    ) -> None:
        self._repository = repository
        self._coordinator = coordinator
        self._publisher = publisher
        self._id_factory = id_factory or (lambda: uuid.uuid4().hex)
        self._processor = processor
        self._listeners = []

    def receive_descriptor(
        self, chat_id: int, user_id: int, message_id: int, caption: str | None
    ) -> ImportSession:
        existing = self._find_message(chat_id, message_id)
        if existing is not None:
            return existing
        session = self._collecting_or_create(chat_id, user_id)
        if message_id in session.descriptor_message_ids:
            return session
        captions = session.captions + ((caption,) if caption and caption.strip() else ())
        session = replace(
            session,
            captions=captions,
            descriptor_message_ids=session.descriptor_message_ids + (message_id,),
        )
        self._repository.save(session)
        return session

    def receive_video(
        self,
        *,
        chat_id: int,
        user_id: int,
        message_id: int,
        filename: str,
        expected_size: int,
        caption: str | None = None,
    ) -> ImportSession:
        existing = self._find_message(chat_id, message_id)
        if existing is not None:
            return existing
        session = self._collecting_or_create(chat_id, user_id)
        if any(file.message_id == message_id for file in session.files):
            return session
        file = ImportFile(
            message_id=message_id,
            filename=filename,
            expected_size=expected_size,
            state=FileState.RECEIVED,
        )
        captions = session.captions + ((caption,) if caption and caption.strip() else ())
        session = replace(session, files=session.files + (file,), captions=captions)
        self._repository.save(session)
        self._coordinator.start(session.session_id, file)
        _LOGGER.info("received video session=%s message=%d", session.session_id, message_id)
        return session

    def finish_collection(self, user_id: int) -> ImportSession:
        session = self._collecting_for(user_id)
        if session is None:
            raise ImporterError("operator has no collecting session")
        if not session.files:
            raise ImporterError("cannot finish an empty session")
        hint = parse_editorial_hint(
            session.captions, tuple(file.filename for file in session.files)
        )
        session = replace(session, state=SessionState.SEALED, editorial_hint=hint)
        self._repository.save(session)
        return session

    def edit_metadata(
        self, session_id: str, user_id: int, title: str, year: int
    ) -> ImportSession:
        session = self._owned(session_id, user_id)
        title = title.strip()
        if not title or not 1000 <= year <= 9999:
            raise ImporterError("title and four-digit year are required")
        session = replace(
            session,
            editorial_hint=EditorialHint(title, year),
            metadata_confirmed=False,
        )
        self._repository.save(session)
        return session

    def confirm_metadata(
        self,
        session_id: str,
        user_id: int,
        title: str | None = None,
        year: int | None = None,
    ) -> ImportSession:
        if title is not None or year is not None:
            if title is None or year is None:
                raise ImporterError("title and year must be supplied together")
            self.edit_metadata(session_id, user_id, title, year)
        session = self._owned(session_id, user_id)
        if session.state is not SessionState.SEALED or session.editorial_hint is None:
            raise ImporterError("sealed session needs valid title and year")
        session = replace(session, metadata_confirmed=True)
        self._repository.save(session)
        return self.reconcile(session_id)

    def reconcile(self, session_id: str) -> ImportSession:
        session = self._repository.load(session_id)
        if session.state is SessionState.PUBLISHING:
            return self._finish_publication(session)
        included = tuple(
            file for file in session.files if file.state is not FileState.EXCLUDED
        )
        if (
            session.state is not SessionState.SEALED
            or not session.metadata_confirmed
            or not included
            or any(file.state is not FileState.COMPLETE for file in included)
        ):
            return session
        staged_paths = tuple(file.staging_path for file in included if file.staging_path)
        if self._processor is not None:
            self._processor.process(staged_paths)
        planned_paths = self._publisher.plan_publication(session)
        session = replace(
            session,
            state=SessionState.PUBLISHING,
            published_paths=planned_paths,
        )
        self._repository.save(session)
        return self._finish_publication(session)

    def _finish_publication(self, session: ImportSession) -> ImportSession:
        published_paths = self._publisher.publish(session)
        published_files = tuple(
            replace(file, state=FileState.PUBLISHED)
            if file.state is FileState.COMPLETE
            else file
            for file in session.files
        )
        session = replace(
            session,
            state=SessionState.PUBLISHED,
            files=published_files,
            published_paths=published_paths,
        )
        self._repository.save(session)
        _LOGGER.info("session published session=%s files=%d", session.session_id, len(published_paths))
        return session

    def recover(self) -> None:
        for session in self._repository.list_all():
            if session.state is SessionState.PUBLISHING or (
                session.state is SessionState.SEALED and session.metadata_confirmed
            ):
                self.reconcile(session.session_id)

    def add_listener(self, listener) -> None:
        self._listeners.append(listener)

    async def file_changed(self, session_id: str) -> ImportSession:
        session = self.reconcile(session_id)
        for listener in tuple(self._listeners):
            result = listener(session)
            if inspect.isawaitable(result):
                await result
        return session

    def retry_file(self, session_id: str, user_id: int, message_id: int) -> None:
        self._owned(session_id, user_id)
        self._coordinator.retry(session_id, message_id)

    async def exclude_file(
        self, session_id: str, user_id: int, message_id: int
    ) -> ImportSession:
        self._owned(session_id, user_id)
        await self._coordinator.exclude(session_id, message_id)
        return self.reconcile(session_id)

    async def delete_session(self, session_id: str, user_id: int) -> None:
        self._owned(session_id, user_id)
        await self._coordinator.cancel_session(session_id)

    def get(self, session_id: str, user_id: int) -> ImportSession:
        return self._owned(session_id, user_id)

    def _collecting_or_create(self, chat_id: int, user_id: int) -> ImportSession:
        current = self._collecting_for(user_id)
        if current is not None:
            if current.chat_id != chat_id:
                raise ImporterError("collecting session belongs to another chat")
            return current
        session = ImportSession(
            session_id=self._id_factory(),
            chat_id=chat_id,
            user_id=user_id,
            state=SessionState.COLLECTING,
        )
        self._repository.create(session)
        return session

    def _collecting_for(self, user_id: int) -> ImportSession | None:
        for session in self._repository.list_all():
            if session.user_id == user_id and session.state is SessionState.COLLECTING:
                return session
        return None

    def _find_message(self, chat_id: int, message_id: int) -> ImportSession | None:
        for session in self._repository.list_all():
            if session.chat_id != chat_id:
                continue
            if message_id in session.descriptor_message_ids or any(
                file.message_id == message_id for file in session.files
            ):
                return session
        return None

    def _owned(self, session_id: str, user_id: int) -> ImportSession:
        session = self._repository.load(session_id)
        if session.user_id != user_id:
            raise ImporterError("session belongs to another operator")
        return session
