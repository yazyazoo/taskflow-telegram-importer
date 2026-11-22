from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


class SessionState(StrEnum):
    COLLECTING = "collecting"
    SEALED = "sealed"
    PUBLISHING = "publishing"
    PUBLISHED = "published"
    FAILED = "failed"


class FileState(StrEnum):
    RECEIVED = "received"
    DOWNLOADING = "downloading"
    COMPLETE = "complete"
    FAILED = "failed"
    EXCLUDED = "excluded"
    PUBLISHED = "published"


@dataclass(frozen=True, slots=True)
class EditorialHint:
    title: str
    year: int


@dataclass(frozen=True, slots=True)
class ImportFile:
    message_id: int
    file_id: str
    file_unique_id: str
    filename: str
    expected_size: int
    state: FileState
    staging_path: Path | None = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class ImportSession:
    session_id: str
    chat_id: int
    user_id: int
    state: SessionState
    files: tuple[ImportFile, ...] = ()
    captions: tuple[str, ...] = ()
    descriptor_message_ids: tuple[int, ...] = ()
    editorial_hint: EditorialHint | None = None
    published_paths: tuple[Path, ...] = ()
