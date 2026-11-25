from dataclasses import replace
from pathlib import Path

from taskflow_telegram_importer.sessions import (
    EditorialHint,
    FileState,
    ImportFile,
    ImportMode,
    ImportSession,
    SessionState,
)
from taskflow_telegram_importer.telegram.rendering import render_session


def _session(
    state: SessionState = SessionState.COLLECTING,
    *,
    metadata_confirmed: bool = False,
) -> ImportSession:
    return ImportSession(
        session_id="abc123",
        chat_id=20,
        user_id=10,
        state=state,
        files=(
            ImportFile(1, "one.mkv", 100, FileState.COMPLETE, Path("/tmp/one.mkv")),
            ImportFile(2, "two.mkv", 100, FileState.FAILED, error="network"),
        ),
        editorial_hint=EditorialHint("Cape Fear", 2025),
        metadata_confirmed=metadata_confirmed,
    )


def test_collecting_status_shows_concurrent_counts_and_finish_action() -> None:
    rendered = render_session(_session())

    assert "File: 2" in rendered.text
    assert "Completati: 1" in rendered.text
    assert "Falliti: 1" in rendered.text
    assert ("Ho finito di inoltrare · 2 file", "finish:abc123") in rendered.buttons
    assert ("Riprova two.mkv", "retry:abc123:2") in rendered.buttons
    assert ("Escludi two.mkv", "exclude:abc123:2") in rendered.buttons


def test_sealed_status_offers_manual_and_quick_branches() -> None:
    rendered = render_session(_session(SessionState.SEALED))

    assert "Cape Fear (2025)" in rendered.text
    assert ("Finalizza con WebUI TaskFlow", "manual:abc123") in rendered.buttons
    assert ("Quick Workflow", "quick:abc123") in rendered.buttons
    assert ("Annulla", "delete-request:abc123") in rendered.buttons


def test_confirmed_sealed_status_hides_confirmation_actions() -> None:
    rendered = render_session(
        replace(
            _session(SessionState.SEALED, metadata_confirmed=True),
            mode=ImportMode.MANUAL,
        )
    )

    assert "Dati confermati" in rendered.text
    assert "Download in corso" in rendered.text
    assert ("Finalizza con WebUI TaskFlow", "manual:abc123") not in rendered.buttons
    assert ("Quick Workflow", "quick:abc123") not in rendered.buttons
    assert ("Riprova two.mkv", "retry:abc123:2") in rendered.buttons
    assert ("Escludi two.mkv", "exclude:abc123:2") in rendered.buttons
    assert ("Annulla", "delete-request:abc123") in rendered.buttons


def test_published_status_is_final_and_has_no_actions() -> None:
    session = _session(SessionState.PUBLISHED)
    session = replace(
        session,
        files=tuple(replace(file, state=FileState.PUBLISHED) for file in session.files),
    )
    rendered = render_session(session)

    assert "Pubblicazione completata" in rendered.text
    assert rendered.buttons == ()


def test_delete_confirmation_is_explicit() -> None:
    rendered = render_session(_session(), confirm_delete=True)

    assert ("Conferma eliminazione", "delete-confirm:abc123") in rendered.buttons
    assert ("Torna indietro", "show:abc123") in rendered.buttons


def test_download_status_shows_each_file_progress_speed_eta_and_queue() -> None:
    session = _session(SessionState.SEALED, metadata_confirmed=True)
    session = replace(
        session,
        files=(
            ImportFile(
                message_id=1,
                filename="one.mkv",
                expected_size=100_000_000,
                state=FileState.DOWNLOADING,
                downloaded_bytes=50_000_000,
                download_speed_bps=5_000_000,
                download_eta_seconds=10,
            ),
            ImportFile(
                message_id=2,
                filename="two.mkv",
                expected_size=100_000_000,
                state=FileState.RECEIVED,
            ),
        ),
    )

    rendered = render_session(session, refresh_seconds=30)

    assert "one.mkv · download 50.0% · 47.7 MiB / 95.4 MiB" in rendered.text
    assert "4.8 MiB/s · ETA 10s" in rendered.text
    assert "two.mkv · in coda #1" in rendered.text
    assert "Aggiornamento ogni 30 secondi" in rendered.text
