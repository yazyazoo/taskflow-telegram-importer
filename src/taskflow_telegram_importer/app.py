from __future__ import annotations

import argparse
import asyncio
import logging
import signal
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from telegram import Bot
from telegram.ext import Application

from taskflow_telegram_importer.config import load_settings, resolve_secret
from taskflow_telegram_importer.downloads import DownloadCoordinator
from taskflow_telegram_importer.errors import ImporterError
from taskflow_telegram_importer.imports import ImportService
from taskflow_telegram_importer.logging import LoggingController, configure_logging
from taskflow_telegram_importer.publisher import FilesystemPublisher
from taskflow_telegram_importer.processors import VideoProcessor
from taskflow_telegram_importer.sessions import SessionRepository
from taskflow_telegram_importer.telegram import build_application

_LOGGER = logging.getLogger("taskflow_telegram_importer.runtime")


class LateBoundTelegramSource:
    def __init__(self) -> None:
        self._bot: Bot | None = None

    def bind(self, bot: Bot) -> None:
        self._bot = bot

    async def get_local_file(self, file_id: str) -> Path:
        if self._bot is None:
            raise ImporterError("Telegram source is not bound")
        telegram_file = await self._bot.get_file(file_id)
        if not telegram_file.file_path:
            raise ImporterError("local Bot API returned no file path")
        path = Path(telegram_file.file_path)
        if not path.is_absolute() or path.is_symlink() or not path.is_file():
            raise ImporterError("local Bot API returned an unsafe file path")
        return path


@dataclass(slots=True)
class Runtime:
    application: Application
    coordinator: DownloadCoordinator
    publisher: FilesystemPublisher
    long_poll_timeout: float
    logging_controller: LoggingController | None = None
    recoverer: Callable[[], None] | None = None
    _initialized: bool = False
    _started: bool = False
    _polling: bool = False

    async def start(self) -> None:
        self.publisher.preflight()
        await self.application.initialize()
        self._initialized = True
        await self.application.start()
        self._started = True
        self.coordinator.recover()
        if self.recoverer is not None:
            self.recoverer()
        if self.application.updater is None:
            raise RuntimeError("Telegram application has no updater")
        await self.application.updater.start_polling(timeout=self.long_poll_timeout)
        self._polling = True
        _LOGGER.info("runtime started")

    async def shutdown(self) -> None:
        try:
            if self._polling and self.application.updater is not None:
                await self.application.updater.stop()
            try:
                await self.coordinator.shutdown()
            finally:
                try:
                    if self._started:
                        await self.application.stop()
                finally:
                    if self._initialized:
                        await self.application.shutdown()
        finally:
            if self.logging_controller is not None:
                self.logging_controller.close()

    async def run_until_stopped(self, stop_event: asyncio.Event) -> None:
        try:
            await self.start()
            await stop_event.wait()
        finally:
            await self.shutdown()


def compose(project_root: Path) -> Runtime:
    settings = load_settings(project_root)
    token = resolve_secret(settings.telegram.token_command)
    logging_controller = configure_logging(
        settings.logging.level, settings.paths.log_file, secrets=(token,)
    )
    try:
        publisher = FilesystemPublisher(
            settings.paths.staging,
            settings.paths.gate,
            settings.files.minimum_free_gib,
        )
        repository = SessionRepository(settings.paths.staging / ".sessions")
        source = LateBoundTelegramSource()
        coordinator = DownloadCoordinator(repository, publisher, source)
        processor = VideoProcessor(settings.files.allowed_extensions, settings.paths.staging)
        service = ImportService(repository, coordinator, publisher, processor=processor)
        coordinator.set_terminal_callback(service.file_terminal)
        application = build_application(settings, service, token=token)
        source.bind(application.bot)
        return Runtime(
            application,
            coordinator,
            publisher,
            settings.telegram.long_poll_request_timeout_seconds,
            logging_controller,
            service.recover,
        )
    except Exception:
        logging_controller.close()
        raise


async def _run(project_root: Path) -> None:
    runtime = compose(project_root)
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(signum, stop_event.set)
    await runtime.run_until_stopped(stop_event)


def main() -> None:
    parser = argparse.ArgumentParser(description="TaskFlow Telegram Importer")
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    arguments = parser.parse_args()
    asyncio.run(_run(arguments.project_root.resolve()))
