from dataclasses import replace
from pathlib import Path

from taskflow_telegram_importer.sessions import (
    EditorialHint,
    FileState,
    ImportFile,
    ImportMode,
    ImportSession,
    SessionState,
    VideoMetadata,
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

    assert rendered.text.startswith("📦 SESSIONE\nabc123")
    assert "━━━━━━━━━━━━━━━━━━━━\n🎬 CONTENUTO" in rendered.text
    assert "━━━━━━━━━━━━━━━━━━━━\n📊 RIEPILOGO" in rendered.text
    assert "━━━━━━━━━━━━━━━━━━━━\n📁 FILE 1/2" in rendered.text
    assert "File: 2  ·  ✅ 1  ·  ❌ 1  ·  ⏭ 0" in rendered.text
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

    assert "⬇️ DOWNLOAD\n• Stato: in corso" in rendered.text
    assert "• Progresso: 50.0% · 47.7 MiB / 95.4 MiB" in rendered.text
    assert "• Velocità: 4.8 MiB/s" in rendered.text
    assert "• ETA: 10s" in rendered.text
    assert "📁 FILE 2/2\n\ntwo.mkv" in rendered.text
    assert "• Stato: in coda #1" in rendered.text
    assert "Aggiornamento ogni 30 secondi" in rendered.text


def test_collecting_panel_shows_metadata_for_all_files_in_arrival_order() -> None:
    session = replace(
        _session(),
        files=(
            ImportFile(
                1,
                "first.mp4",
                2_311_467_422,
                FileState.RECEIVED,
                metadata=VideoMetadata(1920, 816, 3319.92),
            ),
            ImportFile(
                2,
                "second.mkv",
                734_003_200,
                FileState.RECEIVED,
                metadata=VideoMetadata(),
            ),
        ),
    )

    rendered = render_session(session)

    first = rendered.text.index("📁 FILE 1/2\n\nfirst.mp4")
    second = rendered.text.index("📁 FILE 2/2\n\nsecond.mkv")
    assert first < second
    assert "🎞 METADATI VIDEO" in rendered.text
    assert "• Risoluzione: 1920 × 816" in rendered.text
    assert "• Durata: 55m 20s" in rendered.text
    assert "• Dimensione: 2.15 GiB" in rendered.text
    assert "• Bitrate stimato: ~5.57 Mbit/s" in rendered.text
    assert "• Risoluzione: non disponibile" in rendered.text
    assert "• Durata: non disponibile" in rendered.text
    assert "• Dimensione: 700.0 MiB" in rendered.text
    assert "• Bitrate stimato: non disponibile" in rendered.text
    assert rendered.buttons[-2:] == (
        ("Ho finito di inoltrare · 2 file", "finish:abc123"),
        ("Elimina intera sessione", "delete-request:abc123"),
    )
