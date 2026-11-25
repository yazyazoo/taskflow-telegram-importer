from __future__ import annotations

import os
import re
import shutil
import stat
import logging
from dataclasses import dataclass
from pathlib import Path

from taskflow_telegram_importer.errors import ImporterError
from taskflow_telegram_importer.sessions import FileState, ImportSession, SessionState

from .names import normalize_session_directory


_SESSION_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
_GIB = 1024**3
_LOGGER = logging.getLogger("taskflow_telegram_importer.publisher")


@dataclass(frozen=True, slots=True)
class DownloadTarget:
    temporary: Path
    final: Path


class FilesystemPublisher:
    def __init__(self, staging: Path, gate: Path, minimum_free_gib: float) -> None:
        self.staging = Path(staging)
        self.gate = Path(gate)
        self.minimum_free_bytes = int(minimum_free_gib * _GIB)

    def preflight(self) -> None:
        _ensure_directory_path_safe(self.staging)
        _ensure_directory_path_safe(self.gate)
        self.staging.mkdir(parents=True, exist_ok=True)
        self.gate.mkdir(parents=True, exist_ok=True)
        _ensure_directory_path_safe(self.staging)
        _ensure_directory_path_safe(self.gate)
        if _device_id(self.staging) != _device_id(self.gate):
            raise ImporterError("staging and gate must use the same filesystem")

    def prepare_download(
        self,
        session_id: str,
        filename: str,
        expected_size: int,
    ) -> DownloadTarget:
        self.preflight()
        _validate_session_id(session_id)
        _validate_filename(filename)
        if expected_size < 0:
            raise ImporterError("Telegram file size is invalid")
        if _free_bytes(self.staging) - expected_size < self.minimum_free_bytes:
            raise ImporterError("insufficient free space in staging")

        session_directory = self.staging / session_id
        _require_contained(session_directory, self.staging)
        if session_directory.is_symlink():
            raise ImporterError("session staging directory is a symlink")
        session_directory.mkdir(mode=0o700, parents=False, exist_ok=True)
        _ensure_directory_path_safe(session_directory)
        final = session_directory / filename
        temporary = session_directory / f".{filename}.part"
        _require_contained(final, self.staging)
        if final.exists() or final.is_symlink() or temporary.exists() or temporary.is_symlink():
            raise ImporterError("staging target already exists")
        return DownloadTarget(temporary=temporary, final=final)

    def finalize_download(self, target: DownloadTarget, expected_size: int) -> Path:
        session_directory = target.final.parent
        _require_contained(target.temporary, self.staging)
        _require_contained(target.final, self.staging)
        _ensure_directory_path_safe(session_directory)
        try:
            metadata = target.temporary.lstat()
            if target.temporary.is_symlink() or not stat.S_ISREG(metadata.st_mode):
                raise ImporterError("downloaded staging object is not a regular file")
            if metadata.st_size != expected_size:
                raise ImporterError("staged file size does not match expected size")
            descriptor = os.open(target.temporary, os.O_RDONLY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
            os.replace(target.temporary, target.final)
            _fsync_directory(session_directory)
            _LOGGER.info(
                "staged file session=%s file=%s bytes=%d",
                session_directory.name,
                target.final.name,
                expected_size,
            )
            return target.final
        except Exception:
            target.temporary.unlink(missing_ok=True)
            raise

    def plan_publication(self, session: ImportSession) -> tuple[Path, ...]:
        files = tuple(item for item in session.files if item.state is not FileState.EXCLUDED)
        if len(files) == 1:
            return (self.gate / files[0].filename,)
        target_directory = self.gate / _publication_directory(session)
        return tuple(target_directory / item.filename for item in files)

    def publish(self, session: ImportSession) -> tuple[Path, ...]:
        self.preflight()
        if session.state not in {SessionState.SEALED, SessionState.PUBLISHING}:
            raise ImporterError("session is not confirmed for publication")
        files = tuple(item for item in session.files if item.state is not FileState.EXCLUDED)
        if not files or any(
            item.state is not FileState.COMPLETE or item.staging_path is None for item in files
        ):
            raise ImporterError("all included files must be complete before publication")

        session_directory = self.staging / session.session_id
        _require_contained(session_directory, self.staging)
        planned = self.plan_publication(session)
        if session.state is SessionState.PUBLISHING and session.published_paths != planned:
            raise ImporterError("persisted publication plan does not match session")
        if _publication_is_complete(planned, files) and all(
            item.staging_path is not None and not item.staging_path.exists()
            for item in files
        ):
            if session_directory.exists():
                try:
                    session_directory.rmdir()
                except OSError as exc:
                    raise ImporterError(
                        "completed publication left unexpected staging files"
                    ) from exc
            return planned
        for item in files:
            assert item.staging_path is not None
            _require_contained(item.staging_path, session_directory)
            if item.staging_path.parent != session_directory or item.staging_path.is_symlink():
                raise ImporterError("staged file is outside the session directory")
            if not item.staging_path.is_file():
                raise ImporterError("staged file is missing")

        if len(files) == 1:
            item = files[0]
            target = planned[0]
            _require_contained(target, self.gate)
            _ensure_absent(target)
            os.rename(item.staging_path, target)
            session_directory.rmdir()
            _fsync_directory(self.gate)
            _LOGGER.info("published session=%s files=1", session.session_id)
            return (target,)

        target_directory = planned[0].parent
        _require_contained(target_directory, self.gate)
        _ensure_absent(target_directory)
        actual_names = {path.name for path in session_directory.iterdir()}
        expected_names = {item.filename for item in files}
        if actual_names != expected_names:
            raise ImporterError("session staging directory contains unexpected files")
        os.rename(session_directory, target_directory)
        _fsync_directory(self.gate)
        _LOGGER.info("published session=%s files=%d", session.session_id, len(files))
        return planned

    def discard_staged(self, session_id: str, path: Path) -> None:
        expected_parent = self.staging / session_id
        _require_contained(path, expected_parent)
        _reject_symlink_parent(path, self.staging)
        path.unlink(missing_ok=True)
        try:
            expected_parent.rmdir()
        except OSError:
            pass

    def discard_incomplete_download(self, session_id: str, filename: str) -> None:
        _validate_session_id(session_id)
        _validate_filename(filename)
        session_directory = self.staging / session_id
        self.discard_staged(session_id, session_directory / f".{filename}.part")
        self.discard_staged(session_id, session_directory / filename)

    def delete_owned_paths(self, session: ImportSession) -> None:
        candidates = [
            item.staging_path for item in session.files if item.staging_path is not None
        ]
        candidates.extend(session.published_paths)
        for candidate in candidates:
            root = self.staging if _is_contained(candidate, self.staging) else self.gate
            if not _is_contained(candidate, root):
                raise ImporterError(f"refusing to delete path outside importer roots: {candidate}")
            _reject_symlink_parent(candidate, root)
            try:
                candidate.unlink()
            except FileNotFoundError:
                pass
            parent = candidate.parent
            if parent not in {self.staging, self.gate} and _is_contained(parent, root):
                try:
                    parent.rmdir()
                except OSError:
                    pass


def _validate_session_id(session_id: str) -> None:
    if not _SESSION_ID.fullmatch(session_id):
        raise ImporterError("invalid session ID")


def _validate_filename(filename: str) -> None:
    if (
        not filename
        or "\x00" in filename
        or Path(filename).is_absolute()
        or Path(filename).name != filename
        or filename in {".", ".."}
    ):
        raise ImporterError("filename must be one safe basename")


def _ensure_absent(path: Path) -> None:
    if path.exists() or path.is_symlink():
        raise ImporterError(f"publication target already exists: {path.name}")


def _is_contained(path: Path, root: Path) -> bool:
    absolute_path = Path(os.path.abspath(path))
    absolute_root = Path(os.path.abspath(root))
    return absolute_path != absolute_root and absolute_root in absolute_path.parents


def _require_contained(path: Path, root: Path) -> None:
    if not _is_contained(path, root):
        raise ImporterError(f"path is outside importer root: {path}")


def _reject_symlink_parent(path: Path, root: Path) -> None:
    current = path.parent
    while current != root:
        if current.is_symlink():
            raise ImporterError(f"path parent is a symlink: {current}")
        current = current.parent


def _ensure_directory_path_safe(path: Path) -> None:
    absolute = Path(os.path.abspath(path))
    chain = tuple(reversed(absolute.parents)) + (absolute,)
    for component in chain:
        if component.is_symlink():
            raise ImporterError(f"directory path contains a symlink: {component}")
    if absolute.exists() and not absolute.is_dir():
        raise ImporterError(f"directory path is not a directory: {absolute}")


def _publication_is_complete(planned, files) -> bool:
    if len(planned) != len(files):
        return False
    for target, item in zip(planned, files, strict=True):
        if target.is_symlink() or not target.is_file() or target.stat().st_size != item.expected_size:
            return False
    return True


def _publication_directory(session: ImportSession) -> str:
    if session.editorial_hint is not None:
        return normalize_session_directory(
            session.editorial_hint.title, session.editorial_hint.year
        )
    return session.session_id


def _device_id(path: Path) -> int:
    return path.stat().st_dev


def _free_bytes(path: Path) -> int:
    return shutil.disk_usage(path).free


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
