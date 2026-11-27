from __future__ import annotations

from dataclasses import dataclass

from taskflow_telegram_importer.sessions import (
    FileState, ImportFile, ImportMode, ImportSession, QuickStage, SessionState,
)


@dataclass(frozen=True, slots=True)
class RenderedStatus:
    text: str
    buttons: tuple[tuple[str, str], ...]


_SECTION_SEPARATOR = "━" * 20


def render_session(
    session: ImportSession, *, confirm_delete: bool = False, refresh_seconds: int = 30
) -> RenderedStatus:
    complete = sum(file.state in {FileState.COMPLETE, FileState.PUBLISHED} for file in session.files)
    failed = sum(file.state is FileState.FAILED for file in session.files)
    excluded = sum(file.state is FileState.EXCLUDED for file in session.files)
    lines = ["📦 SESSIONE", session.session_id]
    _append_section(lines, "🎬 CONTENUTO", _content_lines(session))
    _append_section(
        lines,
        "📊 RIEPILOGO",
        _summary_lines(session, complete, failed, excluded, refresh_seconds),
    )

    control_lines, buttons = _controls(session, confirm_delete)
    if control_lines:
        _append_section(lines, "⚙️ CONFIGURAZIONE", control_lines)

    queued = 0
    for position, file in enumerate(session.files, start=1):
        if file.state is FileState.RECEIVED and session.state is not SessionState.COLLECTING:
            queued += 1
        _append_section(
            lines,
            f"📁 FILE {position}/{len(session.files)}",
            _file_lines(file, session.state, queued if queued else None),
        )
    return RenderedStatus("\n".join(lines), tuple(buttons))


def _append_section(lines: list[str], heading: str, content: list[str]) -> None:
    lines.extend(["", _SECTION_SEPARATOR, heading, "", *content])


def _content_lines(session: ImportSession) -> list[str]:
    if session.editorial_hint is None:
        lines = ["Titolo da definire"]
    else:
        lines = [f"{session.editorial_hint.title} ({session.editorial_hint.year})"]

    if session.mode is ImportMode.MANUAL:
        lines.append("Ramo: WebUI TaskFlow")
    elif session.mode is ImportMode.QUICK:
        lines.append("Ramo: Quick Workflow")
        if session.quick is not None:
            lines.append(f"Quick Workflow: {session.quick.stage.value}")
            if session.quick.workflow_id:
                lines.append(f"Workflow TaskFlow: {session.quick.workflow_id}")
            if session.quick.error:
                lines.append(f"Errore: {session.quick.error}")
    else:
        lines.append("Ramo: da scegliere")
    return lines


def _summary_lines(
    session: ImportSession,
    complete: int,
    failed: int,
    excluded: int,
    refresh_seconds: int,
) -> list[str]:
    lines = [
        f"Stato: {session.state.value}",
        (
            f"File: {len(session.files)}  ·  ✅ {complete}  ·  "
            f"❌ {failed}  ·  ⏭ {excluded}"
        ),
    ]
    if session.state is SessionState.PUBLISHED:
        lines.append("Pubblicazione completata")
    elif session.state is SessionState.SEALED and session.metadata_confirmed:
        lines.append("Dati confermati · Download in corso")
    if any(file.state is FileState.DOWNLOADING for file in session.files):
        lines.append(f"Aggiornamento ogni {refresh_seconds} secondi")
    return lines


def _file_lines(
    file: ImportFile,
    session_state: SessionState,
    queue_position: int | None,
) -> list[str]:
    return [
        file.filename,
        "",
        "🎞 METADATI VIDEO",
        *_video_metadata_lines(file),
        "",
        "⬇️ DOWNLOAD",
        *_download_lines(file, session_state, queue_position),
    ]


def _video_metadata_lines(file: ImportFile) -> list[str]:
    metadata = file.metadata
    resolution = "non disponibile"
    if metadata is not None and metadata.width is not None and metadata.height is not None:
        resolution = f"{metadata.width} × {metadata.height}"

    duration = "non disponibile"
    if metadata is not None and metadata.duration_seconds is not None:
        duration = _duration(round(metadata.duration_seconds))

    bitrate = "non disponibile"
    if metadata is not None and metadata.duration_seconds is not None and file.expected_size > 0:
        value = file.expected_size * 8 / metadata.duration_seconds / 1_000_000
        bitrate = f"~{value:.2f} Mbit/s"

    return [
        f"• Risoluzione: {resolution}",
        f"• Durata: {duration}",
        f"• Dimensione: {_file_size(file.expected_size)}",
        f"• Bitrate stimato: {bitrate}",
    ]


