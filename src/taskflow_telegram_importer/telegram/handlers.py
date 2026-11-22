from __future__ import annotations

from pathlib import Path

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatType
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from taskflow_telegram_importer.config import Settings, resolve_secret
from taskflow_telegram_importer.errors import ImporterError
from taskflow_telegram_importer.imports import ImportService
from taskflow_telegram_importer.sessions import SessionState

from .rendering import RenderedStatus, render_session


class TelegramHandlers:
    def __init__(
        self,
        service: ImportService,
        allowed_user_ids: tuple[int, ...],
        allowed_extensions: tuple[str, ...],
    ) -> None:
        self._service = service
        self._allowed_users = frozenset(allowed_user_ids)
        self._extensions = frozenset(value.lower() for value in allowed_extensions)
        self._status_messages: dict[int, tuple[int, int]] = {}
        self._bots = {}
        self._editing: dict[int, str] = {}
        if hasattr(service, "add_listener"):
            service.add_listener(self.session_changed)

    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._authorized(update):
            return
        user_id = update.effective_user.id
        self._bots[user_id] = context.bot
        chat_id = update.effective_chat.id
        message = update.effective_message

        if user_id in self._editing and message.text:
            await self._handle_metadata_text(user_id, message.text, update, context)
            return

        media = message.document or message.video
        try:
            if media is not None:
                filename = getattr(media, "file_name", None)
                if not filename or Path(filename).suffix.lower() not in self._extensions:
                    await message.reply_text("File ignorato: filename o estensione non supportati.")
                    return
                session = self._service.receive_video(
                    chat_id=chat_id,
                    user_id=user_id,
                    message_id=message.message_id,
                    file_id=media.file_id,
                    file_unique_id=media.file_unique_id,
                    filename=filename,
                    expected_size=int(media.file_size or 0),
                    caption=message.caption,
                )
            elif message.photo and message.caption:
                session = self._service.receive_descriptor(
                    chat_id, user_id, message.message_id, message.caption
                )
            else:
                return
            await self._show_status(update, context, session)
        except ImporterError as exc:
            await message.reply_text(str(exc))

    async def handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._authorized(update) or update.callback_query is None:
            return
        query = update.callback_query
        self._bots[update.effective_user.id] = context.bot
        await query.answer()
        data = query.data or ""
        user_id = update.effective_user.id
        try:
            action, session_id, *tail = data.split(":")
            selected = self._service.get(session_id, user_id)
            if action == "finish":
                if selected.state is not SessionState.COLLECTING:
                    raise ImporterError("stale finish action")
                session = self._service.finish_collection(user_id)
                if session.session_id != session_id:
                    raise ImporterError("stale finish action")
            else:
                if action == "confirm":
                    session = self._service.confirm_metadata(session_id, user_id)
                elif action == "edit":
                    self._editing[user_id] = session_id
                    await query.message.reply_text("Invia: Titolo | Anno")
                    return
                elif action == "retry":
                    self._service.retry_file(session_id, user_id, int(tail[0]))
                    session = self._service.get(session_id, user_id)
                elif action == "exclude":
                    session = await self._service.exclude_file(
                        session_id, user_id, int(tail[0])
                    )
                elif action == "delete-request":
                    session = self._service.get(session_id, user_id)
                    await self._show_status(update, context, session, confirm_delete=True)
                    return
                elif action == "delete-confirm":
                    await self._service.delete_session(session_id, user_id)
                    await query.edit_message_text("Sessione eliminata.")
                    self._status_messages.pop(user_id, None)
                    return
                elif action == "show":
                    session = self._service.get(session_id, user_id)
                else:
                    return
            await self._show_status(update, context, session)
        except (ImporterError, ValueError) as exc:
            await query.message.reply_text(str(exc))

    async def session_changed(self, session) -> None:
        current = self._status_messages.get(session.user_id)
        bot = self._bots.get(session.user_id)
        if current is None or bot is None:
            return
        rendered = render_session(session)
        await bot.edit_message_text(
            chat_id=current[0],
            message_id=current[1],
            text=rendered.text,
            reply_markup=_markup(rendered),
        )

    async def _handle_metadata_text(self, user_id, text, update, context) -> None:
        try:
            title, year_text = (part.strip() for part in text.rsplit("|", 1))
            session_id = self._editing[user_id]
            session = self._service.edit_metadata(session_id, user_id, title, int(year_text))
            self._editing.pop(user_id, None)
            await self._show_status(update, context, session)
        except (ValueError, ImporterError):
            await update.effective_message.reply_text("Formato non valido. Usa: Titolo | Anno")

    async def _show_status(
        self, update, context, session, *, confirm_delete: bool = False
    ) -> None:
        rendered = render_session(session, confirm_delete=confirm_delete)
        markup = _markup(rendered)
        user_id = update.effective_user.id
        current = self._status_messages.get(user_id)
        if current is not None:
            try:
                await context.bot.edit_message_text(
                    chat_id=current[0],
                    message_id=current[1],
                    text=rendered.text,
                    reply_markup=markup,
                )
                return
            except Exception:
                self._status_messages.pop(user_id, None)
        sent = await update.effective_message.reply_text(rendered.text, reply_markup=markup)
        self._status_messages[user_id] = (update.effective_chat.id, sent.message_id)

    def _authorized(self, update: Update) -> bool:
        return bool(
            update.effective_user
            and update.effective_chat
            and update.effective_chat.type == ChatType.PRIVATE
            and update.effective_user.id in self._allowed_users
        )


def build_application(
    settings: Settings,
    service: ImportService,
    *,
    token: str | None = None,
) -> Application:
    resolved_token = token or resolve_secret(settings.telegram.token_command)
    application = (
        ApplicationBuilder()
        .token(resolved_token)
        .base_url(settings.telegram.api_base_url)
        .local_mode(settings.telegram.local_mode)
        .concurrent_updates(False)
        .build()
    )
    handlers = TelegramHandlers(
        service,
        settings.telegram.allowed_user_ids,
        settings.files.allowed_extensions,
    )
    application.add_handler(CallbackQueryHandler(handlers.handle_callback))
    application.add_handler(MessageHandler(filters.ALL, handlers.handle_message))
    return application


def _markup(rendered: RenderedStatus) -> InlineKeyboardMarkup | None:
    if not rendered.buttons:
        return None
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(label, callback_data=data)] for label, data in rendered.buttons]
    )
