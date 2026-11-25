from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from taskflow_telegram_importer.errors import ImporterError
from taskflow_telegram_importer.publisher import FilesystemPublisher
from taskflow_telegram_importer.sessions import (
    EditorialHint,
    FileState,
    ImportFile,
    ImportSession,
    SessionState,
)


def _publisher(tmp_path: Path, reserve: float = 0) -> FilesystemPublisher:
    return FilesystemPublisher(tmp_path / "staging", tmp_path / "gate", reserve)


def _source(tmp_path: Path, name: str = "episode.mkv", content: bytes = b"video") -> Path:
    path = tmp_path / "source" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def _stage(
    publisher: FilesystemPublisher,
    session_id: str,
    filename: str,
    content: bytes,
) -> Path:
    target = publisher.prepare_download(session_id, filename, len(content))
    target.temporary.write_bytes(content)
    return publisher.finalize_download(target, len(content))


def _file(message_id: int, filename: str, staging_path: Path) -> ImportFile:
    return ImportFile(
        message_id=message_id,
        filename=filename,
        expected_size=staging_path.stat().st_size,
        state=FileState.COMPLETE,
        staging_path=staging_path,
    )


def _session(files: tuple[ImportFile, ...]) -> ImportSession:
    return ImportSession(
        session_id="session-one",
        chat_id=20,
        user_id=10,
        state=SessionState.SEALED,
        files=files,
        editorial_hint=EditorialHint("Cape Fear", 2025),
    )


@pytest.mark.parametrize("filename", ["../escape.mkv", "/tmp/escape.mkv", "a/b.mkv", "bad\x00.mkv"])
def test_prepare_rejects_unsafe_filenames(tmp_path: Path, filename: str) -> None:
    publisher = _publisher(tmp_path)

    with pytest.raises(ImporterError, match="filename"):
        publisher.prepare_download("session-one", filename, 5)


def test_finalize_rejects_symlink_partial_file(tmp_path: Path) -> None:
    publisher = _publisher(tmp_path)
    source = _source(tmp_path)
    target = publisher.prepare_download("session-one", "episode.mkv", 5)
    target.temporary.symlink_to(source)

    with pytest.raises(ImporterError, match="regular"):
        publisher.finalize_download(target, 5)


def test_prepare_rejects_symlink_session_directory(tmp_path: Path) -> None:
    publisher = _publisher(tmp_path)
    publisher.preflight()
    outside = tmp_path / "outside"
    outside.mkdir()
    (publisher.staging / "session-one").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ImporterError, match="symlink"):
        publisher.prepare_download("session-one", "episode.mkv", 5)

    assert not (outside / "episode.mkv").exists()


def test_preflight_rejects_different_filesystems(tmp_path: Path, monkeypatch) -> None:
    publisher = _publisher(tmp_path)
    monkeypatch.setattr(
        "taskflow_telegram_importer.publisher.filesystem._device_id",
        lambda path: 1 if path == publisher.staging else 2,
    )

    with pytest.raises(ImporterError, match="same filesystem"):
        publisher.preflight()


def test_finalize_download_atomically_promotes_part_file(tmp_path: Path) -> None:
    publisher = _publisher(tmp_path)
    target = publisher.prepare_download(
        "session-one", "Original Name.mkv", len(b"complete-video")
    )
    target.temporary.write_bytes(b"complete-video")

    staged = publisher.finalize_download(target, len(b"complete-video"))

    assert staged == publisher.staging / "session-one" / "Original Name.mkv"
    assert staged.read_bytes() == b"complete-video"
    assert not list(staged.parent.glob("*.part"))


def test_prepare_rejects_size_mismatch_without_complete_file(tmp_path: Path) -> None:
    publisher = _publisher(tmp_path)
    target = publisher.prepare_download("session-one", "episode.mkv", 100)
    target.temporary.write_bytes(b"short")

    with pytest.raises(ImporterError, match="size"):
        publisher.finalize_download(target, 100)

    assert not (publisher.staging / "session-one" / "episode.mkv").exists()