def _download_lines(
    file: ImportFile,
    session_state: SessionState,
    queue_position: int | None,
) -> list[str]:
    if file.state is FileState.DOWNLOADING:
        total = file.expected_size
        percent = file.downloaded_bytes / total * 100 if total else 0.0
        lines = [
            "• Stato: in corso",
            (
                f"• Progresso: {percent:.1f}% · "
                f"{_mib(file.downloaded_bytes):.1f} MiB / {_mib(total):.1f} MiB"
            ),
        ]
        if file.download_speed_bps > 0:
            lines.append(f"• Velocità: {_mib(file.download_speed_bps):.1f} MiB/s")
        if file.download_eta_seconds is not None:
            lines.append(f"• ETA: {_duration(file.download_eta_seconds)}")
        return lines
    if file.state is FileState.RECEIVED:
        if session_state is SessionState.COLLECTING:
            return ["• Stato: raccolto"]
        return [f"• Stato: in coda #{queue_position}"]
    if file.state in {FileState.COMPLETE, FileState.PUBLISHED}:
        return ["• Stato: ✅ completato"]
    if file.state is FileState.FAILED:
        return ["• Stato: ❌ fallito"]
    return ["• Stato: ⏭ escluso"]


def _controls(
    session: ImportSession, confirm_delete: bool
) -> tuple[list[str], list[tuple[str, str]]]:
    lines: list[str] = []
    buttons: list[tuple[str, str]] = []
    for file in session.files:
        if file.state is FileState.FAILED:
            buttons.append((f"Riprova {file.filename}", f"retry:{session.session_id}:{file.message_id}"))
            buttons.append((f"Escludi {file.filename}", f"exclude:{session.session_id}:{file.message_id}"))

    if confirm_delete:
        buttons.extend(
            [
                ("Conferma eliminazione", f"delete-confirm:{session.session_id}"),
                ("Torna indietro", f"show:{session.session_id}"),
            ]
        )
    elif session.state is SessionState.COLLECTING:
        buttons.append((f"Ho finito di inoltrare · {len(session.files)} file", f"finish:{session.session_id}"))
        buttons.append(("Elimina intera sessione", f"delete-request:{session.session_id}"))
    elif session.state is SessionState.SEALED:
        if session.mode is None:
            buttons.extend(
                [
                    ("Finalizza con WebUI TaskFlow", f"manual:{session.session_id}"),
                    ("Quick Workflow", f"quick:{session.session_id}"),
                    ("Annulla", f"delete-request:{session.session_id}"),
                ]
            )
        elif session.mode is ImportMode.QUICK and session.quick is not None:
            _render_quick_controls(session, lines, buttons)
        elif session.metadata_confirmed:
            buttons.append(("Annulla", f"delete-request:{session.session_id}"))
    return lines, buttons


def _render_quick_controls(session, lines, buttons) -> None:
    draft = session.quick
    if draft.stage is QuickStage.MEDIA_KIND:
        lines.append("Scegli il tipo di contenuto per la ricerca TMDB.")
        buttons.extend(
            [
                ("Film", f"kind:{session.session_id}:movie"),
                ("Serie TV", f"kind:{session.session_id}:tv"),
            ]
        )
    elif draft.stage is QuickStage.QUERY:
        lines.append("Inserisci titolo e anno prima della ricerca TMDB.")
        buttons.append(("Cerca su TMDB", f"query:{session.session_id}"))
    elif draft.stage is QuickStage.CANDIDATES:
        lines.append("Scegli il risultato TMDB corretto.")
        buttons.extend(
            (
                f"{candidate.title} ({candidate.year}) · TMDB {candidate.tmdb_id}",
                f"candidate:{session.session_id}:{candidate.tmdb_id}",
            )
            for candidate in draft.candidates
        )
    elif draft.stage is QuickStage.PRESET:
        lines.append("Scegli il preset TaskFlow.")
        buttons.extend(
            (preset.name, f"preset:{session.session_id}:{index}")
            for index, preset in enumerate(draft.presets)
        )
    elif draft.stage is QuickStage.READY:
        lines.append(
            "Configurazione pronta · "
            f"cleanup {'ON' if draft.cleanup_on_success else 'OFF'} · "
            f"sub-ita {'ON' if draft.sub_ita else 'OFF'}"
        )
        buttons.extend(
            [
                ("Attiva/disattiva cleanup", f"cleanup:{session.session_id}"),
                ("Attiva/disattiva sub-ita", f"subita:{session.session_id}"),
                ("Avvia Quick Workflow", f"quick-start:{session.session_id}"),
            ]
        )
    elif draft.stage is QuickStage.DOWNLOADING:
        lines.append("Configurazione salvata · Download in corso")
    buttons.append(("Annulla", f"delete-request:{session.session_id}"))


def _mib(value: int | float) -> float:
    return float(value) / (1024 * 1024)


def _duration(seconds: int) -> str:
    minutes, remainder = divmod(seconds, 60)
    if minutes:
        return f"{minutes}m {remainder:02d}s"
    return f"{remainder}s"


def _file_size(value: int) -> str:
    gibibyte = 1024 ** 3
    if value >= gibibyte:
        return f"{value / gibibyte:.2f} GiB"
    return f"{_mib(value):.1f} MiB"
