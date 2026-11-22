from pathlib import Path

from taskflow_telegram_importer.sessions import (
    EditorialHint,
    FileState,
    ImportFile,
    ImportSession,
    SessionState,
)
from taskflow_telegram_importer.telegram.rendering import render_session


def _session(state: SessionState = SessionState.COLLECTING) -> ImportSession:
    return ImportSession(
        session_id="abc123",
        chat_id=20,
        user_id=10,
        state=state,
        files=(
            ImportFile(1, "f1", "u1", "one.mkv", 100, FileState.COMPLETE, Path("/tmp/one.mkv")),
            ImportFile(2, "f2", "u2", "two.mkv", 100, FileState.FAILED, error="network"),
        ),
        editorial_hint=EditorialHint("Cape Fear", 2025),
    )


def test_collecting_status_shows_concurrent_counts_and_finish_action() -> None:
    rendered = render_session(_session())

    assert "File: 2" in rendered.text
    assert "Completati: 1" in rendered.text
    assert "Falliti: 1" in rendered.text
    assert ("Ho finito di inoltrare · 2 file", "finish") in rendered.buttons
    assert ("Riprova two.mkv", "retry:abc123:2") in rendered.buttons
    assert ("Escludi two.mkv", "exclude:abc123:2") in rendered.buttons


def test_sealed_status_offers_confirm_edit_and_cancel() -> None:
    rendered = render_session(_session(SessionState.SEALED))

    assert "Cape Fear (2025)" in rendered.text
    assert ("Conferma e pubblica", "confirm:abc123") in rendered.buttons
    assert ("Modifica", "edit:abc123") in rendered.buttons
    assert ("Annulla", "delete-request:abc123") in rendered.buttons


def test_delete_confirmation_is_explicit() -> None:
    rendered = render_session(_session(), confirm_delete=True)

    assert ("Conferma eliminazione", "delete-confirm:abc123") in rendered.buttons
    assert ("Torna indietro", "show:abc123") in rendered.buttons
