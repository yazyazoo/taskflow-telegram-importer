from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from taskflow_telegram_importer.errors import ImporterError
from taskflow_telegram_importer.sessions import (
    FileState,
    ImportFile,
    ImportSession,
    SessionRepository,
    SessionState,
)


def _file(message_id: int = 10) -> ImportFile:
    return ImportFile(
        message_id=message_id,
        file_id=f"file-{message_id}",
        file_unique_id=f"unique-{message_id}",
        filename=f"episode-{message_id}.mkv",
        expected_size=123456789012,
        state=FileState.RECEIVED,
    )


def _session(
    session_id: str = "session-one",
    user_id: int = 100,
    state: SessionState = SessionState.COLLECTING,
) -> ImportSession:
    return ImportSession(
        session_id=session_id,
        chat_id=200,
        user_id=user_id,
        state=state,
        files=(_file(),),
        captions=("Cape Fear (2025)",),
        descriptor_message_ids=(9,),
    )


def test_manifest_round_trip_preserves_large_ids_paths_and_states(tmp_path: Path) -> None:
    repository = SessionRepository(tmp_path)
    staged = replace(
        _file(), state=FileState.COMPLETE, staging_path=tmp_path / "episode-10.mkv"
    )
    session = replace(
        _session(),
        files=(staged,),
        state=SessionState.PUBLISHED,
        published_paths=(tmp_path / "gate" / "episode-10.mkv",),
    )

    repository.create(session)

    assert repository.load(session.session_id) == session


def test_rejects_unknown_manifest_schema(tmp_path: Path) -> None:
    repository = SessionRepository(tmp_path)
    repository.directory.mkdir(parents=True, exist_ok=True)
    (repository.directory / "bad.json").write_text(
        json.dumps({"schema_version": 99, "session_id": "bad"}), encoding="utf-8"
    )

    with pytest.raises(ImporterError, match="schema"):
        repository.load("bad")


def test_rejects_duplicate_message_ids(tmp_path: Path) -> None:
    repository = SessionRepository(tmp_path)
    session = replace(_session(), files=(_file(10), _file(10)))

    with pytest.raises(ImporterError, match="duplicate message"):
        repository.create(session)


def test_allows_only_one_collecting_session_per_user(tmp_path: Path) -> None:
    repository = SessionRepository(tmp_path)
    repository.create(_session("first"))

    with pytest.raises(ImporterError, match="collecting session"):
        repository.create(_session("second"))


def test_allows_multiple_sealed_sessions_for_same_user(tmp_path: Path) -> None:
    repository = SessionRepository(tmp_path)
    repository.create(_session("first", state=SessionState.SEALED))
    repository.create(_session("second", state=SessionState.SEALED))

    assert {item.session_id for item in repository.list_all()} == {"first", "second"}


def test_save_atomically_replaces_committed_manifest(tmp_path: Path) -> None:
    repository = SessionRepository(tmp_path)
    original = _session()
    repository.create(original)
    updated = replace(original, state=SessionState.SEALED)

    repository.save(updated)

    assert repository.load(original.session_id) == updated
    assert not list(repository.directory.glob("*.tmp"))


def test_truncated_temporary_manifest_does_not_hide_committed_state(
    tmp_path: Path,
) -> None:
    repository = SessionRepository(tmp_path)
    original = _session()
    repository.create(original)
    (repository.directory / ".session-one.json.tmp").write_text(
        '{"schema_version":', encoding="utf-8"
    )

    assert repository.load(original.session_id) == original
    assert repository.list_all() == (original,)


def test_manifest_symlink_is_never_followed(tmp_path: Path) -> None:
    repository = SessionRepository(tmp_path)
    repository.directory.mkdir(parents=True, exist_ok=True)
    target = tmp_path / "outside.json"
    target.write_text("{}", encoding="utf-8")
    (repository.directory / "session-one.json").symlink_to(target)

    with pytest.raises(ImporterError, match="symlink"):
        repository.load("session-one")


def test_delete_removes_only_requested_manifest(tmp_path: Path) -> None:
    repository = SessionRepository(tmp_path)
    repository.create(_session("first", user_id=1))
    repository.create(_session("second", user_id=2))

    repository.delete_manifest("first")

    assert [item.session_id for item in repository.list_all()] == ["second"]
