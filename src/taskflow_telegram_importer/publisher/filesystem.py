from __future__ import annotations

import os
import re
import shutil
import stat
from pathlib import Path

from taskflow_telegram_importer.errors import ImporterError
from taskflow_telegram_importer.sessions import FileState, ImportSession, SessionState

from .names import normalize_session_directory


_SESSION_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
_GIB = 1024**3


class FilesystemPublisher:
    def __init__(self, staging: Path, gate: Path, minimum_free_gib: float) -> None:
        self.staging = Path(staging)
        self.gate = Path(gate)
        self.minimum_free_bytes = int(minimum_free_gib * _GIB)

    def preflight(self) -> None:
        self.staging.mkdir(parents=True, exist_ok=True)
        self.gate.mkdir(parents=True, exist_ok=True)
        if _device_id(self.staging) != _device_id(self.gate):
            raise ImporterError("staging and gate must use the same filesystem")

    def prepare_file(
        self,
        session_id: str,
        filename: str,
        source: Path,
        expected_size: int,
    ) -> Path:
        self.preflight()
        _validate_session_id(session_id)
        _validate_filename(filename)
        source = Path(source)
        try:
            source_stat = source.lstat()
        except OSError as exc:
            raise ImporterError("Telegram source is not readable") from exc
        if not stat.S_ISREG(source_stat.st_mode) or source.is_symlink():
            raise ImporterError("Telegram source must be a regular file")
        if expected_size < 0 or source_stat.st_size != expected_size:
            raise ImporterError("Telegram source size does not match expected size")
        if _free_bytes(self.staging) - expected_size < self.minimum_free_bytes:
            raise ImporterError("insufficient free space in staging")

        session_directory = self.staging / session_id
        _require_contained(session_directory, self.staging)
        session_directory.mkdir(mode=0o700, parents=False, exist_ok=True)
        target = session_directory / filename
        temporary = session_directory / f".{filename}.part"
        _require_contained(target, self.staging)
        if target.exists() or target.is_symlink() or temporary.exists() or temporary.is_symlink():
            raise ImporterError("staging target already exists")

        source_flags = os.O_RDONLY
        target_flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            source_flags |= os.O_NOFOLLOW
            target_flags |= os.O_NOFOLLOW
        try:
            source_fd = os.open(source, source_flags)
            target_fd = os.open(temporary, target_flags, 0o600)
            with os.fdopen(source_fd, "rb") as source_handle, os.fdopen(
                target_fd, "wb"
            ) as target_handle:
                shutil.copyfileobj(source_handle, target_handle, length=1024 * 1024)
                target_handle.flush()
                os.fsync(target_handle.fileno())
            if temporary.stat().st_size != expected_size:
                raise ImporterError("staged file size does not match expected size")
            os.rename(temporary, target)
            _fsync_directory(session_directory)
            return target
        except Exception:
            temporary.unlink(missing_ok=True)
            raise

    def publish(self, session: ImportSession) -> tuple[Path, ...]:
        self.preflight()
        if session.state is not SessionState.SEALED or session.editorial_hint is None:
            raise ImporterError("session is not confirmed for publication")
        files = tuple(item for item in session.files if item.state is not FileState.EXCLUDED)
        if not files or any(
            item.state is not FileState.COMPLETE or item.staging_path is None for item in files
        ):
            raise ImporterError("all included files must be complete before publication")

        session_directory = self.staging / session.session_id
        _require_contained(session_directory, self.staging)
        for item in files:
            assert item.staging_path is not None
            _require_contained(item.staging_path, session_directory)
            if item.staging_path.parent != session_directory or item.staging_path.is_symlink():
                raise ImporterError("staged file is outside the session directory")
            if not item.staging_path.is_file():
                raise ImporterError("staged file is missing")

        if len(files) == 1:
            item = files[0]
            target = self.gate / item.filename
            _require_contained(target, self.gate)
            _ensure_absent(target)
            os.rename(item.staging_path, target)
            session_directory.rmdir()
            _fsync_directory(self.gate)
            return (target,)

        directory_name = normalize_session_directory(
            session.editorial_hint.title, session.editorial_hint.year
        )
        target_directory = self.gate / directory_name
        _require_contained(target_directory, self.gate)
        _ensure_absent(target_directory)
        actual_names = {path.name for path in session_directory.iterdir()}
        expected_names = {item.filename for item in files}
        if actual_names != expected_names:
            raise ImporterError("session staging directory contains unexpected files")
        os.rename(session_directory, target_directory)
        _fsync_directory(self.gate)
        return tuple(target_directory / item.filename for item in files)

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