def test_prepare_rejects_insufficient_free_space(tmp_path: Path, monkeypatch) -> None:
    publisher = _publisher(tmp_path, reserve=1)
    monkeypatch.setattr(
        "taskflow_telegram_importer.publisher.filesystem._free_bytes", lambda path: 10
    )

    with pytest.raises(ImporterError, match="free space"):
        publisher.prepare_download("session-one", "episode.mkv", 5)


def test_publishes_one_file_at_gate_root(tmp_path: Path) -> None:
    publisher = _publisher(tmp_path)
    staged = _stage(publisher, "session-one", "episode.mkv", b"video")

    published = publisher.publish(_session((_file(1, "episode.mkv", staged),)))

    assert published == (publisher.gate / "episode.mkv",)
    assert published[0].read_bytes() == b"video"


def test_single_file_recovery_accepts_completed_target_and_empty_session_dir(
    tmp_path: Path,
) -> None:
    publisher = _publisher(tmp_path)
    staged = _stage(publisher, "session-one", "episode.mkv", b"video")
    base = _session((_file(1, "episode.mkv", staged),))
    planned = publisher.plan_publication(base)
    publishing = replace(
        base, state=SessionState.PUBLISHING, published_paths=planned
    )
    publisher.publish(publishing)
    (publisher.staging / "session-one").mkdir()

    assert publisher.publish(publishing) == planned
    assert not (publisher.staging / "session-one").exists()


def test_publishes_multiple_files_by_one_directory_rename(tmp_path: Path) -> None:
    publisher = _publisher(tmp_path)
    first = _stage(publisher, "session-one", "one.mkv", b"one")
    second = _stage(publisher, "session-one", "two.mkv", b"two")

    published = publisher.publish(
        _session((_file(1, "one.mkv", first), _file(2, "two.mkv", second)))
    )

    target = publisher.gate / "Cape_Fear_2025"
    assert published == (target / "one.mkv", target / "two.mkv")
    assert [path.name for path in published] == ["one.mkv", "two.mkv"]
    assert not (publisher.staging / "session-one").exists()


def test_publish_refuses_existing_target_before_moving_any_file(tmp_path: Path) -> None:
    publisher = _publisher(tmp_path)
    first = _stage(publisher, "session-one", "one.mkv", b"video")
    second = _stage(publisher, "session-one", "two.mkv", b"video")
    target = publisher.gate / "Cape_Fear_2025"
    target.mkdir(parents=True)

    with pytest.raises(ImporterError, match="already exists"):
        publisher.publish(_session((_file(1, "one.mkv", first), _file(2, "two.mkv", second))))

    assert first.exists() and second.exists()


def test_delete_removes_only_manifest_owned_paths(tmp_path: Path) -> None:
    publisher = _publisher(tmp_path)
    staged = _stage(publisher, "session-one", "episode.mkv", b"video")
    unrelated = publisher.gate / "keep.mkv"
    unrelated.parent.mkdir(parents=True, exist_ok=True)
    unrelated.write_bytes(b"keep")
    published = publisher.gate / "owned.mkv"
    published.write_bytes(b"owned")
    session = replace(
        _session((_file(1, "episode.mkv", staged),)), published_paths=(published,)
    )

    publisher.delete_owned_paths(session)

    assert not staged.exists()
    assert not published.exists()
    assert unrelated.read_bytes() == b"keep"


def test_delete_rejects_manifest_path_outside_owned_roots(tmp_path: Path) -> None:
    publisher = _publisher(tmp_path)
    outside = tmp_path / "outside.mkv"
    outside.write_bytes(b"keep")
    session = replace(_session(()), published_paths=(outside,))

    with pytest.raises(ImporterError, match="outside"):
        publisher.delete_owned_paths(session)

    assert outside.exists()
