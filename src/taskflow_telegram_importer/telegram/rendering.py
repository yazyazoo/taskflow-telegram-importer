from __future__ import annotations

from dataclasses import dataclass

from taskflow_telegram_importer.sessions import (
    FileState, ImportFile, ImportMode, ImportSession, QuickStage, SessionState,
)


@dataclass(frozen=True, slots=True)
class RenderedStatus:
    text: str
    buttons: tuple[tuple[str, str], ...]


def render_session(
    session: ImportSession, *, confirm_delete: bool = False, refresh_seconds: int = 30
) -> RenderedStatus:
    complete = sum(file.state in {FileState.COMPLETE, FileState.PUBLISHED} for file in session.files)
    failed = sum(file.state is FileState.FAILED for file in session.files)
    excluded = sum(file.state is FileState.EXCLUDED for file in session.files)
    lines = [
        f"Sessione {session.session_id}",
        f"Stato: {session.state.value}",
        f"File: {len(session.files)} · Completati: {complete} · Falliti: {failed} · Esclusi: {excluded}",
    ]
    if session.editorial_hint is not None:
        lines.append(f"Titolo: {session.editorial_hint.title} ({session.editorial_hint.year})")
    if session.state is SessionState.PUBLISHED:
        lines.append("Pubblicazione completata")
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

    queued = 0
    for position, file in enumerate(session.files, start=1):
        if file.state is FileState.DOWNLOADING:
            total = file.expected_size
            percent = file.downloaded_bytes / total * 100 if total else 0.0
            detail = (
                f"{file.filename} · download {percent:.1f}% · "
                f"{_mib(file.downloaded_bytes):.1f} MiB / {_mib(total):.1f} MiB"
            )
            if file.download_speed_bps > 0:
                detail += f" · {_mib(file.download_speed_bps):.1f} MiB/s"
            if file.download_eta_seconds is not None:
                detail += f" · ETA {_duration(file.download_eta_seconds)}"
            lines.append(detail)
        elif file.state is FileState.RECEIVED:
            if session.state is SessionState.COLLECTING:
                lines.append(f"{position}. {file.filename} · raccolto")
                lines.append(f"   {_technical_metadata(file)}")
            else:
                queued += 1
                lines.append(f"{file.filename} · in coda #{queued}")
        elif file.state in {FileState.COMPLETE, FileState.PUBLISHED}:
            lines.append(f"{file.filename} · completato")
        elif file.state is FileState.FAILED:
            lines.append(f"{file.filename} · fallito")
        elif file.state is FileState.EXCLUDED:
            lines.append(f"{file.filename} · escluso")

    if any(file.state is FileState.DOWNLOADING for file in session.files):
        lines.append(f"Aggiornamento ogni {refresh_seconds} secondi")

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
            lines.append("Dati confermati · Download in corso")
            buttons.append(("Annulla", f"delete-request:{session.session_id}"))
    return RenderedStatus("\n".join(lines), tuple(buttons))


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


def _technical_metadata(file: ImportFile) -> str:
    metadata = file.metadata
    if (
        metadata is not None
        and metadata.width is not None
        and metadata.height is not None
    ):
        resolution = f"{metadata.width}×{metadata.height}"
    else:
        resolution = "risoluzione non disponibile"

    if metadata is not None and metadata.duration_seconds is not None:
        duration = _duration(round(metadata.duration_seconds))
    else:
        duration = "durata non disponibile"

    if (
        metadata is not None
        and metadata.duration_seconds is not None
        and file.expected_size > 0
    ):
        bitrate = file.expected_size * 8 / metadata.duration_seconds / 1_000_000
        bitrate_text = f"~{bitrate:.2f} Mbit/s"
    else:
        bitrate_text = "bitrate non disponibile"

    return (
        f"{resolution} · {duration} · {bitrate_text} · "
        f"{_file_size(file.expected_size)}"
    )


def _file_size(value: int) -> str:
    gibibyte = 1024 ** 3
    if value >= gibibyte:
        return f"{value / gibibyte:.2f} GiB"
    return f"{_mib(value):.1f} MiB"
