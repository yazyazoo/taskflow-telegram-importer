from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from taskflow_telegram_importer.errors import ImporterError

from .models import (
    EditorialHint, FileState, ImportFile, ImportMode, ImportSession, QuickStage,
    QuickWorkflowDraft, SessionState, TmdbCandidate, VideoMetadata,
    WorkflowPreset,
)


_SCHEMA_VERSION = 2
_SESSION_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")


class SessionRepository:
    def __init__(self, directory: Path) -> None:
        self.directory = Path(directory)

    def create(self, session: ImportSession) -> None:
        self._validate(session)
        path = self._path(session.session_id)
        if path.exists() or path.is_symlink():
            raise ImporterError(f"session already exists: {session.session_id}")
        if session.state is SessionState.COLLECTING:
            for current in self.list_all():
                if (
                    current.user_id == session.user_id
                    and current.state is SessionState.COLLECTING
                ):
                    raise ImporterError("user already has a collecting session")
        self._write(session)

    def load(self, session_id: str) -> ImportSession:
        path = self._path(session_id)
        self._reject_symlink(path)
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ImporterError(f"could not read session manifest: {session_id}") from exc
        if raw.get("schema_version") != _SCHEMA_VERSION:
            raise ImporterError("unsupported session manifest schema")
        try:
            session = _decode_session(raw)
        except (KeyError, TypeError, ValueError) as exc:
            raise ImporterError(f"invalid session manifest: {session_id}") from exc
        self._validate(session)
        return session

    def save(self, session: ImportSession) -> None:
        self._validate(session)
        path = self._path(session.session_id)
        self._reject_symlink(path)
        if not path.exists():
            raise ImporterError(f"session does not exist: {session.session_id}")
        self._write(session)

    def list_all(self) -> tuple[ImportSession, ...]:
        if not self.directory.exists():
            return ()
        sessions = [self.load(path.stem) for path in sorted(self.directory.glob("*.json"))]
        return tuple(sessions)

    def delete_manifest(self, session_id: str) -> None:
        path = self._path(session_id)
        self._reject_symlink(path)
        try:
            path.unlink()
        except FileNotFoundError:
            return
        self._fsync_directory()

    def _path(self, session_id: str) -> Path:
        if not _SESSION_ID.fullmatch(session_id):
            raise ImporterError("invalid session ID")
        return self.directory / f"{session_id}.json"

    def _write(self, session: ImportSession) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self._path(session.session_id)
        self._reject_symlink(path)
        temporary = self.directory / f".{session.session_id}.json.tmp"
        self._reject_symlink(temporary)
        flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        payload = json.dumps(_encode_session(session), indent=2, sort_keys=True)
        try:
            descriptor = os.open(temporary, flags, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(payload)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
            self._fsync_directory()
        except OSError as exc:
            raise ImporterError(f"could not persist session: {session.session_id}") from exc

    def _fsync_directory(self) -> None:
        descriptor = os.open(self.directory, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    @staticmethod
    def _reject_symlink(path: Path) -> None:
        if path.is_symlink():
            raise ImporterError(f"manifest path is a symlink: {path.name}")

    @staticmethod
    def _validate(session: ImportSession) -> None:
        message_ids = [item.message_id for item in session.files]
        if len(message_ids) != len(set(message_ids)):
            raise ImporterError("session contains a duplicate message ID")
        if session.user_id <= 0 or session.chat_id == 0:
            raise ImporterError("session contains invalid Telegram IDs")
        for item in session.files:
            if item.message_id <= 0 or item.expected_size < 0:
                raise ImporterError("session file contains invalid Telegram data")


def _encode_session(session: ImportSession) -> dict[str, Any]:
    return {
        "schema_version": _SCHEMA_VERSION,
        "session_id": session.session_id,
        "chat_id": session.chat_id,
        "user_id": session.user_id,
        "state": session.state.value,
        "files": [
            {
                "message_id": item.message_id,
                "filename": item.filename,
                "expected_size": item.expected_size,
                "state": item.state.value,
                "staging_path": str(item.staging_path) if item.staging_path else None,
                "error": item.error,
                "downloaded_bytes": item.downloaded_bytes,
                "download_speed_bps": item.download_speed_bps,
                "download_eta_seconds": item.download_eta_seconds,
                "metadata": (
                    {
                        "width": item.metadata.width,
                        "height": item.metadata.height,
                        "duration_seconds": item.metadata.duration_seconds,
                    }
                    if item.metadata is not None
                    else None
                ),
            }
            for item in session.files
        ],
        "captions": list(session.captions),
        "descriptor_message_ids": list(session.descriptor_message_ids),
        "editorial_hint": (
            {"title": session.editorial_hint.title, "year": session.editorial_hint.year}
            if session.editorial_hint
            else None
        ),
        "metadata_confirmed": session.metadata_confirmed,
        "published_paths": [str(path) for path in session.published_paths],
        "mode": session.mode.value if session.mode else None,
        "quick": _encode_quick(session.quick),
    }


def _encode_quick(draft: QuickWorkflowDraft | None) -> dict[str, Any] | None:
    if draft is None:
        return None
    return {
        "stage": draft.stage.value,
        "media_kind": draft.media_kind,
        "query_title": draft.query_title,
        "query_year": draft.query_year,
        "candidates": [
            {
                "tmdb_id": item.tmdb_id,
                "title": item.title,
                "original_title": item.original_title,
                "year": item.year,
                "overview": item.overview,
                "poster_path": item.poster_path,
            }
            for item in draft.candidates
        ],
        "selected_tmdb_id": draft.selected_tmdb_id,
        "presets": [{"code": item.code, "name": item.name} for item in draft.presets],
        "preset_code": draft.preset_code,
        "cleanup_on_success": draft.cleanup_on_success,
        "sub_ita": draft.sub_ita,
        "taskflow_package_ids": list(draft.taskflow_package_ids),
        "workflow_id": draft.workflow_id,
        "error": draft.error,
    }


def _decode_session(raw: dict[str, Any]) -> ImportSession:
    hint_raw = raw["editorial_hint"]
    hint = (
        EditorialHint(title=str(hint_raw["title"]), year=int(hint_raw["year"]))
        if hint_raw is not None
        else None
    )
    quick_raw = raw.get("quick")
    quick = None if quick_raw is None else QuickWorkflowDraft(
        stage=QuickStage(quick_raw["stage"]),
        media_kind=quick_raw.get("media_kind"),
        query_title=quick_raw.get("query_title"),
        query_year=(int(quick_raw["query_year"]) if quick_raw.get("query_year") is not None else None),
        candidates=tuple(
            TmdbCandidate(
                int(item["tmdb_id"]), str(item["title"]), str(item["original_title"]),
                int(item["year"]), str(item["overview"]), item.get("poster_path"),
            )
            for item in quick_raw.get("candidates", [])
        ),
        selected_tmdb_id=(
            int(quick_raw["selected_tmdb_id"])
            if quick_raw.get("selected_tmdb_id") is not None else None
        ),
        presets=tuple(
            WorkflowPreset(str(item["code"]), str(item["name"]))
            for item in quick_raw.get("presets", [])
        ),
        preset_code=quick_raw.get("preset_code"),
        cleanup_on_success=bool(quick_raw.get("cleanup_on_success", False)),
        sub_ita=bool(quick_raw.get("sub_ita", False)),
        taskflow_package_ids=tuple(str(value) for value in quick_raw.get("taskflow_package_ids", [])),
        workflow_id=quick_raw.get("workflow_id"),
        error=quick_raw.get("error"),
    )
    return ImportSession(
        session_id=str(raw["session_id"]),
        chat_id=int(raw["chat_id"]),
        user_id=int(raw["user_id"]),
        state=SessionState(raw["state"]),
        files=tuple(
            ImportFile(
                message_id=int(item["message_id"]),
                filename=str(item["filename"]),
                expected_size=int(item["expected_size"]),
                state=FileState(item["state"]),
                staging_path=(
                    Path(item["staging_path"]) if item["staging_path"] else None
                ),
                error=item["error"],
                downloaded_bytes=int(item["downloaded_bytes"]),
                download_speed_bps=float(item["download_speed_bps"]),
                download_eta_seconds=(
                    int(item["download_eta_seconds"])
                    if item["download_eta_seconds"] is not None
                    else None
                ),
                metadata=_decode_video_metadata(item.get("metadata")),
            )
            for item in raw["files"]
        ),
        captions=tuple(str(value) for value in raw["captions"]),
        descriptor_message_ids=tuple(int(value) for value in raw["descriptor_message_ids"]),
        editorial_hint=hint,
        metadata_confirmed=bool(raw.get("metadata_confirmed", False)),
        published_paths=tuple(Path(value) for value in raw["published_paths"]),
        mode=ImportMode(raw["mode"]) if raw.get("mode") is not None else None,
        quick=quick,
    )


def _decode_video_metadata(raw: dict[str, Any] | None) -> VideoMetadata | None:
    if raw is None:
        return None
    return VideoMetadata(
        width=int(raw["width"]) if raw.get("width") is not None else None,
        height=int(raw["height"]) if raw.get("height") is not None else None,
        duration_seconds=(
            float(raw["duration_seconds"])
            if raw.get("duration_seconds") is not None
            else None
        ),
    )
