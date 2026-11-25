from __future__ import annotations

from pathlib import Path

from telethon import Button

from taskflow_telegram_importer.errors import ImporterError
from taskflow_telegram_importer.imports import ImportService
from taskflow_telegram_importer.sessions import FileState, SessionState

from .messages import operator_error_message
from .rendering import RenderedStatus, render_session


class TelegramHandlers:
    def __init__(
        self,
        service: ImportService,
        client,
        allowed_user_ids: tuple[int, ...],
        allowed_extensions: tuple[str, ...],
        *,
        taskflow_webui_url: str,
        refresh_seconds: int,
    ) -> None:
        self._service = service
        self._client = client
        self._allowed_users = frozenset(allowed_user_ids)
        self._extensions = frozenset(value.lower() for value in allowed_extensions)
        self._taskflow_webui_url = taskflow_webui_url
        self._refresh_seconds = refresh_seconds
        self._status_messages: dict[int, tuple[int, int]] = {}
        self._editing: dict[int, tuple[str, str] | str] = {}
        self._terminal_notifications: set[tuple[str, str]] = set()
        service.add_listener(self.session_changed)

    async def handle_message(self, event) -> None:
        if not self._authorized(event):
            return
        user_id = int(event.sender_id)
        chat_id = int(event.chat_id)
        message = event.message
        text = (getattr(message, "text", None) or "").strip()

        if text == "/taskflow":
            await self._client.send_message(
                chat_id,
                "Apri TaskFlow dal telefono.",
                buttons=[[Button.url("Apri TaskFlow WebUI", self._taskflow_webui_url)]],
            )
            return

        if user_id in self._editing and text:
            await self._handle_metadata_text(user_id, chat_id, text)
            return

        media_file = getattr(message, "file", None)
        caption = getattr(message, "raw_text", None) or ""
        try:
            if media_file is not None:
                filename = getattr(media_file, "name", None)
                if not filename or Path(filename).suffix.lower() not in self._extensions:
                    await self._client.send_message(
                        chat_id,
                        "File ignorato: nome o estensione non supportati.",
                    )
                    return
                session = self._service.receive_video(
                    chat_id=chat_id,
                    user_id=user_id,
                    message_id=int(message.id),
                    filename=filename,
                    expected_size=int(getattr(media_file, "size", 0) or 0),
                    caption=caption,
                )
            elif getattr(message, "photo", None) is not None and caption:
                session = self._service.receive_descriptor(
                    chat_id, user_id, int(message.id), caption
                )
            else:
                return
            await self._show_status(user_id, chat_id, session)
        except ImporterError as exc:
            await self._client.send_message(chat_id, operator_error_message(exc))

    async def handle_callback(self, event) -> None:
        if not self._authorized(event):
            return
        await event.answer()
        data = bytes(event.data or b"").decode("utf-8", errors="strict")
        user_id = int(event.sender_id)
        chat_id = int(event.chat_id)
        try:
            action, session_id, *tail = data.split(":")
            selected = self._service.get(session_id, user_id)
            if action == "finish":
                if selected.state is not SessionState.COLLECTING:
                    raise ImporterError("stale finish action")
                session = self._service.finish_collection(user_id)
                if session.session_id != session_id:
                    raise ImporterError("stale finish action")
            elif action == "manual":
                session = self._service.start_manual(session_id, user_id)
            elif action == "quick":
                session = self._service.begin_quick(session_id, user_id)
            elif action == "kind":
                session = self._service.set_quick_media_kind(
                    session_id, user_id, tail[0]
                )
            elif action == "query":
                self._editing[user_id] = ("quick-query", session_id)
                await self._client.send_message(chat_id, "Invia: Titolo | Anno")
                return
            elif action == "candidate":
                session = await self._service.select_quick_candidate(
                    session_id, user_id, int(tail[0])
                )
            elif action == "preset":
                index = int(tail[0])
                if selected.quick is None or not 0 <= index < len(selected.quick.presets):
                    raise ImporterError("TaskFlow preset is unavailable")
                session = self._service.select_quick_preset(
                    session_id, user_id, selected.quick.presets[index].code
                )
            elif action == "cleanup":
                if selected.quick is None:
                    raise ImporterError("session is not a quick workflow")
                session = self._service.configure_quick(
                    session_id,
                    user_id,
                    cleanup_on_success=not selected.quick.cleanup_on_success,
                )
            elif action == "subita":
                if selected.quick is None:
                    raise ImporterError("session is not a quick workflow")
                session = self._service.configure_quick(
                    session_id, user_id, sub_ita=not selected.quick.sub_ita
                )
            elif action == "quick-start":
                session = self._service.start_quick(session_id, user_id)
            elif action == "confirm":
                session = self._service.confirm_metadata(session_id, user_id)
            elif action == "edit":
                self._editing[user_id] = ("metadata", session_id)
                await self._client.send_message(chat_id, "Invia: Titolo | Anno")
                return
            elif action == "retry":
                self._service.retry_file(session_id, user_id, int(tail[0]))
                session = self._service.get(session_id, user_id)
            elif action == "exclude":
                session = await self._service.exclude_file(
                    session_id, user_id, int(tail[0])
                )
            elif action == "delete-request":
                await self._show_status(
                    user_id, chat_id, selected, confirm_delete=True
                )
                return
            elif action == "delete-confirm":
                await self._service.delete_session(session_id, user_id)
                await event.edit("Sessione eliminata.", buttons=None)
                self._status_messages.pop(user_id, None)
                return
            elif action == "show":
                session = selected
            else:
                return
            await self._show_status(user_id, chat_id, session)
        except (ImporterError, ValueError, IndexError, UnicodeError) as exc:
            await self._client.send_message(chat_id, operator_error_message(exc))

    async def session_changed(self, session) -> None:
        current = self._status_messages.get(session.user_id)
        if current is None:
            return
        rendered = render_session(session, refresh_seconds=self._refresh_seconds)
        await self._client.edit_message(
            current[0], current[1], rendered.text, buttons=_buttons(rendered)
        )
        await self._notify_terminal_state(session)

    async def _handle_metadata_text(
        self, user_id: int, chat_id: int, text: str
    ) -> None:
        try:
            title, year_text = (part.strip() for part in text.rsplit("|", 1))
            editing = self._editing[user_id]
            mode, session_id = editing if isinstance(editing, tuple) else ("metadata", editing)
            if mode == "quick-query":
                session = await self._service.search_quick(
                    session_id, user_id, title, int(year_text)
                )
                confirmation = "Ricerca TMDB completata. Scegli un risultato."
            else:
                session = self._service.edit_metadata(
                    session_id, user_id, title, int(year_text)
                )
                confirmation = "Titolo e anno aggiornati."
            self._editing.pop(user_id, None)
            await self._delete_previous_status(user_id)
            await self._client.send_message(chat_id, confirmation)
            await self._show_status(user_id, chat_id, session)
        except (ValueError, ImporterError):
            await self._client.send_message(
                chat_id, "Formato non valido. Usa: Titolo | Anno"
            )

    async def _delete_previous_status(self, user_id: int) -> None:
        current = self._status_messages.pop(user_id, None)
        if current is None:
            return
        try:
            await self._client.delete_messages(current[0], [current[1]])
        except Exception:
            pass

    async def _show_status(
        self,
        user_id: int,
        chat_id: int,
        session,
        *,
        confirm_delete: bool = False,
    ) -> None:
        rendered = render_session(
            session,
            confirm_delete=confirm_delete,
            refresh_seconds=self._refresh_seconds,
        )
        current = self._status_messages.get(user_id)
        if current is not None:
            try:
                await self._client.edit_message(
                    current[0], current[1], rendered.text, buttons=_buttons(rendered)
                )
                return
            except Exception:
                self._status_messages.pop(user_id, None)
        sent = await self._client.send_message(
            chat_id, rendered.text, buttons=_buttons(rendered)
        )
        self._status_messages[user_id] = (chat_id, int(sent.id))

    async def _notify_terminal_state(self, session) -> None:
        failed = tuple(
            item.message_id for item in session.files if item.state is FileState.FAILED
        )
        if session.state is SessionState.PUBLISHED:
            key = (session.session_id, "published")
            if session.quick is not None and session.quick.workflow_id:
                message = (
                    f"Sessione {session.session_id}: workflow TaskFlow "
                    f"{session.quick.workflow_id} creato e avviato."
                )
            else:
                message = f"Sessione {session.session_id}: pubblicazione completata."
        elif failed:
            key = (session.session_id, "failed:" + ",".join(map(str, failed)))
            message = f"Sessione {session.session_id}: uno o piu download sono falliti."
        else:
            return
        if key in self._terminal_notifications:
            return
        self._terminal_notifications.add(key)
        await self._client.send_message(session.chat_id, message)

    def _authorized(self, event) -> bool:
        return bool(
            event.is_private
            and event.sender_id is not None
            and int(event.sender_id) in self._allowed_users
        )


def _buttons(rendered: RenderedStatus):
    if not rendered.buttons:
        return None
    return [
        [Button.inline(label, data.encode("utf-8"))]
        for label, data in rendered.buttons
    ]
