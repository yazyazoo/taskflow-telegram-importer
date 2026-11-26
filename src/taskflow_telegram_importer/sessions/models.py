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


class ImportMode(StrEnum):
    MANUAL = "manual"
    QUICK = "quick"


class QuickStage(StrEnum):
    MEDIA_KIND = "media_kind"
    QUERY = "query"
    CANDIDATES = "candidates"
    PRESET = "preset"
    READY = "ready"
    DOWNLOADING = "downloading"
    PUBLISHED = "published"
    CREATING = "creating"
    STARTED = "started"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class VideoMetadata:
    width: int | None = None
    height: int | None = None
    duration_seconds: float | None = None


@dataclass(frozen=True, slots=True)
class EditorialHint:
    title: str
    year: int


@dataclass(frozen=True, slots=True)
class TmdbCandidate:
    tmdb_id: int
    title: str
    original_title: str
    year: int
    overview: str
    poster_path: str | None


@dataclass(frozen=True, slots=True)
class WorkflowPreset:
    code: str
    name: str


@dataclass(frozen=True, slots=True)
class QuickWorkflowDraft:
    stage: QuickStage
    media_kind: str | None = None
    query_title: str | None = None
    query_year: int | None = None
    candidates: tuple[TmdbCandidate, ...] = ()
    selected_tmdb_id: int | None = None
    presets: tuple[WorkflowPreset, ...] = ()
    preset_code: str | None = None
    cleanup_on_success: bool = False
    sub_ita: bool = False
    taskflow_package_ids: tuple[str, ...] = ()
    workflow_id: str | None = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class ImportFile:
    message_id: int
    filename: str
    expected_size: int
    state: FileState
    staging_path: Path | None = None
    error: str | None = None
    downloaded_bytes: int = 0
    download_speed_bps: float = 0.0
    download_eta_seconds: int | None = None
    metadata: VideoMetadata | None = None


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
    metadata_confirmed: bool = False
    published_paths: tuple[Path, ...] = ()
    mode: ImportMode | None = None
    quick: QuickWorkflowDraft | None = None
