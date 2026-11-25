from __future__ import annotations

from dataclasses import dataclass

from taskflow_telegram_importer.sessions import FileState, ImportSession, SessionState


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

    queued = 0
    for file in session.files:
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
        if session.metadata_confirmed:
            lines.append("Dati confermati · Download in corso")
            buttons.append(("Annulla", f"delete-request:{session.session_id}"))
        else:
            buttons.extend(
                [
                    ("Conferma e pubblica", f"confirm:{session.session_id}"),
                    ("Modifica", f"edit:{session.session_id}"),
                    ("Annulla", f"delete-request:{session.session_id}"),
                ]
            )
    return RenderedStatus("\n".join(lines), tuple(buttons))


def _mib(value: int | float) -> float:
    return float(value) / (1024 * 1024)


def _duration(seconds: int) -> str:
    minutes, remainder = divmod(seconds, 60)
    if minutes:
        return f"{minutes}m {remainder:02d}s"
    return f"{remainder}s"
