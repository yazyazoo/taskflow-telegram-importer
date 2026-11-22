from __future__ import annotations

from dataclasses import dataclass

from taskflow_telegram_importer.sessions import FileState, ImportSession, SessionState


@dataclass(frozen=True, slots=True)
class RenderedStatus:
    text: str
    buttons: tuple[tuple[str, str], ...]


def render_session(
    session: ImportSession, *, confirm_delete: bool = False
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
        buttons.append((f"Ho finito di inoltrare · {len(session.files)} file", "finish"))
        buttons.append(("Elimina intera sessione", f"delete-request:{session.session_id}"))
    elif session.state is SessionState.SEALED:
        buttons.extend(
            [
                ("Conferma e pubblica", f"confirm:{session.session_id}"),
                ("Modifica", f"edit:{session.session_id}"),
                ("Annulla", f"delete-request:{session.session_id}"),
            ]
        )
    return RenderedStatus("\n".join(lines), tuple(buttons))
