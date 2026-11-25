from __future__ import annotations

import asyncio
import logging
import tomllib
from pathlib import Path

import pytest

from taskflow_telegram_importer.app import Runtime
from taskflow_telegram_importer.logging import SecretRedactionFilter


class FakeGateway:
    def __init__(self, events, *, fail=False):
        self.events = events
        self.fail = fail

    async def start(self):
        self.events.append("telegram-start")
        if self.fail:
            raise ConnectionError("MTProto unavailable")

    async def stop(self):
        self.events.append("telegram-stop")


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
async def test_startup_connects_mtproto_before_recovering_downloads() -> None:
    events = []
    runtime = Runtime(FakeGateway(events), FakeCoordinator(events), FakePublisher(events))

    await runtime.start()

    assert events == ["filesystem-preflight", "telegram-start", "recover"]


@pytest.mark.asyncio
async def test_failed_mtproto_startup_is_cleaned_up() -> None:
    events = []
    runtime = Runtime(
        FakeGateway(events, fail=True), FakeCoordinator(events), FakePublisher(events)
    )

    with pytest.raises(ConnectionError, match="unavailable"):
        await runtime.run_until_stopped(asyncio.Event())

    assert events[-2:] == ["telegram-stop", "coordinator-shutdown"]


@pytest.mark.asyncio
async def test_shutdown_stops_updates_before_download_jobs() -> None:
    events = []
    runtime = Runtime(FakeGateway(events), FakeCoordinator(events), FakePublisher(events))
    await runtime.start()
    events.clear()

    await runtime.shutdown()

    assert events == ["telegram-stop", "coordinator-shutdown"]


def test_secret_filter_redacts_all_telegram_credentials() -> None:
    filter = SecretRedactionFilter(("bot-token", "api-id", "api-hash"))
    record = logging.LogRecord(
        "test", logging.ERROR, __file__, 1, "token=%s api=%s hash=%s",
        ("bot-token", "api-id", "api-hash"), None,
    )

    assert filter.filter(record) is True
    assert "bot-token" not in record.getMessage()
    assert "api-id" not in record.getMessage()
    assert "api-hash" not in record.getMessage()


def test_project_declares_mtproto_client_and_native_crypto_accelerator() -> None:
    with (Path(__file__).parents[1] / "pyproject.toml").open("rb") as handle:
        dependencies = tomllib.load(handle)["project"]["dependencies"]

    normalized = [dependency.lower() for dependency in dependencies]
    assert "telethon==1.46.0" in normalized
    assert "cryptg==0.6.1" in normalized
