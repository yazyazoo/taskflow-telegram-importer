from __future__ import annotations

from pathlib import Path

import pytest

from taskflow_telegram_importer.http import JsonResponse
from taskflow_telegram_importer.taskflow import TaskFlowClient


class TransportStub:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    async def request(self, method, url, *, headers=None, query=None, body=None, timeout_seconds=30):
        self.calls.append((method, url, headers, query, body, timeout_seconds))
        return JsonResponse(200 if method == "GET" else 201, self.responses.pop(0))


@pytest.mark.asyncio
async def test_resolve_filesystem_packages_matches_exact_published_paths_and_sizes() -> None:
    target = Path("/gate/Show (2026)/episode.mkv")
    transport = TransportStub([
        [{"id": "7251391", "code": "local-media", "type": "filesystem"}],
        {"id": "7251391"},
        [{"id": "1111111", "integration_id": "7251391", "status": "ready",
          "workflow_id": None, "details": {"file": str(target), "size": 123}}],
    ])
    client = TaskFlowClient(
        transport,
        base_url="https://taskflow.example/api/v1",
        token="token",
        filesystem_integration_code="local-media",
        timeout_seconds=30,
        reconciliation_poll_seconds=0,
        reconciliation_timeout_seconds=1,
    )

    package_ids = await client.resolve_filesystem_packages(((target, 123),))

    assert package_ids == ("1111111",)
    assert transport.calls[1][0:2] == (
        "POST", "https://taskflow.example/api/v1/integrations/7251391/refresh"
    )


@pytest.mark.asyncio
async def test_create_then_start_uses_package_ids_and_preset() -> None:
    transport = TransportStub([
        {"id": "7654321", "status": "created"},
        {"id": "7654321", "status": "queued"},
    ])
    client = TaskFlowClient(
        transport,
        base_url="https://taskflow.example/api/v1",
        token="token",
        filesystem_integration_code="local-media",
        timeout_seconds=30,
        reconciliation_poll_seconds=1,
        reconciliation_timeout_seconds=30,
    )

    workflow = await client.create_and_start({
        "packages": ["1111111"],
        "preset": "direct-media",
        "workflow_name": "Show_2026",
        "media_kind": "tv",
        "tmdb": {"tmdb_id": 42},
    })

    assert workflow["id"] == "7654321"
    assert transport.calls[0][0:2] == (
        "POST", "https://taskflow.example/api/v1/workflows"
    )
    assert transport.calls[1][0:2] == (
        "POST", "https://taskflow.example/api/v1/workflows/7654321/start"
    )
