from __future__ import annotations

import asyncio
import logging
import tomllib
from pathlib import Path

import pytest

from taskflow_telegram_importer.app import Runtime
from taskflow_telegram_importer.logging import SecretRedactionFilter


class FakeUpdater:
    def __init__(self, events, *, fail=False):
        self.events = events
        self.fail = fail

    async def start_polling(self, **kwargs):
        self.events.append(("polling", kwargs["timeout"]))
        if self.fail:
            raise ConnectionError("Bot API unavailable")

    async def stop(self):
        self.events.append("updater-stop")


class FakeApplication:
    def __init__(self, events, *, fail_polling=False):
        self.events = events
        self.updater = FakeUpdater(events, fail=fail_polling)

    async def initialize(self):
        self.events.append("application-initialize")

    async def start(self):
        self.events.append("application-start")

    async def stop(self):
        self.events.append("application-stop")

    async def shutdown(self):
        self.events.append("application-shutdown")


class FakePublisher:
    def __init__(self, events, *, fail=False):
        self.events = events
        self.fail = fail

    def preflight(self):
        self.events.append("filesystem-preflight")
        if self.fail:
            raise OSError("invalid filesystem")


class FakeCoordinator:
    def __init__(self, events, *, fail_shutdown=False):
        self.events = events
        self.fail_shutdown = fail_shutdown

    def recover(self):
        self.events.append("recover")

    async def shutdown(self):
        self.events.append("coordinator-shutdown")
        if self.fail_shutdown:
            raise RuntimeError("coordinator shutdown failed")


@pytest.mark.asyncio
async def test_startup_recovers_before_long_polling() -> None:
    events = []
    runtime = Runtime(
        FakeApplication(events),
        FakeCoordinator(events),
        FakePublisher(events),
        long_poll_timeout=30,
    )

    await runtime.start()

    assert events == [
        "filesystem-preflight",
        "application-initialize",
        "application-start",
        "recover",
        ("polling", 30),
    ]


@pytest.mark.asyncio
async def test_unavailable_bot_api_fails_startup() -> None:
    events = []
    runtime = Runtime(
        FakeApplication(events, fail_polling=True),
        FakeCoordinator(events),
        FakePublisher(events),
        long_poll_timeout=30,
    )

    with pytest.raises(ConnectionError, match="unavailable"):
        await runtime.start()


@pytest.mark.asyncio
async def test_failed_startup_is_cleaned_up_by_runtime_lifecycle() -> None:
    events = []
    runtime = Runtime(
        FakeApplication(events, fail_polling=True),
        FakeCoordinator(events),
        FakePublisher(events),
        long_poll_timeout=30,
    )

    with pytest.raises(ConnectionError):
        await runtime.run_until_stopped(asyncio.Event())

    assert events[-3:] == [
        "coordinator-shutdown",
        "application-stop",
        "application-shutdown",
    ]


@pytest.mark.asyncio
async def test_invalid_filesystem_stops_before_application_initialization() -> None:
    events = []
    runtime = Runtime(
        FakeApplication(events),
        FakeCoordinator(events),
        FakePublisher(events, fail=True),
        long_poll_timeout=30,
    )

    with pytest.raises(OSError, match="filesystem"):
        await runtime.start()

    assert events == ["filesystem-preflight"]


@pytest.mark.asyncio
async def test_shutdown_stops_updates_before_work_and_application() -> None:
    events = []
    runtime = Runtime(
        FakeApplication(events),
        FakeCoordinator(events),
        FakePublisher(events),
        long_poll_timeout=30,
    )

    await runtime.start()
    events.clear()
    await runtime.shutdown()

    assert events == [
        "updater-stop",
        "coordinator-shutdown",
        "application-stop",
        "application-shutdown",
    ]


@pytest.mark.asyncio
async def test_run_until_stopped_performs_signal_style_shutdown() -> None:
    events = []
    stop = asyncio.Event()
    stop.set()
    runtime = Runtime(
        FakeApplication(events),
        FakeCoordinator(events),
        FakePublisher(events),
        long_poll_timeout=30,
    )

    await runtime.run_until_stopped(stop)

    assert "recover" in events
    assert events[-4:] == [
        "updater-stop",
        "coordinator-shutdown",
        "application-stop",
        "application-shutdown",
    ]


@pytest.mark.asyncio
async def test_application_is_closed_even_if_coordinator_shutdown_fails() -> None:
    events = []
    runtime = Runtime(
        FakeApplication(events),
        FakeCoordinator(events, fail_shutdown=True),
        FakePublisher(events),
        long_poll_timeout=30,
    )
    await runtime.start()

    with pytest.raises(RuntimeError, match="coordinator shutdown"):
        await runtime.shutdown()

    assert events[-2:] == ["application-stop", "application-shutdown"]


def test_secret_filter_redacts_all_configured_values() -> None:
    filter = SecretRedactionFilter(("bot-token", "api-id", "api-hash"))
    record = logging.LogRecord(
        "test",
        logging.ERROR,
        __file__,
        1,
        "token=%s api=%s hash=%s",
        ("bot-token", "api-id", "api-hash"),
        None,
    )

    assert filter.filter(record) is True
    assert "bot-token" not in record.getMessage()
    assert "api-id" not in record.getMessage()
    assert "api-hash" not in record.getMessage()


def test_project_declares_no_taskflow_http_dependency() -> None:
    with (Path(__file__).parents[1] / "pyproject.toml").open("rb") as handle:
        pyproject = tomllib.load(handle)

    dependencies = pyproject["project"]["dependencies"]
    assert all(not dependency.lower().startswith("taskflow") for dependency in dependencies)
