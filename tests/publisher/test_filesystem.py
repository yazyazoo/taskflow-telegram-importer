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


def _file(message_id: int, filename: str, staging_path: Path) -> ImportFile:
    return ImportFile(
        message_id=message_id,
        file_id=f"file-{message_id}",
        file_unique_id=f"unique-{message_id}",
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
    source = _source(tmp_path)

    with pytest.raises(ImporterError, match="filename"):
        publisher.prepare_file("session-one", filename, source, source.stat().st_size)


def test_prepare_rejects_symlink_source(tmp_path: Path) -> None:
    publisher = _publisher(tmp_path)
    source = _source(tmp_path)
    link = tmp_path / "link.mkv"
    link.symlink_to(source)

    with pytest.raises(ImporterError, match="regular"):
        publisher.prepare_file("session-one", "episode.mkv", link, source.stat().st_size)


def test_preflight_rejects_different_filesystems(tmp_path: Path, monkeypatch) -> None:
    publisher = _publisher(tmp_path)
    monkeypatch.setattr(
        "taskflow_telegram_importer.publisher.filesystem._device_id",
        lambda path: 1 if path == publisher.staging else 2,
    )

    with pytest.raises(ImporterError, match="same filesystem"):
        publisher.preflight()


def test_prepare_copies_complete_file_with_unchanged_basename(tmp_path: Path) -> None:
    publisher = _publisher(tmp_path)
    source = _source(tmp_path, "Original Name.mkv", b"complete-video")

    staged = publisher.prepare_file(
        "session-one", "Original Name.mkv", source, len(b"complete-video")
    )

    assert staged == publisher.staging / "session-one" / "Original Name.mkv"
    assert staged.read_bytes() == b"complete-video"
    assert not list(staged.parent.glob("*.part"))


def test_prepare_rejects_size_mismatch_without_complete_file(tmp_path: Path) -> None:
    publisher = _publisher(tmp_path)
    source = _source(tmp_path, content=b"short")

    with pytest.raises(ImporterError, match="size"):
        publisher.prepare_file("session-one", "episode.mkv", source, 100)

    assert not (publisher.staging / "session-one" / "episode.mkv").exists()


def test_prepare_rejects_insufficient_free_space(tmp_path: Path, monkeypatch) -> None:
    publisher = _publisher(tmp_path, reserve=1)
    source = _source(tmp_path, content=b"video")
    monkeypatch.setattr(
        "taskflow_telegram_importer.publisher.filesystem._free_bytes", lambda path: 10
    )

    with pytest.raises(ImporterError, match="free space"):
        publisher.prepare_file("session-one", "episode.mkv", source, 5)


def test_publishes_one_file_at_gate_root(tmp_path: Path) -> None:
    publisher = _publisher(tmp_path)
    source = _source(tmp_path)
    staged = publisher.prepare_file("session-one", "episode.mkv", source, 5)

    published = publisher.publish(_session((_file(1, "episode.mkv", staged),)))

    assert published == (publisher.gate / "episode.mkv",)
    assert published[0].read_bytes() == b"video"


def test_publishes_multiple_files_by_one_directory_rename(tmp_path: Path) -> None:
    publisher = _publisher(tmp_path)
    first_source = _source(tmp_path, "one.mkv", b"one")
    second_source = _source(tmp_path, "two.mkv", b"two")
    first = publisher.prepare_file("session-one", "one.mkv", first_source, 3)
    second = publisher.prepare_file("session-one", "two.mkv", second_source, 3)

    published = publisher.publish(
        _session((_file(1, "one.mkv", first), _file(2, "two.mkv", second)))
    )

    target = publisher.gate / "Cape_Fear_2025"
    assert published == (target / "one.mkv", target / "two.mkv")
    assert [path.name for path in published] == ["one.mkv", "two.mkv"]
    assert not (publisher.staging / "session-one").exists()


def test_publish_refuses_existing_target_before_moving_any_file(tmp_path: Path) -> None:
    publisher = _publisher(tmp_path)
    first = publisher.prepare_file("session-one", "one.mkv", _source(tmp_path, "one.mkv"), 5)
    second = publisher.prepare_file("session-one", "two.mkv", _source(tmp_path, "two.mkv"), 5)
    target = publisher.gate / "Cape_Fear_2025"
    target.mkdir(parents=True)

    with pytest.raises(ImporterError, match="already exists"):
        publisher.publish(_session((_file(1, "one.mkv", first), _file(2, "two.mkv", second))))

    assert first.exists() and second.exists()


def test_delete_removes_only_manifest_owned_paths(tmp_path: Path) -> None:
    publisher = _publisher(tmp_path)
    staged = publisher.prepare_file("session-one", "episode.mkv", _source(tmp_path), 5)
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
