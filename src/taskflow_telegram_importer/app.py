from __future__ import annotations

import argparse
import asyncio
import inspect
import logging
import signal
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from taskflow_telegram_importer.config import load_settings
from taskflow_telegram_importer.automation import QuickWorkflowOrchestrator
from taskflow_telegram_importer.downloads import DownloadCoordinator
from taskflow_telegram_importer.imports import ImportService
from taskflow_telegram_importer.http import UrllibJsonTransport
from taskflow_telegram_importer.logging import LoggingController, configure_logging
from taskflow_telegram_importer.processors import VideoProcessor
from taskflow_telegram_importer.publisher import FilesystemPublisher
from taskflow_telegram_importer.sessions import SessionRepository
from taskflow_telegram_importer.taskflow import TaskFlowClient
from taskflow_telegram_importer.tmdb import TmdbClient
from taskflow_telegram_importer.telegram import (
    TelegramHandlers,
    TelethonFileSource,
    TelethonGateway,
    build_client,
)

_LOGGER = logging.getLogger("taskflow_telegram_importer.runtime")


@dataclass(slots=True)
class Runtime:
    gateway: TelethonGateway
    coordinator: DownloadCoordinator
    publisher: FilesystemPublisher
    logging_controller: LoggingController | None = None
    recoverer: Callable[[], object] | None = None
    _started: bool = False

    async def start(self) -> None:
        self.publisher.preflight()
        await self.gateway.start()
        self._started = True
        self.coordinator.recover()
        if self.recoverer is not None:
            recovered = self.recoverer()
            if inspect.isawaitable(recovered):
                await recovered
        _LOGGER.info("runtime started")

    async def shutdown(self) -> None:
        try:
            try:
                await self.gateway.stop()
            finally:
                await self.coordinator.shutdown()
        finally:
            self._started = False
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
    telegram = settings.telegram
    logging_controller = configure_logging(
        settings.logging.level,
        settings.paths.log_file,
        secrets=(str(telegram.api_id), telegram.api_hash, telegram.bot_token),
    )
    try:
        publisher = FilesystemPublisher(
            settings.paths.staging,
            settings.paths.gate,
            settings.files.minimum_free_gib,
        )
        repository = SessionRepository(settings.paths.staging / ".sessions")
        client = build_client(
            session_path=telegram.session_path,
            api_id=telegram.api_id,
            api_hash=telegram.api_hash,
        )
        source = TelethonFileSource(client)
        coordinator = DownloadCoordinator(
            repository,
            publisher,
            source,
            max_concurrent_downloads=telegram.max_concurrent_downloads,
            progress_refresh_seconds=telegram.progress_refresh_seconds,
        )
        processor = VideoProcessor(
            settings.files.allowed_extensions, settings.paths.staging
        )
        transport = UrllibJsonTransport()
        taskflow_client = TaskFlowClient(
            transport,
            base_url=settings.taskflow.api_base_url,
            token=settings.taskflow.api_token,
            filesystem_integration_code=settings.taskflow.filesystem_integration_code,
            timeout_seconds=settings.taskflow.request_timeout_seconds,
            reconciliation_poll_seconds=settings.taskflow.reconciliation_poll_seconds,
            reconciliation_timeout_seconds=settings.taskflow.reconciliation_timeout_seconds,
        )
        tmdb_client = TmdbClient(
            transport,
            base_url=settings.tmdb.api_base_url,
            api_key=settings.tmdb.api_key,
            language=settings.tmdb.language,
            timeout_seconds=settings.tmdb.request_timeout_seconds,
            max_results=settings.tmdb.max_results,
        )
        service = ImportService(
            repository,
            coordinator,
            publisher,
            processor=processor,
            tmdb_client=tmdb_client,
            taskflow_client=taskflow_client,
            quick_orchestrator=QuickWorkflowOrchestrator(taskflow_client),
            episode_patterns=settings.episode_patterns,
        )
        coordinator.set_change_callback(service.file_changed)
        handlers = TelegramHandlers(
            service,
            client,
            telegram.allowed_user_ids,
            settings.files.allowed_extensions,
            taskflow_webui_url=settings.taskflow.webui_url,
            refresh_seconds=round(telegram.progress_refresh_seconds),
        )
        gateway = TelethonGateway(
            client,
            handlers,
            bot_token=telegram.bot_token,
            session_path=telegram.session_path,
        )
        return Runtime(
            gateway,
            coordinator,
            publisher,
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
